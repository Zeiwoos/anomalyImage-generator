from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG: Dict[str, Any] = {
    "project": {
        "reference_root": "Anomaly-reference",
        "knowledge_root": "knowledge-bank",
        "intermediate_root": "中间产物",
        "database": "中间产物/pipeline.sqlite3",
    },
    "dataset": {
        "root": "",
        "mode": "auto",
        "labelme_glob": "**/*.json",
        "image_extensions": [".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"],
        "deletion_scope": "sample_dir",
    },
    "generation": {
        "reference_count": 2,
        "roi_padding_px": 20,
        "roi_padding_ratio": 0.08,
        "edit_context_min_padding_px": 96,
        "edit_context_padding_ratio": 0.35,
        "force_grayscale_if_source_is_grayscale": True,
        "auto_mask_min_difference": 10,
        "auto_mask_dilate_px": 2,
        "max_attempts": 30,
        "auto_retry_failed": True,
        "max_auto_retries_per_sample_per_run": 1,
        "manual_review_after_retry_exhausted": True,
        "retry_backoff_seconds": 2,
        "multi_label_mode": "per_shape",
        "multi_roi_source_mode": "sequential_success",
        "allow_size_normalization": True,
        "size_aspect_tolerance": 0.02,
        "local_tone_match": True,
        "tone_match_ring_px": 12,
        "max_boundary_seam_mean": 2.5,
        "max_boundary_seam_p95": 10.0,
        "roi_feather_px": 3,
        "roi_edge_guard_px": 12,
    },
    "core": {
        "adapter": "openai_image_edits",
        "claude_settings": "",
        "base_url": "",
        "base_url_env": "PIPELINE_API_BASE_URL",
        "api_key_env": "PIPELINE_API_KEY",
        "model": "gpt-image-2",
        "endpoint": "/v1/images/edits",
        "files_endpoint": "/v1/files",
        "quality": "low",
        "output_format": "png",
        "size_mode": "source_if_supported",
        "normalize_request_size": True,
        "image_field": "image[]",
        "proxy_mode": "direct",
        "timeout_seconds": 420,
        "transport_retries": 2,
        "transport_retry_backoff_seconds": 2,
        "transport_job_retries": 1,
        "command": [],
        "response_base64_field": "data.0.b64_json",
        "response_url_field": "data.0.url",
        "extra_body": {},
    },
    "intelligence": {
        "enabled": False,
        "model": "gpt-5.6-sol",
        "endpoint": "/v1/responses",
        "reasoning_effort": "high",
        "planner_reasoning_effort": "high",
        "critic_reasoning_effort": "medium",
        "comparison_reasoning_effort": "medium",
        "orchestrator": True,
        "batch_planner": True,
        "parallel_planning": True,
        "parallel_planning_lookahead": 1,
        "batch_planner_max_rois": 4,
        "batch_reference_candidate_count": 2,
        "reference_candidate_count": 3,
        "approved_example_count": 1,
        "failed_example_count": 1,
        "agentic_generation": True,
        "candidate_count": 1,
        "stop_after_first_passing_candidate": True,
        "recent_failure_memory": 2,
        "critic_reference_count": 1,
        "comparative_critic": False,
        "compact_core_prompt": True,
        "planner": True,
        "critic": True,
        "critic_gate": True,
        "fail_open": True,
        "timeout_seconds": 300,
        "transport_retries": 2,
        "transport_retry_backoff_seconds": 2,
    },
    "review": {"host": "127.0.0.1", "port": 8895, "open_browser": True},
    "export": {"root": "", "mask_format": "png"},
}

ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        expanded = ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
        return os.path.expanduser(expanded)
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


def load_config(path: Path) -> Dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError("配置文件不存在：{}".format(path))
    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, dict):
        raise ValueError("配置文件根节点必须是 JSON object")
    config = _expand(_merge(DEFAULT_CONFIG, loaded))
    config["_config_path"] = str(path)
    config["_project_root"] = str(path.parent.resolve())
    return config


def resolve_project_path(config: Dict[str, Any], value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = Path(config["_project_root"]) / path
    return path.resolve()


def project_paths(config: Dict[str, Any]) -> Dict[str, Path]:
    project = config["project"]
    return {
        "root": Path(config["_project_root"]),
        "reference": resolve_project_path(config, project["reference_root"]),
        "knowledge": resolve_project_path(config, project["knowledge_root"]),
        "intermediate": resolve_project_path(config, project["intermediate_root"]),
        "database": resolve_project_path(config, project["database"]),
    }


def load_claude_environment(config: Dict[str, Any]) -> Dict[str, str]:
    """Load selected API environment values without logging secret contents."""
    core = config["core"]
    values: Dict[str, str] = {}
    settings_value = str(core.get("claude_settings") or "").strip()
    if settings_value:
        settings = Path(settings_value)
        if settings.is_file():
            try:
                payload = json.loads(settings.read_text(encoding="utf-8-sig"))
                env = payload.get("env", {}) if isinstance(payload, dict) else {}
                if isinstance(env, dict):
                    for key, value in env.items():
                        if isinstance(value, (str, int, float)):
                            values[str(key)] = str(value)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
    credentials_path = Path(config["_project_root"]) / "api_credentials.local.json"
    if credentials_path.is_file():
        try:
            local_payload = json.loads(credentials_path.read_text(encoding="utf-8-sig"))
            if isinstance(local_payload, dict):
                for key, value in local_payload.items():
                    if isinstance(value, (str, int, float)) and str(value):
                        values[str(key)] = str(value)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    for key in (str(core.get("base_url_env") or ""), str(core.get("api_key_env") or "")):
        if key and os.environ.get(key):
            values[key] = os.environ[key]
    return values


def save_local_api_credentials(config: Dict[str, Any], values: Dict[str, str]) -> Path:
    """Persist only explicitly supplied local credentials outside config.json."""
    path = Path(config["_project_root"]) / "api_credentials.local.json"
    existing: Dict[str, str] = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                existing = {str(key): str(value) for key, value in payload.items() if value}
        except (OSError, ValueError, json.JSONDecodeError):
            existing = {}
    for key, value in values.items():
        if value:
            existing[str(key)] = str(value)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def save_config_sections(config: Dict[str, Any], updates: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Update whitelisted runtime sections while preserving unrelated config keys."""
    path = Path(config["_config_path"])
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("配置文件根节点必须是object")
    allowed = {"core", "intelligence", "generation"}
    for section, values in updates.items():
        if section not in allowed or not isinstance(values, dict):
            continue
        target = payload.setdefault(section, {})
        if not isinstance(target, dict):
            target = payload[section] = {}
        target.update(values)
    fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".config_", suffix=".json")
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return load_config(path)
