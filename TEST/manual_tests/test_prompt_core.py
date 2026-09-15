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
        """A08: selected ROI identity and new feedback reach the preview prompt."""
        target = self.rows[1]["id"]
        result = self.app.preview_prompts([target], ["ANOMALY_TOO_WEAK"], "A08_FEEDBACK")
        self.assertEqual(result["count"], 1)
        prompt = result["items"][0]["prompt"]
        self.assertIn(target, prompt)
        self.assertIn("A08_FEEDBACK", prompt)
        self.assertIn("ACTIVE_TARGET", prompt)
        self.assertIn("CONTEXT_ONLY_DO_NOT_EDIT", prompt)

    def test_A09_reference_matching_and_root_boundary(self):
        """A09: reference lookup selects fault labels and excludes out-of-library paths."""
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
        """A10: decode the actual multipart body; check source-first, reference bytes and transparent edit mask."""
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
        """A11: inconsistent image and mask size must not be submitted upstream."""
        mask = self.root / "wrong.png"
        Image.new("L", (8, 8)).save(mask)
        with self.assertRaises(ValueError):
            OpenAIImageEditsAdapter._source_and_mask(self.annotation.with_suffix(".png"), mask)


class ConfigurationApiCases(LocalHttpTest):
    def test_A12_api_settings_redact_key_and_persist_locally(self):
        """A12: saving a key never echoes it into public responses or main config."""
        status, payload = self.request("POST", "/api/api-settings", {"api_key": "A12-secret", "intelligence": {"enabled": False}})
        self.assertEqual(status, 200)
        status, public = self.request("GET", "/api/api-settings")
        self.assertEqual(status, 200)
        self.assertNotIn("A12-secret", json.dumps(public))
        self.assertNotIn("A12-secret", self.config_path.read_text())
        self.assertTrue((self.root / "api_credentials.local.json").is_file())

    def test_A13_invalid_quality_rejected_without_config_change(self):
        """A13: invalid quality returns 400 and preserves the previous configuration."""
        before = self.config_path.read_bytes()
        status, _ = self.request("POST", "/api/api-settings", {"core": {"quality": "ultra"}})
        self.assertEqual(status, 400)
        self.assertEqual(before, self.config_path.read_bytes())

    def test_A14_prompt_preview_endpoint_is_read_only(self):
        """A14: POST preview returns selected ROI only and does not save feedback."""
        target = self.rows[1]["id"]
        status, payload = self.request("POST", "/api/prompt-preview", {"sample_ids": [target], "comment": "DRAFT_ONLY"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["count"], 1)
        self.assertEqual(payload["result"]["items"][0]["id"], target)
        self.assertEqual(self.pipeline.db.get_sample(target)["anomaly_comment"], "")

    def test_A15_api_probe_dispatch_and_validation(self):
        """A15: API probe routes to requested provider; no real upstream call in this case."""
        with patch("anomaly_factory.review_server.probe_core", return_value={"probe": "fixture"}) as probe:
            status, payload = self.request("POST", "/api/api-probe", {"target": "core"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"], {"probe": "fixture"})
        probe.assert_called_once()
        self.assertEqual(self.request("POST", "/api/api-probe", {"target": "invalid"})[0], 400)

    def test_D01_explicit_zero_transport_job_retries_survives_save(self):
        """D01: the documented zero lower bound must not become two retries."""
        code, result = self.request('POST', '/api/api-settings', {
            'core': {'transport_job_retries': 0}, 'intelligence': {'enabled': False}})
        self.assertEqual(code, 200, result)
        actual = self.pipeline.config['core']['transport_job_retries']
        self.assertEqual(actual, 0, 'Explicit zero became %r' % actual)

