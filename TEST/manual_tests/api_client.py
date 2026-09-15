from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional


class ApiError(AssertionError):
    """Raised when the review API cannot satisfy a test request."""


@dataclass(frozen=True)
class BinaryResponse:
    body: bytes
    status: int
    content_type: str


class ReviewApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)

    def _url(self, path: str, query: Optional[Dict[str, Any]] = None) -> str:
        url = self.base_url + "/" + path.lstrip("/")
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url

    def request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
    ) -> BinaryResponse:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(
            self._url(path, query), data=body, headers=headers, method=method.upper()
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return BinaryResponse(
                    response.read(),
                    int(response.status),
                    response.headers.get_content_type(),
                )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"{method} {request.full_url} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(
                f"无法连接审核后端 {self.base_url}：{exc.reason}。请先启动请先启动 start_review_tool.bat或 ./start_review_tool.sh，"
                "并核对 config.local.json 中的端口。"
            ) from exc

    @staticmethod
    def _decode_json(response: BinaryResponse, method: str, path: str) -> Dict[str, Any]:
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            preview = response.body[:300].decode("utf-8", errors="replace")
            raise ApiError(f"{method} {path} 未返回有效JSON：{preview}") from exc
        if not isinstance(payload, dict):
            raise ApiError(f"{method} {path} 返回值不是JSON对象")
        return payload

    def get_json(self, path: str, query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._decode_json(self.request("GET", path, query=query), "GET", path)

    def post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._decode_json(self.request("POST", path, payload=payload), "POST", path)

    def get_binary(self, path: str, query: Optional[Dict[str, Any]] = None) -> BinaryResponse:
        return self.request("GET", path, query=query)

    def wait_worker_idle(self, timeout_seconds: float = 1800, interval_seconds: float = 1.0) -> Dict[str, Any]:
        deadline = time.monotonic() + float(timeout_seconds)
        last: Dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.get_json("/api/worker-status")
            if not last.get("running"):
                return last
            time.sleep(max(0.05, float(interval_seconds)))
        raise ApiError(f"等待生成队列结束超时；最后状态：{last}")

