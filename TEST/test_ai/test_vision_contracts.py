import base64
import io
import json
from unittest.mock import Mock

from PIL import Image

from anomaly_factory.intelligence import VisionLLMClient, _json_from_text
from TEST._shared.fixtures import IsolatedPipelineTest


class VisionContractCases(IsolatedPipelineTest):
    def client(self):
        client = VisionLLMClient.__new__(VisionLLMClient)
        client.config = {"model": "fixture-model", "reasoning_effort": "low", "critic_reference_count": 1}
        return client

    def batch_items(self):
        self.seed_attempts()
        return [{"roi_id": r["id"], "labels": r["labels"], "shapes": r["shapes"],
                 "source_path": r["image_path"],
                 "roi_mask_path": self.pipeline.db.active_attempt(r["id"])["mask_path"],
                 "references": [self.references / "pair" / "00_fault.png"],
                 "base_prompt": "VISION_BANK_RULES"} for r in self.rows]

    def test_T01_wire_request_contains_source_reference_and_instruction(self):
        """T01：视觉模型请求应包含源图、参考图、指令和严格的输出格式。

        准备：准备两张测试图片和 JSON 格式约束，用 Mock 替代网络请求。
        执行：调用请求构造方法，从 Mock 捕获实际构造的请求体并解码图片。
        预期：指令正确、两张图片顺序及内容正确、输出格式约束一致，且 store 为 false。
        """
        client = self.client()
        client._request = Mock(return_value={"output_text": '{"ok":true}'})
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
        source = self.annotation.with_suffix(".png")
        reference = self.references / "pair" / "00_fault.png"
        result, _ = client._call_json("test", "T01_INSTRUCTION", [source, reference], schema)
        self.assertTrue(result["ok"])
        body = client._request.call_args.args[0]
        content = body["input"][0]["content"]
        self.assertEqual(content[0]["text"], "T01_INSTRUCTION")
        self.assertEqual(len([c for c in content if c["type"] == "input_image"]), 2)
        for index, node in enumerate(content[1:]):
            with Image.open(io.BytesIO(base64.b64decode(node["image_url"].split(",", 1)[1]))) as actual:
                self.assertEqual(actual.size, (128, 96))
                # 利用源图与参考图的灰度差异，发现图片顺序颠倒或重复传图。
                self.assertLessEqual(abs(actual.getpixel((20, 30)) - (120 if index == 0 else 55)), 5)
        self.assertFalse(body["store"])
        self.assertEqual(body["text"]["format"]["schema"], schema)

    def test_T02_batch_plan_maps_every_roi_and_audits_references(self):
        """T02：批量规划结果应覆盖全部目标，并记录参考图使用信息。

        准备：准备两个区域及参考图，模拟每个区域各返回一份合法规划。
        执行：调用真实的批量规划逻辑，并读取生成的审计 JSON。
        预期：结果 ID 与输入一致；审计有两个区域及参考图记录；提示词含知识库标记。
        """
        client, items = self.client(), self.batch_items()
        client._call_json = Mock(return_value=({"roi_plans": [
            {"roi_id": item["roi_id"], "edit_instruction": item["roi_id"], "selected_reference_indices": [0]}
            for item in items]}, {"id": "fixture"}))
        folder = self.root / "batch"
        plans = client.plan_batch(self.annotation.with_suffix(".png"), items, folder)
        self.assertEqual(set(plans), {r["id"] for r in self.rows})
        audit = json.loads((folder / "intelligence_batch_plan.json").read_text(encoding="utf-8"))
        self.assertEqual(len(audit["request"]["items"]), 2)
        self.assertTrue(all(i["reference_images"] for i in audit["request"]["items"]))
        self.assertIn("VISION_BANK_RULES", client._call_json.call_args.args[1])

    def test_T03_missing_roi_in_model_response_is_rejected(self):
        """T03：模型响应漏掉区域时，应拒绝该批量规划。

        准备：请求含两个区域，但模拟响应只给第一个区域的规划。
        执行：调用批量规划方法处理这份响应。
        预期：抛出 ValueError，不能静默忽略遗漏的区域。
        """
        client, items = self.client(), self.batch_items()
        client._call_json = Mock(return_value=({"roi_plans": [{"roi_id": items[0]["roi_id"]}]}, {}))
        with self.assertRaises(ValueError):
            client.plan_batch(self.annotation.with_suffix(".png"), items, self.root / "bad_batch")

    def test_T04_extra_roi_in_model_response_is_rejected(self):
        """T04：模型响应虚构额外区域时，应拒绝该批量规划。

        准备：在完整的合法响应后追加一个输入中不存在的 invented 区域。
        执行：调用批量规划方法处理这份模拟响应。
        预期：抛出 ValueError，不能接受额外的编辑目标。
        """
        client, items = self.client(), self.batch_items()
        client._call_json = Mock(return_value=({"roi_plans": [
            {"roi_id": item["roi_id"]} for item in items] + [{"roi_id": "invented"}]}, {}))
        with self.assertRaises(ValueError):
            client.plan_batch(self.annotation.with_suffix(".png"), items, self.root / "extra_batch")

    def test_T05_non_json_response_is_rejected(self):
        """T05：普通文字不能被当作有效的 JSON 规划。

        准备：准备一段不含 JSON 的英文回复。
        执行：直接调用 JSON 提取和解析函数。
        预期：抛出 ValueError 或 JSONDecodeError。
        """
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            _json_from_text("I cannot provide a plan")

    def test_T06_critic_sees_source_candidate_context_and_reference(self):
        """T06：视觉质检应按顺序接收图片，并保存模型的否决意见。

        准备：准备源图、候选图、上下文图和参考图，模拟不通过的质检结果。
        执行：调用质检方法，检查传给模型封装方法的图片列表及审计文件。
        预期：返回不通过；四张图片顺序正确；审计保留 T06_RETRY 修改意见。
        """
        client = self.client()
        self.seed_attempts()
        row = self.rows[0]
        from pathlib import Path
        attempt = self.pipeline.db.active_attempt(row["id"])
        source, candidate = Path(row["image_path"]), Path(attempt["candidate_path"])
        context, reference = Path(attempt["mask_path"]), self.references / "pair" / "00_fault.png"
        verdict = {"pass": False, "reason_codes": ["WRONG_STRUCTURE"], "revision_instruction": "T06_RETRY"}
        client._call_json = Mock(return_value=(verdict, {}))
        result = client.critique(source, candidate, context, row["labels"], {}, self.root, [reference])
        self.assertFalse(result["pass"])
        self.assertEqual(client._call_json.call_args.args[2], [source, candidate, context, reference])
        audit = json.loads((self.root / "intelligence_critic.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["result"]["revision_instruction"], "T06_RETRY")

    def test_T07_candidate_comparison_includes_all_candidates(self):
        """T07：候选比较应提交全部候选图，并保留模型选择的下标。

        准备：准备两个候选图，模拟模型选择下标 1。
        执行：调用候选比较方法，再检查内部调用收到的图片列表。
        预期：返回选择下标 1；图片顺序为基图、上下文图、全部候选图、参考图。
        """
        client = self.client()
        self.seed_attempts()
        from pathlib import Path
        paths = [Path(self.pipeline.db.active_attempt(r["id"])["candidate_path"]) for r in self.rows]
        source = self.annotation.with_suffix(".png")
        reference = self.references / "pair" / "00_fault.png"
        client._call_json = Mock(return_value=({"selected_index": 1, "pass": True,"candidate_scores":[{"index":0},{"index":1}]}, {}))
        result = client.compare_candidates(source, source, paths, ["DS_LS"], {}, [], self.root, [reference])
        self.assertEqual(result["selected_index"], 1)
        self.assertEqual(client._call_json.call_args.args[2], [source, source] + paths + [reference])
