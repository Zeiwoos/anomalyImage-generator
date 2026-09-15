from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageOps

from .config import load_claude_environment


@dataclass
class CoreRequest:
    source_path: Path
    roi_mask_path: Path
    prompt_path: Path
    output_path: Path
    reference_paths: List[Path]
    sample_id: str
    attempt: int


class CoreAdapter:
    name = "base"
    supports_multi_output = False

    def generate(self, request: CoreRequest) -> Dict[str, Any]:
        raise NotImplementedError

    def generate_many(self, request: CoreRequest, output_paths: List[Path]) -> List[Dict[str, Any]]:
        """Generate several candidates for one identical edit request.

        Adapters without native multi-output support deliberately fall back to
        separate calls.  The pipeline can therefore enable candidate batching
        without making non-OpenAI adapters unusable.
        """
        results: List[Dict[str, Any]] = []
        for output_path in output_paths:
            child = CoreRequest(
                request.source_path, request.roi_mask_path, request.prompt_path,
                output_path, request.reference_paths, request.sample_id, request.attempt,
            )
            results.append(self.generate(child))
        return results


class CoreTransportError(RuntimeError):
    """Retryable gateway/network failure; it must not consume a logical image version."""

    retryable = True


class MockAdapter(CoreAdapter):
    name = "mock"

    def generate(self, request: CoreRequest) -> Dict[str, Any]:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(request.source_path) as opened:
            image = opened.convert("L") if opened.mode == "L" else opened.convert("RGB")
            image.save(request.output_path, format="PNG")
        return {"adapter": self.name, "warning": "MOCK_CORE_NO_ANOMALY"}


class CommandAdapter(CoreAdapter):
    name = "command"

    def __init__(self, config: Dict[str, Any], runtime_env: Dict[str, str]) -> None:
        self.config = config
        self.runtime_env = runtime_env

    def generate(self, request: CoreRequest) -> Dict[str, Any]:
        template = self.config.get("command") or []
        if not isinstance(template, list) or not template:
            raise ValueError("core.command 必须是非空参数数组，且不要包含密钥")
        values = {
            "input": str(request.source_path),
            "mask": str(request.roi_mask_path),
            "prompt": str(request.prompt_path),
            "output": str(request.output_path),
            "references": os.pathsep.join(str(path) for path in request.reference_paths),
            "sample_id": request.sample_id,
            "attempt": str(request.attempt),
        }
        command = [str(token).format(**values) for token in template]
        env = os.environ.copy()
        env.update(self.runtime_env)
        base_env = str(self.config.get("base_url_env") or "")
        key_env = str(self.config.get("api_key_env") or "")
        if base_env and self.runtime_env.get(base_env):
            env["CORE_BASE_URL"] = self.runtime_env[base_env]
        if key_env and self.runtime_env.get(key_env):
            env["CORE_API_KEY"] = self.runtime_env[key_env]
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            command,
            cwd=str(request.output_path.parent),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=int(self.config.get("timeout_seconds") or 300),
            shell=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "")[-4000:]
            raise RuntimeError("CORE command失败（{}）：{}".format(completed.returncode, stderr))
        if not request.output_path.is_file():
            raise FileNotFoundError("CORE command没有生成输出：{}".format(request.output_path))
        return {"adapter": self.name, "returncode": completed.returncode}


def _data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return "data:{};base64,{}".format(mime, base64.b64encode(path.read_bytes()).decode("ascii"))


def _extract(payload: Any, dotted: str) -> Optional[Any]:
    current = payload
    for token in dotted.split("."):
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            if token not in current:
                return None
            current = current[token]
        else:
            return None
    return current


def _http_opener(config: Dict[str, Any], runtime_env: Dict[str, str], base_url: str):
    """Build an opener while honoring the project proxy policy.

    Python's urllib may read the operating system proxy settings. The private
    gateway used by this project must bypass that proxy when ``no_proxy`` or
    ``NO_PROXY`` explicitly covers the target host.
    """
    mode = str(config.get("proxy_mode") or "auto").strip().lower()
    if mode == "direct":
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if mode == "system":
        return urllib.request.build_opener()
    host = (urlparse(base_url).hostname or "").lower()
    no_proxy = str(runtime_env.get("no_proxy") or runtime_env.get("NO_PROXY") or "")
    tokens = [item.strip().split(":", 1)[0].lstrip(".").lower() for item in no_proxy.split(",") if item.strip()]
    bypass = any(host == token or (token and host.endswith("." + token)) for token in tokens)
    return urllib.request.build_opener(urllib.request.ProxyHandler({})) if bypass else urllib.request.build_opener()


def _png_bytes(path: Path, mode: str = "") -> bytes:
    with Image.open(path) as opened:
        image = opened.convert(mode) if mode else opened.copy()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def normalized_edit_size(width: int, height: int) -> Optional[tuple]:
    """Return a near-source GPT Image size or None when safe normalization is impossible."""
    if width <= 0 or height <= 0 or max(width, height) > 3840:
        return None
    if max(width, height) / max(1, min(width, height)) > 3:
        return None
    pixels = width * height
    if not 655360 <= pixels <= 8294400:
        return None
    target_width = width if width % 16 == 0 else max(16, (width // 16) * 16)
    target_height = height if height % 16 == 0 else max(16, (height // 16) * 16)
    target_pixels = target_width * target_height
    if not 655360 <= target_pixels <= 8294400:
        return None
    return target_width, target_height


def _multipart_body(fields: Dict[str, Any], files: List[tuple]) -> tuple:
    boundary = "----anomalyfactory{}".format(uuid.uuid4().hex)
    chunks: List[bytes] = []
    for name, value in fields.items():
        if value is None or value == "":
            continue
        chunks.append(
            "--{}\r\nContent-Disposition: form-data; name=\"{}\"\r\n\r\n{}\r\n".format(
                boundary, str(name).replace('"', "_"), str(value)
            ).encode("utf-8")
        )
    for field, filename, mime, payload in files:
        chunks.append(
            "--{}\r\nContent-Disposition: form-data; name=\"{}\"; filename=\"{}\"\r\nContent-Type: {}\r\n\r\n".format(
                boundary, str(field).replace('"', "_"), str(filename).replace('"', "_"), mime
            ).encode("utf-8")
        )
        chunks.extend([payload, b"\r\n"])
    chunks.append("--{}--\r\n".format(boundary).encode("ascii"))
    return "multipart/form-data; boundary={}".format(boundary), b"".join(chunks)


class HttpJsonAdapter(CoreAdapter):
    """Configurable JSON/base64 adapter for image-edit gateways.

    The default payload is deliberately simple. A provider-specific wrapper can
    instead be connected with CommandAdapter without changing the pipeline.
    """

    name = "http_json"

    def __init__(self, config: Dict[str, Any], runtime_env: Dict[str, str]) -> None:
        self.config = config
        self.runtime_env = runtime_env

    def generate(self, request: CoreRequest) -> Dict[str, Any]:
        base_env = str(self.config.get("base_url_env") or "")
        key_env = str(self.config.get("api_key_env") or "")
        base_url = str(self.config.get("base_url") or self.runtime_env.get(base_env, "")).rstrip("/") + "/"
        if base_url == "/":
            raise ValueError("未配置 CORE base_url")
        endpoint = str(self.config.get("endpoint") or "")
        url = endpoint if endpoint.startswith(("http://", "https://")) else urljoin(base_url, endpoint.lstrip("/"))
        api_key = self.runtime_env.get(key_env, "") or os.environ.get(key_env, "")
        if not api_key:
            raise ValueError("环境中没有 CORE API 密钥：{}".format(key_env))
        body: Dict[str, Any] = {
            "model": str(self.config.get("model") or self.runtime_env.get("ANTHROPIC_MODEL", "")),
            "prompt": request.prompt_path.read_text(encoding="utf-8"),
            "image": _data_url(request.source_path),
            "mask": _data_url(request.roi_mask_path),
            "reference_images": [_data_url(path) for path in request.reference_paths],
        }
        extra = self.config.get("extra_body")
        if isinstance(extra, dict):
            body.update(extra)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        header = str(self.config.get("auth_header") or "Authorization")
        scheme = str(self.config.get("auth_scheme") or "Bearer").strip()
        headers[header] = "{} {}".format(scheme, api_key).strip()
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        opener = _http_opener(self.config, self.runtime_env, base_url)
        with opener.open(req, timeout=int(self.config.get("timeout_seconds") or 300)) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        encoded = _extract(response_payload, str(self.config.get("response_base64_field") or "data.0.b64_json"))
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(encoded, str) and encoded:
            if encoded.startswith("data:"):
                encoded = encoded.split(",", 1)[1]
            request.output_path.write_bytes(base64.b64decode(encoded))
        else:
            image_url = _extract(response_payload, str(self.config.get("response_url_field") or "data.0.url"))
            if not isinstance(image_url, str) or not image_url:
                raise ValueError("CORE响应中找不到图片字段")
            with opener.open(image_url, timeout=int(self.config.get("timeout_seconds") or 300)) as response:
                request.output_path.write_bytes(response.read())
        return {"adapter": self.name, "endpoint": endpoint, "response_keys": sorted(response_payload.keys()) if isinstance(response_payload, dict) else []}


class OpenAIImageEditsAdapter(CoreAdapter):
    """OpenAI-compatible multipart adapter for ``/v1/images/edits``."""

    name = "openai_image_edits"
    supports_multi_output = True

    def __init__(self, config: Dict[str, Any], runtime_env: Dict[str, str]) -> None:
        self.config = config
        self.runtime_env = runtime_env
        base_env = str(config.get("base_url_env") or "")
        self.base_url = str(config.get("base_url") or runtime_env.get(base_env, "")).strip().rstrip("/") + "/"
        if self.base_url == "/":
            raise ValueError("未配置图像编辑 API base_url")
        key_env = str(config.get("api_key_env") or "")
        self.api_key = runtime_env.get(key_env, "") or os.environ.get(key_env, "")
        if not self.api_key:
            raise ValueError("环境中没有图像编辑 API 密钥：{}".format(key_env))
        self.opener = _http_opener(config, runtime_env, self.base_url)

    def _url(self) -> str:
        endpoint = str(self.config.get("endpoint") or "/v1/images/edits")
        return endpoint if endpoint.startswith(("http://", "https://")) else urljoin(self.base_url, endpoint.lstrip("/"))

    def _auth_headers(self, content_type: str) -> Dict[str, str]:
        header = str(self.config.get("auth_header") or "Authorization")
        scheme = str(self.config.get("auth_scheme") or "Bearer").strip()
        return {"Accept": "application/json", "Content-Type": content_type, header: "{} {}".format(scheme, self.api_key).strip()}

    def probe(self) -> Dict[str, Any]:
        """Perform non-generating gateway checks without exposing credentials."""
        result: Dict[str, Any] = {"base_url": self.base_url.rstrip("/"), "model": str(self.config.get("model") or "gpt-image-2")}
        headers = self._auth_headers("application/json")
        for key, url in (("root", self.base_url), ("models", urljoin(self.base_url, "v1/models"))):
            try:
                with self.opener.open(urllib.request.Request(url, headers=headers, method="GET"), timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    result[key + "_status"] = response.status
                    if key == "models":
                        model_ids = [str(row.get("id")) for row in payload.get("data", []) if isinstance(row, dict)]
                        result["models"] = model_ids
                        result["selected_model_available"] = result["model"] in model_ids
            except Exception as exc:
                result[key + "_error"] = "{}: {}".format(type(exc).__name__, exc)
        content_type, body = _multipart_body(
            {"model": result["model"], "prompt": "protocol validation only"}, []
        )
        req = urllib.request.Request(self._url(), data=body, headers=self._auth_headers(content_type), method="POST")
        try:
            with self.opener.open(req, timeout=15) as response:
                result["image_edits_status"] = response.status
                result["image_edits_recognized"] = True
        except urllib.error.HTTPError as exc:
            detail = exc.read(2000).decode("utf-8", "replace")
            result["image_edits_status"] = exc.code
            result["image_edits_recognized"] = exc.code == 400 and "image" in detail.lower()
        except Exception as exc:
            result["image_edits_error"] = "{}: {}".format(type(exc).__name__, exc)
            result["image_edits_recognized"] = False
        return result

    @staticmethod
    def _source_and_mask(source_path: Path, mask_path: Path, target_size: Optional[tuple] = None) -> tuple:
        with Image.open(source_path) as opened:
            source = opened.copy()
        with Image.open(mask_path) as opened:
            roi = opened.convert("L")
        if roi.size != source.size:
            raise ValueError("ROI mask尺寸{}与源图{}不一致".format(roi.size, source.size))
        original_size = source.size
        if target_size and tuple(target_size) != source.size:
            source = source.resize(tuple(target_size), Image.Resampling.LANCZOS)
            roi = roi.resize(tuple(target_size), Image.Resampling.NEAREST)
        source_buffer = io.BytesIO()
        source.save(source_buffer, format="PNG")
        # Image Edits replaces transparent pixels. Pipeline ROI is white=edit.
        alpha_mask = Image.new("RGBA", roi.size, (0, 0, 0, 255))
        alpha_mask.putalpha(ImageOps.invert(roi.point(lambda value: 255 if value >= 128 else 0, mode="L")))
        mask_buffer = io.BytesIO()
        alpha_mask.save(mask_buffer, format="PNG")
        return source_buffer.getvalue(), mask_buffer.getvalue(), original_size, source.size

    def generate(self, request: CoreRequest) -> Dict[str, Any]:
        return self.generate_many(request, [request.output_path])[0]

    def generate_many(self, request: CoreRequest, output_paths: List[Path]) -> List[Dict[str, Any]]:
        if not output_paths:
            raise ValueError("CORE多候选输出路径不能为空")
        if len(output_paths) > 10:
            raise ValueError("单次CORE请求最多输出10张候选")
        with Image.open(request.source_path) as opened:
            original_size = opened.size
        target_size = None
        if bool(self.config.get("normalize_request_size", True)):
            target_size = normalized_edit_size(*original_size)
        source_bytes, mask_bytes, source_size, submitted_size = self._source_and_mask(
            request.source_path, request.roi_mask_path, target_size
        )
        fields: Dict[str, Any] = {
            "model": str(self.config.get("model") or "gpt-image-2"),
            "prompt": request.prompt_path.read_text(encoding="utf-8"),
            "quality": str(self.config.get("quality") or "high"),
            "output_format": str(self.config.get("output_format") or "png"),
            "n": len(output_paths),
        }
        size_mode = str(self.config.get("size_mode") or "source_if_supported").lower()
        width, height = submitted_size
        source_size_supported = (
            width <= 3840 and height <= 3840 and width % 16 == 0 and height % 16 == 0
            and max(width, height) / max(1, min(width, height)) <= 3
            and 655360 <= width * height <= 8294400
        )
        if size_mode == "source" or (size_mode == "source_if_supported" and source_size_supported):
            fields["size"] = "{}x{}".format(width, height)
        extra = self.config.get("extra_form")
        if isinstance(extra, dict):
            fields.update(extra)
        image_field = str(self.config.get("image_field") or "image[]")
        files: List[tuple] = [
            (image_field, "source.png", "image/png", source_bytes),
            ("mask", "mask.png", "image/png", mask_bytes),
        ]
        for index, path in enumerate(request.reference_paths):
            files.append((image_field, "reference_{:02d}.png".format(index + 1), "image/png", _png_bytes(path)))
        content_type, body = _multipart_body(fields, files)
        transport_limit = max(1, int(self.config.get("transport_retries") or 4))
        transport_backoff = max(0.0, float(self.config.get("transport_retry_backoff_seconds") or 2.0))
        retryable_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
        response_payload: Dict[str, Any] = {}
        transport_errors: List[str] = []
        for output_path in output_paths:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        for transport_attempt in range(1, transport_limit + 1):
            req = urllib.request.Request(self._url(), data=body, headers=self._auth_headers(content_type), method="POST")
            try:
                with self.opener.open(req, timeout=int(self.config.get("timeout_seconds") or 300)) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                data = response_payload.get("data") if isinstance(response_payload, dict) else None
                if not isinstance(data, list) or len(data) < len(output_paths):
                    returned = len(data) if isinstance(data, list) else 0
                    raise ValueError("Image Edits请求{}张但只返回{}张".format(len(output_paths), returned))
                for index, output_path in enumerate(output_paths):
                    item = data[index] if isinstance(data[index], dict) else {}
                    encoded = item.get("b64_json")
                    if isinstance(encoded, str) and encoded:
                        output_path.write_bytes(base64.b64decode(encoded.split(",", 1)[-1]))
                        continue
                    image_url = item.get("url")
                    if not isinstance(image_url, str) or not image_url:
                        raise ValueError("Image Edits响应中找不到data[{}].b64_json或url".format(index))
                    with self.opener.open(image_url, timeout=int(self.config.get("timeout_seconds") or 300)) as response:
                        output_path.write_bytes(response.read())
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read(4000).decode("utf-8", "replace")
                message = "HTTP {}：{}".format(exc.code, detail)
                if exc.code not in retryable_statuses:
                    raise RuntimeError("Image Edits API失败（{}）".format(message)) from exc
                transport_errors.append(message)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, EOFError) as exc:
                transport_errors.append("{}: {}".format(type(exc).__name__, exc))
            if transport_attempt >= transport_limit:
                raise CoreTransportError(
                    "Image Edits传输连续失败{}次：{}".format(transport_limit, transport_errors[-1] if transport_errors else "unknown")
                )
            if transport_backoff:
                time.sleep(min(20.0, transport_backoff * transport_attempt))
        common = {
            "adapter": self.name, "endpoint": self._url(), "model": fields["model"],
            "reference_count": len(request.reference_paths), "image_count": 1 + len(request.reference_paths),
            "source_size": list(source_size), "submitted_source_size": list(submitted_size),
            "requested_size": fields.get("size", "auto"), "requested_output_count": len(output_paths),
            "returned_output_count": len(response_payload.get("data") or []) if isinstance(response_payload, dict) else 0,
            "request_inputs": ["source"] + ["reference_{:02d}".format(index + 1) for index in range(len(request.reference_paths))],
            "usage": response_payload.get("usage", {}) if isinstance(response_payload, dict) else {},
            "transport_attempts": transport_attempt,
            "transport_errors_before_success": transport_errors,
        }
        return [{**common, "output_index": index} for index in range(len(output_paths))]


class OpenAIResponsesImageAdapter(CoreAdapter):
    """Use a GPT-5.x mainline model and its Responses image-generation tool.

    Files are uploaded with ``purpose=vision``.  The source image is the first
    input image, optional knowledge-bank references follow it, and the LabelMe
    ROI is supplied as an alpha mask.  Uploaded temporary files are deleted on
    a best-effort basis after the response is received.
    """

    name = "openai_responses_image"

    def __init__(self, config: Dict[str, Any], runtime_env: Dict[str, str]) -> None:
        self.config = config
        self.runtime_env = runtime_env
        self.opener = _http_opener(config, runtime_env, self._base_url())

    def _base_url(self) -> str:
        base_env = str(self.config.get("base_url_env") or "")
        value = str(self.config.get("base_url") or self.runtime_env.get(base_env, "")).strip()
        if not value:
            raise ValueError("未配置 GPT-5.6 API base_url")
        return value.rstrip("/") + "/"

    def _api_key(self) -> str:
        key_env = str(self.config.get("api_key_env") or "")
        value = self.runtime_env.get(key_env, "") or os.environ.get(key_env, "")
        if not value:
            raise ValueError("环境中没有 GPT-5.6 API 密钥：{}".format(key_env))
        return value

    def _url(self, key: str, default: str) -> str:
        endpoint = str(self.config.get(key) or default)
        return endpoint if endpoint.startswith(("http://", "https://")) else urljoin(self._base_url(), endpoint.lstrip("/"))

    def _headers(self, content_type: str = "") -> Dict[str, str]:
        header = str(self.config.get("auth_header") or "Authorization")
        scheme = str(self.config.get("auth_scheme") or "Bearer").strip()
        headers = {"Accept": "application/json", header: "{} {}".format(scheme, self._api_key()).strip()}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _json_request(self, url: str, payload: Optional[Dict[str, Any]], method: str = "POST") -> Dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = self._headers("application/json" if payload is not None else "")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with self.opener.open(req, timeout=int(self.config.get("timeout_seconds") or 300)) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _upload_bytes(self, filename: str, payload: bytes, mime: str) -> str:
        boundary = "----anomalyfactory{}".format(uuid.uuid4().hex)
        chunks = [
            "--{}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nvision\r\n".format(boundary).encode("ascii"),
            "--{}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{}\"\r\nContent-Type: {}\r\n\r\n".format(
                boundary, filename.replace('"', "_"), mime
            ).encode("utf-8"),
            payload,
            "\r\n--{}--\r\n".format(boundary).encode("ascii"),
        ]
        body = b"".join(chunks)
        req = urllib.request.Request(
            self._url("files_endpoint", "/v1/files"), data=body,
            headers=self._headers("multipart/form-data; boundary={}".format(boundary)), method="POST",
        )
        with self.opener.open(req, timeout=int(self.config.get("timeout_seconds") or 300)) as response:
            result = json.loads(response.read().decode("utf-8"))
        file_id = result.get("id") if isinstance(result, dict) else None
        if not isinstance(file_id, str) or not file_id:
            raise ValueError("Files API 响应中没有 file id")
        return file_id

    def _upload_path(self, path: Path) -> str:
        suffix = path.suffix.lower()
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        return self._upload_bytes(path.name, path.read_bytes(), mime)

    def _upload_edit_mask(self, path: Path) -> str:
        # OpenAI image-edit masks edit transparent pixels. Pipeline ROI uses
        # white=editable, therefore invert it into the alpha channel.
        with Image.open(path) as opened:
            roi = opened.convert("L")
        rgba = Image.new("RGBA", roi.size, (0, 0, 0, 255))
        rgba.putalpha(ImageOps.invert(roi))
        buffer = io.BytesIO()
        rgba.save(buffer, format="PNG")
        return self._upload_bytes("roi_mask_alpha.png", buffer.getvalue(), "image/png")

    def _delete_file(self, file_id: str) -> None:
        try:
            self._json_request(self._url("files_endpoint", "/v1/files").rstrip("/") + "/" + file_id, None, "DELETE")
        except Exception:
            pass

    def generate(self, request: CoreRequest) -> Dict[str, Any]:
        uploaded: List[str] = []
        try:
            source_id = self._upload_path(request.source_path)
            uploaded.append(source_id)
            mask_id = self._upload_edit_mask(request.roi_mask_path)
            uploaded.append(mask_id)
            content: List[Dict[str, Any]] = [
                {"type": "input_text", "text": request.prompt_path.read_text(encoding="utf-8")},
                {"type": "input_image", "file_id": source_id, "detail": str(self.config.get("image_detail") or "original")},
            ]
            reference_ids: List[str] = []
            for path in request.reference_paths:
                file_id = self._upload_path(path)
                uploaded.append(file_id)
                reference_ids.append(file_id)
                content.append({"type": "input_image", "file_id": file_id, "detail": "auto"})
            tool: Dict[str, Any] = {
                "type": "image_generation",
                "quality": str(self.config.get("quality") or "high"),
                "input_image_mask": {"file_id": mask_id},
            }
            action = str(self.config.get("action") or "edit").strip()
            if action:
                tool["action"] = action
            body: Dict[str, Any] = {
                "model": str(self.config.get("model") or self.runtime_env.get("ANTHROPIC_MODEL", "gpt-5.6-sol")),
                "input": [{"role": "user", "content": content}],
                "tools": [tool],
            }
            effort = str(self.config.get("reasoning_effort") or "").strip()
            if effort:
                body["reasoning"] = {"effort": effort}
            extra = self.config.get("extra_body")
            if isinstance(extra, dict):
                body.update(extra)
            endpoint = self._url("endpoint", "/v1/responses")
            response_payload = self._json_request(endpoint, body)
            encoded = None
            output_types: List[str] = []
            for item in response_payload.get("output", []) if isinstance(response_payload, dict) else []:
                if not isinstance(item, dict):
                    continue
                output_types.append(str(item.get("type") or ""))
                if item.get("type") == "image_generation_call" and isinstance(item.get("result"), str):
                    encoded = item["result"]
                    break
            if not encoded:
                raise ValueError("Responses API 未返回 image_generation_call.result")
            request.output_path.parent.mkdir(parents=True, exist_ok=True)
            request.output_path.write_bytes(base64.b64decode(encoded))
            return {
                "adapter": self.name, "endpoint": endpoint,
                "model": body["model"], "reference_count": len(reference_ids),
                "response_id": response_payload.get("id", ""), "output_types": output_types,
            }
        finally:
            for file_id in uploaded:
                self._delete_file(file_id)


def create_adapter(config: Dict[str, Any]) -> CoreAdapter:
    core = config["core"]
    runtime_env = load_claude_environment(config)
    adapter = str(core.get("adapter") or "mock").lower()
    if adapter == "mock":
        return MockAdapter()
    if adapter == "command":
        return CommandAdapter(core, runtime_env)
    if adapter == "http_json":
        return HttpJsonAdapter(core, runtime_env)
    if adapter == "openai_image_edits":
        return OpenAIImageEditsAdapter(core, runtime_env)
    if adapter == "openai_responses_image":
        return OpenAIResponsesImageAdapter(core, runtime_env)
    raise ValueError("未知 CORE adapter：{}".format(adapter))


def probe_core(config: Dict[str, Any]) -> Dict[str, Any]:
    adapter = create_adapter(config)
    if isinstance(adapter, OpenAIImageEditsAdapter):
        return adapter.probe()
    raise ValueError("probe-core当前仅支持openai_image_edits")
