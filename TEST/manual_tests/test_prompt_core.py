import base64
import io
import json
from email import policy
from email.parser import BytesParser
from unittest.mock import Mock, patch

from PIL import Image

from anomaly_factory.core import CoreRequest, OpenAIImageEditsAdapter
from TEST._shared.fixtures import IsolatedPipelineTest, LocalHttpTest


class PromptCases(IsolatedPipelineTest):
    def test_A08_feedback_and_target_identity_reach_prompt(self):
        """A08：预览提示词应包含选中目标的身份和本次反馈。

        准备：选择第二个区域，设置异常过弱原因和 A08_FEEDBACK 反馈标记。
        执行：直接调用提示词预览方法；这里没有发送 HTTP 请求。
        预期：仅返回一条预览，包含目标 ID、反馈、活动目标和仅作上下文的标记。
        """
        target = self.rows[1]["id"]
        result = self.app.preview_prompts([target], ["ANOMALY_TOO_WEAK"], "A08_FEEDBACK")
        self.assertEqual(result["count"], 1)
        prompt = result["items"][0]["prompt"]
        self.assertIn(target, prompt)
        self.assertIn("A08_FEEDBACK", prompt)
        self.assertIn("ACTIVE_TARGET", prompt)
        self.assertIn("CONTEXT_ONLY_DO_NOT_EDIT", prompt)

    def test_A09_reference_matching_and_root_boundary(self):
        """A09：参考图应按标签匹配，并拒绝参考库目录之外的路径。

        准备：使用合成参考库，再故意将索引指向库外图片。
        执行：先查询正常索引，再查询含越界路径的索引。
        预期：正常查询得到一张故障参考及一个匹配区域；越界查询返回空列表。
        """
        kb = self.pipeline.knowledge
        examples = kb.reference_examples(["DS_LS"], 2)
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]["image"].stem, "00_fault")
        self.assertEqual(len(examples[0]["shapes"]), 1)
        external = self.root / "external.png"
        Image.new("L", (8, 8)).save(external)
        kb.reference_index["labels"]["DS_LS"] = [{"image": "../external.png"}]
        self.assertEqual(kb.reference_examples(["DS_LS"], 2), [])

    def test_A10_core_packet_preserves_image_order_mask_and_prompt(self):
        """A10：图片生成请求应正确携带源图、参考图、掩膜和提示词。

        准备：创建图片和掩膜；用 Mock 预设模型响应，不调用真实外部 API。
        执行：实际构造 multipart 多部分请求，再从 Mock 中取出请求并解码。
        预期：源图在前、参考图内容正确；编辑区透明；提示词完整；模拟结果正确保存。
        """
        row = self.rows[0]
        source = self.annotation.with_suffix(".png")
        mask = Image.new("L", (128, 96), 0)
        mask.paste(255, (16, 24, 32, 40))
        mask_path = self.root / "mask.png"
        mask.save(mask_path)
        prompt_path = self.root / "prompt.txt"
        prompt_path.write_text("A10_PROMPT_LABELME", encoding="utf-8")
        reference = self.references / "pair" / "00_fault.png"
        output = self.root / "out.png"
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        encoded = base64.b64encode(source.read_bytes()).decode()
        response.read.return_value = json.dumps({"data": [{"b64_json": encoded}]}).encode()
        adapter = OpenAIImageEditsAdapter({"base_url_env": "BASE", "api_key_env": "KEY", "quality": "high"},
                                         {"BASE": "https://example.invalid", "KEY": "fixture-token"})
        adapter.opener = Mock()
        adapter.opener.open.return_value = response
        adapter.generate(CoreRequest(source, mask_path, prompt_path, output, [reference], row["id"], 1))
        request = adapter.opener.open.call_args.args[0]
        header = ("Content-Type: " + request.get_header("Content-type") + "\r\nMIME-Version: 1.0\r\n\r\n").encode()
        parts = list(BytesParser(policy=policy.default).parsebytes(header + request.data).iter_parts())
        images = [p for p in parts if p.get_param("name", header="content-disposition") == "image[]"]
        self.assertEqual([p.get_filename() for p in images], ["source.png", "reference_01.png"])
        with Image.open(io.BytesIO(images[0].get_payload(decode=True))) as actual:
            self.assertEqual(actual.size, (128, 96))
            self.assertEqual(actual.getpixel((0, 0)), 120)
        with Image.open(io.BytesIO(images[1].get_payload(decode=True))) as actual, Image.open(reference) as expected:
            self.assertEqual(actual.tobytes(), expected.tobytes())
            self.assertEqual(actual.getpixel((20, 30)), 55)
        alpha_part = next(p for p in parts if p.get_param("name", header="content-disposition") == "mask")
        with Image.open(io.BytesIO(alpha_part.get_payload(decode=True))) as actual:
            self.assertEqual(actual.getpixel((20, 30))[3], 0)
            self.assertEqual(actual.getpixel((0, 0))[3], 255)
        self.assertIn(b"A10_PROMPT_LABELME", request.data)
        self.assertEqual(output.read_bytes(), source.read_bytes())

    def test_A11_core_rejects_mismatched_mask_before_request(self):
        """A11：源图与掩膜尺寸不一致时，应在提交请求前拒绝处理。

        准备：源图为 128×96，故意创建一张 8×8 掩膜。
        执行：调用源图与掩膜的预处理方法。
        预期：抛出 ValueError；没有抛出异常才表示该测试失败。
        """
        mask = self.root / "wrong.png"
        Image.new("L", (8, 8)).save(mask)
        with self.assertRaises(ValueError):
            OpenAIImageEditsAdapter._source_and_mask(self.annotation.with_suffix(".png"), mask)


class ConfigurationApiCases(LocalHttpTest):
    def test_A12_api_settings_redact_key_and_persist_locally(self):
        """A12：保存 API 密钥后，公开响应和主配置不能暴露明文密钥。

        准备：使用临时服务，准备仅供测试的 A12-secret 密钥。
        执行：通过 HTTP 保存配置，再读取公开配置和临时配置文件。
        预期：两次请求均返回 200；公开响应及主配置不含密钥；独立凭据文件存在。
        """
        status, payload = self.request("POST", "/api/api-settings", {"api_key": "A12-secret", "intelligence": {"enabled": False}})
        self.assertEqual(status, 200)
        status, public = self.request("GET", "/api/api-settings")
        self.assertEqual(status, 200)
        self.assertNotIn("A12-secret", json.dumps(public))
        self.assertNotIn("A12-secret", self.config_path.read_text())
        self.assertTrue((self.root / "api_credentials.local.json").is_file())

    def test_A13_invalid_quality_rejected_without_config_change(self):
        """A13：非法生成质量参数应被拒绝，原配置应保持不变。

        准备：先读取配置文件原始字节，作为修改前的比较依据。
        执行：通过 HTTP 提交不支持的 quality=ultra。
        预期：返回 400，配置文件内容与提交前完全一致。
        """
        before = self.config_path.read_bytes()
        status, _ = self.request("POST", "/api/api-settings", {"core": {"quality": "ultra"}})
        self.assertEqual(status, 400)
        self.assertEqual(before, self.config_path.read_bytes())

    def test_A14_prompt_preview_endpoint_is_read_only(self):
        """A14：预览提示词不能把草稿反馈写入数据库。

        准备：选择第二个区域，准备 DRAFT_ONLY 草稿意见。
        执行：通过 HTTP 请求提示词预览，然后读取数据库。
        预期：返回 200 且只包含选中区域；数据库中的反馈意见仍为空。
        """
        target = self.rows[1]["id"]
        status, payload = self.request("POST", "/api/prompt-preview", {"sample_ids": [target], "comment": "DRAFT_ONLY"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["count"], 1)
        self.assertEqual(payload["result"]["items"][0]["id"], target)
        self.assertEqual(self.pipeline.db.get_sample(target)["anomaly_comment"], "")

    def test_A15_api_probe_dispatch_and_validation(self):
        """A15：连接探测应分派给指定提供方，并拒绝无效目标。

        准备：用 patch 替换外部 CORE 探测函数，返回固定的测试结果。
        执行：先通过本地 HTTP 请求探测 core，再请求无效目标 invalid。
        预期：core 请求返回 200 和预设结果，探测函数只调用一次；无效目标返回 400。
        """
        with patch("anomaly_factory.review_server.probe_core", return_value={"probe": "fixture"}) as probe:
            status, payload = self.request("POST", "/api/api-probe", {"target": "core"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"], {"probe": "fixture"})
        probe.assert_called_once()
        self.assertEqual(self.request("POST", "/api/api-probe", {"target": "invalid"})[0], 400)

    def test_D01_explicit_zero_transport_job_retries_survives_save(self):
        """D01：显式设置重试次数为 0 后，不能被默认值 2 覆盖。

        准备：使用临时配置和服务，关闭真实智能模型调用。
        执行：通过 HTTP 保存 transport_job_retries=0，再读取内存配置。
        预期：保存返回 200，实际重试次数仍为 0。原版在数值检查处暴露缺陷。
        """
        code, result = self.request('POST', '/api/api-settings', {
            'core': {'transport_job_retries': 0}, 'intelligence': {'enabled': False}})
        self.assertEqual(code, 200, result)
        actual = self.pipeline.config['core']['transport_job_retries']
        self.assertEqual(actual, 0, 'Explicit zero became %r' % actual)

