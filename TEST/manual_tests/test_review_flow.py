from pathlib import Path

from PIL import Image

from TEST._shared.fixtures import LocalHttpTest, png_url


class ReviewFlowCases(LocalHttpTest):
    def test_B01_health_items_worker_routes(self):
        """B01：实际 HTTP 读取接口应返回包含两个 ROI 的分组样本和空闲工作线程状态。"""
        status, health = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])
        status, payload = self.request("GET", "/api/items")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(len(payload["items"][0]["children"]), 2)
        status, worker = self.request("GET", "/api/worker-status")
        self.assertEqual(status, 200)
        self.assertFalse(worker["running"])

    def test_B02_reject_only_selected_roi_and_save_feedback(self):
        """B02：拒绝选中的 ROI 后应仅将其加入队列，同组 ROI 仍应保持待审核状态。"""
        target, sibling = [row["id"] for row in self.rows]
        status, _ = self.request("POST", "/api/review-batch", {
            "sample_ids": [target], "stage": "anomaly", "status": "rejected", "reason_codes": ["WRONG_STRUCTURE"]})
        self.assertEqual(status, 200)
        self.assertEqual(self.pipeline.db.get_sample(target)["workflow"], "regen_queued")
        self.assertEqual(self.pipeline.db.get_sample(sibling)["workflow"], "anomaly_review")
        status, _ = self.request("POST", "/api/generation-feedback", {
            "sample_ids": [target], "comment": "B02_RETRY", "reason_codes": ["ANOMALY_TOO_WEAK"]})
        self.assertEqual(status, 200)
        self.assertEqual(self.pipeline.db.get_sample(target)["anomaly_comment"], "B02_RETRY")
        self.assertEqual(self.pipeline.db.get_sample(sibling)["anomaly_comment"], "")

    def test_B03_approval_reaches_completed_after_mask_only(self):
        """B03：异常审核通过后才能通过掩码审核，最终工作流应为 completed。"""
        target = self.rows[0]["id"]
        for stage, workflow in [("anomaly", "mask_review"), ("mask", "completed")]:
            status, response = self.request("POST", "/api/review", {
                "sample_id": target, "stage": stage, "status": "approved"})
            self.assertEqual(status, 200)
            self.assertEqual(response["result"]["workflow"], workflow)

    def test_B04_mask_review_before_anomaly_approval_fails(self):
        """B04：异常审核通过前提交掩码审核应返回 400，并保持原状态。"""
        target = self.rows[0]["id"]
        status, _ = self.request("POST", "/api/review", {"sample_id": target, "stage": "mask", "status": "approved"})
        self.assertEqual(status, 400)
        self.assertEqual(self.pipeline.db.get_sample(target)["workflow"], "anomaly_review")

    def test_B05_bad_batch_prevalidation_has_no_partial_approval(self):
        """B05：批量请求包含未知 ID 时，不应通过其中有效样本的审核。"""
        target = self.rows[0]["id"]
        status, _ = self.request("POST", "/api/review-batch", {
            "sample_ids": [target, "nonexistent"], "stage": "anomaly", "status": "approved"})
        self.assertEqual(status, 400)
        self.assertEqual(self.pipeline.db.get_sample(target)["anomaly_status"], "pending")

    def test_B06_mask_save_binary_backup_and_size_validation(self):
        """B06：编辑后的掩码应二值化、备份并重置为待审核；尺寸错误的掩码应被拒绝。"""
        target = self.rows[0]["id"]
        self.app.review(target, "anomaly", "approved", [], "")
        edited = Image.new("L", (128, 96), 0)
        edited.paste(180, (18, 30, 25, 38))
        status, response = self.request("POST", "/api/mask", {"sample_id": target, "png": png_url(edited)})
        self.assertEqual(status, 200)
        mask_path = Path(self.pipeline.db.active_attempt(target)["mask_path"])
        with Image.open(mask_path) as actual:
            self.assertEqual(set(actual.getdata()), {0, 255})
        self.assertEqual(len(list((mask_path.parent / "mask_backups").glob("*.png"))), 1)
        status, _ = self.request("POST", "/api/mask", {"sample_id": target, "png": png_url(Image.new("L", (8, 8)))})
        self.assertEqual(status, 400)

    def test_B07_image_bytes_and_unknown_image(self):
        """B07：图像接口应返回真实源文件字节，未知样本应返回 404。"""
        target = self.rows[0]["id"]
        status, data = self.request("GET", "/api/image?sample=" + target + "&kind=source")
        self.assertEqual(status, 200)
        self.assertEqual(data, Path(self.rows[0]["image_path"]).read_bytes())
        self.assertEqual(self.request("GET", "/api/image?sample=missing&kind=candidate")[0], 404)

    def test_B08_csv_includes_independent_roi_outcomes(self):
        """B08：下载的结果应包含两个 ROI 的 ID 以及已保存的拒绝反馈。"""
        target = self.rows[0]["id"]
        self.app.review(target, "anomaly", "rejected", ["WRONG_STRUCTURE"], "B08")
        status, data = self.request("GET", "/api/export-results")
        self.assertEqual(status, 200)
        text = data.decode("utf-8-sig")
        for row in self.rows:
            self.assertIn(row["id"], text)
        self.assertIn("B08", text)

    def test_B09_bad_json_and_unknown_routes(self):
        """B09：格式错误的 JSON 应返回 400，未知接口应返回 404。"""
        self.assertEqual(self.request("POST", "/api/review", raw=b"{")[0], 400)
        self.assertEqual(self.request("POST", "/api/no-such-route", {})[0], 404)

    def test_B10_delete_requires_confirmation_and_is_recoverable(self):
        """B10：删除操作必须准确确认 ID，并将整个合成样本目录移入回收目录。"""
        target = self.rows[0]["id"]
        status, _ = self.request("POST", "/api/delete-sample", {"sample_id": target, "confirmation": "wrong"})
        self.assertEqual(status, 400)
        self.assertTrue(self.annotation.is_file())
        status, payload = self.request("POST", "/api/delete-sample", {"sample_id": target, "confirmation": target})
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["affected_samples"], 2)
        self.assertTrue((Path(payload["result"]["moved_to"]) / "source.png").is_file())
        self.assertEqual(self.pipeline.db.list_samples(), [])

    def test_B11_export_requires_all_roi_approvals(self):
        """B11：审核未完成的分组不应导出；全部通过后应导出一张图像和一个合并掩码。"""
        first, second = [r["id"] for r in self.rows]
        for stage in ("anomaly", "mask"):
            self.app.review(first, stage, "approved", [], "")
        self.assertEqual(self.pipeline.export_approved(self.root / "partial")["exported"], 0)
        for stage in ("anomaly", "mask"):
            self.app.review(second, stage, "approved", [], "")
        result = self.pipeline.export_approved(self.root / "export")
        self.assertEqual(result["exported"], 1)
        masks = list((self.root / "export").rglob("*__mask.png"))
        self.assertEqual(len(masks), 1)
        with Image.open(masks[0]) as mask:
            self.assertEqual(mask.getpixel((20, 30)), 255)
            self.assertEqual(mask.getpixel((64, 30)), 255)
            self.assertEqual(mask.getpixel((0, 0)), 0)

    def test_D03_anomaly_cannot_use_normal_stage_to_skip_mask_review(self):
        """D03：正常样本审核只能用于正常样本。"""
        target = self.rows[0]['id']
        before = self.pipeline.db.get_sample(target)
        self.assertEqual(before['split'], 'anomaly')
        code, result = self.request('POST', '/api/review', {
            'sample_id': target, 'stage': 'normal', 'status': 'approved'})
        after = self.pipeline.db.get_sample(target)
        self.assertEqual((code, after['workflow']), (400, before['workflow']), result)

    def test_D03b_normal_cannot_use_anomaly_stage(self):
        """D03b 反向边界：正常数据不能进入异常样本审核流程。"""
        target = self.rows[0]['id']
        with self.pipeline.db.connect() as connection:
            connection.execute("UPDATE samples SET split='normal',workflow='normal_review' WHERE id=?", (target,))
        code, _ = self.request('POST', '/api/review', {
            'sample_id': target, 'stage': 'anomaly', 'status': 'approved'})
        self.assertEqual(code, 400)

