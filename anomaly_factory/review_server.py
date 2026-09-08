from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import os
import shutil
import socket
import tempfile
import threading
import time
import webbrowser
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageChops

from .config import load_claude_environment, save_config_sections, save_local_api_credentials
from .core import probe_core
from .intelligence import create_intelligence, probe_intelligence
from .pipeline import Pipeline


STATIC_DIR = Path(__file__).resolve().parent / "static"
ANOMALY_REASONS = [
    "ANOMALY_TOO_SMALL", "ANOMALY_TOO_WEAK", "WRONG_LABEL", "WRONG_STRUCTURE", "PARTIAL_REMOVAL",
    "BACKGROUND_CHANGED", "COLOR_SHIFT", "EDGE_ARTIFACT", "ROI_MISALIGNED", "OIL_TOO_SMALL",
    "OIL_LOOKS_LIKE_SHADOW", "OTHER",
]
MASK_REASONS = ["MASK_TOO_COARSE", "MASK_MISSING_AREA", "MASK_EXTRA_AREA", "MASK_EDGE_INACCURATE", "OTHER"]


def timestamp_token() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def atomic_save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".mask_", suffix=".png")
    os.close(fd)
    try:
        image.save(temp_name, format="PNG", optimize=True)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


class ReviewApplication:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self.worker_lock = threading.Lock()
        self.worker_state: Dict[str, Any] = {
            "running": False, "last_result": None, "last_error": "", "total": 0, "completed": 0,
            "succeeded": 0, "failed": 0, "current_id": "", "current_path": "", "current_labels": [],
            "current_stage": "", "current_stage_started_at": 0.0, "current_batch_ids": [],
            "parallel_planning": {"active": False, "status": "idle", "sample_ids": []},
            "jobs": [],
        }
        self.image_cache: OrderedDict[tuple, tuple] = OrderedDict()
        self.image_cache_lock = threading.Lock()
        self.image_cache_limit = 32

    def cached_image(self, key: tuple) -> Optional[tuple]:
        with self.image_cache_lock:
            value = self.image_cache.get(key)
            if value is not None:
                self.image_cache.move_to_end(key)
            return value

    def remember_image(self, key: tuple, value: tuple) -> tuple:
        with self.image_cache_lock:
            self.image_cache[key] = value
            self.image_cache.move_to_end(key)
            while len(self.image_cache) > self.image_cache_limit:
                self.image_cache.popitem(last=False)
        return value

    def layered_mode(self) -> bool:
        return str(self.pipeline.config.get("generation", {}).get("multi_label_mode") or "per_shape") == "per_image_layered"

    def api_settings(self) -> Dict[str, Any]:
        config = self.pipeline.config
        core = config.get("core", {})
        intelligence = config.get("intelligence", {})
        generation = config.get("generation", {})
        runtime = load_claude_environment(config)
        base_env = str(core.get("base_url_env") or "")
        key_env = str(core.get("api_key_env") or "")
        base_url = str(core.get("base_url") or runtime.get(base_env, ""))
        return {
            "core": {
                "adapter": core.get("adapter", "openai_image_edits"), "base_url": base_url,
                "endpoint": core.get("endpoint", "/v1/images/edits"), "model": core.get("model", "gpt-image-2"),
                "quality": core.get("quality", "high"), "timeout_seconds": core.get("timeout_seconds", 900),
                "transport_retries": int(core.get("transport_retries") or 4),
                "transport_job_retries": int(core.get("transport_job_retries") or 2),
                "proxy_mode": core.get("proxy_mode", "direct"), "api_key_configured": bool(runtime.get(key_env)),
                "api_key_env": key_env, "credential_file": str(Path(config["_project_root"]) / "api_credentials.local.json"),
            },
            "intelligence": {
                "enabled": bool(intelligence.get("enabled", True)), "model": intelligence.get("model", "gpt-5.6-sol"),
                "endpoint": intelligence.get("endpoint", "/v1/responses"),
                "reasoning_effort": intelligence.get("reasoning_effort", "high"),
                "orchestrator": bool(intelligence.get("orchestrator", True)),
                "batch_planner": bool(intelligence.get("batch_planner", True)),
                "parallel_planning": bool(intelligence.get("parallel_planning", True)),
                "batch_planner_max_rois": int(intelligence.get("batch_planner_max_rois") or 4),
                "batch_reference_candidate_count": int(intelligence.get("batch_reference_candidate_count") or 3),
                "planner": bool(intelligence.get("planner", True)), "critic": bool(intelligence.get("critic", True)),
                "critic_gate": bool(intelligence.get("critic_gate", True)),
                "reference_candidate_count": int(intelligence.get("reference_candidate_count") or 5),
                "approved_example_count": int(intelligence.get("approved_example_count") if intelligence.get("approved_example_count") is not None else 2),
                "failed_example_count": int(intelligence.get("failed_example_count") if intelligence.get("failed_example_count") is not None else 1),
                "agentic_generation": bool(intelligence.get("agentic_generation", True)),
                "candidate_count": int(intelligence.get("candidate_count") or 3),
                "recent_failure_memory": int(intelligence.get("recent_failure_memory") or 4),
                "comparative_critic": bool(intelligence.get("comparative_critic", True)),
                "timeout_seconds": int(intelligence.get("timeout_seconds") or 180),
                "transport_retries": int(intelligence.get("transport_retries") or 4),
            },
            "generation": {
                "reference_count": int(generation.get("reference_count") or 2),
                "edit_context_min_padding_px": int(generation.get("edit_context_min_padding_px") or 96),
                "edit_context_padding_ratio": float(generation.get("edit_context_padding_ratio") or 0.35),
                "max_attempts": int(generation.get("max_attempts") or 30),
                "max_auto_retries_per_sample_per_run": int(generation.get("max_auto_retries_per_sample_per_run") if generation.get("max_auto_retries_per_sample_per_run") is not None else 25),
                "manual_review_after_retry_exhausted": bool(generation.get("manual_review_after_retry_exhausted", True)),
                "multi_roi_source_mode": str(generation.get("multi_roi_source_mode") or "sequential_success"),
            },
        }

    def save_api_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.worker_state.get("running"):
            raise ValueError("生成队列正在运行，请等待结束后再修改API配置")
        core_in = payload.get("core") if isinstance(payload.get("core"), dict) else {}
        intel_in = payload.get("intelligence") if isinstance(payload.get("intelligence"), dict) else {}
        gen_in = payload.get("generation") if isinstance(payload.get("generation"), dict) else {}
        base_url = str(core_in.get("base_url") or "").strip().rstrip("/")
        if base_url and not base_url.startswith(("http://", "https://")):
            raise ValueError("API Base URL必须以http://或https://开头")
        quality = str(core_in.get("quality") or "high")
        if quality not in {"low", "medium", "high", "auto"}:
            raise ValueError("图像质量只能是low/medium/high/auto")
        effort = str(intel_in.get("reasoning_effort") or "high")
        if effort not in {"low", "medium", "high", "xhigh"}:
            raise ValueError("推理强度只能是low/medium/high/xhigh")
        updates = {
            "core": {
                "adapter": str(core_in.get("adapter") or "openai_image_edits"),
                "base_url": base_url, "endpoint": str(core_in.get("endpoint") or "/v1/images/edits"),
                "model": str(core_in.get("model") or "gpt-image-2"), "quality": quality,
                "timeout_seconds": max(30, min(3600, int(core_in.get("timeout_seconds") or 900))),
                "transport_retries": max(1, min(10, int(core_in.get("transport_retries") or 4))),
                "transport_job_retries": max(0, min(10, int(core_in.get("transport_job_retries") or 2))),
                "proxy_mode": str(core_in.get("proxy_mode") or "direct"),
            },
            "intelligence": {
                "enabled": bool(intel_in.get("enabled", True)), "model": str(intel_in.get("model") or "gpt-5.6-sol"),
                "endpoint": str(intel_in.get("endpoint") or "/v1/responses"), "reasoning_effort": effort,
                "orchestrator": bool(intel_in.get("orchestrator", True)),
                "batch_planner": bool(intel_in.get("batch_planner", True)),
                "parallel_planning": bool(intel_in.get("parallel_planning", True)),
                "batch_planner_max_rois": max(2, min(8, int(intel_in.get("batch_planner_max_rois") or 4))),
                "batch_reference_candidate_count": max(1, min(5, int(intel_in.get("batch_reference_candidate_count") or 3))),
                "planner": bool(intel_in.get("planner", True)), "critic": bool(intel_in.get("critic", True)),
                "critic_gate": bool(intel_in.get("critic_gate", True)),
                "reference_candidate_count": max(1, min(8, int(intel_in.get("reference_candidate_count") or 5))),
                "approved_example_count": max(0, min(5, int(intel_in.get("approved_example_count") if intel_in.get("approved_example_count") is not None else 2))),
                "failed_example_count": max(0, min(1, int(intel_in.get("failed_example_count") if intel_in.get("failed_example_count") is not None else 1))),
                "agentic_generation": bool(intel_in.get("agentic_generation", True)),
                "candidate_count": max(1, min(6, int(intel_in.get("candidate_count") or 3))),
                "recent_failure_memory": max(0, min(8, int(intel_in.get("recent_failure_memory") or 4))),
                "comparative_critic": bool(intel_in.get("comparative_critic", True)),
                "compact_core_prompt": True,
                "timeout_seconds": max(30, min(900, int(intel_in.get("timeout_seconds") or 180))),
                "transport_retries": max(1, min(10, int(intel_in.get("transport_retries") or 4))),
                "transport_retry_backoff_seconds": 2,
            },
            "generation": {
                "reference_count": max(1, min(5, int(gen_in.get("reference_count") or 2))),
                "edit_context_min_padding_px": max(16, min(1024, int(gen_in.get("edit_context_min_padding_px") or 96))),
                "edit_context_padding_ratio": max(0.05, min(1.5, float(gen_in.get("edit_context_padding_ratio") or 0.35))),
                "max_attempts": max(1, min(100, int(gen_in.get("max_attempts") or 30))),
                "max_auto_retries_per_sample_per_run": max(0, min(99, int(gen_in.get("max_auto_retries_per_sample_per_run") if gen_in.get("max_auto_retries_per_sample_per_run") is not None else 25))),
                "manual_review_after_retry_exhausted": bool(gen_in.get("manual_review_after_retry_exhausted", True)),
                "multi_roi_source_mode": "sequential_success" if str(gen_in.get("multi_roi_source_mode") or "sequential_success") == "sequential_success" else "independent",
            },
        }
        key = str(payload.get("api_key") or "").strip()
        if key:
            key_env = str(self.pipeline.config.get("core", {}).get("api_key_env") or "PIPELINE_API_KEY")
            save_local_api_credentials(self.pipeline.config, {key_env: key})
        new_config = save_config_sections(self.pipeline.config, updates)
        self.pipeline.config = new_config
        try:
            self.pipeline.intelligence = create_intelligence(new_config)
            self.pipeline.intelligence_startup_error = ""
        except Exception as exc:
            self.pipeline.intelligence = None
            self.pipeline.intelligence_startup_error = str(exc)
        return self.api_settings()

    def probe_api(self, target: str) -> Dict[str, Any]:
        if target == "core":
            return probe_core(self.pipeline.config)
        if target == "intelligence":
            return probe_intelligence(self.pipeline.config)
        if target == "all":
            return {"core": probe_core(self.pipeline.config), "intelligence": probe_intelligence(self.pipeline.config)}
        raise ValueError("target只能是core/intelligence/all")

    @staticmethod
    def group_id_for(row: Dict[str, Any]) -> str:
        token = str(row.get("json_path") or row["relative_json"])
        return "group_{}".format(hashlib.sha1(token.encode("utf-8")).hexdigest()[:20])

    def group_rows(self, group_id: str) -> List[Dict[str, Any]]:
        rows = [
            row for row in self.pipeline.db.list_samples()
            if row.get("source_mode") == "labelme" and self.group_id_for(row) == group_id
        ]
        if not rows:
            raise KeyError("原图分组不存在：{}".format(group_id))
        return rows

    def _public_task_items(self) -> List[Dict[str, Any]]:
        rows = self.pipeline.db.list_samples()
        annotations_by_json: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for row in rows:
            group = annotations_by_json.setdefault(str(row.get("json_path") or row["relative_json"]), {})
            for shape in row.get("shapes") or []:
                code = str(shape.get("label") or "")
                canonical = self.pipeline.knowledge.resolve_label(code)
                info = self.pipeline.knowledge.labels.get(canonical, {})
                index = int(shape.get("index", -1))
                key = "{}:{}".format(index, code)
                group[key] = {
                    "index": index,
                    "code": code,
                    "canonical_code": canonical,
                    "name": info.get("name_zh", code),
                    "family": info.get("family", "unknown"),
                    "shape_type": str(shape.get("shape_type") or "polygon"),
                    "points": shape.get("points") or [],
                }
        output = []
        for row in rows:
            attempt = self.pipeline.db.active_attempt(row["id"])
            labels = []
            for code in row["labels"]:
                canonical = self.pipeline.knowledge.resolve_label(code)
                info = self.pipeline.knowledge.labels.get(canonical, {})
                labels.append({"code": code, "name": info.get("name_zh", code), "family": info.get("family", "unknown")})
            version = row.get("updated_at") or "0"
            images = {"source": "/api/image?sample={}&kind=source&v={}".format(row["id"], version)}
            if row.get("source_mode") == "labelme":
                images["edit_region"] = "/api/image?sample={}&kind=edit_region&v={}".format(row["id"], version)
            qc = {}
            if attempt:
                images.update(
                    {
                        "candidate": "/api/image?sample={}&kind=candidate&v={}".format(row["id"], version),
                        "mask": "/api/image?sample={}&kind=mask&v={}".format(row["id"], version),
                        "roi": "/api/image?sample={}&kind=roi&v={}".format(row["id"], version),
                        "raw": "/api/image?sample={}&kind=raw&v={}".format(row["id"], version),
                    }
                )
                qc = attempt.get("qc") or {}
            active_shape_keys = {
                "{}:{}".format(int(shape.get("index", -1)), str(shape.get("label") or ""))
                for shape in (row.get("shapes") or [])
            }
            annotations = []
            for key, annotation in sorted(
                annotations_by_json.get(str(row.get("json_path") or row["relative_json"]), {}).items(),
                key=lambda item: (item[1]["index"], item[0]),
            ):
                annotations.append({**annotation, "active": key in active_shape_keys})
            output.append(
                {
                    "id": row["id"], "relative_json": row["relative_json"], "labels": labels,
                    "split": row.get("split", "anomaly"), "source_mode": row.get("source_mode", "labelme"),
                    "workflow": row["workflow"], "active_attempt": row["active_attempt"],
                    "anomaly_status": row["anomaly_status"], "anomaly_reason_codes": row["anomaly_reason_codes"],
                    "anomaly_comment": row["anomaly_comment"], "mask_status": row["mask_status"],
                    "mask_reason_codes": row["mask_reason_codes"], "mask_comment": row["mask_comment"],
                    "warnings": row["warnings"], "width": row["width"], "height": row["height"],
                    "stage": "normal" if row.get("split") == "normal" else ("mask" if row["workflow"] in {"mask_review", "completed"} else "anomaly"),
                    # Prompt preview is intentionally loaded on demand through
                    # /api/prompt-preview for only the selected ROI(s).  Building
                    # every prompt here repeatedly rasterizes masks and can make
                    # queue polling contend with a running generation worker.
                    "qc": qc, "images": images, "annotations": annotations,
                    "updated_at": row.get("updated_at") or "",
                }
            )
        return output

    @staticmethod
    def _group_workflow(children: List[Dict[str, Any]]) -> str:
        workflows = {child["workflow"] for child in children}
        for value in ("regen_queued", "pending_generation", "qc_failed", "core_not_configured", "anomaly_review", "normal_review", "mask_review", "hold"):
            if value in workflows:
                return value
        return "completed" if workflows == {"completed"} else next(iter(workflows), "pending_generation")

    def public_items(self) -> List[Dict[str, Any]]:
        tasks = self._public_task_items()
        if not self.layered_mode():
            return tasks
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        passthrough: List[Dict[str, Any]] = []
        for task in tasks:
            if task.get("source_mode") != "labelme":
                passthrough.append(task)
                continue
            row = self.pipeline.db.get_sample(task["id"])
            grouped.setdefault(self.group_id_for(row), []).append(task)
        output = list(passthrough)
        for group_id, children in grouped.items():
            children.sort(key=lambda child: min([shape.get("index", 0) for shape in child.get("annotations") or [{}]]))
            first = children[0]
            labels_by_code: Dict[str, Dict[str, Any]] = {}
            annotations = []
            warnings = []
            for child in children:
                for label in child["labels"]:
                    labels_by_code.setdefault(label["code"], label)
                warnings.extend(child.get("warnings") or [])
                for annotation in child.get("annotations") or []:
                    if annotation.get("active"):
                        annotations.append(
                            {
                                **annotation, "child_id": child["id"], "workflow": child["workflow"],
                                "stage": child["stage"], "active": True,
                            }
                        )
            workflow = self._group_workflow(children)
            version = max([str(child.get("updated_at") or child.get("active_attempt") or "0") for child in children])
            any_candidate = any(child.get("images", {}).get("candidate") for child in children)
            images = {
                "source": "/api/image?sample={}&kind=source&v={}".format(group_id, version),
                "candidate": "/api/image?sample={}&kind=candidate&v={}".format(group_id, version) if any_candidate else "",
                "mask": "/api/image?sample={}&kind=mask&v={}".format(group_id, version) if any_candidate else "",
                "roi": "/api/image?sample={}&kind=roi&v={}".format(group_id, version) if any_candidate else "",
                "edit_region": "/api/image?sample={}&kind=edit_region&v={}".format(group_id, version),
            }
            if workflow in {"mask_review", "completed"}:
                stage = "mask"
            elif first.get("split") == "normal":
                stage = "normal"
            else:
                stage = "anomaly"
            output.append(
                {
                    "id": group_id,
                    "relative_json": str(first["relative_json"]).split("::shape[", 1)[0],
                    "labels": list(labels_by_code.values()), "split": first.get("split", "anomaly"),
                    "source_mode": "labelme_group", "workflow": workflow,
                    "active_attempt": max(int(child.get("active_attempt") or 0) for child in children),
                    "anomaly_status": "pending", "anomaly_reason_codes": [], "anomaly_comment": "",
                    "mask_status": "pending", "mask_reason_codes": [], "mask_comment": "",
                    "warnings": sorted(set(warnings)), "width": first["width"], "height": first["height"],
                    "stage": stage, "qc": {"children": [{"id": child["id"], "qc": child.get("qc") or {}} for child in children]},
                    # The group revision must change after every child ROI is
                    # saved.  The browser uses it both as an image cache key
                    # and to decide whether the live composite needs redraw.
                    "updated_at": version,
                    "images": images, "annotations": annotations, "children": children,
                }
            )
        return sorted(output, key=lambda item: str(item["relative_json"]).lower())

    def public_counts(self, items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in items if items is not None else self.public_items():
            counts[item["workflow"]] = counts.get(item["workflow"], 0) + 1
        return counts

    def image_path(self, sample_id: str, kind: str) -> Path:
        row = self.pipeline.db.get_sample(sample_id)
        if kind == "source":
            path = Path(row["image_path"])
        else:
            attempt = self.pipeline.db.active_attempt(sample_id)
            if not attempt:
                raise FileNotFoundError("样本没有生成版本")
            key = {"candidate": "candidate_path", "mask": "mask_path", "roi": "roi_mask_path", "raw": "raw_output_path"}.get(kind)
            if not key:
                raise KeyError("unsupported image kind")
            path = Path(attempt[key])
        if not path.is_file():
            raise FileNotFoundError(str(path))
        return path.resolve()

    def group_image(self, group_id: str, kind: str) -> Image.Image:
        rows = self.group_rows(group_id)
        first = rows[0]
        with Image.open(Path(first["image_path"])) as opened:
            source = opened.copy()
        if kind == "source":
            return source
        if kind not in {"candidate", "mask", "roi", "edit_region"}:
            raise KeyError("unsupported group image kind")
        if kind == "candidate":
            output = source.copy()
        else:
            output = Image.new("L", source.size, 0)
        rows.sort(key=lambda row: min([int(shape.get("index", 0)) for shape in row.get("shapes") or [{}]]))
        for row in rows:
            if kind == "edit_region":
                _, layer_mask, _ = self.pipeline.generation_masks(row)
                output = ImageChops.lighter(output, layer_mask)
                continue
            attempt = self.pipeline.db.active_attempt(row["id"])
            if not attempt:
                continue
            if kind == "candidate":
                with Image.open(Path(attempt["candidate_path"])) as opened:
                    layer = opened.convert(output.mode)
                with Image.open(Path(attempt["mask_path"])) as opened:
                    layer_mask = opened.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="L")
                if layer.size != output.size or layer_mask.size != output.size:
                    raise ValueError("ROI图层尺寸与原图不一致")
                output = Image.composite(layer, output, layer_mask)
            else:
                key = "mask_path" if kind == "mask" else "roi_mask_path"
                with Image.open(Path(attempt[key])) as opened:
                    layer_mask = opened.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="L")
                if layer_mask.size != output.size:
                    raise ValueError("Mask图层尺寸与原图不一致")
                output = ImageChops.lighter(output, layer_mask)
        return output

    def image_bytes(self, sample_id: str, kind: str, revision: str = "") -> tuple:
        revision = str(revision or "")[:256]
        cache_key = (sample_id, kind, revision)
        cached = self.cached_image(cache_key) if revision else None
        if cached is not None:
            return cached
        if kind == "edit_region" and not sample_id.startswith("group_"):
            row = self.pipeline.db.get_sample(sample_id)
            queued = row["workflow"] in {"pending_generation", "regen_queued", "qc_failed", "core_not_configured"}
            attempt = self.pipeline.db.active_attempt(sample_id)
            if attempt and not queued and Path(attempt["roi_mask_path"]).is_file():
                with Image.open(Path(attempt["roi_mask_path"])) as opened:
                    edit_region = opened.convert("L")
            else:
                _, edit_region, _ = self.pipeline.generation_masks(row)
            buffer = io.BytesIO()
            edit_region.save(buffer, format="PNG", compress_level=1)
            result = (buffer.getvalue(), "image/png")
            return self.remember_image(cache_key, result) if revision else result
        if sample_id.startswith("group_"):
            if kind == "source":
                rows = self.group_rows(sample_id)
                path = Path(rows[0]["image_path"])
                result = (path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                return self.remember_image(cache_key, result) if revision else result
            image = self.group_image(sample_id, kind)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", compress_level=1)
            result = (buffer.getvalue(), "image/png")
            return self.remember_image(cache_key, result) if revision else result
        path = self.image_path(sample_id, kind)
        return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    def save_mask(self, sample_id: str, data_url: str) -> Dict[str, Any]:
        prefix = "data:image/png;base64,"
        if not data_url.startswith(prefix):
            raise ValueError("mask必须是PNG data URL")
        encoded = data_url[len(prefix):]
        if len(encoded) > 64 * 1024 * 1024:
            raise ValueError("mask数据过大")
        payload = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(payload)) as opened:
            mask = opened.convert("L")
        if sample_id.startswith("group_"):
            return self.save_group_mask(sample_id, mask)
        row = self.pipeline.db.get_sample(sample_id)
        if row["workflow"] not in {"mask_review", "completed"}:
            raise ValueError("异常图通过后才能编辑Mask")
        attempt = self.pipeline.db.active_attempt(sample_id)
        if not attempt:
            raise ValueError("样本没有生成版本")
        expected = (int(row["width"]), int(row["height"]))
        if mask.size != expected:
            raise ValueError("mask尺寸{}与图片{}不一致".format(mask.size, expected))
        mask = mask.point(lambda value: 255 if value >= 128 else 0, mode="L")
        path = Path(attempt["mask_path"])
        if path.is_file():
            backup = path.parent / "mask_backups" / "mask_{}.png".format(timestamp_token())
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        atomic_save(mask, path)
        self.pipeline.db.save_mask_path(sample_id, int(attempt["attempt"]), path)
        self.pipeline.export_results_csv()
        area = mask.histogram()[255] / max(1, mask.width * mask.height)
        return {"sample_id": sample_id, "mask_area_fraction": area, "status": "pending"}

    def save_group_mask(self, group_id: str, mask: Image.Image) -> Dict[str, Any]:
        rows = self.group_rows(group_id)
        expected = (int(rows[0]["width"]), int(rows[0]["height"]))
        if mask.size != expected:
            raise ValueError("mask尺寸{}与图片{}不一致".format(mask.size, expected))
        mask = mask.point(lambda value: 255 if value >= 128 else 0, mode="L")
        saved = 0
        for row in rows:
            if row["workflow"] not in {"mask_review", "completed"}:
                continue
            attempt = self.pipeline.db.active_attempt(row["id"])
            if not attempt:
                continue
            with Image.open(Path(attempt["roi_mask_path"])) as opened:
                allowed = opened.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="L")
            child_mask = ImageChops.multiply(mask, allowed)
            path = Path(attempt["mask_path"])
            if path.is_file():
                backup = path.parent / "mask_backups" / "mask_{}.png".format(timestamp_token())
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
            atomic_save(child_mask, path)
            self.pipeline.db.save_mask_path(row["id"], int(attempt["attempt"]), path)
            saved += 1
        if not saved:
            raise ValueError("该分组尚无可编辑的Mask图层")
        self.pipeline.export_results_csv()
        area = mask.histogram()[255] / max(1, mask.width * mask.height)
        return {"sample_id": group_id, "mask_area_fraction": area, "saved_layers": saved, "status": "pending"}

    def validate_review(self, sample_id: str, stage: str, status: str, reason_codes: List[str]) -> None:
        allowed = set(MASK_REASONS if stage == "mask" else ANOMALY_REASONS)
        unknown = [code for code in reason_codes if code not in allowed]
        if unknown:
            raise ValueError("未知审核原因码：{}".format(",".join(unknown)))
        sample = self.pipeline.db.get_sample(sample_id)
        attempt = self.pipeline.db.active_attempt(sample_id)
        if not attempt:
            raise ValueError("样本没有可审核的生成版本")
        # Automatic QC is advisory. A candidate routed here after exhausting
        # smart retries keeps all warnings visible, while the human remains
        # the final authority and may explicitly approve it.
        if stage == "mask" and sample["workflow"] not in {"mask_review", "completed"}:
            raise ValueError("异常图尚未通过，不能审核Mask")

    def review(self, sample_id: str, stage: str, status: str, reason_codes: List[str], comment: str) -> Dict[str, Any]:
        self.validate_review(sample_id, stage, status, reason_codes)
        result = self.pipeline.db.review(sample_id, stage, status, reason_codes, comment)
        self.pipeline.export_results_csv()
        return {"id": result["id"], "workflow": result["workflow"], "status": status}

    def review_batch(self, sample_ids: List[str], stage: str, status: str, reason_codes: List[str], comment: str) -> Dict[str, Any]:
        unique_ids = list(dict.fromkeys(sample_ids))
        if not unique_ids or len(unique_ids) > 200:
            raise ValueError("请选择1至200个ROI")
        for sample_id in unique_ids:
            self.validate_review(sample_id, stage, status, reason_codes)
        results = [self.review(sample_id, stage, status, reason_codes, comment) for sample_id in unique_ids]
        return {"reviewed": len(results), "items": results}

    def save_generation_feedback(self, sample_ids: List[str], reason_codes: List[str], comment: str) -> Dict[str, Any]:
        unique_ids = list(dict.fromkeys(sample_ids))
        if not unique_ids or len(unique_ids) > 200:
            raise ValueError("请选择1至200个ROI")
        unknown = [code for code in reason_codes if code not in set(ANOMALY_REASONS)]
        if unknown:
            raise ValueError("未知审核原因码：{}".format(",".join(unknown)))
        results = [self.pipeline.db.save_generation_feedback(sample_id, reason_codes, comment) for sample_id in unique_ids]
        self.pipeline.export_results_csv()
        return {
            "saved": len(results),
            "items": [{"id": row["id"], "workflow": row["workflow"]} for row in results],
        }

    def preview_prompts(self, sample_ids: List[str], reason_codes: List[str], comment: str) -> Dict[str, Any]:
        unique_ids = list(dict.fromkeys(sample_ids))
        if not unique_ids or len(unique_ids) > 200:
            raise ValueError("请选择1至200个ROI")
        output = []
        for sample_id in unique_ids:
            row = self.pipeline.db.get_sample(sample_id)
            if row.get("source_mode") != "labelme" or not row.get("shapes"):
                continue
            labels = []
            for code in row["labels"]:
                canonical = self.pipeline.knowledge.resolve_label(code)
                info = self.pipeline.knowledge.labels.get(canonical, {})
                labels.append({"code": code, "name": info.get("name_zh", code)})
            output.append(
                {
                    "id": sample_id, "labels": labels, "workflow": row["workflow"],
                    "attempt": self.pipeline.db.next_attempt(sample_id),
                    "prompt": self.pipeline.build_prompt_for_row(row, reason_codes=reason_codes, comment=comment),
                }
            )
        return {"count": len(output), "items": output}

    def delete_sample_dir(self, sample_id: str, confirmation: str) -> Dict[str, Any]:
        row = self.group_rows(sample_id)[0] if sample_id.startswith("group_") else self.pipeline.db.get_sample(sample_id)
        if confirmation.strip() != sample_id:
            raise ValueError("请输入完整sample_id确认")
        dataset_root = self.pipeline.dataset_root().resolve()
        source = Path(row["sample_dir"]).resolve()
        if source == dataset_root:
            raise ValueError("拒绝删除数据集根目录")
        try:
            source.relative_to(dataset_root)
        except ValueError as exc:
            raise ValueError("样本目录不在数据集根目录内") from exc
        if not source.is_dir():
            raise FileNotFoundError(source)
        trash = dataset_root / "_review_deleted_samples"
        trash.mkdir(parents=True, exist_ok=True)
        destination = trash / "{}__{}".format(source.name, timestamp_token())
        shutil.move(str(source), str(destination))
        count = self.pipeline.db.mark_deleted_directory(source)
        self.pipeline.export_results_csv()
        return {"moved_to": str(destination), "affected_samples": count, "recoverable": True}

    def run_queue(self) -> Dict[str, Any]:
        if not self.worker_lock.acquire(False):
            return {"started": False, "reason": "worker_running"}
        rows = [
            row for row in self.pipeline.db.list_samples()
            if row["workflow"] in {"pending_generation", "regen_queued", "qc_failed"}
        ]
        self.worker_state = {
            "running": True, "last_result": None, "last_error": "", "total": len(rows), "completed": 0,
            "succeeded": 0, "failed": 0, "current_id": "", "current_path": "", "current_labels": [],
            "current_stage": "", "current_stage_started_at": 0.0, "current_batch_ids": [],
            "parallel_planning": {"active": False, "status": "idle", "sample_ids": []},
            "jobs": [
                {
                    "id": row["id"], "path": row["relative_json"], "labels": list(row.get("labels") or []),
                    "status": "waiting", "workflow": row["workflow"], "attempt": int(row.get("active_attempt") or 0),
                    "error": "",
                    "stage": "waiting",
                    "agentic": bool(self.pipeline.config.get("intelligence", {}).get("agentic_generation", False)),
                    "candidate_count": int(self.pipeline.config.get("intelligence", {}).get("candidate_count") or 1),
                }
                for row in rows
            ],
        }

        generation = self.pipeline.config.get("generation", {})
        auto_retry = bool(generation.get("auto_retry_failed", True))
        retry_limit = max(0, int(generation.get("max_auto_retries_per_sample_per_run") or 0))
        manual_after_exhausted = bool(generation.get("manual_review_after_retry_exhausted", True))
        retry_backoff = max(0.0, float(generation.get("retry_backoff_seconds") or 0))
        transport_job_limit = max(0, int(self.pipeline.config.get("core", {}).get("transport_job_retries") or 0))
        intel_config = self.pipeline.config.get("intelligence", {})
        batch_planner_enabled = bool(
            intel_config.get("enabled", False)
            and intel_config.get("planner", True)
            and intel_config.get("batch_planner", True)
        )
        parallel_planning_enabled = bool(
            batch_planner_enabled and intel_config.get("parallel_planning", True)
        )
        planning_lookahead = max(1, min(2, int(intel_config.get("parallel_planning_lookahead") or 1)))
        sequential_roi_sources = str(generation.get("multi_roi_source_mode") or "sequential_success") == "sequential_success"
        batch_max_rois = max(2, min(8, int(intel_config.get("batch_planner_max_rois") or 4)))
        source_groups: Dict[str, List[int]] = {}
        for index, row in enumerate(rows):
            source_groups.setdefault(str(row.get("image_path") or "").lower(), []).append(index)
        batch_members: Dict[int, List[int]] = {}
        planning_groups: List[List[int]] = []
        if batch_planner_enabled:
            for indexes in source_groups.values():
                for start in range(0, len(indexes), batch_max_rois):
                    chunk = indexes[start:start + batch_max_rois]
                    if len(chunk) >= 2 or parallel_planning_enabled:
                        planning_groups.append(chunk)
                        for index in chunk:
                            batch_members[index] = chunk
        planning_groups.sort(key=lambda members: min(members))

        def worker() -> None:
            results = []
            batch_plan_cache: Dict[str, Dict[str, Any]] = {}
            batch_plan_attempts: Dict[str, int] = {}
            prepared_batches = set()
            planning_futures: Dict[tuple, Future] = {}
            planner_executor: Optional[ThreadPoolExecutor] = None
            if parallel_planning_enabled:
                planner_executor = ThreadPoolExecutor(
                    max_workers=planning_lookahead, thread_name_prefix="visual-plan-prefetch"
                )

            def update_group_progress(members: List[int], sample_id: str, event: Dict[str, Any]) -> None:
                member_index = next((value for value in members if rows[value]["id"] == sample_id), None)
                if member_index is None:
                    return
                member_job = self.worker_state["jobs"][member_index]
                member_job.update(
                    {
                        "stage": "prefetch_planning",
                        "batch_size": int(event.get("batch_size") or len(members)),
                        "attempt": int(event.get("attempt") or member_job.get("attempt") or 0),
                    }
                )
                if member_job.get("status") == "waiting":
                    member_job["status"] = "planning"

            def execute_group_plan(members: List[int]) -> Dict[str, Dict[str, Any]]:
                member_ids = [rows[member]["id"] for member in members]
                # A dedicated client owns its own urllib opener. The planner
                # can therefore run while the main client critiques the
                # current CORE result without sharing transport state.
                planner_client = create_intelligence(self.pipeline.config)
                return self.pipeline.prepare_batch_plans(
                    member_ids,
                    progress_callback=lambda sample_id, event: update_group_progress(members, sample_id, event),
                    intelligence_client=planner_client,
                )

            def planning_done(batch_key: tuple, members: List[int], future: Future) -> None:
                error = ""
                try:
                    future.result()
                    stage = "prefetch_ready"
                except Exception as exc:
                    stage = "prefetch_failed"
                    error = str(exc)
                for member in members:
                    member_job = self.worker_state["jobs"][member]
                    if member_job.get("status") == "planning":
                        member_job.update({"status": "waiting", "stage": stage})
                        if error:
                            member_job["batch_plan_error"] = error
                parallel = self.worker_state.get("parallel_planning") or {}
                if tuple(parallel.get("batch_key") or []) == batch_key:
                    self.worker_state["parallel_planning"] = {
                        "active": False,
                        "status": "ready" if not error else "failed",
                        "sample_ids": [rows[member]["id"] for member in members],
                        "batch_key": list(batch_key),
                        "error": error,
                    }

            def schedule_group(members: List[int]) -> Future:
                batch_key = tuple(members)
                existing = planning_futures.get(batch_key)
                if existing is not None:
                    return existing
                prepared_batches.add(batch_key)
                member_ids = [rows[member]["id"] for member in members]
                for member in members:
                    member_job = self.worker_state["jobs"][member]
                    if member_job.get("status") == "waiting":
                        member_job.update({"status": "planning", "stage": "prefetch_planning"})
                self.worker_state["parallel_planning"] = {
                    "active": True,
                    "status": "planning",
                    "sample_ids": member_ids,
                    "batch_key": list(batch_key),
                    "started_at": time.time(),
                }
                if planner_executor is not None:
                    future = planner_executor.submit(execute_group_plan, members)
                else:
                    future = Future()
                    try:
                        future.set_result(execute_group_plan(members))
                    except Exception as exc:
                        future.set_exception(exc)
                planning_futures[batch_key] = future
                future.add_done_callback(lambda done, key=batch_key, values=members: planning_done(key, values, done))
                return future

            def collect_group(members: List[int], foreground: bool = False) -> None:
                batch_key = tuple(members)
                future = schedule_group(members)
                if foreground and not future.done():
                    lead = members[0]
                    self.worker_state.update(
                        {
                            "current_id": rows[lead]["id"],
                            "current_path": rows[lead]["relative_json"],
                            "current_labels": list(rows[lead].get("labels") or []),
                            "current_stage": "batch_planning",
                            "current_stage_started_at": time.time(),
                            "current_batch_ids": [rows[member]["id"] for member in members],
                        }
                    )
                try:
                    plans = future.result()
                    for member in members:
                        member_id = rows[member]["id"]
                        if member_id in plans:
                            batch_plan_cache[member_id] = plans[member_id]
                            batch_plan_attempts[member_id] = self.pipeline.db.next_attempt(member_id)
                        member_job = self.worker_state["jobs"][member]
                        if member_job.get("status") == "planning":
                            member_job.update({"status": "waiting", "stage": "batch_plan_ready"})
                except Exception as exc:
                    # Prefetch is an optimization. A failed plan falls back to
                    # generate_sample's normal single-ROI planner.
                    for member in members:
                        member_job = self.worker_state["jobs"][member]
                        member_job["batch_plan_error"] = str(exc)
                        if member_job.get("status") == "planning":
                            member_job.update({"status": "waiting", "stage": "waiting"})

            def schedule_lookahead(after_index: int) -> None:
                scheduled = 0
                for members in planning_groups:
                    batch_key = tuple(members)
                    if min(members) <= after_index or batch_key in prepared_batches:
                        continue
                    if (
                        sequential_roi_sources
                        and str(rows[members[0]].get("image_path") or "").lower()
                        == str(rows[after_index].get("image_path") or "").lower()
                    ):
                        # A later chunk from the same image may need the
                        # current chunk's accepted output as its planning
                        # context. It is intentionally not prefetched.
                        continue
                    schedule_group(members)
                    scheduled += 1
                    if scheduled >= planning_lookahead:
                        break
            try:
                pending = deque(range(len(rows)))
                while pending:
                    index = pending.popleft()
                    row = rows[index]
                    job = self.worker_state["jobs"][index]
                    members = batch_members.get(index) or []
                    batch_key = tuple(members)
                    if members:
                        collect_group(members, foreground=True)
                        # Start the next image/group before CORE is invoked for
                        # the current ROI. This is the overlap that hides most
                        # of the next planning latency.
                        schedule_lookahead(index)
                    job["status"] = "running"
                    job.setdefault("retry_count", 0)
                    self.worker_state.update(
                        {
                            "current_id": row["id"], "current_path": row["relative_json"],
                            "current_labels": list(row.get("labels") or []),
                            "current_stage": "preparing", "current_stage_started_at": time.time(),
                            "current_batch_ids": [],
                        }
                    )
                    try:
                        def update_progress(event: Dict[str, Any]) -> None:
                            stage = str(event.get("stage") or "")
                            job["stage"] = stage
                            if stage and self.worker_state.get("current_stage") != stage:
                                self.worker_state["current_stage_started_at"] = time.time()
                            for key in (
                                "attempt", "candidate_index", "candidate_count", "candidate_passed",
                                "candidate_failures", "mask_geometry", "mask_pixels", "workflow",
                            ):
                                if key in event:
                                    job[key] = event[key]
                            self.worker_state["current_stage"] = stage

                        expected_attempt = self.pipeline.db.next_attempt(row["id"])
                        cached_plan = batch_plan_cache.get(row["id"])
                        if batch_plan_attempts.get(row["id"]) != expected_attempt:
                            cached_plan = None
                        result = self.pipeline.generate_sample(
                            row["id"], progress_callback=update_progress, precomputed_plan=cached_plan
                        )
                        results.append(result)
                        qc = result.get("qc") or {}
                        workflow = str(result.get("workflow") or row["workflow"])
                        failure_codes = [str(code) for code in qc.get("failures") or []]
                        failure_detail = str(qc.get("error") or "")
                        job.update(
                            {
                                "workflow": workflow,
                                "attempt": int(result.get("attempt") or job["attempt"]),
                                "failure_codes": failure_codes,
                                "error": failure_detail or "；".join(failure_codes),
                            }
                        )
                        if workflow == "anomaly_review":
                            job.update({"status": "succeeded", "stage": "complete"})
                            self.worker_state["succeeded"] += 1
                            self.worker_state["completed"] += 1
                            continue
                        retries = int(job.get("retry_count") or 0)
                        comparison_codes = ((((qc.get("agent") or {}).get("comparison") or {}).get("reason_codes")) or [])
                        signature = "|".join(sorted(str(code) for code in (comparison_codes or failure_codes))) or "UNKNOWN"
                        signatures = list(job.get("failure_signatures") or []) + [signature]
                        job["failure_signatures"] = signatures[-4:]
                        repeated_failure = len(signatures) >= 3 and len(set(signatures[-3:])) == 1
                        can_retry = auto_retry and workflow == "qc_failed" and retries < retry_limit and not repeated_failure
                        if can_retry:
                            job.update({"status": "retrying", "stage": "retry_wait", "retry_count": retries + 1})
                            pending.append(index)
                            if retry_backoff:
                                time.sleep(retry_backoff)
                            continue
                        if repeated_failure:
                            job["error"] = "同一失败模式连续3轮，已停止盲目消耗并转人工审核：{}".format(signature)
                        if workflow == "qc_failed" and manual_after_exhausted:
                            self.pipeline.db.set_workflow(row["id"], "anomaly_review")
                            job.update({"status": "needs_review", "stage": "complete", "workflow": "anomaly_review"})
                            self.worker_state["succeeded"] += 1
                            self.worker_state["completed"] += 1
                            continue
                        job.update({"status": "failed", "stage": "failed"})
                        self.worker_state["failed"] += 1
                        self.worker_state["completed"] += 1
                    except Exception as exc:
                        if bool(getattr(exc, "retryable", False)) and int(job.get("transport_retry_count") or 0) < transport_job_limit:
                            count = int(job.get("transport_retry_count") or 0) + 1
                            job.update(
                                {
                                    "status": "transport_retrying", "transport_retry_count": count,
                                    "stage": "transport_retry",
                                    "error": str(exc), "failure_codes": ["CORE_TRANSPORT_ERROR"],
                                }
                            )
                            pending.appendleft(index)
                            if retry_backoff:
                                time.sleep(retry_backoff)
                            continue
                        results.append({"sample_id": row["id"], "error": str(exc)})
                        job.update(
                            {
                                "status": "failed", "stage": "failed", "error": str(exc),
                                "failure_codes": ["PIPELINE_ERROR"],
                            }
                        )
                        self.worker_state["failed"] += 1
                        self.worker_state["completed"] += 1
                self.worker_state["last_result"] = results
            except Exception as exc:
                self.worker_state["last_error"] = str(exc)
            finally:
                if planner_executor is not None:
                    planner_executor.shutdown(wait=False, cancel_futures=True)
                self.worker_state.update(
                    {
                        "running": False, "current_id": "", "current_path": "", "current_labels": [],
                        "current_stage": "", "current_stage_started_at": 0.0, "current_batch_ids": [],
                        "parallel_planning": {"active": False, "status": "idle", "sample_ids": []},
                    }
                )
                self.worker_state["running"] = False
                self.worker_lock.release()

        threading.Thread(target=worker, daemon=True).start()
        return {"started": True, "total": len(rows)}


APP: Optional[ReviewApplication] = None


class Handler(BaseHTTPRequestHandler):
    server_version = "AnomalyFactoryReviewer/2.0"

    @property
    def app(self) -> ReviewApplication:
        assert APP is not None
        return APP

    def log_message(self, fmt: str, *args: object) -> None:
        print("[{}] {}".format(self.log_date_time_string(), fmt % args))

    def send_bytes(
        self, data: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK,
        attachment: str = "", cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
        if attachment:
            self.send_header("Content-Disposition", 'attachment; filename="{}"'.format(attachment))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 72 * 1024 * 1024:
            raise ValueError("invalid request size")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        return payload

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "counts": self.app.pipeline.db.counts(), "worker": self.app.worker_state})
            return
        if parsed.path == "/api/items":
            items = self.app.public_items()
            self.send_json(
                {
                    "items": items, "counts": self.app.public_counts(items),
                    "results": str(self.app.pipeline.paths["intermediate"] / "review_results.csv"),
                    "anomaly_reasons": ANOMALY_REASONS, "mask_reasons": MASK_REASONS,
                    "worker": self.app.worker_state,
                }
            )
            return
        if parsed.path == "/api/worker-status":
            self.send_json(self.app.worker_state)
            return
        if parsed.path == "/api/api-settings":
            self.send_json({"ok": True, "result": self.app.api_settings()})
            return
        if parsed.path == "/api/image":
            query = parse_qs(parsed.query)
            try:
                revision = query.get("v", [""])[0]
                data, content_type = self.app.image_bytes(
                    query.get("sample", [""])[0], query.get("kind", [""])[0], revision,
                )
                cache_control = "private, max-age=31536000, immutable" if revision else "no-store"
                self.send_bytes(data, content_type, cache_control=cache_control)
            except (KeyError, FileNotFoundError, ValueError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/export-results":
            path = self.app.pipeline.export_results_csv()
            self.send_bytes(path.read_bytes(), "text/csv; charset=utf-8", attachment="review_results.csv")
            return
        static_name = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
        path = (STATIC_DIR / static_name).resolve()
        try:
            path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_bytes(path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self.read_json()
            if parsed.path == "/api/review":
                result = self.app.review(
                    str(body["sample_id"]), str(body["stage"]), str(body["status"]),
                    [str(code) for code in body.get("reason_codes", [])], str(body.get("comment", "")),
                )
            elif parsed.path == "/api/review-batch":
                result = self.app.review_batch(
                    [str(sample_id) for sample_id in body.get("sample_ids", [])],
                    str(body["stage"]), str(body["status"]),
                    [str(code) for code in body.get("reason_codes", [])], str(body.get("comment", "")),
                )
            elif parsed.path == "/api/prompt-preview":
                result = self.app.preview_prompts(
                    [str(sample_id) for sample_id in body.get("sample_ids", [])],
                    [str(code) for code in body.get("reason_codes", [])], str(body.get("comment", "")),
                )
            elif parsed.path == "/api/generation-feedback":
                result = self.app.save_generation_feedback(
                    [str(sample_id) for sample_id in body.get("sample_ids", [])],
                    [str(code) for code in body.get("reason_codes", [])], str(body.get("comment", "")),
                )
            elif parsed.path == "/api/mask":
                result = self.app.save_mask(str(body["sample_id"]), str(body["png"]))
            elif parsed.path == "/api/run-queue":
                result = self.app.run_queue()
            elif parsed.path == "/api/api-settings":
                result = self.app.save_api_settings(body)
            elif parsed.path == "/api/api-probe":
                result = self.app.probe_api(str(body.get("target") or "all"))
            elif parsed.path == "/api/delete-sample":
                result = self.app.delete_sample_dir(str(body["sample_id"]), str(body.get("confirmation", "")))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_json({"ok": True, "result": result})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except (FileNotFoundError, OSError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except RuntimeError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)


def available_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError("没有可用端口")


def serve(pipeline: Pipeline, no_browser: bool = False) -> None:
    global APP
    APP = ReviewApplication(pipeline)
    review = pipeline.config["review"]
    host = str(review.get("host") or "127.0.0.1")
    port = available_port(host, int(review.get("port") or 8895))
    server = ThreadingHTTPServer((host, port), Handler)
    url = "http://{}:{}".format(host, port)
    print("\n工业异常生成与Mask一体化审核台已启动")
    print("地址：{}".format(url))
    print("数据集：{}".format(pipeline.dataset_root()))
    print("中间产物：{}".format(pipeline.paths["intermediate"]))
    print("按 Ctrl+C 关闭\n")
    if not no_browser and bool(review.get("open_browser", True)):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n审核台已关闭")
    finally:
        server.server_close()
