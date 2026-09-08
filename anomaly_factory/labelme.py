from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter


@dataclass
class LabelShape:
    label: str
    shape_type: str
    points: List[Tuple[float, float]]
    index: int


@dataclass
class LabelMeSample:
    sample_id: str
    json_path: Path
    image_path: Path
    relative_json: str
    width: int
    height: int
    shapes: List[LabelShape]
    labels: List[str]
    warnings: List[str]


def safe_id(value: str) -> str:
    prefix = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return "{}__{}".format(prefix[-100:], digest)


def _resolve_image(json_path: Path, payload: Dict[str, Any], extensions: Sequence[str]) -> Path:
    image_path = str(payload.get("imagePath") or "").strip()
    candidates: List[Path] = []
    if image_path:
        raw = Path(image_path)
        candidates.append(raw if raw.is_absolute() else json_path.parent / raw)
    for suffix in extensions:
        candidates.append(json_path.with_suffix(suffix))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("找不到 JSON 对应图片：{}".format(json_path))


def parse_labelme(json_path: Path, dataset_root: Path, extensions: Sequence[str]) -> LabelMeSample:
    payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("LabelMe JSON 根节点必须是 object")
    image_path = _resolve_image(json_path, payload, extensions)
    with Image.open(image_path) as opened:
        width, height = opened.size
    warnings: List[str] = []
    declared = (int(payload.get("imageWidth") or width), int(payload.get("imageHeight") or height))
    if declared != (width, height):
        warnings.append("JSON尺寸{}x{}与图片{}x{}不一致".format(declared[0], declared[1], width, height))
    shapes: List[LabelShape] = []
    for index, raw in enumerate(payload.get("shapes") or []):
        if not isinstance(raw, dict):
            warnings.append("shape[{}]不是object".format(index))
            continue
        label = str(raw.get("label") or "").strip()
        shape_type = str(raw.get("shape_type") or "polygon").strip().lower()
        points: List[Tuple[float, float]] = []
        for point in raw.get("points") or []:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
        if not label or len(points) < 2:
            warnings.append("shape[{}]缺少有效标签或坐标".format(index))
            continue
        shapes.append(LabelShape(label=label, shape_type=shape_type, points=points, index=index))
    if not shapes:
        warnings.append("NO_SHAPES")
    relative = json_path.resolve().relative_to(dataset_root.resolve()).as_posix()
    labels = sorted(set(shape.label for shape in shapes))
    return LabelMeSample(
        sample_id=safe_id(relative),
        json_path=json_path.resolve(),
        image_path=image_path,
        relative_json=relative,
        width=width,
        height=height,
        shapes=shapes,
        labels=labels,
        warnings=warnings,
    )


def discover_samples(dataset_root: Path, glob_pattern: str, extensions: Sequence[str]) -> Tuple[List[LabelMeSample], List[str]]:
    samples: List[LabelMeSample] = []
    errors: List[str] = []
    for json_path in sorted(dataset_root.glob(glob_pattern)):
        if not json_path.is_file():
            continue
        try:
            samples.append(parse_labelme(json_path, dataset_root, extensions))
        except Exception as exc:
            errors.append("{}: {}".format(json_path, exc))
    return samples, errors


def expand_per_shape(samples: Iterable[LabelMeSample]) -> List[LabelMeSample]:
    """Turn each LabelMe shape into an independent generation task.

    The paired-data specification intentionally places one target ROI together
    with 1–2 unrelated anomaly ROIs in a normal JSON. Generating all shapes in
    one request would mix categories, so the default pipeline expands them.
    """
    output: List[LabelMeSample] = []
    for sample in samples:
        if not sample.shapes:
            output.append(sample)
            continue
        for shape in sample.shapes:
            task_key = "{}::shape[{}]::{}".format(sample.relative_json, shape.index, shape.label)
            output.append(
                LabelMeSample(
                    sample_id=safe_id(task_key), json_path=sample.json_path, image_path=sample.image_path,
                    relative_json=task_key, width=sample.width, height=sample.height,
                    shapes=[shape], labels=[shape.label], warnings=list(sample.warnings),
                )
            )
    return output


def _shape_points(shape: LabelShape) -> List[Tuple[int, int]]:
    return [(int(round(x)), int(round(y))) for x, y in shape.points]


def draw_shape(mask: Image.Image, shape: LabelShape, value: int = 255) -> None:
    draw = ImageDraw.Draw(mask)
    points = _shape_points(shape)
    if shape.shape_type == "rectangle" and len(points) >= 2:
        x_values = [p[0] for p in points]
        y_values = [p[1] for p in points]
        draw.rectangle((min(x_values), min(y_values), max(x_values), max(y_values)), fill=value)
    elif shape.shape_type == "circle" and len(points) >= 2:
        cx, cy = points[0]
        px, py = points[1]
        radius = int(round(((px - cx) ** 2 + (py - cy) ** 2) ** 0.5))
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=value)
    elif shape.shape_type in {"line", "linestrip"}:
        draw.line(points, fill=value, width=3, joint="curve")
    elif len(points) >= 3:
        draw.polygon(points, fill=value)
    else:
        draw.line(points, fill=value, width=3)


def build_roi_mask(sample: LabelMeSample, padding_px: int, padding_ratio: float) -> Image.Image:
    mask = Image.new("L", (sample.width, sample.height), 0)
    for shape in sample.shapes:
        draw_shape(mask, shape)
    if mask.getbbox() is None:
        return mask
    bbox = mask.getbbox()
    span = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    padding = max(int(padding_px), int(round(span * float(padding_ratio))))
    if padding > 0:
        size = min(255, padding * 2 + 1)
        if size % 2 == 0:
            size -= 1
        mask = mask.filter(ImageFilter.MaxFilter(max(3, size)))
    return mask.point(lambda value: 255 if value >= 128 else 0, mode="L")


def expand_binary_mask(mask: Image.Image, padding: int) -> Image.Image:
    """Expand a binary mask by an arbitrary radius without the 255px filter limit."""
    output = mask.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="L")
    remaining = max(0, int(padding))
    bbox = output.getbbox()
    if remaining <= 0 or bbox is None:
        return output
    # Pillow's rank filter cost grows quickly with both kernel and canvas
    # size.  Dilation cannot affect pixels farther than ``padding`` from the
    # foreground, so process only that local crop instead of a multi-megapixel
    # full frame.  This preserves exact morphology while avoiding minutes of
    # CPU work for small LabelMe targets.
    left = max(0, bbox[0] - remaining)
    top = max(0, bbox[1] - remaining)
    right = min(output.width, bbox[2] + remaining)
    bottom = min(output.height, bbox[3] + remaining)
    local = output.crop((left, top, right, bottom))

    def shifted_zero(image: Image.Image, dx: int = 0, dy: int = 0) -> Image.Image:
        """Translate without ImageChops.offset's wrap-around pixels."""
        shifted = Image.new("L", image.size, 0)
        width, height = image.size
        source_left, source_top = max(0, -dx), max(0, -dy)
        source_right, source_bottom = min(width, width - dx), min(height, height - dy)
        if source_right > source_left and source_bottom > source_top:
            shifted.paste(
                image.crop((source_left, source_top, source_right, source_bottom)),
                (source_left + dx, source_top + dy),
            )
        return shifted

    def dilate_axis(image: Image.Image, radius: int, horizontal: bool) -> Image.Image:
        # After coverage=c, unioning shifts by c+1 grows the exact continuous
        # interval to 2c+1.  This gives an exact square MaxFilter dilation in
        # O(log(radius)) C-backed image operations instead of a 255x255 rank
        # filter whose cost dominated review-image switching.
        coverage = 0
        expanded_axis = image
        while coverage < radius:
            step = min(coverage + 1, radius - coverage)
            positive = shifted_zero(expanded_axis, step if horizontal else 0, 0 if horizontal else step)
            negative = shifted_zero(expanded_axis, -step if horizontal else 0, 0 if horizontal else -step)
            expanded_axis = ImageChops.lighter(expanded_axis, ImageChops.lighter(positive, negative))
            coverage += step
        return expanded_axis

    local = dilate_axis(local, remaining, True)
    local = dilate_axis(local, remaining, False)
    expanded = Image.new("L", output.size, 0)
    expanded.paste(local, (left, top))
    return expanded.point(lambda value: 255 if value >= 128 else 0, mode="L")


def build_edit_context_mask(
    sample: LabelMeSample,
    minimum_padding_px: int,
    padding_ratio: float,
) -> tuple:
    """Build the broad CORE edit region around the LabelMe focus annotation.

    LabelMe geometry remains the semantic focus.  This separate mask is wider
    so the image model can reconstruct occluded structure and physically
    connected effects immediately outside an incomplete annotation box.
    """
    focus = build_roi_mask(sample, 0, 0.0)
    bbox = focus.getbbox()
    if bbox is None:
        return focus, focus.copy(), {"focus_bbox": None, "edit_bbox": None, "padding_px": 0}
    span = max(1, bbox[2] - bbox[0], bbox[3] - bbox[1])
    padding = max(int(minimum_padding_px), int(round(span * float(padding_ratio))))
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(sample.width, bbox[2] + padding)
    bottom = min(sample.height, bbox[3] + padding)
    edit = Image.new("L", focus.size, 0)
    radius = max(0, min(padding, (right - left) // 4, (bottom - top) // 4))
    ImageDraw.Draw(edit).rounded_rectangle((left, top, right, bottom), radius=radius, fill=255)
    return focus, edit, {
        "focus_bbox": list(bbox),
        "edit_bbox": list(edit.getbbox()) if edit.getbbox() else None,
        "padding_px": padding,
        "padding_ratio": float(padding_ratio),
    }


def shapes_to_json(shapes: Iterable[LabelShape]) -> str:
    rows = [
        {"label": s.label, "shape_type": s.shape_type, "points": s.points, "index": s.index}
        for s in shapes
    ]
    return json.dumps(rows, ensure_ascii=False)
