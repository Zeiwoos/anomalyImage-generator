from __future__ import annotations

import argparse
import base64
import io
import json
import mimetypes
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse

from PIL import Image, ImageDraw

from .config import load_claude_environment, load_config, project_paths
from .core import OpenAIImageEditsAdapter, _extract, _http_opener, _multipart_body
from .intelligence import _response_text


STATIC_DIR = Path(__file__).resolve().parent / "speed_test_static"
MAX_BODY_BYTES = 35 * 1024 * 1024
MAX_IMAGE_BYTES = 25 * 1024 * 1024


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _default_source(path: Path) -> Path:
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("L", (1024, 1024), 45)
    draw = ImageDraw.Draw(image)
    for y in range(1024):
        shade = 35 + round(70 * y / 1023)
        draw.line((0, y, 1023, y), fill=shade)
    draw.rounded_rectangle((135, 205, 890, 815), radius=45, fill=125, outline=175, width=12)
    draw.ellipse((285, 330, 740, 785), fill=78, outline=190, width=16)
    draw.ellipse((400, 445, 625, 670), fill=145, outline=55, width=20)
    for x in (245, 780):
        draw.ellipse((x - 45, 465, x + 45, 555), fill=55, outline=175, width=9)
    image.save(path, format="PNG", optimize=True)
    return path


def _decode_image(data_url: str, output: Path) -> Path:
    if not data_url:
        raise ValueError("没有上传图片")
    encoded = data_url.split(",", 1)[1] if "," in data_url else data_url
    try:
        payload = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("上传图片不是有效Base64") from exc
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("上传图片超过25MB")
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            image = opened.convert("L") if opened.mode in {"1", "L", "I", "I;16", "F"} else opened.convert("RGB")
            image.load()
    except Exception as exc:
        raise ValueError("上传内容不是有效图片") from exc
    if image.width * image.height > 24_000_000:
        raise ValueError("图片像素数超过2400万")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)
    return output


def _image_data_url(path: Path, maximum: int = 2048) -> Tuple[str, Tuple[int, int]]:
    with Image.open(path) as opened:
        image = opened.convert("L") if opened.mode in {"1", "L", "I", "I;16", "F"} else opened.convert("RGB")
        original_size = image.size
        if max(image.size) > maximum:
            scale = maximum / max(image.size)
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"), original_size


class APIBenchmark:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.core = dict(config.get("core") or {})
        self.intelligence = {**self.core, **dict(config.get("intelligence") or {})}
        self.runtime = load_claude_environment(config)
        base_env = str(self.core.get("base_url_env") or "")
        self.base_url = str(self.core.get("base_url") or self.runtime.get(base_env, "")).strip().rstrip("/") + "/"
        if self.base_url == "/":
            raise ValueError("没有配置API base_url")
        key_env = str(self.core.get("api_key_env") or "")
        self.api_key = self.runtime.get(key_env, "") or os.environ.get(key_env, "")
        if not self.api_key:
            raise ValueError("没有配置API密钥：{}".format(key_env))
        self.opener = _http_opener(self.core, self.runtime, self.base_url)
        self.auth_header = str(self.core.get("auth_header") or "Authorization")
        self.auth_scheme = str(self.core.get("auth_scheme") or "Bearer").strip()

    def _url(self, endpoint: str) -> str:
        return endpoint if endpoint.startswith(("http://", "https://")) else urljoin(self.base_url, endpoint.lstrip("/"))

    def _headers(self, content_type: str = "application/json") -> Dict[str, str]:
        headers = {"Accept": "application/json", self.auth_header: "{} {}".format(self.auth_scheme, self.api_key).strip()}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _timed(self, request: urllib.request.Request, timeout: int) -> Tuple[bytes, Dict[str, Any]]:
        started = time.perf_counter()
        try:
            with self.opener.open(request, timeout=timeout) as response:
                headers_at = time.perf_counter()
                payload = response.read()
                completed = time.perf_counter()
                status = int(getattr(response, "status", 200))
                response_headers = dict(response.headers.items()) if getattr(response, "headers", None) else {}
        except urllib.error.HTTPError as exc:
            headers_at = time.perf_counter()
            payload = exc.read()
            completed = time.perf_counter()
            detail = payload[:4000].decode("utf-8", "replace")
            raise RuntimeError("HTTP {}：{}".format(exc.code, detail)) from exc
        return payload, {
            "http_status": status,
            "ttfb_seconds": round(headers_at - started, 3),
            "download_seconds": round(completed - headers_at, 3),
            "api_total_seconds": round(completed - started, 3),
            "response_bytes": len(payload),
            "request_id": response_headers.get("x-request-id", ""),
        }

    @staticmethod
    def _finalize(kind: str, url: str, request_bytes: int, prepared_at: float, result: Dict[str, Any]) -> Dict[str, Any]:
        result.update(
            {
                "kind": kind, "url": url, "request_bytes": request_bytes,
                "wall_seconds": round(time.perf_counter() - prepared_at, 3), "finished_at": _now(),
            }
        )
        return result

    def gateway(self) -> Dict[str, Any]:
        started = time.perf_counter()
        url = self._url("/v1/models")
        request = urllib.request.Request(url, headers=self._headers(""), method="GET")
        raw, metrics = self._timed(request, 30)
        payload = json.loads(raw.decode("utf-8"))
        models = [str(row.get("id")) for row in payload.get("data", []) if isinstance(row, dict)]
        metrics.update({"models": models, "model_count": len(models)})
        return self._finalize("gateway", url, 0, started, metrics)

    def text(self, prompt: str = "") -> Dict[str, Any]:
        started = time.perf_counter()
        url = self._url(str(self.intelligence.get("endpoint") or "/v1/responses"))
        body = {
            "model": str(self.intelligence.get("model") or "gpt-5.6-sol"),
            "input": prompt.strip() or "用一句中文回答：当前API文本响应测速正常。",
            "reasoning": {"effort": "low"}, "store": False,
        }
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        raw, metrics = self._timed(urllib.request.Request(url, data=encoded, headers=self._headers(), method="POST"), 180)
        payload = json.loads(raw.decode("utf-8"))
        metrics.update({"model": body["model"], "output_preview": _response_text(payload)[:500], "usage": payload.get("usage", {})})
        return self._finalize("text", url, len(encoded), started, metrics)

    def vision(self, source: Path, prompt: str = "") -> Dict[str, Any]:
        started = time.perf_counter()
        url = self._url(str(self.intelligence.get("endpoint") or "/v1/responses"))
        data_url, source_size = _image_data_url(source)
        body = {
            "model": str(self.intelligence.get("model") or "gpt-5.6-sol"),
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": prompt.strip() or "用不超过80个中文字概括这张工业图像中的主要可见结构。"},
                {"type": "input_image", "image_url": data_url, "detail": "high"},
            ]}],
            "reasoning": {"effort": "low"}, "store": False,
        }
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        raw, metrics = self._timed(urllib.request.Request(url, data=encoded, headers=self._headers(), method="POST"), 300)
        payload = json.loads(raw.decode("utf-8"))
        metrics.update(
            {"model": body["model"], "source_size": list(source_size), "output_preview": _response_text(payload)[:800], "usage": payload.get("usage", {})}
        )
        return self._finalize("vision", url, len(encoded), started, metrics)

    def image_edit(self, source: Path, output_dir: Path, prompt: str = "") -> Dict[str, Any]:
        started = time.perf_counter()
        run_id = uuid.uuid4().hex[:12]
        with Image.open(source) as opened:
            width, height = opened.size
        roi = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(roi)
        margin_x, margin_y = round(width * 0.32), round(height * 0.32)
        draw.rounded_rectangle((margin_x, margin_y, width - margin_x, height - margin_y), radius=max(8, min(width, height) // 30), fill=255)
        mask_path = output_dir / "{}_roi.png".format(run_id)
        roi.save(mask_path, format="PNG")
        source_bytes, mask_bytes, source_size, submitted_size = OpenAIImageEditsAdapter._source_and_mask(source, mask_path)
        model = str(self.core.get("model") or "gpt-image-2")
        fields: Dict[str, Any] = {
            "model": model,
            "prompt": prompt.strip() or "Only inside the transparent mask, add one clearly visible irregular dark oil stain on the metal surface. Preserve every other pixel-level visual element, geometry, lighting, and grayscale appearance. Return the full image without text or markings.",
            "quality": str(self.core.get("quality") or "medium"),
            "output_format": str(self.core.get("output_format") or "png"), "n": 1,
        }
        if (
            width <= 3840 and height <= 3840 and width % 16 == 0 and height % 16 == 0
            and max(width, height) / max(1, min(width, height)) <= 3 and 655360 <= width * height <= 8294400
        ):
            fields["size"] = "{}x{}".format(width, height)
        image_field = str(self.core.get("image_field") or "image[]")
        content_type, body = _multipart_body(
            fields,
            [(image_field, "source.png", "image/png", source_bytes), ("mask", "mask.png", "image/png", mask_bytes)],
        )
        url = self._url(str(self.core.get("endpoint") or "/v1/images/edits"))
        raw, metrics = self._timed(
            urllib.request.Request(url, data=body, headers=self._headers(content_type), method="POST"),
            int(self.core.get("timeout_seconds") or 900),
        )
        payload = json.loads(raw.decode("utf-8"))
        encoded = _extract(payload, str(self.core.get("response_base64_field") or "data.0.b64_json"))
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("生图响应没有data[0].b64_json，测速完成但无法保存预览")
        output_name = "{}_result.png".format(run_id)
        output_path = output_dir / output_name
        output_path.write_bytes(base64.b64decode(encoded.split(",", 1)[-1]))
        metrics.update(
            {
                "model": model, "quality": fields["quality"], "source_size": list(source_size),
                "requested_size": fields.get("size", "auto"), "usage": payload.get("usage", {}),
                "result_url": "/api/result/" + output_name,
            }
        )
        return self._finalize("image_edit", url, len(body), started, metrics)


class SpeedTestApplication:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.benchmark = APIBenchmark(config)
        self.output_dir = project_paths(config)["intermediate"] / "api_speed_test"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.default_source = _default_source(self.output_dir / "default_source.png")
        self.history: list[Dict[str, Any]] = []
        self.lock = threading.Lock()

    def public_config(self) -> Dict[str, Any]:
        return {
            "base_url": self.benchmark.base_url.rstrip("/"),
            "text_model": str(self.benchmark.intelligence.get("model") or "gpt-5.6-sol"),
            "image_model": str(self.benchmark.core.get("model") or "gpt-image-2"),
            "quality": str(self.benchmark.core.get("quality") or "medium"),
            "default_source": "/api/result/default_source.png",
        }

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        kind = str(payload.get("kind") or "")
        if kind not in {"gateway", "text", "vision", "image_edit"}:
            raise ValueError("未知测速类型")
        if not self.lock.acquire(False):
            raise RuntimeError("已有测速正在进行，请等待完成")
        try:
            source = self.default_source
            image_data = str(payload.get("image_data") or "")
            if image_data:
                source = _decode_image(image_data, self.output_dir / "uploaded_{}.png".format(uuid.uuid4().hex[:12]))
            prompt = str(payload.get("prompt") or "")[:5000]
            if kind == "gateway":
                result = self.benchmark.gateway()
            elif kind == "text":
                result = self.benchmark.text(prompt)
            elif kind == "vision":
                result = self.benchmark.vision(source, prompt)
            else:
                if payload.get("confirm_cost") is not True:
                    raise ValueError("真实生图测速必须确认会产生一次API调用与费用")
                result = self.benchmark.image_edit(source, self.output_dir, prompt)
            result["success"] = True
            result["id"] = uuid.uuid4().hex[:10]
            self.history.insert(0, result)
            del self.history[30:]
            return result
        finally:
            self.lock.release()


class Handler(BaseHTTPRequestHandler):
    app: SpeedTestApplication

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self._json(200, self.app.public_config())
            return
        if parsed.path == "/api/history":
            self._json(200, {"history": self.app.history})
            return
        if parsed.path.startswith("/api/result/"):
            name = Path(unquote(parsed.path[len("/api/result/"):])).name
            path = (self.app.output_dir / name).resolve()
            try:
                path.relative_to(self.app.output_dir.resolve())
            except ValueError:
                self.send_error(403)
                return
            self._file(path)
            return
        name = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
        path = (STATIC_DIR / name).resolve()
        try:
            path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(403)
            return
        self._file(path)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/run":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError("请求体为空或超过35MB")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求必须是JSON object")
            self._json(200, self.app.run(payload))
        except RuntimeError as exc:
            self._json(409, {"success": False, "error": str(exc)})
        except Exception as exc:
            self._json(400, {"success": False, "error": str(exc)})


def main() -> int:
    parser = argparse.ArgumentParser(description="API real speed tester")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent.parent / "config.json"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8897)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    app = SpeedTestApplication(load_config(Path(args.config)))
    Handler.app = app
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://{}:{}/".format(args.host, args.port)
    print("API speed test: {}".format(url), flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
