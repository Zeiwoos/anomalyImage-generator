from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from .config import project_paths, resolve_project_path
from .core import CoreRequest, CoreTransportError, create_adapter
from .db import Database, now_iso
from .intelligence import create_intelligence
from .knowledge import KnowledgeBase
from .labelme import LabelMeSample, build_edit_context_mask, discover_samples, expand_binary_mask, expand_per_shape, safe_id, shapes_to_json


LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", getattr(Image, "LANCZOS", 1))


def is_grayscale_visual(image: Image.Image) -> bool:
    if image.mode in {"1", "L", "I", "I;16", "F"}:
        return True
    rgb = image.convert("RGB")
    r, g, b = rgb.split()
    return ImageChops.difference(r, g).getbbox() is None and ImageChops.difference(r, b).getbbox() is None


def binary_mask_from_difference(source: Image.Image, candidate: Image.Image, allowed: Image.Image, threshold: int, dilate: int) -> Image.Image:
    difference = ImageChops.difference(source.convert("L"), candidate.convert("L"))
    binary = difference.point(lambda value: 255 if value >= threshold else 0, mode="L")
    binary = ImageChops.multiply(binary, allowed.convert("L"))
    if binary.getbbox() is not None:
        binary = binary.filter(ImageFilter.MedianFilter(3))
        if dilate > 0:
            size = min(31, int(dilate) * 2 + 1)
            binary = binary.filter(ImageFilter.MaxFilter(max(3, size)))
        binary = ImageChops.multiply(binary, allowed.convert("L"))
    return binary.point(lambda value: 255 if value >= 128 else 0, mode="L")


def match_local_tone(source: Image.Image, generated: Image.Image, allowed: Image.Image, ring_px: int) -> tuple:
    """Match generated luminance/color to source using the inner ROI boundary.

    The boundary is expected to contain unchanged context even when the anomaly
    occupies the ROI center. This removes rectangular exposure seams without
    borrowing pixels from outside the allowed edit region.
    """
    size = min(31, max(3, int(ring_px) * 2 + 1))
    if size % 2 == 0:
        size -= 1
    eroded = allowed.convert("L").filter(ImageFilter.MinFilter(size))
    ring = ImageChops.subtract(allowed.convert("L"), eroded)
    if ring.getbbox() is None:
        ring = allowed.convert("L")
    # Ignore conspicuously edited pixels while estimating tone.  Using the
    # whole rectangular ring lets a dark anomaly drag the mean and creates the
    # exact gray patch that this normalization is intended to prevent.
    luminance_difference = ImageChops.difference(source.convert("L"), generated.convert("L"))
    stable = luminance_difference.point(lambda value: 255 if value <= 28 else 0, mode="L")
    stable_ring = ImageChops.multiply(ring, stable)
    if stable_ring.histogram()[255] >= 64:
        ring = stable_ring
    source_bands = source.split()
    generated_bands = generated.split()
    if len(source_bands) != len(generated_bands):
        return generated, {"applied": False, "reason": "mode_mismatch"}
    output_bands = []
    rows = []
    for source_band, generated_band in zip(source_bands, generated_bands):
        source_stat = ImageStat.Stat(source_band, mask=ring)
        generated_stat = ImageStat.Stat(generated_band, mask=ring)
        source_mean = float(source_stat.mean[0])
        generated_mean = float(generated_stat.mean[0])
        source_std = float(source_stat.stddev[0])
        generated_std = float(generated_stat.stddev[0])
        gain = source_std / generated_std if generated_std > 1.0 else 1.0
        gain = max(0.90, min(1.10, gain))
        # A whole ROI can carry a sizable API exposure offset; permit its full
        # correction while still bounding pathological responses.
        offset = max(-48.0, min(48.0, source_mean - gain * generated_mean))
        output_bands.append(generated_band.point(lambda value, g=gain, o=offset: max(0, min(255, int(round(g * value + o))))))
        rows.append({"gain": gain, "offset": offset, "source_mean": source_mean, "generated_mean": generated_mean})
    return Image.merge(source.mode, output_bands), {
        "applied": True, "ring_px": ring_px, "stable_pixels": ring.histogram()[255], "bands": rows,
    }


def boundary_seam_metrics(source: Image.Image, candidate: Image.Image, allowed: Image.Image, ring_px: int = 8) -> Dict[str, float]:
    """Measure unintended gray/exposure discontinuity along the edit boundary."""
    size = min(31, max(3, int(ring_px) * 2 + 1))
    if size % 2 == 0:
        size -= 1
    allowed_l = allowed.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="L")
    eroded = allowed_l.filter(ImageFilter.MinFilter(size))
    ring = ImageChops.subtract(allowed_l, eroded)
    difference = ImageChops.difference(source.convert("L"), candidate.convert("L"))
    histogram = difference.histogram(mask=ring)
    count = max(1, sum(histogram))
    mean = sum(index * value for index, value in enumerate(histogram)) / count
    cumulative = 0
    p95 = 0
    target = count * 0.95
    for index, value in enumerate(histogram):
        cumulative += value
        if cumulative >= target:
            p95 = index
            break
    return {"mean_abs_difference": mean, "p95_abs_difference": float(p95), "pixels": float(sum(histogram))}


def qc_metrics(
    source: Image.Image,
    candidate: Image.Image,
    mask: Image.Image,
    allowed: Image.Image,
    adapter_name: str,
    seam_mean_limit: float = 2.5,
    seam_p95_limit: float = 10.0,
) -> Dict[str, Any]:
    width, height = source.size
    pixels = max(1, width * height)
    changed = mask.histogram()[255]
    bbox = mask.getbbox()
    border = False
    if bbox is not None:
        border = bbox[0] <= 0 or bbox[1] <= 0 or bbox[2] >= width or bbox[3] >= height
    failures: List[str] = []
    if changed == 0:
        failures.append("EMPTY_CHANGE")
    if changed / pixels > 0.45:
        failures.append("CHANGE_TOO_LARGE")
    if border:
        failures.append("CHANGE_TOUCHES_BORDER")
    if adapter_name == "mock":
        failures.append("CORE_NOT_CONFIGURED")
    seam = boundary_seam_metrics(source, candidate, allowed)
    if seam["mean_abs_difference"] > seam_mean_limit or seam["p95_abs_difference"] > seam_p95_limit:
        failures.append("ROI_TONE_SEAM")
    return {
        "changed_pixels": changed,
        "changed_area_fraction": changed / pixels,
        "changed_bbox": list(bbox) if bbox else None,
        "touches_border": border,
        "source_mode": source.mode,
        "candidate_mode": candidate.mode,
        "allowed_bbox": list(allowed.getbbox()) if allowed.getbbox() else None,
        "boundary_seam": seam,
        "failures": failures,
        "passed": not failures,
    }


class Pipeline:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.paths = project_paths(config)
        self.paths["intermediate"].mkdir(parents=True, exist_ok=True)
        self.db = Database(self.paths["database"])
        self.knowledge = KnowledgeBase(self.paths["knowledge"], self.paths["reference"])
        self.intelligence = None
        self.intelligence_startup_error = ""
        try:
            self.intelligence = create_intelligence(config)
        except Exception as exc:
            if not bool(config.get("intelligence", {}).get("fail_open", True)):
                raise
            self.intelligence_startup_error = str(exc)

    def dataset_root(self) -> Path:
        value = str(self.config["dataset"].get("root") or "").strip()
        if not value:
            raise ValueError("请先在 config.json 设置 dataset.root")
        path = resolve_project_path(self.config, value)
        if not path.is_dir():
            raise FileNotFoundError("待处理数据集不存在：{}".format(path))
        return path

    def scan(self) -> Dict[str, Any]:
        dataset_root = self.dataset_root()
        dataset = self.config["dataset"]
        samples, errors = discover_samples(dataset_root, str(dataset["labelme_glob"]), dataset["image_extensions"])
        mode = str(dataset.get("mode") or "auto").lower()
        manifest = dataset_root / "dataset_manifest.csv"
        if mode == "manifest" or (mode == "auto" and not samples and manifest.is_file()):
            return self._scan_manifest(dataset_root, manifest)
        multi_label_mode = str(self.config["generation"].get("multi_label_mode") or "per_shape").lower()
        if multi_label_mode in {"per_shape", "per_image_layered"}:
            samples = expand_per_shape(samples)
        unknown_count = 0
        empty_count = 0
        for sample in samples:
            warnings = list(sample.warnings)
            unknown = self.knowledge.validate_labels(sample.labels)
            if unknown:
                warnings.append("UNKNOWN_LABELS:" + ",".join(unknown))
                unknown_count += 1
            if not sample.shapes:
                empty_count += 1
            self.db.upsert_sample(
                {
                    "id": sample.sample_id,
                    "relative_json": sample.relative_json,
                    "json_path": str(sample.json_path),
                    "image_path": str(sample.image_path),
                    "sample_dir": str(sample.json_path.parent.resolve()),
                    "split": "anomaly",
                    "source_mode": "labelme",
                    "labels_json": json.dumps(sample.labels, ensure_ascii=False),
                    "shapes_json": shapes_to_json(sample.shapes),
                    "warnings_json": json.dumps(warnings, ensure_ascii=False),
                    "width": sample.width,
                    "height": sample.height,
                }
            )
            if warnings:
                if "NO_SHAPES" in warnings or unknown:
                    self.db.set_workflow(sample.sample_id, "hold")
            if any(self.knowledge.label(code).get("operation") == "manual_only" for code in sample.labels if code not in unknown):
                self.db.set_workflow(sample.sample_id, "hold")
        self.db.record_scan_errors(errors)
        self.export_results_csv()
        return {"samples": len(samples), "errors": errors, "unknown_labels": unknown_count, "empty_shapes": empty_count}

    @staticmethod
    def _manifest_label(row: Dict[str, str]) -> str:
        if str(row.get("split") or "").lower() == "normal":
            return "NORMAL"
        label = str(row.get("label") or "").lower()
        subtype = str(row.get("subtype") or "").lower()
        if label == "louyou":
            return "LY"
        if label == "diushi":
            return {"nut_missing": "DS_LM", "bolt_missing": "DS_LS", "large_part": "DS_ZP"}.get(subtype, "LEGACY_DIUSHI")
        return {
            "posun": "PSTQ_CLXDB", "songdong": "LEGACY_SONGDONG", "yiwu": "YW_ZangWu",
        }.get(label, "LEGACY_{}".format((label or "UNKNOWN").upper()))

    @staticmethod
    def _manifest_path(root: Path, value: str) -> Optional[Path]:
        value = str(value or "").strip()
        if not value:
            return None
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        return path.resolve()

    def _scan_manifest(self, dataset_root: Path, manifest: Path) -> Dict[str, Any]:
        """Import an already generated Extra_Data-style dataset for review.

        These rows have no LabelMe ROI, so they are review-only. Rejected rows
        are held instead of being sent to CORE with an invented location.
        """
        if not manifest.is_file():
            raise FileNotFoundError("找不到 dataset_manifest.csv：{}".format(manifest))
        imported = 0
        errors: List[str] = []
        with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                try:
                    part = str(row.get("part") or "").strip()
                    split = str(row.get("split") or "anomaly").strip().lower()
                    query = self._manifest_path(dataset_root, str(row.get("query_image") or ""))
                    source = self._manifest_path(dataset_root, str(row.get("reference_image") or row.get("original_image") or ""))
                    if source is None or not source.is_file():
                        source = self._manifest_path(dataset_root, str(row.get("original_image") or ""))
                    if not part or source is None or query is None or not source.is_file() or not query.is_file():
                        raise FileNotFoundError("part/source/query 缺失")
                    with Image.open(source) as opened:
                        width, height = opened.size
                    sample_id = safe_id("manifest::{}::{}".format(part, split))
                    label = self._manifest_label(row)
                    sample_dir = (dataset_root / part).resolve()
                    self.db.upsert_sample(
                        {
                            "id": sample_id, "relative_json": part, "json_path": str(manifest.resolve()),
                            "image_path": str(source), "sample_dir": str(sample_dir), "split": split,
                            "source_mode": "manifest_review", "labels_json": json.dumps([label], ensure_ascii=False),
                            "shapes_json": "[]", "warnings_json": json.dumps(["REVIEW_ONLY_NO_LABELME_ROI"], ensure_ascii=False),
                            "width": width, "height": height,
                        }
                    )
                    current = self.db.get_sample(sample_id)
                    attempt_dir = self.paths["intermediate"] / "samples" / sample_id / "import_001"
                    attempt_dir.mkdir(parents=True, exist_ok=True)
                    local_mask = attempt_dir / "imported_mask.png"
                    source_mask = self._manifest_path(dataset_root, str(row.get("mask_image") or ""))
                    if not local_mask.is_file():
                        if source_mask is not None and source_mask.is_file():
                            with Image.open(source_mask) as opened:
                                imported_mask = opened.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="L")
                            imported_mask.save(local_mask, format="PNG")
                        else:
                            Image.new("L", (width, height), 0).save(local_mask, format="PNG")
                    if int(current["active_attempt"]) <= 0:
                        prompt_path = attempt_dir / "prompt.txt"
                        prompt_path.write_text("从 dataset_manifest.csv 导入的既有样本，仅供人工审核；无 LabelMe ROI，不自动重生成。\n", encoding="utf-8")
                        qc = {"passed": True, "imported_manifest": True, "generation_enabled": False, "failures": []}
                        self.db.add_attempt(
                            {
                                "sample_id": sample_id, "attempt": 1, "prompt_path": str(prompt_path),
                                "roi_mask_path": str(local_mask), "raw_output_path": str(query), "candidate_path": str(query),
                                "mask_path": str(local_mask), "references": [str(source)], "qc": qc, "status": "ready",
                                "workflow": "normal_review" if split == "normal" else "anomaly_review",
                            }
                        )
                    else:
                        self.db.refresh_imported_attempt_paths(sample_id, int(current["active_attempt"]), query, local_mask)
                    imported += 1
                except Exception as exc:
                    errors.append("manifest line {}: {}".format(row_number, exc))
        self.db.record_scan_errors(errors)
        self.export_results_csv()
        return {"samples": imported, "mode": "manifest_review", "errors": errors, "unknown_labels": 0, "empty_shapes": 0}

    def _sample_from_row(self, row: Dict[str, Any]) -> LabelMeSample:
        from .labelme import LabelShape

        shapes = [
            LabelShape(label=item["label"], shape_type=item["shape_type"], points=[tuple(p) for p in item["points"]], index=int(item["index"]))
            for item in row["shapes"]
        ]
        return LabelMeSample(
            sample_id=row["id"], json_path=Path(row["json_path"]), image_path=Path(row["image_path"]),
            relative_json=row["relative_json"], width=int(row["width"]), height=int(row["height"]),
            shapes=shapes, labels=list(row["labels"]), warnings=list(row["warnings"]),
        )

    def _latest_feedback(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "reason_codes": list(row.get("anomaly_reason_codes") or []),
            "comment": str(row.get("anomaly_comment") or ""),
        }

    @staticmethod
    def _render_agent_regions(size: tuple[int, int], regions: Iterable[Dict[str, Any]]) -> tuple[Image.Image, List[Dict[str, Any]]]:
        """Rasterize agent-supplied absolute pixel geometry defensively."""
        width, height = size
        combined = Image.new("L", size, 0)
        accepted: List[Dict[str, Any]] = []
        for raw in regions:
            if not isinstance(raw, dict):
                continue
            shape = str(raw.get("shape") or "polygon").lower()
            points: List[tuple[float, float]] = []
            for point in raw.get("points") or []:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                try:
                    x = max(0.0, min(float(width - 1), float(point[0])))
                    y = max(0.0, min(float(height - 1), float(point[1])))
                except (TypeError, ValueError):
                    continue
                points.append((x, y))
            if (shape == "polygon" and len(points) < 3) or (shape in {"rectangle", "ellipse"} and len(points) < 2):
                continue
            layer = Image.new("L", size, 0)
            draw = ImageDraw.Draw(layer)
            if shape == "polygon":
                draw.polygon(points, fill=255)
            else:
                xs = [point[0] for point in points]
                ys = [point[1] for point in points]
                box = (min(xs), min(ys), max(xs), max(ys))
                if box[2] <= box[0] or box[3] <= box[1]:
                    continue
                if shape == "ellipse":
                    draw.ellipse(box, fill=255)
                else:
                    shape = "rectangle"
                    draw.rectangle(box, fill=255)
            padding = max(0, min(256, int(raw.get("padding_px") or 0)))
            if padding:
                layer = expand_binary_mask(layer, padding)
            if layer.getbbox() is None:
                continue
            combined = ImageChops.lighter(combined, layer)
            accepted.append(
                {
                    "shape": shape, "points": [[round(x, 2), round(y, 2)] for x, y in points],
                    "padding_px": padding, "purpose": str(raw.get("purpose") or "")[:500],
                    "raster_bbox": list(layer.getbbox() or ()),
                }
            )
        return combined, accepted

    def generation_masks(
        self,
        row: Dict[str, Any],
        scale: str = "normal",
        geometry: str = "",
        mask_spec: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """Return LabelMe focus and the wider context-aware CORE edit region."""
        sample = self._sample_from_row(row)
        generation = self.config.get("generation", {})
        minimum = int(
            generation.get("edit_context_min_padding_px")
            or generation.get("roi_padding_px")
            or 0
        )
        ratio = float(
            generation.get("edit_context_padding_ratio")
            if generation.get("edit_context_padding_ratio") is not None
            else generation.get("roi_padding_ratio") or 0.0
        )
        scale_factors = {"tight": 0.55, "normal": 1.0, "wide": 1.55, "very_wide": 2.2}
        factor = scale_factors.get(str(scale), 1.0)
        focus, rounded, meta = build_edit_context_mask(sample, max(16, round(minimum * factor)), ratio * factor)
        if not geometry:
            operations = {str(self.knowledge.label(code).get("operation") or "") for code in row.get("labels") or []}
            geometry = "rounded_context" if operations.intersection({"remove", "remove_large_part", "displace", "reorient"}) else "focus_dilation"
        if geometry == "focus_dilation" and focus.getbbox() is not None:
            padding = int(meta.get("padding_px") or 0)
            edit = expand_binary_mask(focus, padding)
            meta["edit_bbox"] = list(edit.getbbox()) if edit.getbbox() else None
        else:
            geometry = "rounded_context"
            edit = rounded
        requested_regions = list((mask_spec or {}).get("mask_regions") or [])
        requested_protected = list((mask_spec or {}).get("protected_regions") or [])
        if requested_regions:
            semantic, accepted_regions = self._render_agent_regions(focus.size, requested_regions)
            protected, accepted_protected = self._render_agent_regions(focus.size, requested_protected)
            semantic = ImageChops.multiply(semantic, rounded)
            if protected.getbbox() is not None:
                semantic = ImageChops.multiply(semantic, ImageChops.invert(protected))
            semantic = semantic.point(lambda value: 255 if value >= 128 else 0, mode="L")
            pixels = int(semantic.histogram()[255])
            intersects_focus = ImageChops.multiply(semantic, focus).getbbox() is not None
            if pixels >= 64 and intersects_focus and accepted_regions:
                edit = semantic
                geometry = "agent_regions"
                meta.update(
                    {
                        "agent_mask_applied": True,
                        "agent_mask_regions": accepted_regions,
                        "agent_protected_regions": accepted_protected,
                        "agent_mask_pixels": pixels,
                        "edit_bbox": list(edit.getbbox()) if edit.getbbox() else None,
                    }
                )
            else:
                meta.update(
                    {
                        "agent_mask_applied": False,
                        "agent_mask_rejection": "empty_or_misaligned",
                        "agent_mask_pixels": pixels,
                    }
                )
        meta["strategy_scale"] = str(scale) if str(scale) in scale_factors else "normal"
        meta["geometry"] = geometry
        return focus, edit, meta

    def approved_reference_paths(self, labels: Iterable[str], limit: int, exclude_sample_id: str = "") -> List[Path]:
        wanted = {self.knowledge.resolve_label(code) for code in labels}
        output: List[Path] = []
        for candidate in reversed(self.db.list_samples()):
            if candidate["id"] == exclude_sample_id or candidate.get("anomaly_status") != "approved":
                continue
            if not wanted.intersection({self.knowledge.resolve_label(code) for code in candidate.get("labels") or []}):
                continue
            attempt = self.db.active_attempt(candidate["id"])
            if attempt:
                path = Path(attempt["candidate_path"])
                if path.is_file() and path not in output:
                    output.append(path)
            if len(output) >= limit:
                break
        return output

    def feedback_memory(self, row: Dict[str, Any], limit: int = 5) -> List[str]:
        wanted = {self.knowledge.resolve_label(code) for code in row.get("labels") or []}
        rows: List[str] = []
        for other in reversed(self.db.list_samples()):
            if other["id"] == row["id"] or not str(other.get("anomaly_comment") or "").strip():
                continue
            if not wanted.intersection({self.knowledge.resolve_label(code) for code in other.get("labels") or []}):
                continue
            codes = "、".join(other.get("anomaly_reason_codes") or [])
            rows.append("{}：{}".format(codes or "审核经验", str(other["anomaly_comment"]).strip()[:600]))
            if len(rows) >= limit:
                break
        return rows

    def _labelme_for_core(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Compact the full LabelMe file without embedding imageData.

        The active per-shape task is marked explicitly; every other shape is
        retained as global context and marked do-not-edit.
        """
        payload = json.loads(Path(row["json_path"]).read_text(encoding="utf-8-sig"))
        active_indexes = {int(shape.get("index", -1)) for shape in row.get("shapes") or []}
        shapes: List[Dict[str, Any]] = []
        for index, raw in enumerate(payload.get("shapes") or []):
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or "")
            canonical = self.knowledge.resolve_label(label)
            shapes.append(
                {
                    "index": index,
                    "role": "ACTIVE_TARGET" if index in active_indexes else "CONTEXT_ONLY_DO_NOT_EDIT",
                    "label": label,
                    "canonical_label": canonical,
                    "shape_type": str(raw.get("shape_type") or "polygon"),
                    "points": raw.get("points") or [],
                    "group_id": raw.get("group_id"),
                }
            )
        return {
            "source_file": str(row["image_path"]),
            "labelme_file": str(row["json_path"]),
            "imagePath": payload.get("imagePath"),
            "imageWidth": int(payload.get("imageWidth") or row["width"]),
            "imageHeight": int(payload.get("imageHeight") or row["height"]),
            "active_shape_indexes": sorted(active_indexes),
            "shapes": shapes,
            "delivery": "serialized_verbatim_as_compact_JSON_inside_prompt",
        }

    @staticmethod
    def _input_file_record(path: Path) -> Dict[str, Any]:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        row: Dict[str, Any] = {
            "path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest.hexdigest(),
        }
        try:
            with Image.open(path) as opened:
                row.update({"image_size": list(opened.size), "image_mode": opened.mode})
        except Exception:
            pass
        return row

    def prepare_reference_candidates(
        self, examples: List[Dict[str, Any]], attempt_dir: Path
    ) -> tuple[List[Path], Dict[str, str], List[Dict[str, Any]]]:
        """Crop bank references around their annotated anomaly, retaining useful context.

        Passing an unlocated full reference caused the planner/CORE to learn a
        visually salient but unrelated dark component.  These crops make the
        labeled anomaly—not the surrounding train hardware—the visual lesson.
        """
        output_dir = attempt_dir / "reference_candidates"
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: List[Path] = []
        descriptions: Dict[str, str] = {}
        manifest: List[Dict[str, Any]] = []
        for index, example in enumerate(examples):
            source_path = Path(example["image"])
            prepared = output_dir / "reference_{:02d}.png".format(index + 1)
            with Image.open(source_path) as opened:
                image = opened.copy()
            points = [
                point
                for shape in example.get("shapes") or []
                for point in shape.get("points") or []
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]
            crop_box = [0, 0, image.width, image.height]
            if points:
                xs = [float(point[0]) for point in points]
                ys = [float(point[1]) for point in points]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
                span = max(1.0, bbox[2] - bbox[0], bbox[3] - bbox[1])
                padding = max(64, round(span * 0.65))
                crop_box = [
                    max(0, int(bbox[0] - padding)), max(0, int(bbox[1] - padding)),
                    min(image.width, int(bbox[2] + padding)), min(image.height, int(bbox[3] + padding)),
                ]
                image = image.crop(tuple(crop_box))
            if is_grayscale_visual(image):
                image = image.convert("L")
            else:
                image = image.convert("RGB")
            image.save(prepared, format="PNG", optimize=True)
            label = str(example.get("label") or "")
            if points:
                description = (
                    "知识库真实参考的 LabelMe 异常局部裁图；标签={}；原图裁剪框={}；"
                    "异常位于裁图中心附近，只学习该异常本体及其接触/流动形态，不学习裁图内其他正常结构。"
                ).format(label or "同类", json.dumps(crop_box, ensure_ascii=False))
            else:
                description = (
                    "历史人工通过的同标签生成样例；标签={}；没有可用的参考标注裁图，"
                    "仅辅助判断异常形态，不得复制其设备与背景。"
                ).format(label or "同类")
            paths.append(prepared)
            descriptions[str(prepared)] = description
            manifest.append(
                {
                    "prepared": str(prepared), "original": str(source_path),
                    "json": str(example.get("json") or ""), "label": label,
                    "source": str(example.get("source") or "reference_bank"),
                    "crop_box": crop_box, "annotated_shapes": example.get("shapes") or [],
                }
            )
        return paths, descriptions, manifest

    @staticmethod
    def _first_shape_index(row: Dict[str, Any]) -> int:
        indexes = [int(shape.get("index", 0)) for shape in row.get("shapes") or []]
        return min(indexes) if indexes else 0

    def generation_source(self, row: Dict[str, Any], attempt_dir: Path) -> tuple[Path, List[str]]:
        """Build a sequential multi-ROI base from earlier successful siblings."""
        mode = str(self.config.get("generation", {}).get("multi_roi_source_mode") or "independent")
        original = Path(row["image_path"])
        if mode != "sequential_success" or row.get("source_mode") != "labelme":
            return original, []
        current_index = self._first_shape_index(row)
        siblings = [
            sibling for sibling in self.db.list_samples()
            if sibling["id"] != row["id"]
            and sibling.get("source_mode") == "labelme"
            and str(sibling.get("json_path")) == str(row.get("json_path"))
            and self._first_shape_index(sibling) < current_index
        ]
        siblings.sort(key=self._first_shape_index)
        with Image.open(original) as opened:
            combined = opened.copy()
        dependencies: List[str] = []
        for sibling in siblings:
            attempt = self.db.active_attempt(sibling["id"])
            if not attempt or not bool((attempt.get("qc") or {}).get("passed", False)):
                continue
            candidate_path = Path(attempt["candidate_path"])
            mask_path = Path(attempt["mask_path"])
            if not candidate_path.is_file() or not mask_path.is_file():
                continue
            with Image.open(candidate_path) as opened:
                candidate = opened.convert(combined.mode)
            with Image.open(mask_path) as opened:
                mask = opened.convert("L")
            if candidate.size != combined.size or mask.size != combined.size:
                continue
            combined = Image.composite(candidate, combined, mask)
            for dependency in list(((attempt.get("qc") or {}).get("agent") or {}).get("base_dependencies") or []) + [sibling["id"]]:
                if dependency not in dependencies:
                    dependencies.append(dependency)
        if not dependencies:
            return original, []
        output = attempt_dir / "agent_sequential_source.png"
        if is_grayscale_visual(combined):
            combined = combined.convert("L")
        combined.save(output, format="PNG", optimize=True)
        return output, dependencies

    def failure_history_contact_sheet(
        self, sample_id: str, attempt_dir: Path, limit: int
    ) -> tuple[Optional[Path], List[Dict[str, Any]]]:
        attempts = [
            attempt for attempt in self.db.attempts_for_sample(sample_id, max(0, limit), descending=True)
            if not bool((attempt.get("qc") or {}).get("passed", False)) and Path(attempt["candidate_path"]).is_file()
        ]
        if not attempts:
            return None, []
        tiles: List[Image.Image] = []
        summaries: List[Dict[str, Any]] = []
        tile_width, tile_height = 480, 380
        for attempt in reversed(attempts):
            with Image.open(attempt["candidate_path"]) as opened:
                image = opened.convert("RGB")
            image.thumbnail((tile_width, tile_height - 34), LANCZOS)
            tile = Image.new("RGB", (tile_width, tile_height), (20, 20, 20))
            tile.paste(image, ((tile_width - image.width) // 2, 32 + (tile_height - 32 - image.height) // 2))
            qc = attempt.get("qc") or {}
            failures = [str(code) for code in qc.get("failures") or []]
            ImageDraw.Draw(tile).text((8, 8), "attempt {} | {}".format(attempt["attempt"], ",".join(failures)[:62]), fill=(245, 210, 120))
            tiles.append(tile)
            critic = (((qc.get("intelligence") or {}).get("critic") or {}).get("result") or {})
            summaries.append(
                {
                    "attempt": int(attempt["attempt"]), "failures": failures,
                    "reason_codes": critic.get("reason_codes") or [],
                    "diagnosis": str(critic.get("diagnosis") or qc.get("error") or "")[:800],
                }
            )
        columns = min(2, len(tiles))
        rows = (len(tiles) + columns - 1) // columns
        sheet = Image.new("RGB", (tile_width * columns, tile_height * rows), (8, 8, 8))
        for index, tile in enumerate(tiles):
            sheet.paste(tile, ((index % columns) * tile_width, (index // columns) * tile_height))
        path = attempt_dir / "agent_failure_history.png"
        sheet.save(path, format="PNG", optimize=True)
        return path, summaries

    def build_core_execution_prompt(
        self,
        row: Dict[str, Any],
        attempt: int,
        plan: Dict[str, Any],
        references: List[Path],
        reference_descriptions: Dict[str, str],
        mask_meta: Dict[str, Any],
        base_dependencies: List[str],
        candidate_index: int,
    ) -> str:
        """Distill the bank/planner output into a short executable CORE prompt."""
        label_rows = []
        for code in row.get("labels") or []:
            canonical = self.knowledge.resolve_label(code)
            info = self.knowledge.label(canonical)
            label_rows.append(
                {"code": code, "name": info.get("name_zh"), "object": info.get("object"), "operation": info.get("operation"),
                 "must": info.get("rules") or [], "forbidden": info.get("forbidden") or []}
            )
        directives = [str(value).strip() for value in plan.get("candidate_directives") or [] if str(value).strip()]
        fallback_directives = [
            "优先保证异常的物理形态、材料、接触、重力和遮挡真实。",
            "优先保证反事实一致性和背景逐像素保真，异常直接影响之外不重绘。",
            "在保持结构真实的前提下确保异常清楚可检测，避免过弱或缺失。",
        ]
        directive = directives[candidate_index] if candidate_index < len(directives) else fallback_directives[candidate_index % len(fallback_directives)]
        active_shapes = [
            {
                "index": int(shape.get("index", -1)), "label": shape.get("label"),
                "shape_type": shape.get("shape_type"), "points": shape.get("points") or [],
            }
            for shape in row.get("shapes") or []
        ]
        reference_lines = [
            "- Image {}：{}".format(index + 2, reference_descriptions.get(str(path), "同类异常参考，只学习异常本体。"))
            for index, path in enumerate(references)
        ]
        feedback = self._latest_feedback(row)
        if bool(mask_meta.get("agent_mask_applied", False)):
            mask_instruction = (
                "编辑Mask由视觉代理按实际目标拆成局部可执行岛，并已扣除硬保护区；它是本轮严格最大可改范围。"
                "必须只在Mask内完成异常本体、直接遮挡恢复、接触阴影或流动影响，不得把每个岛填满；"
                "Mask外以及被扣除的孔洞、边缘和相邻结构必须保持Image 1原像素。"
            )
        else:
            mask_instruction = (
                "编辑Mask是最大允许上下文，不是异常边界也不是异常轮廓；不要填满Mask。"
                "实际变化只能是异常本体及其直接遮挡、接触阴影、背景恢复或流动影响。"
                "Mask边缘必须保持Image 1不变。"
            )
        sections = [
            "你是工业异常图像编辑CORE。只输出编辑后的完整图像，不输出文字。",
            "Image 1 是本轮实际编辑基础图。必须保留其尺寸、视角、构图、灰度域、噪声和所有无关像素。{}".format(
                "其中已包含前序ROI异常，必须完整锁定且不得修复或覆盖：{}。".format("、".join(base_dependencies)) if base_dependencies else ""
            ),
            *(reference_lines or ["- 本轮没有外部异常参考；严格按实例计划执行，不得臆造结构。"]),
            "视觉LLM生成策略总控。当前任务：sample_id={}；{}。".format(
                row["id"], "；".join("shape_index={}".format(shape["index"]) for shape in active_shapes)
            ),
            "当前ACTIVE_TARGET：{}".format(json.dumps(active_shapes, ensure_ascii=False, separators=(",", ":"))),
            "标签执行规则：{}".format(json.dumps(label_rows, ensure_ascii=False, separators=(",", ":"))),
            mask_instruction,
            "视觉代理实例分析：场景={}；物理锚点={}。".format(plan.get("scene_analysis", ""), plan.get("physical_anchor", "")),
            "视觉代理执行指令：{}".format(plan.get("edit_instruction", "")),
            "本候选差异化侧重点：{}".format(directive),
            "必须保留：{}".format("；".join(str(value) for value in plan.get("must_preserve") or []) or "异常直接影响之外的全部内容"),
            "必须避免：{}".format("；".join(str(value) for value in plan.get("negative_patterns_to_avoid") or []) or "矩形贴片、结构重绘、灰度接缝"),
            "背景保持：{}".format(plan.get("background_preservation_plan", "异常以外严格恢复Image 1")),
            "编辑范围元数据：{}".format(json.dumps(mask_meta, ensure_ascii=False, separators=(",", ":"))),
            "审核修正：原因={}；说明={}".format("、".join(feedback["reason_codes"]), feedback["comment"][:1200]),
            "输出前自检：异常语义清楚且物理合理；去掉新增异常可恢复Image 1；没有矩形边、曝光块、色偏、无关结构变化；灰度源图保持严格灰度。",
            "逻辑轮次={}；候选={}. 仅返回完整编辑图像。".format(attempt, candidate_index + 1),
        ]
        return "\n\n".join(section for section in sections if section.strip()) + "\n"

    def process_agent_candidate(
        self,
        adapter: Any,
        source_path: Path,
        sample: LabelMeSample,
        row: Dict[str, Any],
        allowed: Image.Image,
        focus_path: Path,
        roi_path: Path,
        prompt_path: Path,
        raw_path: Path,
        candidate_path: Path,
        mask_path: Path,
        references: List[Path],
        plan: Dict[str, Any],
        candidate_dir: Path,
        attempt: int,
        progress: Optional[Callable[..., None]] = None,
        candidate_index: int = 0,
        candidate_count: int = 1,
    ) -> Dict[str, Any]:
        generation = self.config["generation"]
        if progress is not None:
            progress("core_request", candidate_index=candidate_index, candidate_count=candidate_count)
        adapter_meta = adapter.generate(CoreRequest(source_path, roi_path, prompt_path, raw_path, references, sample.sample_id, attempt))
        if progress is not None:
            progress("core_received", candidate_index=candidate_index, candidate_count=candidate_count)
        with Image.open(source_path) as opened:
            source = opened.copy()
        with Image.open(raw_path) as opened:
            generated = opened.copy()
        failures: List[str] = []
        normalizations: List[Dict[str, Any]] = []
        if generated.size != source.size:
            raw_size = generated.size
            source_ratio = source.width / max(1, source.height)
            generated_ratio = generated.width / max(1, generated.height)
            ratio_error = abs(generated_ratio - source_ratio) / max(source_ratio, 1e-9)
            if bool(generation.get("allow_size_normalization", True)) and ratio_error <= float(generation.get("size_aspect_tolerance", 0.02)):
                generated = generated.resize(source.size, Image.Resampling.LANCZOS)
                normalizations.append({"type": "resize_generated_before_roi_composite", "from": list(raw_size), "to": list(source.size), "aspect_error": ratio_error})
            else:
                failures.append("SIZE_MISMATCH")
                generated = source.copy()
        if is_grayscale_visual(source) and bool(generation.get("force_grayscale_if_source_is_grayscale", True)):
            source = source.convert("L")
            generated = generated.convert("L")
        elif generated.mode != source.mode:
            generated = generated.convert(source.mode)
        if bool(generation.get("local_tone_match", True)):
            generated, tone_meta = match_local_tone(source, generated, allowed, int(generation.get("tone_match_ring_px", 12)))
            normalizations.append({"type": "local_tone_match", **tone_meta})
        blend_mask = allowed
        edge_guard = int(generation.get("roi_edge_guard_px", 0))
        if edge_guard > 0:
            guard_size = min(63, edge_guard * 2 + 1)
            guarded = allowed.filter(ImageFilter.MinFilter(max(3, guard_size)))
            if guarded.getbbox() is not None:
                blend_mask = guarded
        feather = int(generation.get("roi_feather_px", 3))
        if feather > 0:
            blend_mask = ImageChops.multiply(blend_mask.filter(ImageFilter.GaussianBlur(feather)), allowed)
        candidate = Image.composite(generated, source, blend_mask)
        candidate.save(candidate_path, format="PNG")
        draft = binary_mask_from_difference(
            source, candidate, allowed, int(generation["auto_mask_min_difference"]), int(generation["auto_mask_dilate_px"]),
        )
        draft.save(mask_path, format="PNG")
        qc = qc_metrics(
            source, candidate, draft, allowed, adapter.name,
            float(generation.get("max_boundary_seam_mean", 2.5)), float(generation.get("max_boundary_seam_p95", 10.0)),
        )
        qc["failures"] = failures + qc["failures"]
        qc["normalizations"] = normalizations
        qc["core"] = adapter_meta
        candidate_intelligence: Dict[str, Any] = {}
        if self.intelligence is not None and bool(self.config.get("intelligence", {}).get("critic", True)) and adapter.name != "mock" and not qc["failures"]:
            try:
                if progress is not None:
                    progress("candidate_critic", candidate_index=candidate_index, candidate_count=candidate_count)
                roi_context_path = candidate_dir.parent.parent / "intelligence_roi_context.png"
                if not roi_context_path.is_file():
                    from .intelligence import build_roi_context
                    build_roi_context(source_path, roi_path, roi_context_path, focus_path)
                critic = self.intelligence.critique(
                    source_path, candidate_path, roi_context_path, sample.labels, plan, candidate_dir, references=references,
                )
                candidate_intelligence["critic"] = {"ok": True, "result": critic}
                if not bool(critic.get("pass", False)) and bool(self.config.get("intelligence", {}).get("critic_gate", True)):
                    qc["failures"].append("LLM_SEMANTIC_QC_FAILED")
                    qc["error"] = str(critic.get("diagnosis") or "视觉LLM判定候选不满足语义质量门槛")
            except Exception as exc:
                candidate_intelligence["critic"] = {"ok": False, "error": str(exc)}
                intelligence_config = self.config.get("intelligence", {})
                strict_agent = bool(intelligence_config.get("enabled", False) and intelligence_config.get("agentic_generation", False))
                if strict_agent or not bool(intelligence_config.get("fail_open", True)):
                    qc["failures"].append("LLM_CRITIC_ERROR")
        qc["intelligence"] = candidate_intelligence
        qc["passed"] = not qc["failures"]
        (candidate_dir / "qc.json").write_text(json.dumps(qc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if progress is not None:
            progress(
                "candidate_complete", candidate_index=candidate_index, candidate_count=candidate_count,
                candidate_passed=bool(qc["passed"]), candidate_failures=list(qc.get("failures") or []),
            )
        return qc

    def build_prompt_for_row(
        self,
        row: Dict[str, Any],
        attempt: Optional[int] = None,
        reason_codes: Optional[List[str]] = None,
        comment: Optional[str] = None,
        reference_paths: Optional[List[Path]] = None,
        reference_descriptions: Optional[Dict[str, str]] = None,
        mask_scale: str = "normal",
    ) -> str:
        """Build the exact per-ROI prompt used by CORE and UI preview."""
        feedback = self._latest_feedback(row)
        if reason_codes is not None:
            feedback["reason_codes"] = list(reason_codes)
        if comment is not None:
            feedback["comment"] = str(comment)
        attempt_number = int(attempt or self.db.next_attempt(row["id"]))
        references = list(reference_paths) if reference_paths is not None else self.knowledge.reference_paths(
            row["labels"], int(self.config["generation"].get("reference_count") or 0)
        )
        prompt = self.knowledge.build_prompt(
            row["labels"], attempt_number, feedback["reason_codes"], feedback["comment"]
        )
        shape_lines = []
        for shape in row.get("shapes") or []:
            points = [[round(float(point[0]), 2), round(float(point[1]), 2)] for point in shape.get("points") or []]
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            bbox = [min(xs), min(ys), max(xs), max(ys)] if xs and ys else []
            shape_lines.append(
                "- shape_index={}; label={}; shape_type={}; bbox={}; points={}".format(
                    int(shape.get("index", -1)), shape.get("label", ""), shape.get("shape_type", "polygon"),
                    json.dumps(bbox, ensure_ascii=False), json.dumps(points, ensure_ascii=False),
                )
            )
        _, _, mask_meta = self.generation_masks(row, mask_scale)
        memory = self.feedback_memory(row)
        roi_context = [
            "CORE实际输入与身份（必须严格按顺序理解）：",
            "- Image 1 = 待编辑的完整干净源图，包含全局机械结构与场景上下文；先从整图判断零件身份、遮挡、连接、重力与光照，再执行局部异常编辑。只能编辑Image 1，不得裁剪或重构整图。",
            *[
                "- Image {} = 同类异常参考图 {}；{}".format(
                    index + 2, path.name,
                    (reference_descriptions or {}).get(
                        str(path), "只学习异常的材质、形态和物理接触规律，禁止复制其设备结构或背景。"
                    ),
                )
                for index, path in enumerate(references)
            ],
            "- LabelMe标注是异常语义的重点关注区/定位锚点，不是异常边界，也不是唯一上下文。异常本体及其直接造成的遮挡恢复、接触阴影、流淌或相邻表面影响可以自然越过LabelMe框。",
            "- 随请求提交的透明mask是比LabelMe框更大的上下文编辑区：允许在其中完成结构重建和物理连续效果，但仍须以ACTIVE_TARGET为中心；mask边界绝不是物体轮廓，禁止填满编辑区或生成矩形贴片。",
            "- LabelMe标注不会作为彩框图片输入，而是以下完整紧凑JSON文本；ACTIVE_TARGET是本次重点，其余shape提供全局结构关系并且原则上保持不变。",
            json.dumps(self._labelme_for_core(row), ensure_ascii=False, separators=(",", ":")),
            "- 本次参考图数量={}；若为0，说明参考库没有该标签的合规样例，不得把其他类别当作参考。".format(len(references)),
            *(["- 同标签历史审核经验（只吸收规律，不复制具体图像）："] + ["  * " + item for item in memory] if memory else []),
            "",
            "程序指定的本次重点关注任务元数据：",
            "- sample_id={}".format(row["id"]),
            "- image_size={}x{}".format(int(row["width"]), int(row["height"])),
            "- labelme_focus_bbox={}".format(json.dumps(mask_meta.get("focus_bbox"), ensure_ascii=False)),
            "- core_edit_context_bbox={}; outward_padding_px={}".format(
                json.dumps(mask_meta.get("edit_bbox"), ensure_ascii=False), int(mask_meta.get("padding_px") or 0)
            ),
            *shape_lines,
            "上述坐标用于定位异常重点而非裁切编辑；实际上下文编辑范围以随请求提交的宽扩展透明mask为准。可以越过ACTIVE_TARGET框完成直接相关的合理变化，但不得改造无关零件或其他标注目标。",
        ]
        if bool(self.config.get("intelligence", {}).get("enabled", False)):
            roi_context.append("执行时，视觉LLM会读取源图和本ROI定位视图，追加实例级机械结构编辑计划；此处显示的是计划生成前的基础Prompt。")
        return prompt.rstrip() + "\n\n" + "\n".join(roi_context) + "\n"

    def _generate_sample_legacy(self, sample_id: str) -> Dict[str, Any]:
        row = self.db.get_sample(sample_id)
        if row["deleted"]:
            raise ValueError("样本已删除")
        if row.get("source_mode") != "labelme":
            self.db.set_workflow(sample_id, "hold")
            raise ValueError("该样本由既有清单导入且没有LabelMe ROI，不能安全自动重生成")
        if not row["shapes"] or self.knowledge.validate_labels(row["labels"]):
            self.db.set_workflow(sample_id, "hold")
            raise ValueError("样本没有有效shape或包含未知标签")
        attempt = self.db.next_attempt(sample_id)
        maximum = int(self.config["generation"].get("max_attempts") or 5)
        if attempt > maximum:
            self.db.set_workflow(sample_id, "hold")
            raise RuntimeError("已达到最大生成次数 {}".format(maximum))
        sample = self._sample_from_row(row)
        attempt_dir = self.paths["intermediate"] / "samples" / sample_id / "attempt_{:03d}".format(attempt)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        # A transport failure intentionally does not consume a logical
        # attempt, so the same directory can be reused.  Remove stale error
        # markers before the retry to keep the final audit unambiguous.
        for stale_name in ("intelligence_plan_error.json", "transport_error.json", "intelligence_comparison_error.json"):
            stale_path = attempt_dir / stale_name
            if stale_path.is_file():
                stale_path.unlink()
        focus_path = attempt_dir / "labelme_focus_mask.png"
        roi_path = attempt_dir / "core_edit_context_mask.png"
        prompt_path = attempt_dir / "prompt.txt"
        raw_path = attempt_dir / "core_raw.png"
        candidate_path = attempt_dir / "candidate.png"
        mask_path = attempt_dir / "mask_draft.png"
        generation = self.config["generation"]
        intelligence_config = self.config.get("intelligence", {})
        orchestrator_enabled = bool(intelligence_config.get("orchestrator", True))
        core_reference_count = int(generation.get("reference_count") or 2)
        candidate_limit = int(intelligence_config.get("reference_candidate_count") or 5) if orchestrator_enabled else core_reference_count
        reference_examples = self.knowledge.reference_examples(sample.labels, candidate_limit)
        approved_limit = int(intelligence_config.get("approved_example_count") or 0) if orchestrator_enabled else 0
        for approved in self.approved_reference_paths(sample.labels, approved_limit, sample_id):
            if not any(Path(example["image"]) == approved for example in reference_examples):
                reference_examples.append(
                    {"image": approved, "json": None, "label": "、".join(sample.labels), "shapes": [], "source": "approved_generation"}
                )
        reference_examples = reference_examples[:candidate_limit]
        reference_candidates, reference_descriptions, reference_manifest = self.prepare_reference_candidates(
            reference_examples, attempt_dir
        )
        if reference_candidates:
            rotation = ((attempt - 1) * core_reference_count) % len(reference_candidates)
            ordered = reference_candidates[rotation:] + reference_candidates[:rotation]
            references = ordered[:core_reference_count]
        else:
            references = []
        feedback_codes = set(row.get("anomaly_reason_codes") or [])
        fallback_scale = "normal"
        if feedback_codes.intersection({"BACKGROUND_CHANGED", "EDGE_ARTIFACT", "COLOR_SHIFT"}):
            fallback_scale = "tight"
        elif feedback_codes.intersection({"ANOMALY_TOO_SMALL", "ANOMALY_TOO_WEAK", "PARTIAL_REMOVAL", "WRONG_STRUCTURE", "OIL_TOO_SMALL"}):
            fallback_scale = "wide"
        focus, allowed, mask_meta = self.generation_masks(row, fallback_scale)
        focus.save(focus_path, format="PNG")
        allowed.save(roi_path, format="PNG")
        planning_prompt = self.build_prompt_for_row(
            row, attempt, reference_paths=reference_candidates,
            reference_descriptions=reference_descriptions, mask_scale=fallback_scale,
        )
        intelligence_meta: Dict[str, Any] = {}
        plan: Dict[str, Any] = {}
        if self.intelligence_startup_error:
            intelligence_meta["startup_error"] = self.intelligence_startup_error
        if self.intelligence is not None and bool(intelligence_config.get("planner", True)):
            try:
                previous_attempt = self.db.active_attempt(sample_id)
                failed_candidate = (
                    Path(previous_attempt["candidate_path"])
                    if orchestrator_enabled
                    and int(
                        intelligence_config.get("failed_example_count")
                        if intelligence_config.get("failed_example_count") is not None
                        else 1
                    ) > 0
                    and previous_attempt
                    and Path(previous_attempt["candidate_path"]).is_file()
                    else None
                )
                plan = self.intelligence.plan(
                    sample.image_path, roi_path, sample.labels, row.get("shapes") or [],
                    planning_prompt, reference_candidates, attempt_dir, focus_mask_path=focus_path,
                    failed_candidate_path=failed_candidate,
                )
                edit_instruction = str(plan.get("edit_instruction") or "").strip()
                if not edit_instruction:
                    raise ValueError("智能规划结果缺少edit_instruction")
                selected_indices = []
                for value in plan.get("selected_reference_indices") or []:
                    index = int(value)
                    if 0 <= index < len(reference_candidates) and index not in selected_indices:
                        selected_indices.append(index)
                if selected_indices and orchestrator_enabled:
                    references = [reference_candidates[index] for index in selected_indices[:core_reference_count]]
                strategy_scale = str(plan.get("edit_context_scale") or fallback_scale)
                if not orchestrator_enabled or strategy_scale not in {"tight", "normal", "wide", "very_wide"}:
                    strategy_scale = fallback_scale
                focus, allowed, mask_meta = self.generation_masks(row, strategy_scale)
                focus.save(focus_path, format="PNG")
                allowed.save(roi_path, format="PNG")
                if bool(mask_meta.get("agent_mask_applied", False)):
                    allowed.save(attempt_dir / "agent_semantic_mask.png", format="PNG")
                intelligence_meta["planner"] = {"ok": True, "result": plan}
            except Exception as exc:
                intelligence_meta["planner"] = {"ok": False, "error": str(exc)}
                (attempt_dir / "intelligence_plan_error.json").write_text(
                    json.dumps(intelligence_meta["planner"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                if not bool(intelligence_config.get("fail_open", True)):
                    raise
        prompt = self.build_prompt_for_row(
            row, attempt, reference_paths=references, reference_descriptions=reference_descriptions,
            mask_scale=str(mask_meta.get("strategy_scale") or fallback_scale)
        )
        if plan:
            prompt += "\n\n视觉LLM生成策略总控：\n- 场景分析：{}\n- 物理锚点/泄漏源：{}\n- 参考选择理由：{}\n- 必须避免的失败形态：{}\n- 背景保持计划：{}\n- 策略摘要：{}\n- 重试动作：{}\n- 编辑范围：{}\n- CORE执行指令：{}\n".format(
                str(plan.get("scene_analysis") or "按完整源图识别当前结构"),
                str(plan.get("physical_anchor") or "围绕ACTIVE_TARGET的真实接触结构"),
                str(plan.get("reference_rationale") or "按标注异常局部选择同类参考"),
                "；".join(str(value) for value in plan.get("negative_patterns_to_avoid") or []) or "矩形贴片、灰度接缝、无关结构变化",
                str(plan.get("background_preservation_plan") or "异常直接影响之外逐像素保持源图"),
                str(plan.get("strategy_summary") or "本轮按当前结构重新规划"),
                str(plan.get("retry_action") or "initial"), str(mask_meta.get("strategy_scale") or fallback_scale),
                str(plan.get("edit_instruction") or "").strip(),
            )
        prompt_path.write_text(prompt, encoding="utf-8")
        labelme_core_path = attempt_dir / "labelme_for_core.json"
        labelme_core_path.write_text(
            json.dumps(self._labelme_for_core(row), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        input_manifest_path = attempt_dir / "input_manifest.json"
        input_manifest = {
            "sample_id": sample_id,
            "attempt": attempt,
            "strategy": {
                "fallback_edit_context_scale": fallback_scale,
                "final_edit_context_scale": str(mask_meta.get("strategy_scale") or fallback_scale),
                "reference_candidates": [self._input_file_record(path) for path in reference_candidates],
                "reference_candidate_provenance": reference_manifest,
                "selected_reference_indices": [
                    reference_candidates.index(path) for path in references if path in reference_candidates
                ],
                "planner_result": plan,
                "previous_failed_candidate": (
                    self._input_file_record(failed_candidate)
                    if 'failed_candidate' in locals() and failed_candidate is not None and failed_candidate.is_file()
                    else None
                ),
            },
            "image_order": [
                {"index": 1, "role": "EDIT_SOURCE_FULL_CONTEXT", **self._input_file_record(sample.image_path)},
                *[
                    {"index": index + 2, "role": "ANOMALY_REFERENCE_ONLY", **self._input_file_record(path)}
                    for index, path in enumerate(references)
                ],
            ],
            "roi_mask": self._input_file_record(roi_path),
            "labelme_focus_mask": self._input_file_record(focus_path),
            "mask_relationship": {
                "labelme_focus": "semantic target anchor; anomaly may cross it when physically required",
                "core_edit_context": "broader allowed edit region submitted as the Image Edits alpha mask",
                **mask_meta,
            },
            "labelme_original": self._input_file_record(sample.json_path),
            "labelme_delivery": "compact JSON serialized into prompt.txt",
            "labelme_for_core": self._input_file_record(labelme_core_path),
            "prompt": self._input_file_record(prompt_path),
            "core_model": str(self.config.get("core", {}).get("model") or ""),
            "core_quality": str(self.config.get("core", {}).get("quality") or ""),
        }
        input_manifest_path.write_text(json.dumps(input_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        job = {
            "sample_id": sample_id,
            "attempt": attempt,
            "source": str(sample.image_path),
            "labelme": str(sample.json_path),
            "labels": sample.labels,
            "roi_mask": str(roi_path),
            "labelme_focus_mask": str(focus_path),
            "mask_relationship": mask_meta,
            "prompt": str(prompt_path),
            "references": [str(path) for path in references],
            "reference_candidates": [str(path) for path in reference_candidates],
            "generation_strategy": plan,
            "labelme_for_core": str(labelme_core_path),
            "input_manifest": str(input_manifest_path),
            "intelligence": intelligence_meta,
            "created_at": now_iso(),
        }
        (attempt_dir / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        adapter = create_adapter(self.config)
        adapter_meta: Dict[str, Any] = {}
        try:
            adapter_meta = adapter.generate(
                CoreRequest(sample.image_path, roi_path, prompt_path, raw_path, references, sample_id, attempt)
            )
            with Image.open(sample.image_path) as opened:
                source = opened.copy()
            with Image.open(raw_path) as opened:
                generated = opened.copy()
            failures: List[str] = []
            normalizations: List[Dict[str, Any]] = []
            if generated.size != source.size:
                raw_size = generated.size
                source_ratio = source.width / max(1, source.height)
                generated_ratio = generated.width / max(1, generated.height)
                ratio_error = abs(generated_ratio - source_ratio) / max(source_ratio, 1e-9)
                if bool(generation.get("allow_size_normalization", True)) and ratio_error <= float(generation.get("size_aspect_tolerance", 0.02)):
                    generated = generated.resize(source.size, Image.Resampling.LANCZOS)
                    normalizations.append(
                        {"type": "resize_generated_before_roi_composite", "from": list(raw_size), "to": list(source.size), "aspect_error": ratio_error}
                    )
                else:
                    failures.append("SIZE_MISMATCH")
                    generated = source.copy()
            source_gray = is_grayscale_visual(source)
            if source_gray and bool(generation["force_grayscale_if_source_is_grayscale"]):
                source = source.convert("L")
                generated = generated.convert("L")
            elif generated.mode != source.mode:
                generated = generated.convert(source.mode)
            if bool(generation.get("local_tone_match", True)):
                generated, tone_meta = match_local_tone(
                    source, generated, allowed, int(generation.get("tone_match_ring_px", 12))
                )
                normalizations.append({"type": "local_tone_match", **tone_meta})
            blend_mask = allowed
            edge_guard = int(generation.get("roi_edge_guard_px", 0))
            if edge_guard > 0:
                guard_size = min(63, edge_guard * 2 + 1)
                guarded = allowed.filter(ImageFilter.MinFilter(max(3, guard_size)))
                if guarded.getbbox() is not None:
                    blend_mask = guarded
            feather = int(generation.get("roi_feather_px", 3))
            if feather > 0:
                blend_mask = blend_mask.filter(ImageFilter.GaussianBlur(feather))
                blend_mask = ImageChops.multiply(blend_mask, allowed)
            candidate = Image.composite(generated, source, blend_mask)
            candidate.save(candidate_path, format="PNG")
            draft = binary_mask_from_difference(
                source, candidate, allowed,
                int(generation["auto_mask_min_difference"]), int(generation["auto_mask_dilate_px"]),
            )
            draft.save(mask_path, format="PNG")
            qc = qc_metrics(
                source, candidate, draft, allowed, adapter.name,
                float(generation.get("max_boundary_seam_mean", 2.5)),
                float(generation.get("max_boundary_seam_p95", 10.0)),
            )
            qc["failures"] = failures + qc["failures"]
            qc["passed"] = not qc["failures"]
            qc["normalizations"] = normalizations
            qc["core"] = adapter_meta
            critic_result: Dict[str, Any] = {}
            if (
                self.intelligence is not None
                and bool(self.config.get("intelligence", {}).get("critic", True))
                and adapter.name != "mock"
                and not qc["failures"]
            ):
                try:
                    roi_context_path = attempt_dir / "intelligence_roi_context.png"
                    if not roi_context_path.is_file():
                        from .intelligence import build_roi_context
                        build_roi_context(sample.image_path, roi_path, roi_context_path, focus_path)
                    critic_result = self.intelligence.critique(
                        sample.image_path, candidate_path, roi_context_path, sample.labels, plan, attempt_dir,
                        references=references,
                    )
                    intelligence_meta["critic"] = {"ok": True, "result": critic_result}
                    if not bool(critic_result.get("pass", False)) and bool(self.config.get("intelligence", {}).get("critic_gate", True)):
                        qc["failures"].append("LLM_SEMANTIC_QC_FAILED")
                        qc["error"] = str(critic_result.get("diagnosis") or "视觉LLM判定候选不满足语义质量门槛")
                except Exception as exc:
                    intelligence_meta["critic"] = {"ok": False, "error": str(exc)}
                    (attempt_dir / "intelligence_critic_error.json").write_text(
                        json.dumps(intelligence_meta["critic"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )
                    if not bool(self.config.get("intelligence", {}).get("fail_open", True)):
                        qc["failures"].append("LLM_CRITIC_ERROR")
            qc["intelligence"] = intelligence_meta
            qc["passed"] = not qc["failures"]
            workflow = "anomaly_review" if qc["passed"] else ("core_not_configured" if "CORE_NOT_CONFIGURED" in qc["failures"] else "qc_failed")
            status = "ready" if qc["passed"] else "failed"
        except Exception as exc:
            with Image.open(sample.image_path) as opened:
                fallback = opened.convert("L") if is_grayscale_visual(opened) else opened.convert("RGB")
                fallback.save(candidate_path, format="PNG")
            Image.new("L", (sample.width, sample.height), 0).save(mask_path)
            qc = {"passed": False, "failures": ["CORE_ERROR"], "error": str(exc)}
            workflow = "qc_failed"
            status = "failed"
        (attempt_dir / "qc.json").write_text(json.dumps(qc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.db.add_attempt(
            {
                "sample_id": sample_id, "attempt": attempt, "prompt_path": str(prompt_path), "roi_mask_path": str(roi_path),
                "raw_output_path": str(raw_path), "candidate_path": str(candidate_path), "mask_path": str(mask_path),
                "references": [str(path) for path in references], "qc": qc, "status": status, "workflow": workflow,
            }
        )
        critic_payload = (qc.get("intelligence") or {}).get("critic", {}).get("result", {})
        if workflow == "qc_failed" and isinstance(critic_payload, dict) and critic_payload and not critic_payload.get("pass", False):
            codes = [str(code) for code in critic_payload.get("reason_codes") or []]
            if not codes:
                codes = ["OTHER"]
            diagnosis = str(critic_payload.get("diagnosis") or "").strip()
            revision = str(critic_payload.get("revision_instruction") or "").strip()
            comment = "视觉LLM质检：{}\n下一轮修正：{}".format(diagnosis, revision).strip()
            self.db.save_generation_feedback(sample_id, codes, comment)
        elif workflow == "qc_failed":
            failure_codes = [str(code) for code in qc.get("failures") or []]
            reason_map = {
                "EMPTY_CHANGE": "ANOMALY_TOO_WEAK",
                "CHANGE_TOO_LARGE": "BACKGROUND_CHANGED",
                "CHANGE_TOUCHES_BORDER": "EDGE_ARTIFACT",
                "SIZE_MISMATCH": "BACKGROUND_CHANGED",
                "ROI_TONE_SEAM": "BACKGROUND_CHANGED",
                "CORE_ERROR": "OTHER",
                "LLM_CRITIC_ERROR": "OTHER",
            }
            feedback_codes = sorted({reason_map.get(code, "OTHER") for code in failure_codes}) or ["OTHER"]
            detail = str(qc.get("error") or "").strip()
            correction = {
                "EMPTY_CHANGE": "上一轮几乎没有有效异常变化；下一轮必须生成清晰可见且符合标签的异常。",
                "CHANGE_TOO_LARGE": "上一轮改动范围过大；下一轮只编辑ACTIVE_TARGET对应局部并完整保持外围结构。",
                "CHANGE_TOUCHES_BORDER": "上一轮改动触及图像边界；下一轮异常必须完全位于允许区域内部。",
                "SIZE_MISMATCH": "上一轮输出几何尺寸不兼容；下一轮保持与Image 1一致的构图和比例。",
                "ROI_TONE_SEAM": "上一轮编辑区边缘存在灰度或曝光接缝；下一轮保持mask边缘源图像素和局部灰度完全连续，禁止矩形亮度块。",
                "CORE_ERROR": "上一轮CORE请求失败；重试时保持相同任务定义。",
            }
            instructions = [correction[code] for code in failure_codes if code in correction]
            comment = "自动质检失败：{}。{}{}".format(
                "、".join(failure_codes), " ".join(instructions), (" 错误详情：" + detail) if detail else ""
            ).strip()
            self.db.save_generation_feedback(sample_id, feedback_codes, comment)
        self.export_results_csv()
        return {"sample_id": sample_id, "attempt": attempt, "workflow": workflow, "qc": qc}

    def prepare_batch_plans(
        self,
        sample_ids: Iterable[str],
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        intelligence_client: Optional[Any] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Pre-plan one or more ROIs from one source image.

        ``intelligence_client`` lets the queue use a dedicated HTTP client for
        look-ahead planning while the main client is critiquing the current
        CORE result. Separate clients avoid sharing urllib opener state across
        threads while keeping the generated plan format identical.
        """
        ids = list(dict.fromkeys(str(value) for value in sample_ids))
        intel = self.config.get("intelligence", {})
        planner_client = intelligence_client or self.intelligence
        if not ids or planner_client is None or not bool(intel.get("planner", True)):
            return {}
        rows = [self.db.get_sample(sample_id) for sample_id in ids]
        source_paths = {str(Path(row["image_path"]).resolve()).lower() for row in rows}
        if len(source_paths) != 1:
            raise ValueError("批量规划仅允许同一源图的ROI")
        maximum = int(self.config["generation"].get("max_attempts") or 5)
        attempts = {row["id"]: self.db.next_attempt(row["id"]) for row in rows}
        if any(attempt > maximum for attempt in attempts.values()):
            raise RuntimeError("批量规划中有ROI达到最大逻辑生成次数 {}".format(maximum))
        signature = "|".join("{}:{}".format(row["id"], attempts[row["id"]]) for row in rows)
        batch_id = safe_id("batch_plan::{}::{}".format(rows[0]["image_path"], signature))
        batch_dir = self.paths["intermediate"] / "batch_plans" / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        generation = self.config["generation"]
        orchestrator = bool(intel.get("orchestrator", True))
        core_reference_count = int(generation.get("reference_count") or 2)
        configured_reference_limit = int(intel.get("reference_candidate_count") or 5) if orchestrator else core_reference_count
        batch_reference_limit = max(1, min(configured_reference_limit, int(intel.get("batch_reference_candidate_count") or 3)))
        items: List[Dict[str, Any]] = []

        for row in rows:
            sample_id = row["id"]
            attempt = attempts[sample_id]
            attempt_dir = self.paths["intermediate"] / "samples" / sample_id / "attempt_{:03d}".format(attempt)
            attempt_dir.mkdir(parents=True, exist_ok=True)
            sample = self._sample_from_row(row)
            planning_source, _ = self.generation_source(row, attempt_dir)
            examples = self.knowledge.reference_examples(sample.labels, batch_reference_limit)
            for approved in self.approved_reference_paths(sample.labels, int(intel.get("approved_example_count") or 0), sample_id):
                if not any(Path(example["image"]) == approved for example in examples):
                    examples.append(
                        {"image": approved, "json": None, "label": "、".join(sample.labels), "shapes": [], "source": "approved_generation"}
                    )
            examples = examples[:batch_reference_limit]
            references, descriptions, _ = self.prepare_reference_candidates(examples, attempt_dir)
            feedback_codes = set(row.get("anomaly_reason_codes") or [])
            if feedback_codes.intersection({"BACKGROUND_CHANGED", "EDGE_ARTIFACT", "COLOR_SHIFT"}):
                fallback_scale = "tight"
            elif feedback_codes.intersection({"ANOMALY_TOO_SMALL", "ANOMALY_TOO_WEAK", "PARTIAL_REMOVAL", "WRONG_STRUCTURE", "OIL_TOO_SMALL"}):
                fallback_scale = "wide"
            else:
                fallback_scale = "normal"
            focus, allowed, _ = self.generation_masks(row, fallback_scale)
            focus_path = attempt_dir / "labelme_focus_mask.png"
            roi_path = attempt_dir / "core_edit_context_mask.png"
            focus.save(focus_path, format="PNG")
            allowed.save(roi_path, format="PNG")
            failure_sheet, failure_history = self.failure_history_contact_sheet(
                sample_id, attempt_dir, int(intel.get("recent_failure_memory") or 0)
            )
            planning_prompt = self.build_prompt_for_row(
                row,
                attempt,
                reference_paths=references,
                reference_descriptions=descriptions,
                mask_scale=fallback_scale,
            )
            if failure_history:
                planning_prompt += "\n\n最近失败轮次记忆：\n{}\n不得在这些失败模式之间循环。\n".format(
                    json.dumps(failure_history, ensure_ascii=False, indent=2)
                )
            items.append(
                {
                    "roi_id": sample_id,
                    "source_path": planning_source,
                    "roi_mask_path": roi_path,
                    "focus_mask_path": focus_path,
                    "labels": sample.labels,
                    "shapes": row.get("shapes") or [],
                    "base_prompt": planning_prompt,
                    "references": references,
                    "failed_candidate_path": failure_sheet,
                }
            )
            if progress_callback is not None:
                progress_callback(sample_id, {"stage": "batch_planning", "attempt": attempt, "batch_size": len(rows)})

        plans = planner_client.plan_batch(Path(rows[0]["image_path"]), items, batch_dir)
        shared_audit = batch_dir / "intelligence_batch_plan.json"
        for row in rows:
            sample_id = row["id"]
            attempt_dir = self.paths["intermediate"] / "samples" / sample_id / "attempt_{:03d}".format(attempts[sample_id])
            audit = {
                "request": {"batch_plan": str(shared_audit), "batch_id": batch_id, "roi_id": sample_id, "batch_size": len(rows)},
                "result": plans[sample_id],
                "response": {"shared_audit": str(shared_audit)},
            }
            (attempt_dir / "intelligence_plan.json").write_text(
                json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        return plans

    def generate_sample(
        self,
        sample_id: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        precomputed_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run one logical agent round, potentially using several CORE candidates."""
        def progress(stage: str, **details: Any) -> None:
            if progress_callback is None:
                return
            try:
                progress_callback({"sample_id": sample_id, "stage": stage, **details})
            except Exception:
                # UI progress must never affect the generation transaction.
                pass

        row = self.db.get_sample(sample_id)
        if row["deleted"]:
            raise ValueError("样本已删除")
        if row.get("source_mode") != "labelme":
            self.db.set_workflow(sample_id, "hold")
            raise ValueError("该样本没有LabelMe ROI，不能安全自动重生成")
        if not row.get("shapes") or self.knowledge.validate_labels(row.get("labels") or []):
            self.db.set_workflow(sample_id, "hold")
            raise ValueError("样本没有有效shape或包含未知标签")
        attempt = self.db.next_attempt(sample_id)
        maximum = int(self.config["generation"].get("max_attempts") or 5)
        if attempt > maximum:
            self.db.set_workflow(sample_id, "hold")
            raise RuntimeError("已达到最大逻辑生成次数 {}".format(maximum))
        progress("preparing", attempt=attempt)

        sample = self._sample_from_row(row)
        attempt_dir = self.paths["intermediate"] / "samples" / sample_id / "attempt_{:03d}".format(attempt)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        # Retryable transport failures do not consume a logical attempt, so
        # this directory may be reused by the next run.
        for stale_name in ("intelligence_plan_error.json", "transport_error.json", "intelligence_comparison_error.json"):
            stale_path = attempt_dir / stale_name
            if stale_path.is_file():
                stale_path.unlink()
        focus_path = attempt_dir / "labelme_focus_mask.png"
        roi_path = attempt_dir / "core_edit_context_mask.png"
        prompt_path = attempt_dir / "prompt.txt"
        raw_path = attempt_dir / "core_raw.png"
        candidate_path = attempt_dir / "candidate.png"
        mask_path = attempt_dir / "mask_draft.png"
        generation = self.config["generation"]
        intel = self.config.get("intelligence", {})
        orchestrator = bool(intel.get("orchestrator", True))
        agentic = bool(intel.get("enabled", False) and intel.get("agentic_generation", False))
        generation_source, base_dependencies = self.generation_source(row, attempt_dir)

        core_reference_count = int(generation.get("reference_count") or 2)
        reference_limit = int(intel.get("reference_candidate_count") or 5) if orchestrator else core_reference_count
        examples = self.knowledge.reference_examples(sample.labels, reference_limit)
        for approved in self.approved_reference_paths(sample.labels, int(intel.get("approved_example_count") or 0), sample_id):
            if not any(Path(example["image"]) == approved for example in examples):
                examples.append({"image": approved, "json": None, "label": "、".join(sample.labels), "shapes": [], "source": "approved_generation"})
        examples = examples[:reference_limit]
        reference_candidates, reference_descriptions, reference_manifest = self.prepare_reference_candidates(examples, attempt_dir)
        if reference_candidates:
            rotation = ((attempt - 1) * core_reference_count) % len(reference_candidates)
            ordered = reference_candidates[rotation:] + reference_candidates[:rotation]
            references = ordered[:core_reference_count]
        else:
            references = []

        feedback_codes = set(row.get("anomaly_reason_codes") or [])
        if feedback_codes.intersection({"BACKGROUND_CHANGED", "EDGE_ARTIFACT", "COLOR_SHIFT"}):
            fallback_scale = "tight"
        elif feedback_codes.intersection({"ANOMALY_TOO_SMALL", "ANOMALY_TOO_WEAK", "PARTIAL_REMOVAL", "WRONG_STRUCTURE", "OIL_TOO_SMALL"}):
            fallback_scale = "wide"
        else:
            fallback_scale = "normal"
        focus, allowed, mask_meta = self.generation_masks(row, fallback_scale)
        focus.save(focus_path, format="PNG")
        allowed.save(roi_path, format="PNG")

        failure_sheet, failure_history = self.failure_history_contact_sheet(
            sample_id, attempt_dir, int(intel.get("recent_failure_memory") or 0)
        )
        planning_prompt = self.build_prompt_for_row(
            row, attempt, reference_paths=reference_candidates,
            reference_descriptions=reference_descriptions, mask_scale=fallback_scale,
        )
        if failure_history:
            planning_prompt += "\n\n最近失败轮次记忆：\n{}\n不得在这些失败模式之间循环。\n".format(
                json.dumps(failure_history, ensure_ascii=False, indent=2)
            )
        intelligence_meta: Dict[str, Any] = {}
        plan: Dict[str, Any] = {}
        if self.intelligence_startup_error:
            intelligence_meta["startup_error"] = self.intelligence_startup_error
        if precomputed_plan is not None:
            plan = dict(precomputed_plan)
            intelligence_meta["planner"] = {"ok": True, "mode": "same_image_batch", "result": plan}
            progress("batch_plan_ready", attempt=attempt)
        elif self.intelligence is not None and bool(intel.get("planner", True)):
            try:
                progress("planning", attempt=attempt)
                plan = self.intelligence.plan(
                    generation_source, roi_path, sample.labels, row.get("shapes") or [], planning_prompt,
                    reference_candidates, attempt_dir, focus_mask_path=focus_path, failed_candidate_path=failure_sheet,
                )
                if not str(plan.get("edit_instruction") or "").strip():
                    raise ValueError("智能规划结果缺少edit_instruction")
                intelligence_meta["planner"] = {"ok": True, "mode": "single_roi", "result": plan}
            except Exception as exc:
                intelligence_meta["planner"] = {"ok": False, "error": str(exc)}
                (attempt_dir / "intelligence_plan_error.json").write_text(
                    json.dumps(intelligence_meta["planner"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                # In agentic mode the planner is a required control-plane
                # stage.  Continuing with a generic prompt would silently
                # revert to the old "LLM as prompt writer" pipeline.
                if agentic or not bool(intel.get("fail_open", True)):
                    raise
        if plan:
            try:
                if not str(plan.get("edit_instruction") or "").strip():
                    raise ValueError("智能规划结果缺少edit_instruction")
                selected_indices: List[int] = []
                for value in plan.get("selected_reference_indices") or []:
                    index = int(value)
                    if 0 <= index < len(reference_candidates) and index not in selected_indices:
                        selected_indices.append(index)
                if selected_indices and orchestrator:
                    references = [reference_candidates[index] for index in selected_indices[:core_reference_count]]
                scale = str(plan.get("edit_context_scale") or fallback_scale)
                if scale not in {"tight", "normal", "wide", "very_wide"}:
                    scale = fallback_scale
                focus, allowed, mask_meta = self.generation_masks(
                    row, scale, str(plan.get("mask_geometry") or ""), plan,
                )
                focus.save(focus_path, format="PNG")
                allowed.save(roi_path, format="PNG")
                if bool(mask_meta.get("agent_mask_applied", False)):
                    allowed.save(attempt_dir / "agent_semantic_mask.png", format="PNG")
                progress(
                    "mask_ready", attempt=attempt, mask_geometry=mask_meta.get("geometry"),
                    mask_pixels=int(mask_meta.get("agent_mask_pixels") or allowed.histogram()[255]),
                )
            except Exception as exc:
                intelligence_meta["planner"] = {"ok": False, "error": str(exc)}
                (attempt_dir / "intelligence_plan_error.json").write_text(
                    json.dumps(intelligence_meta["planner"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                if agentic or not bool(intel.get("fail_open", True)):
                    raise
        if not plan:
            plan = {
                "edit_instruction": "按当前标签在ACTIVE_TARGET附近生成清楚、物理合理的异常，并保持所有无关结构。",
                "must_preserve": ["异常直接影响之外的全部内容"],
                "negative_patterns_to_avoid": ["矩形贴片", "背景重绘", "灰度接缝"],
                "background_preservation_plan": "Mask边缘和异常之外严格使用Image 1",
                "candidate_directives": [],
            }

        labelme_core_path = attempt_dir / "labelme_for_core.json"
        labelme_core_path.write_text(json.dumps(self._labelme_for_core(row), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        adapter = create_adapter(self.config)
        requested = max(1, min(6, int(intel.get("candidate_count") or 3))) if agentic and adapter.name != "mock" else 1
        candidate_root = attempt_dir / "candidates"
        candidate_root.mkdir(parents=True, exist_ok=True)
        records: List[Dict[str, Any]] = []
        transport_errors: List[str] = []
        for candidate_index in range(requested):
            candidate_dir = candidate_root / "candidate_{:02d}".format(candidate_index + 1)
            candidate_dir.mkdir(parents=True, exist_ok=True)
            paths = {
                "prompt": candidate_dir / "prompt.txt", "raw": candidate_dir / "core_raw.png",
                "candidate": candidate_dir / "candidate.png", "mask": candidate_dir / "mask_draft.png",
            }
            paths["prompt"].write_text(
                self.build_core_execution_prompt(
                    row, attempt, plan, references, reference_descriptions, mask_meta, base_dependencies, candidate_index,
                ),
                encoding="utf-8",
            )
            try:
                candidate_qc = self.process_agent_candidate(
                    adapter, generation_source, sample, row, allowed, focus_path, roi_path,
                    paths["prompt"], paths["raw"], paths["candidate"], paths["mask"],
                    references, plan, candidate_dir, attempt, progress, candidate_index, requested,
                )
                records.append({"original_index": candidate_index, "dir": candidate_dir, **paths, "qc": candidate_qc})
                # Balanced mode generates alternatives only when the previous
                # candidate actually failed. This keeps candidate diversity as
                # a fallback without paying for redundant CORE + critic calls.
                if (
                    bool(candidate_qc.get("passed"))
                    and bool(intel.get("stop_after_first_passing_candidate", False))
                ):
                    break
            except CoreTransportError as exc:
                transport_errors.append(str(exc))
                (candidate_dir / "transport_error.json").write_text(
                    json.dumps({"retryable": True, "error": str(exc)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
        if not records:
            (attempt_dir / "transport_error.json").write_text(
                json.dumps({"retryable": True, "errors": transport_errors}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            raise CoreTransportError("所有候选均在传输阶段失败；本轮未创建图片版本")

        selected_position = next((index for index, record in enumerate(records) if bool(record["qc"].get("passed"))), 0)
        comparison: Dict[str, Any] = {}
        if agentic and bool(intel.get("comparative_critic", True)) and self.intelligence is not None and len(records) > 1:
            try:
                progress("comparing", attempt=attempt, candidate_count=len(records))
                roi_context_path = attempt_dir / "intelligence_roi_context.png"
                if not roi_context_path.is_file():
                    from .intelligence import build_roi_context
                    build_roi_context(generation_source, roi_path, roi_context_path, focus_path)
                reports = []
                for index, record in enumerate(records):
                    critic = (((record["qc"].get("intelligence") or {}).get("critic") or {}).get("result") or {})
                    reports.append(
                        {
                            "index": index, "program_failures": record["qc"].get("failures") or [],
                            "changed_area_fraction": record["qc"].get("changed_area_fraction"),
                            "boundary_seam": record["qc"].get("boundary_seam"), "semantic_critic": critic,
                        }
                    )
                comparison = self.intelligence.compare_candidates(
                    generation_source, roi_context_path, [record["candidate"] for record in records],
                    sample.labels, plan, reports, attempt_dir, references=references,
                )
                proposed = int(comparison.get("selected_index", selected_position))
                if 0 <= proposed < len(records):
                    selected_position = proposed
                intelligence_meta["comparison"] = {"ok": True, "result": comparison}
            except Exception as exc:
                intelligence_meta["comparison"] = {"ok": False, "error": str(exc)}
                if agentic or not bool(intel.get("fail_open", True)):
                    records[selected_position]["qc"]["failures"].append("LLM_CRITIC_ERROR")

        selected = records[selected_position]
        shutil.copy2(selected["prompt"], prompt_path)
        shutil.copy2(selected["raw"], raw_path)
        shutil.copy2(selected["candidate"], candidate_path)
        shutil.copy2(selected["mask"], mask_path)
        qc = dict(selected["qc"])
        selected_critic = ((qc.get("intelligence") or {}).get("critic") or {})
        if selected_critic:
            intelligence_meta["critic"] = selected_critic
        qc["intelligence"] = intelligence_meta
        if comparison and not bool(comparison.get("pass", False)):
            qc["failures"].append("LLM_COMPARATIVE_QC_FAILED")
            qc["error"] = str(comparison.get("diagnosis") or "多候选横向比较未达到准入标准")
        qc["agent"] = {
            "enabled": agentic, "logical_attempt": attempt, "requested_candidate_count": requested,
            "generated_candidate_count": len(records), "selected_candidate_index": selected_position,
            "transport_errors": transport_errors, "base_source": str(generation_source),
            "base_dependencies": base_dependencies, "failure_history": failure_history,
            "candidate_summaries": [
                {"index": index, "passed": bool(record["qc"].get("passed")), "failures": record["qc"].get("failures") or [], "path": str(record["candidate"])}
                for index, record in enumerate(records)
            ],
            "comparison": comparison,
        }
        qc["passed"] = not qc["failures"]
        workflow = "anomaly_review" if qc["passed"] else ("core_not_configured" if "CORE_NOT_CONFIGURED" in qc["failures"] else "qc_failed")
        status = "ready" if qc["passed"] else "failed"

        input_manifest_path = attempt_dir / "input_manifest.json"
        input_manifest = {
            "sample_id": sample_id, "logical_attempt": attempt,
            "pipeline_mode": "agentic_multi_candidate" if agentic else "single_candidate",
            "source_original": self._input_file_record(sample.image_path),
            "source_submitted": self._input_file_record(generation_source), "base_dependencies": base_dependencies,
            "strategy": {
                "fallback_edit_context_scale": fallback_scale, "final_edit_context_scale": mask_meta.get("strategy_scale"),
                "mask_geometry": mask_meta.get("geometry"), "planner_result": plan,
                "reference_candidates": [self._input_file_record(path) for path in reference_candidates],
                "reference_candidate_provenance": reference_manifest, "failure_history": failure_history,
            },
            "image_order": [
                {"index": 1, "role": "EDIT_SOURCE_FULL_CONTEXT", **self._input_file_record(generation_source)},
                *[{"index": index + 2, "role": "ANOMALY_REFERENCE_ONLY", **self._input_file_record(path)} for index, path in enumerate(references)],
            ],
            "roi_mask": self._input_file_record(roi_path), "labelme_focus_mask": self._input_file_record(focus_path),
            "mask_relationship": {
                "labelme_focus": "semantic target anchor; anomaly may cross it when physically required",
                "core_edit_context": "agent-selected maximum editable context", **mask_meta,
            },
            "labelme_original": self._input_file_record(sample.json_path), "labelme_for_core": self._input_file_record(labelme_core_path),
            "selected_prompt": self._input_file_record(prompt_path),
            "candidates": [
                {"index": index, "prompt": self._input_file_record(record["prompt"]), "candidate": self._input_file_record(record["candidate"]), "qc": record["qc"]}
                for index, record in enumerate(records)
            ],
            "selected_candidate_index": selected_position, "comparison": comparison,
            "core_model": str(self.config.get("core", {}).get("model") or ""), "core_quality": str(self.config.get("core", {}).get("quality") or ""),
        }
        input_manifest_path.write_text(json.dumps(input_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        job = {
            "sample_id": sample_id, "attempt": attempt, "source": str(generation_source), "source_original": str(sample.image_path),
            "base_dependencies": base_dependencies, "labelme": str(sample.json_path), "labels": sample.labels,
            "roi_mask": str(roi_path), "labelme_focus_mask": str(focus_path), "mask_relationship": mask_meta,
            "prompt": str(prompt_path), "references": [str(path) for path in references],
            "reference_candidates": [str(path) for path in reference_candidates], "generation_strategy": plan,
            "agent": qc["agent"], "labelme_for_core": str(labelme_core_path), "input_manifest": str(input_manifest_path),
            "intelligence": intelligence_meta, "created_at": now_iso(),
        }
        (attempt_dir / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (attempt_dir / "qc.json").write_text(json.dumps(qc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        progress("saving", attempt=attempt, workflow=workflow)
        self.db.add_attempt(
            {
                "sample_id": sample_id, "attempt": attempt, "prompt_path": str(prompt_path), "roi_mask_path": str(roi_path),
                "raw_output_path": str(raw_path), "candidate_path": str(candidate_path), "mask_path": str(mask_path),
                "references": [str(path) for path in references], "qc": qc, "status": status, "workflow": workflow,
            }
        )

        comparison_result = ((qc.get("intelligence") or {}).get("comparison") or {}).get("result") or {}
        critic_result = ((qc.get("intelligence") or {}).get("critic") or {}).get("result") or {}
        if workflow == "qc_failed" and comparison_result and not comparison_result.get("pass", False):
            codes = [str(code) for code in comparison_result.get("reason_codes") or []] or ["OTHER"]
            comment = "多候选比较质检：{}\n下一轮修正：{}\n策略切换：{}".format(
                comparison_result.get("diagnosis", ""), comparison_result.get("revision_instruction", ""),
                comparison_result.get("next_strategy", "structural_reanalysis"),
            ).strip()
            self.db.save_generation_feedback(sample_id, codes, comment)
        elif workflow == "qc_failed" and critic_result and not critic_result.get("pass", False):
            codes = [str(code) for code in critic_result.get("reason_codes") or []] or ["OTHER"]
            comment = "视觉LLM质检：{}\n下一轮修正：{}".format(
                critic_result.get("diagnosis", ""), critic_result.get("revision_instruction", "")
            ).strip()
            self.db.save_generation_feedback(sample_id, codes, comment)
        elif workflow == "qc_failed":
            reason_map = {
                "EMPTY_CHANGE": "ANOMALY_TOO_WEAK", "CHANGE_TOO_LARGE": "BACKGROUND_CHANGED",
                "CHANGE_TOUCHES_BORDER": "EDGE_ARTIFACT", "SIZE_MISMATCH": "BACKGROUND_CHANGED",
                "ROI_TONE_SEAM": "BACKGROUND_CHANGED", "LLM_CRITIC_ERROR": "OTHER",
            }
            codes = sorted({reason_map.get(str(code), "OTHER") for code in qc.get("failures") or []}) or ["OTHER"]
            self.db.save_generation_feedback(sample_id, codes, "代理轮次失败：{}。下一轮必须改变参考、Mask或实例策略，禁止重复同一做法。".format("、".join(qc.get("failures") or [])))
        self.export_results_csv()
        progress("complete", attempt=attempt, workflow=workflow)
        return {"sample_id": sample_id, "attempt": attempt, "workflow": workflow, "qc": qc}

    def generate(self, queued_only: bool = False, sample_ids: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        selected = set(sample_ids or [])
        results = []
        for row in self.db.list_samples():
            if selected and row["id"] not in selected:
                continue
            if queued_only:
                if row["workflow"] != "regen_queued":
                    continue
            elif row["workflow"] not in {"pending_generation", "regen_queued", "qc_failed"}:
                continue
            try:
                results.append(self.generate_sample(row["id"]))
            except Exception as exc:
                results.append({"sample_id": row["id"], "error": str(exc)})
        return results

    def export_results_csv(self) -> Path:
        path = self.paths["intermediate"] / "review_results.csv"
        fields = [
            "sample_id", "relative_json", "split", "source_mode", "labels", "workflow", "active_attempt", "anomaly_status",
            "anomaly_reason_codes", "anomaly_comment", "mask_status", "mask_reason_codes", "mask_comment",
            "warnings", "deleted", "updated_at",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in self.db.list_samples(include_deleted=True):
                writer.writerow(
                    {
                        "sample_id": row["id"], "relative_json": row["relative_json"], "split": row.get("split", "anomaly"),
                        "source_mode": row.get("source_mode", "labelme"), "labels": ";".join(row["labels"]),
                        "workflow": row["workflow"], "active_attempt": row["active_attempt"], "anomaly_status": row["anomaly_status"],
                        "anomaly_reason_codes": ";".join(row["anomaly_reason_codes"]), "anomaly_comment": row["anomaly_comment"],
                        "mask_status": row["mask_status"], "mask_reason_codes": ";".join(row["mask_reason_codes"]),
                        "mask_comment": row["mask_comment"], "warnings": ";".join(row["warnings"]),
                        "deleted": int(row["deleted"]), "updated_at": row["updated_at"],
                    }
                )
        return path

    def export_approved(self, output_root: Optional[Path] = None) -> Dict[str, Any]:
        configured = str(self.config.get("export", {}).get("root") or "").strip()
        if output_root is None:
            if not configured:
                raise ValueError("请通过 --output 或 config.json 的 export.root 指定导出目录")
            output_root = resolve_project_path(self.config, configured)
        output_root = output_root.resolve()
        dataset_root = self.dataset_root().resolve()
        if output_root == dataset_root:
            raise ValueError("导出目录不能与源数据集根目录相同")
        output_root.mkdir(parents=True, exist_ok=True)
        mask_format = str(self.config.get("export", {}).get("mask_format") or "png").lower()
        if mask_format not in {"png", "jpg", "jpeg"}:
            raise ValueError("mask_format仅支持png/jpg/jpeg")
        rows: List[Dict[str, Any]] = []
        all_samples = self.db.list_samples()
        layered = str(self.config.get("generation", {}).get("multi_label_mode") or "per_shape").lower() == "per_image_layered"
        handled_groups = set()
        for sample in all_samples:
            if sample["workflow"] != "completed":
                continue
            if layered and sample.get("source_mode") == "labelme":
                group_key = str(sample["json_path"])
                if group_key in handled_groups:
                    continue
                handled_groups.add(group_key)
                group = [row for row in all_samples if row.get("source_mode") == "labelme" and str(row["json_path"]) == group_key]
                if not group or any(row["workflow"] != "completed" for row in group):
                    continue
                group_attempts = [(row, self.db.active_attempt(row["id"])) for row in group]
                if any(attempt is None for _, attempt in group_attempts):
                    continue
                group_attempts.sort(key=lambda pair: min([int(shape.get("index", 0)) for shape in pair[0].get("shapes") or [{}]]))
                source = Path(group[0]["image_path"])
                with Image.open(source) as opened:
                    combined = opened.copy()
                union_mask = Image.new("L", combined.size, 0)
                for child, child_attempt in group_attempts:
                    assert child_attempt is not None
                    with Image.open(Path(child_attempt["candidate_path"])) as opened:
                        layer = opened.convert(combined.mode)
                    with Image.open(Path(child_attempt["roi_mask_path"])) as opened:
                        roi = opened.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="L")
                    with Image.open(Path(child_attempt["mask_path"])) as opened:
                        child_mask = opened.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="L")
                    if layer.size != combined.size or roi.size != combined.size or child_mask.size != combined.size:
                        raise ValueError("多ROI图层尺寸不一致：{}".format(child["id"]))
                    combined = Image.composite(layer, combined, child_mask)
                    union_mask = ImageChops.lighter(union_mask, child_mask)
                base_relative = str(group[0]["relative_json"]).split("::shape[", 1)[0]
                relative_parent = Path(base_relative).parent
                sample_out = output_root / relative_parent
                reference_dir = sample_out / "reference"
                anomaly_dir = sample_out / "anomaly_query"
                mask_dir = sample_out / "mask"
                annotation_dir = sample_out / "annotation"
                for folder in (reference_dir, anomaly_dir, mask_dir, annotation_dir):
                    folder.mkdir(parents=True, exist_ok=True)
                labels = list(dict.fromkeys(code for child in group for code in child["labels"]))
                label_token = "_".join(labels)
                anomaly_path = anomaly_dir / "{}__{}.jpg".format(source.stem, label_token)
                mask_suffix = ".png" if mask_format == "png" else ".jpg"
                mask_path = mask_dir / "{}__{}__mask{}".format(source.stem, label_token, mask_suffix)
                shutil.copy2(source, reference_dir / source.name)
                annotation_output = annotation_dir / Path(group[0]["json_path"]).name
                shutil.copy2(Path(group[0]["json_path"]), annotation_output)
                export_image = combined.convert("L") if is_grayscale_visual(combined) else combined.convert("RGB")
                export_image.save(anomaly_path, format="JPEG", quality=100, subsampling=0, optimize=True)
                if mask_format == "png":
                    union_mask.save(mask_path, format="PNG", optimize=True)
                else:
                    union_mask.save(mask_path, format="JPEG", quality=100, subsampling=0)
                rows.append(
                    {
                        "sample_id": safe_id("layered::" + base_relative), "labels": ";".join(labels),
                        "attempt": max(int(attempt["attempt"]) for _, attempt in group_attempts if attempt is not None),
                        "source": str((reference_dir / source.name).resolve()), "anomaly": str(anomaly_path.resolve()),
                        "mask": str(mask_path.resolve()), "labelme": str(annotation_output.resolve()),
                    }
                )
                continue
            attempt = self.db.active_attempt(sample["id"])
            if not attempt:
                continue
            if sample.get("source_mode") == "manifest_review":
                relative_parent = Path(sample["relative_json"])
            else:
                relative_parent = Path(str(sample["relative_json"]).split("::shape[", 1)[0]).parent
            sample_out = output_root / relative_parent
            reference_dir = sample_out / "reference"
            normal_dir = sample_out / "normal_query"
            anomaly_dir = sample_out / "anomaly_query"
            mask_dir = sample_out / "mask"
            annotation_dir = sample_out / "annotation"
            folders = (reference_dir, normal_dir) if sample.get("split") == "normal" else (reference_dir, anomaly_dir, mask_dir, annotation_dir)
            for folder in folders:
                folder.mkdir(parents=True, exist_ok=True)
            source = Path(sample["image_path"])
            label_token = "_".join(sample["labels"])
            if sample.get("split") == "normal":
                normal_path = normal_dir / source.name
                shutil.copy2(source, reference_dir / source.name)
                with Image.open(Path(attempt["candidate_path"])) as opened:
                    image = opened.convert("L") if is_grayscale_visual(opened) else opened.convert("RGB")
                    image.save(normal_path, format="JPEG", quality=100, subsampling=0, optimize=True)
                rows.append(
                    {
                        "sample_id": sample["id"], "labels": ";".join(sample["labels"]), "attempt": attempt["attempt"],
                        "source": str((reference_dir / source.name).resolve()), "anomaly": str(normal_path.resolve()),
                        "mask": "", "labelme": "",
                    }
                )
                continue
            anomaly_path = anomaly_dir / "{}__{}.jpg".format(source.stem, label_token)
            mask_suffix = ".png" if mask_format == "png" else ".jpg"
            mask_path = mask_dir / "{}__{}__mask{}".format(source.stem, label_token, mask_suffix)
            shutil.copy2(source, reference_dir / source.name)
            annotation_output = annotation_dir / Path(sample["json_path"]).name
            if sample.get("source_mode") == "labelme":
                shutil.copy2(Path(sample["json_path"]), annotation_output)
            with Image.open(Path(attempt["candidate_path"])) as opened:
                image = opened.convert("L") if is_grayscale_visual(opened) else opened.convert("RGB")
                image.save(anomaly_path, format="JPEG", quality=100, subsampling=0, optimize=True)
            with Image.open(Path(attempt["mask_path"])) as opened:
                mask = opened.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="L")
                if mask_format == "png":
                    mask.save(mask_path, format="PNG", optimize=True)
                else:
                    mask.save(mask_path, format="JPEG", quality=100, subsampling=0)
            rows.append(
                {
                    "sample_id": sample["id"], "labels": ";".join(sample["labels"]), "attempt": attempt["attempt"],
                    "source": str((reference_dir / source.name).resolve()), "anomaly": str(anomaly_path.resolve()),
                    "mask": str(mask_path.resolve()), "labelme": str(annotation_output.resolve()) if sample.get("source_mode") == "labelme" else "",
                }
            )
        manifest = output_root / "export_manifest.csv"
        with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
            fields = ["sample_id", "labels", "attempt", "source", "anomaly", "mask", "labelme"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return {"exported": len(rows), "output_root": str(output_root), "manifest": str(manifest)}
