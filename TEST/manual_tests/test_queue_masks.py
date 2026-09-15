import threading
import time
from unittest.mock import patch

from PIL import Image, ImageChops

from anomaly_factory.db import Database
from anomaly_factory.pipeline import binary_mask_from_difference, qc_metrics
from TEST._shared.fixtures import LocalHttpTest


class QueueMaskCases(LocalHttpTest):
    def test_B12_queue_duplicate_start_and_completion(self):
        """B12：重复启动应返回 worker_running，原工作线程应恰好完成一次。"""
        target = self.rows[0]["id"]
        self.pipeline.db.set_workflow(target, "regen_queued")
        entered, release = threading.Event(), threading.Event()
        def generate(sample_id, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test barrier timeout")
            self.pipeline.db.set_workflow(sample_id, "anomaly_review")
            return {"sample_id": sample_id, "attempt": 2, "workflow": "anomaly_review", "qc": {"passed": True}}
        with patch.object(self.pipeline, "generate_sample", side_effect=generate) as call:
            try:
                self.assertEqual(self.request("POST", "/api/run-queue", {})[0], 200)
                self.assertTrue(entered.wait(2))
                status, second = self.request("POST", "/api/run-queue", {})
                self.assertEqual(status, 200)
                self.assertFalse(second["result"]["started"])
                self.assertEqual(second["result"]["reason"], "worker_running")
            finally:
                release.set()
                deadline = time.monotonic() + 4
                while self.app.worker_state["running"] and time.monotonic() < deadline:
                    time.sleep(0.02)
            self.assertFalse(self.app.worker_state["running"])
            self.assertEqual(call.call_count, 1)
        self.assertEqual(self.app.worker_state["completed"], 1)

    def test_B13_persisted_review_survives_database_reopen(self):
        """B13：重新打开 SQLite 后应保留审核结果和反馈；本用例不验证服务器进程重启。"""
        target = self.rows[0]["id"]
        self.app.review(target, "anomaly", "rejected", ["WRONG_STRUCTURE"], "B13_PERSIST")
        reopened = Database(self.pipeline.db.path)
        saved = reopened.get_sample(target)
        self.assertEqual(saved["workflow"], "regen_queued")
        self.assertEqual(saved["anomaly_comment"], "B13_PERSIST")

    def test_B14_difference_mask_does_not_escape_allowed_area(self):
        """B14：即使执行膨胀，生成的异常掩码也不能超出允许区域。"""
        source = Image.new("L", (128, 96), 120)
        candidate = Image.new("L", source.size, 45)
        allowed = Image.new("L", source.size, 0)
        allowed.paste(255, (16, 24, 32, 40))
        mask = binary_mask_from_difference(source, candidate, allowed, 10, 8)
        self.assertIsNotNone(mask.getbbox())
        self.assertIsNone(ImageChops.subtract(mask, allowed).getbbox())

    def test_B15_empty_or_border_changes_fail_qc(self):
        """B15：无变化和触及边界的异常掩码都应无法通过确定性质量检查。"""
        source = Image.new("L", (128, 96), 120)
        allowed = Image.new("L", source.size, 255)
        empty = Image.new("L", source.size, 0)
        self.assertIn("EMPTY_CHANGE", qc_metrics(source, source, empty, allowed, "fixture")["failures"])
        border = empty.copy()
        border.paste(255, (0, 0, 10, 10))
        self.assertIn("CHANGE_TOUCHES_BORDER", qc_metrics(source, source, border, allowed, "fixture")["failures"])
