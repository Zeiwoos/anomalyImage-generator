"""复制为 test_模块名.py 后填写；带写操作的示例默认跳过。"""

from __future__ import annotations

import unittest

from base import ManualApiTestCase


class ExampleTest(ManualApiTestCase):
    def test_read_only_example(self) -> None:
        items = self.items()
        self.assertIsInstance(items, list)

    @unittest.skip("模板：确认使用专用测试数据集后删除此装饰器")
    def test_generation_queue_example(self) -> None:
        response = self.client.post_json("/api/run-queue", {})
        self.assertTrue(response.get("ok"), response)
        final_state = self.wait_worker_idle()
        self.assertFalse(final_state.get("running"), final_state)

    @unittest.skip("模板：填写专用测试样本ID后删除此装饰器")
    def test_review_example(self) -> None:
        sample_id = "REPLACE_WITH_TEST_SAMPLE_ID"
        response = self.client.post_json(
            "/api/review",
            {
                "sample_id": sample_id,
                "stage": "anomaly",
                "status": "approved",
                "reason_codes": [],
                "comment": "接口测试",
            },
        )
        self.assertTrue(response.get("ok"), response)

