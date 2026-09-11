from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from typing import Any, Dict

from api_client import ApiError, ReviewApiClient


TEST_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG: Dict[str, Any] = {
    "base_url": "http://127.0.0.1:8898",
    "timeout_seconds": 15,
    "worker_timeout_seconds": 1800,
    "poll_interval_seconds": 1.0,
}


def load_test_config() -> Dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    local_path = TEST_ROOT / "config.local.json"
    if local_path.is_file():
        payload = json.loads(local_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("config.local.json 必须是JSON对象")
        config.update(payload)
    if os.environ.get("ANOMALY_TEST_BASE_URL"):
        config["base_url"] = os.environ["ANOMALY_TEST_BASE_URL"]
    if os.environ.get("ANOMALY_TEST_TIMEOUT_SECONDS"):
        config["timeout_seconds"] = float(os.environ["ANOMALY_TEST_TIMEOUT_SECONDS"])
    return config


class ManualApiTestCase(unittest.TestCase):
    config: Dict[str, Any]
    client: ReviewApiClient

    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_test_config()
        cls.client = ReviewApiClient(
            str(cls.config["base_url"]), float(cls.config["timeout_seconds"])
        )
        try:
            health = cls.client.get_json("/api/health")
        except ApiError as exc:
            raise AssertionError(str(exc)) from exc
        if health.get("ok") is not True:
            raise AssertionError(f"后端健康检查未通过：{health}")

    def items(self) -> list[Dict[str, Any]]:
        payload = self.client.get_json("/api/items")
        items = payload.get("items")
        self.assertIsInstance(items, list, payload)
        return items

    def wait_worker_idle(self) -> Dict[str, Any]:
        return self.client.wait_worker_idle(
            float(self.config["worker_timeout_seconds"]),
            float(self.config["poll_interval_seconds"]),
        )

    def assert_has_keys(self, payload: Dict[str, Any], *keys: str) -> None:
        missing = [key for key in keys if key not in payload]
        self.assertFalse(missing, f"缺少字段 {missing}；实际返回：{payload}")

