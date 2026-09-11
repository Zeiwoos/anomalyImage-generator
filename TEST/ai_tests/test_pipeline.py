from __future__ import annotations

import json
import sys
import shutil
import tempfile
import threading
import time
import unittest
import io
import base64
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from PIL import Image

from anomaly_factory.config import load_config
from anomaly_factory.core import CoreRequest, CoreTransportError, OpenAIImageEditsAdapter, normalized_edit_size
from anomaly_factory.intelligence import build_roi_context
from anomaly_factory.pipeline import Pipeline, boundary_seam_metrics, match_local_tone, qc_metrics
from anomaly_factory.reference_index import build_reference_index
from anomaly_factory.review_server import ReviewApplication


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        dataset = self.root / "dataset" / "part_a"
        dataset.mkdir(parents=True)
        Image.new("L", (80, 60), 120).save(dataset / "source.png")
        payload = {
            "version": "5.0.1", "flags": {}, "imagePath": "source.png", "imageData": None,
            "imageWidth": 80, "imageHeight": 60,
            "shapes": [{"label": "DS_LS", "points": [[24, 18], [48, 40]], "group_id": None, "shape_type": "rectangle", "flags": {}}],
        }
        (dataset / "source.json").write_text(json.dumps(payload), encoding="utf-8")
        reference = self.root / "Anomaly-reference" / "DiuShi" / "LuoShuan"
        reference.mkdir(parents=True)
        for index, shade in enumerate((90, 105), start=1):
            image_name = f"reference_{index}.png"
            Image.new("L", (100, 80), shade).save(reference / image_name)
            reference_payload = {
                "version": "5.0.1", "flags": {}, "imagePath": image_name, "imageData": None,
                "imageWidth": 100, "imageHeight": 80,
                "shapes": [{
                    "label": "DS_LS", "points": [[30, 20], [70, 60]], "group_id": None,
                    "shape_type": "rectangle", "flags": {},
                }],
            }
            (reference / f"reference_{index}.json").write_text(
                json.dumps(reference_payload), encoding="utf-8"
            )
        self.reference_root = reference.parents[1]
        knowledge = self.root / "knowledge-bank"
        knowledge.mkdir()
        shutil.copy2(PROJECT / "knowledge-bank" / "labels.json", knowledge / "labels.json")
        shutil.copy2(PROJECT / "knowledge-bank" / "feedback_rules.json", knowledge / "feedback_rules.json")
        for name in ["01_global_rules.md", "03_missing.md", "08_prompt_protocol.md", "09_quality_gate.md"]:
            shutil.copy2(PROJECT / "knowledge-bank" / name, knowledge / name)
        build_reference_index(self.reference_root, knowledge / "reference_index.json")
        config = {
            "project": {
                "reference_root": str(self.reference_root), "knowledge_root": str(knowledge),
                "intermediate_root": str(self.root / "intermediate"), "database": str(self.root / "intermediate" / "pipeline.sqlite3"),
            },
            "dataset": {"root": str(self.root / "dataset")},
            "core": {"adapter": "mock"},
            "review": {"open_browser": False},
        }
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps(config), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_scan_and_mock_generation(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        scan = pipeline.scan()
        self.assertEqual(scan["samples"], 1)
        row = pipeline.db.list_samples()[0]
        self.assertEqual(row["labels"], ["DS_LS"])
        app = ReviewApplication(pipeline)
        saved = app.save_generation_feedback([row["id"]], ["ANOMALY_TOO_WEAK"], "初次生成也要明显")
        self.assertEqual(saved["saved"], 1)
        pending = pipeline.db.get_sample(row["id"])
        self.assertEqual(pending["workflow"], "pending_generation")
        self.assertEqual(pending["anomaly_comment"], "初次生成也要明显")
        result = pipeline.generate()
        self.assertEqual(result[0]["workflow"], "core_not_configured")
        attempt = pipeline.db.active_attempt(row["id"])
        self.assertTrue(Path(attempt["prompt_path"]).is_file())
        prompt = Path(attempt["prompt_path"]).read_text(encoding="utf-8")
        self.assertIn("初次生成也要明显", prompt)
        self.assertTrue(Path(attempt["roi_mask_path"]).is_file())
        attempt_dir = Path(attempt["prompt_path"]).parent
        self.assertTrue((attempt_dir / "labelme_focus_mask.png").is_file())
        manifest = json.loads((attempt_dir / "input_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["mask_relationship"]["labelme_focus"], "semantic target anchor; anomaly may cross it when physically required")
        with Image.open(attempt_dir / "labelme_focus_mask.png") as focus, Image.open(attempt["roi_mask_path"]) as edit_region:
            self.assertGreater(edit_region.histogram()[255], focus.histogram()[255])
        self.assertIn("不是异常边界", prompt)
        with Image.open(Path(attempt["candidate_path"])) as candidate:
            self.assertEqual(candidate.size, (80, 60))
            self.assertEqual(candidate.mode, "L")

    def test_review_reject_queues_regeneration(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        row = pipeline.db.list_samples()[0]
        pipeline.generate()
        app = ReviewApplication(pipeline)
        reviewed = app.review(row["id"], "anomaly", "rejected", ["WRONG_STRUCTURE"], "结构需要重做")
        self.assertEqual(reviewed["workflow"], "regen_queued")
        saved = app.save_generation_feedback([row["id"]], ["ANOMALY_TOO_WEAK"], "改为只强调异常可见性")
        self.assertEqual(saved["saved"], 1)
        updated = pipeline.db.get_sample(row["id"])
        self.assertEqual(updated["workflow"], "regen_queued")
        self.assertEqual(updated["anomaly_reason_codes"], ["ANOMALY_TOO_WEAK"])
        self.assertEqual(updated["anomaly_comment"], "改为只强调异常可见性")
        prompt_before = pipeline.db.active_attempt(row["id"])["prompt_path"]
        pipeline.generate(queued_only=True)
        attempt = pipeline.db.active_attempt(row["id"])
        self.assertNotEqual(attempt["prompt_path"], prompt_before)
        prompt = Path(attempt["prompt_path"]).read_text(encoding="utf-8")
        self.assertIn("改为只强调异常可见性", prompt)

    def test_review_worker_reports_queue_progress(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        app = ReviewApplication(pipeline)
        started = app.run_queue()
        self.assertTrue(started["started"])
        self.assertEqual(started["total"], 1)
        deadline = time.time() + 5
        while app.worker_state["running"] and time.time() < deadline:
            time.sleep(0.02)
        self.assertFalse(app.worker_state["running"])
        self.assertEqual(app.worker_state["completed"], 1)
        self.assertEqual(app.worker_state["succeeded"] + app.worker_state["failed"], 1)
        self.assertEqual(len(app.worker_state["jobs"]), 1)
        self.assertIn(app.worker_state["jobs"][0]["status"], {"succeeded", "failed"})

    def test_next_image_planning_overlaps_current_core_generation(self) -> None:
        second_dir = self.root / "dataset" / "part_b"
        second_dir.mkdir(parents=True)
        Image.new("L", (80, 60), 126).save(second_dir / "source_b.png")
        payload = {
            "version": "5.0.1", "flags": {}, "imagePath": "source_b.png", "imageData": None,
            "imageWidth": 80, "imageHeight": 60,
            "shapes": [{"label": "LY", "points": [[20, 16], [50, 42]], "group_id": None, "shape_type": "rectangle", "flags": {}}],
        }
        (second_dir / "source_b.json").write_text(json.dumps(payload), encoding="utf-8")
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        pipeline.config["intelligence"].update(
            {
                "enabled": True, "planner": True, "batch_planner": True,
                "parallel_planning": True, "parallel_planning_lookahead": 1,
            }
        )
        pipeline.intelligence = object()
        app = ReviewApplication(pipeline)
        second_plan_started = threading.Event()
        overlap_observed = threading.Event()
        plan_calls = []
        generation_calls = []

        def fake_prepare(sample_ids, progress_callback=None, intelligence_client=None):
            ids = list(sample_ids)
            plan_calls.append(ids)
            if len(plan_calls) == 2:
                second_plan_started.set()
            if progress_callback:
                for sample_id in ids:
                    progress_callback(sample_id, {"stage": "batch_planning", "attempt": 1, "batch_size": len(ids)})
            return {sample_id: {"edit_instruction": "prefetched"} for sample_id in ids}

        def fake_generate(sample_id, progress_callback=None, precomputed_plan=None):
            generation_calls.append(sample_id)
            if len(generation_calls) == 1 and second_plan_started.wait(1.5):
                overlap_observed.set()
            self.assertEqual(precomputed_plan, {"edit_instruction": "prefetched"})
            return {"sample_id": sample_id, "attempt": 1, "workflow": "anomaly_review", "qc": {"passed": True, "failures": []}}

        with patch("anomaly_factory.review_server.create_intelligence", return_value=object()), \
                patch.object(pipeline, "prepare_batch_plans", side_effect=fake_prepare), \
                patch.object(pipeline, "generate_sample", side_effect=fake_generate):
            started = app.run_queue()
            self.assertTrue(started["started"])
            deadline = time.time() + 5
            while app.worker_state["running"] and time.time() < deadline:
                time.sleep(0.02)

        self.assertFalse(app.worker_state["running"])
        self.assertEqual(len(plan_calls), 2)
        self.assertEqual(len(generation_calls), 2)
        self.assertTrue(overlap_observed.is_set())

    def test_api_settings_persist_without_exposing_secret(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        app = ReviewApplication(pipeline)
        saved = app.save_api_settings(
            {
                "api_key": "unit-test-secret",
                "core": {
                    "adapter": "openai_image_edits", "base_url": "https://api.example.invalid",
                    "endpoint": "/v1/images/edits", "model": "gpt-image-2", "quality": "high",
                    "timeout_seconds": 120,
                },
                "intelligence": {
                    "enabled": False, "model": "gpt-5.6-sol", "endpoint": "/v1/responses",
                    "reasoning_effort": "high", "orchestrator": True, "planner": True,
                    "critic": True, "critic_gate": True, "reference_candidate_count": 5,
                    "approved_example_count": 2, "timeout_seconds": 180,
                },
                "generation": {
                    "reference_count": 2, "edit_context_min_padding_px": 96,
                    "edit_context_padding_ratio": 0.35, "max_attempts": 30,
                    "max_auto_retries_per_sample_per_run": 25,
                    "manual_review_after_retry_exhausted": True,
                },
            }
        )
        self.assertTrue(saved["core"]["api_key_configured"])
        self.assertNotIn("unit-test-secret", json.dumps(saved))
        self.assertTrue((self.root / "api_credentials.local.json").is_file())
        persisted = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["core"]["quality"], "high")
        self.assertTrue(persisted["generation"]["manual_review_after_retry_exhausted"])

    def test_retry_exhaustion_routes_candidate_to_human_review(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        pipeline.config["generation"].update(
            {"max_auto_retries_per_sample_per_run": 1, "manual_review_after_retry_exhausted": True, "retry_backoff_seconds": 0}
        )
        row = pipeline.db.list_samples()[0]
        app = ReviewApplication(pipeline)
        outcomes = [
            {"sample_id": row["id"], "attempt": 1, "workflow": "qc_failed", "qc": {"failures": ["LLM_SEMANTIC_QC_FAILED"]}},
            {"sample_id": row["id"], "attempt": 2, "workflow": "qc_failed", "qc": {"failures": ["LLM_SEMANTIC_QC_FAILED"]}},
        ]
        with patch.object(pipeline, "generate_sample", side_effect=outcomes) as generate:
            app.run_queue()
            deadline = time.time() + 5
            while app.worker_state["running"] and time.time() < deadline:
                time.sleep(0.02)
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(app.worker_state["jobs"][0]["status"], "needs_review")
        self.assertEqual(pipeline.db.get_sample(row["id"])["workflow"], "anomaly_review")

    def test_multiple_shapes_are_independent_tasks(self) -> None:
        json_path = self.root / "dataset" / "part_a" / "source.json"
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        payload["shapes"].append(
            {"label": "LY", "points": [[52, 12], [70, 28]], "group_id": None, "shape_type": "rectangle", "flags": {}}
        )
        json_path.write_text(json.dumps(payload), encoding="utf-8")
        pipeline = Pipeline(load_config(self.config_path))
        scan = pipeline.scan()
        self.assertEqual(scan["samples"], 2)
        rows = pipeline.db.list_samples()
        self.assertEqual({tuple(row["labels"]) for row in rows}, {("DS_LS",), ("LY",)})
        self.assertTrue(all(len(row["shapes"]) == 1 for row in rows))
        public = ReviewApplication(pipeline).public_items()
        self.assertEqual(len(public), 2)
        self.assertTrue(all(len(item["annotations"]) == 2 for item in public))
        self.assertTrue(all(sum(1 for shape in item["annotations"] if shape["active"]) == 1 for item in public))
        self.assertEqual(
            {shape["code"] for shape in public[0]["annotations"]},
            {"DS_LS", "LY"},
        )

    def test_same_image_rois_are_planned_in_one_batch(self) -> None:
        json_path = self.root / "dataset" / "part_a" / "source.json"
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        payload["shapes"].append(
            {"label": "LY", "points": [[52, 12], [70, 28]], "group_id": None, "shape_type": "rectangle", "flags": {}}
        )
        json_path.write_text(json.dumps(payload), encoding="utf-8")
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        pipeline.config["intelligence"].update(
            {"enabled": True, "planner": True, "batch_planner": True, "batch_reference_candidate_count": 1}
        )

        class FakeBatchIntelligence:
            def __init__(self) -> None:
                self.calls = 0

            def plan_batch(self, source_path, items, batch_dir):
                self.calls += 1
                self.item_count = len(items)
                (batch_dir / "intelligence_batch_plan.json").write_text("{}", encoding="utf-8")
                return {
                    item["roi_id"]: {
                        "edit_instruction": "独立处理{}".format(item["roi_id"]),
                        "selected_reference_indices": [],
                        "edit_context_scale": "normal",
                        "mask_geometry": "rounded_context",
                        "mask_regions": [],
                        "protected_regions": [],
                        "must_preserve": ["其他结构"],
                        "negative_patterns_to_avoid": ["矩形贴片"],
                        "background_preservation_plan": "保持源图",
                        "candidate_directives": [],
                        "batch_planned": True,
                    }
                    for item in items
                }

        fake = FakeBatchIntelligence()
        pipeline.intelligence = fake
        rows = pipeline.db.list_samples()
        plans = pipeline.prepare_batch_plans([row["id"] for row in rows])
        self.assertEqual(fake.calls, 1)
        self.assertEqual(fake.item_count, 2)
        self.assertEqual(set(plans), {row["id"] for row in rows})
        for row in rows:
            attempt_dir = self.root / "intermediate" / "samples" / row["id"] / "attempt_001"
            audit = json.loads((attempt_dir / "intelligence_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["request"]["batch_size"], 2)
            self.assertTrue(audit["result"]["batch_planned"])

        single = pipeline.prepare_batch_plans([rows[0]["id"]], intelligence_client=fake)
        self.assertEqual(set(single), {rows[0]["id"]})
        self.assertEqual(fake.item_count, 1)

    def test_layered_mode_groups_shapes_and_composes_images(self) -> None:
        json_path = self.root / "dataset" / "part_a" / "source.json"
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        payload["shapes"].append(
            {"label": "LY", "points": [[52, 12], [70, 28]], "group_id": None, "shape_type": "rectangle", "flags": {}}
        )
        json_path.write_text(json.dumps(payload), encoding="utf-8")
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        config["generation"] = {"multi_label_mode": "per_image_layered"}
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        pipeline.generate()
        app = ReviewApplication(pipeline)
        public = app.public_items()
        self.assertEqual(len(public), 1)
        group = public[0]
        self.assertTrue(group["id"].startswith("group_"))
        self.assertEqual(len(group["children"]), 2)
        self.assertEqual({shape["code"] for shape in group["annotations"]}, {"DS_LS", "LY"})
        first_child, second_child = group["children"]
        first_prompt = Path(pipeline.db.active_attempt(first_child["id"])["prompt_path"]).read_text(encoding="utf-8")
        second_prompt = Path(pipeline.db.active_attempt(second_child["id"])["prompt_path"]).read_text(encoding="utf-8")
        self.assertIn(f"sample_id={first_child['id']}", first_prompt)
        self.assertIn("shape_index=0", first_prompt)
        self.assertIn("shape_index=1", second_prompt)
        self.assertNotEqual(first_prompt, second_prompt)
        preview = app.preview_prompts([second_child["id"]], ["WRONG_STRUCTURE"], "只重做第二个ROI")
        self.assertEqual(preview["count"], 1)
        self.assertIn("shape_index=1", preview["items"][0]["prompt"])
        self.assertNotIn("shape_index=0", preview["items"][0]["prompt"])
        self.assertIn('"role":"ACTIVE_TARGET"', preview["items"][0]["prompt"])
        self.assertIn('"role":"CONTEXT_ONLY_DO_NOT_EDIT"', preview["items"][0]["prompt"])
        self.assertIn("Image 1", preview["items"][0]["prompt"])
        self.assertIn("只重做第二个ROI", preview["items"][0]["prompt"])
        candidate, content_type = app.image_bytes(group["id"], "candidate")
        self.assertEqual(content_type, "image/png")
        with Image.open(io.BytesIO(candidate)) as opened:
            self.assertEqual(opened.size, (80, 60))
        selected = group["children"][0]["id"]
        reviewed = app.review_batch([selected], "anomaly", "rejected", ["WRONG_STRUCTURE"], "只重做这个ROI")
        self.assertEqual(reviewed["reviewed"], 1)
        self.assertEqual(pipeline.db.get_sample(selected)["workflow"], "regen_queued")
        other = next(child["id"] for child in group["children"] if child["id"] != selected)
        self.assertNotEqual(pipeline.db.get_sample(other)["workflow"], "regen_queued")
        for child_id in (selected, other):
            pipeline.db.review(child_id, "anomaly", "approved", [], "")
        edited_union = Image.new("L", (80, 60), 0)
        for y in range(12, 42):
            for x in range(20, 72):
                edited_union.putpixel((x, y), 255)
        saved = app.save_group_mask(group["id"], edited_union)
        self.assertEqual(saved["saved_layers"], 2)
        for child_id in (selected, other):
            pipeline.db.review(child_id, "mask", "approved", [], "")
        exported = pipeline.export_approved(self.root / "exported")
        self.assertEqual(exported["exported"], 1)
        manifest_rows = (self.root / "exported" / "export_manifest.csv").read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(len(manifest_rows), 2)

    def test_manifest_normal_is_reviewable_without_mask_stage(self) -> None:
        shutil.rmtree(self.root / "dataset" / "part_a")
        part = self.root / "dataset" / "part_n"
        (part / "reference").mkdir(parents=True)
        (part / "normal_query").mkdir()
        Image.new("L", (80, 60), 120).save(part / "reference" / "n.jpg")
        Image.new("L", (80, 60), 121).save(part / "normal_query" / "n.jpg")
        manifest = self.root / "dataset" / "dataset_manifest.csv"
        manifest.write_text(
            "part,split,label,subtype,original_image,query_image,mask_image,reference_image\n"
            "part_n,normal,normal,,,part_n/normal_query/n.jpg,,part_n/reference/n.jpg\n",
            encoding="utf-8",
        )
        pipeline = Pipeline(load_config(self.config_path))
        scan = pipeline.scan()
        self.assertEqual(scan["mode"], "manifest_review")
        row = pipeline.db.list_samples()[0]
        self.assertEqual(row["split"], "normal")
        self.assertEqual(row["workflow"], "normal_review")
        reviewed = ReviewApplication(pipeline).review(row["id"], "normal", "approved", [], "")
        self.assertEqual(reviewed["workflow"], "completed")

    def test_openai_image_edits_builds_multipart_and_alpha_mask(self) -> None:
        work = self.root / "adapter"
        work.mkdir()
        source = work / "source.jpg"
        reference = work / "reference.jpg"
        mask = work / "mask.png"
        prompt = work / "prompt.txt"
        output = work / "output.png"
        Image.new("L", (64, 64), 120).save(source)
        Image.new("L", (64, 64), 80).save(reference)
        roi = Image.new("L", (64, 64), 0)
        for y in range(20, 40):
            for x in range(18, 38):
                roi.putpixel((x, y), 255)
        roi.save(mask)
        prompt.write_text("局部编辑", encoding="utf-8")
        result_buffer = io.BytesIO()
        Image.new("L", (64, 64), 90).save(result_buffer, format="PNG")
        response_body = json.dumps({"data": [{"b64_json": base64.b64encode(result_buffer.getvalue()).decode("ascii")}]}).encode()

        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return response_body

        class FakeOpener:
            def __init__(self): self.request = None
            def open(self, request, timeout=0): self.request = request; return FakeResponse()

        adapter = OpenAIImageEditsAdapter(
            {"base_url_env": "BASE", "api_key_env": "KEY", "model": "gpt-image-2", "proxy_mode": "direct"},
            {"BASE": "http://127.0.0.1:8317", "KEY": "secret"},
        )
        fake = FakeOpener()
        adapter.opener = fake
        result = adapter.generate(CoreRequest(source, mask, prompt, output, [reference], "sample", 1))
        self.assertEqual(result["adapter"], "openai_image_edits")
        self.assertEqual(result["reference_count"], 1)
        self.assertEqual(result["request_inputs"], ["source", "reference_01"])
        self.assertTrue(output.is_file())
        payload = fake.request.data
        self.assertIn(b'name="model"', payload)
        self.assertIn(b'gpt-image-2', payload)
        self.assertEqual(payload.count(b'name="image[]"'), 2)
        self.assertLess(payload.index(b'filename="source.png"'), payload.index(b'filename="reference_01.png"'))
        self.assertIn(b'name="mask"', payload)
        _, alpha_bytes, original_size, submitted_size = adapter._source_and_mask(source, mask)
        self.assertEqual(original_size, (64, 64))
        self.assertEqual(submitted_size, (64, 64))
        with Image.open(io.BytesIO(alpha_bytes)) as alpha:
            self.assertEqual(alpha.getpixel((0, 0))[3], 255)
            self.assertEqual(alpha.getpixel((25, 25))[3], 0)

    def test_image_edit_size_is_normalized_near_source(self) -> None:
        self.assertEqual(normalized_edit_size(2064, 1544), (2064, 1536))
        self.assertEqual(normalized_edit_size(2048, 1536), (2048, 1536))
        self.assertIsNone(normalized_edit_size(64, 64))

    def test_review_worker_auto_retries_qc_failure_until_review(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        pipeline.config["generation"].update(
            {"auto_retry_failed": True, "max_auto_retries_per_sample_per_run": 3, "retry_backoff_seconds": 0}
        )
        row = pipeline.db.list_samples()[0]
        outcomes = [
            {"sample_id": row["id"], "attempt": 1, "workflow": "qc_failed", "qc": {"failures": ["EMPTY_CHANGE"]}},
            {"sample_id": row["id"], "attempt": 2, "workflow": "qc_failed", "qc": {"failures": ["LLM_SEMANTIC_QC_FAILED"]}},
            {"sample_id": row["id"], "attempt": 3, "workflow": "anomaly_review", "qc": {"failures": []}},
        ]
        app = ReviewApplication(pipeline)
        with patch.object(pipeline, "generate_sample", side_effect=outcomes) as generate:
            started = app.run_queue()
            self.assertTrue(started["started"])
            deadline = time.time() + 5
            while app.worker_state["running"] and time.time() < deadline:
                time.sleep(0.02)
        self.assertEqual(generate.call_count, 3)
        self.assertEqual(app.worker_state["succeeded"], 1)
        self.assertEqual(app.worker_state["failed"], 0)
        self.assertEqual(app.worker_state["jobs"][0]["status"], "succeeded")
        self.assertEqual(app.worker_state["jobs"][0]["retry_count"], 2)

    def test_local_tone_match_removes_roi_exposure_offset(self) -> None:
        source = Image.new("L", (80, 60), 100)
        generated = Image.new("L", (80, 60), 135)
        roi = Image.new("L", (80, 60), 0)
        for y in range(10, 50):
            for x in range(12, 68):
                roi.putpixel((x, y), 255)
        matched, meta = match_local_tone(source, generated, roi, 8)
        self.assertTrue(meta["applied"])
        self.assertLessEqual(abs(matched.getpixel((13, 11)) - 100), 1)

    def test_knowledge_markdown_is_injected_into_core_prompt(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        row = pipeline.db.list_samples()[0]
        prompt = pipeline.build_prompt_for_row(row)
        self.assertIn("全局反事实编辑规则", prompt)
        self.assertIn("mask 只代表", prompt)

    def test_reference_candidate_is_cropped_from_labelme_geometry(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        source = self.root / "reference.png"
        Image.new("L", (400, 300), 100).save(source)
        paths, descriptions, manifest = pipeline.prepare_reference_candidates(
            [{
                "image": source, "json": self.root / "reference.json", "label": "S_HeiJiaoDai",
                "source": "reference_bank", "shapes": [{"points": [[170, 120], [210, 160]]}],
            }],
            self.root / "attempt",
        )
        with Image.open(paths[0]) as prepared:
            self.assertLess(prepared.width, 400)
            self.assertLess(prepared.height, 300)
        self.assertIn("LabelMe 异常局部裁图", descriptions[str(paths[0])])
        self.assertEqual(manifest[0]["label"], "S_HeiJiaoDai")

    def test_boundary_seam_is_rejected(self) -> None:
        source = Image.new("L", (80, 60), 100)
        candidate = source.copy()
        allowed = Image.new("L", source.size, 0)
        for y in range(10, 50):
            for x in range(12, 68):
                allowed.putpixel((x, y), 255)
                candidate.putpixel((x, y), 125)
        mask = allowed.copy()
        seam = boundary_seam_metrics(source, candidate, allowed)
        self.assertGreater(seam["mean_abs_difference"], 20)
        qc = qc_metrics(source, candidate, mask, allowed, "image_core")
        self.assertIn("ROI_TONE_SEAM", qc["failures"])

    def test_transport_failure_does_not_consume_logical_attempt(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        row = pipeline.db.list_samples()[0]

        class TransportFailAdapter:
            name = "fake_image_core"

            def generate(self, request):
                raise CoreTransportError("upstream EOF")

        with patch("anomaly_factory.pipeline.create_adapter", return_value=TransportFailAdapter()):
            with self.assertRaises(CoreTransportError):
                pipeline.generate_sample(row["id"])
        self.assertEqual(pipeline.db.next_attempt(row["id"]), 1)
        self.assertEqual(pipeline.db.attempts_for_sample(row["id"]), [])

    def test_agent_generates_and_compares_multiple_candidates(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        pipeline.config["intelligence"] = {
            "enabled": True, "planner": True, "critic": True, "critic_gate": True, "fail_open": False,
            "agentic_generation": True, "candidate_count": 3, "comparative_critic": True,
            "orchestrator": True, "reference_candidate_count": 3, "approved_example_count": 0,
            "recent_failure_memory": 3,
        }

        class AgentIntelligence:
            def plan(self, source_path, roi_path, labels, shapes, base_prompt, references, attempt_dir, focus_mask_path=None, failed_candidate_path=None):
                build_roi_context(source_path, roi_path, attempt_dir / "intelligence_roi_context.png", focus_mask_path)
                return {
                    "edit_instruction": "移除螺栓并恢复安装孔。", "must_preserve": ["安装板"],
                    "negative_patterns_to_avoid": ["矩形贴片"], "background_preservation_plan": "保留背景",
                    "candidate_directives": ["方案A", "方案B", "方案C"], "mask_geometry": "focus_dilation",
                    "edit_context_scale": "normal", "selected_reference_indices": [],
                }

            def critique(self, source_path, candidate_path, roi_context_path, labels, plan, attempt_dir, references=()):
                return {"pass": True, "reason_codes": [], "diagnosis": "", "revision_instruction": ""}

            def compare_candidates(self, source_path, roi_context_path, candidate_paths, labels, plan, candidate_reports, attempt_dir, references=()):
                return {
                    "selected_index": 1, "pass": True, "reason_codes": [], "candidate_scores": [],
                    "selection_rationale": "候选2最佳", "diagnosis": "", "revision_instruction": "", "next_strategy": "keep",
                }

        class CandidateAdapter:
            name = "fake_image_core"
            calls = 0

            def generate(self, request):
                self.calls += 1
                with Image.open(request.source_path) as opened:
                    output = opened.convert("L")
                for y in range(25, 33):
                    for x in range(32, 40):
                        output.putpixel((x, y), 40 + self.calls * 10)
                output.save(request.output_path, format="PNG")
                return {"adapter": self.name, "call": self.calls}

        pipeline.intelligence = AgentIntelligence()
        adapter = CandidateAdapter()
        row = pipeline.db.list_samples()[0]
        with patch("anomaly_factory.pipeline.create_adapter", return_value=adapter):
            result = pipeline.generate_sample(row["id"])
        self.assertEqual(result["workflow"], "anomaly_review")
        self.assertEqual(adapter.calls, 3)
        self.assertEqual(result["qc"]["agent"]["generated_candidate_count"], 3)
        self.assertEqual(result["qc"]["agent"]["selected_candidate_index"], 1)

    def test_sequential_roi_source_and_dependency_invalidation(self) -> None:
        json_path = self.root / "dataset" / "part_a" / "source.json"
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        payload["shapes"].append(
            {"label": "LY", "points": [[52, 12], [70, 28]], "group_id": None, "shape_type": "rectangle", "flags": {}}
        )
        json_path.write_text(json.dumps(payload), encoding="utf-8")
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        config["generation"] = {"multi_label_mode": "per_image_layered", "multi_roi_source_mode": "sequential_success"}
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        rows = sorted(pipeline.db.list_samples(), key=lambda row: row["shapes"][0]["index"])

        class LocalEditAdapter:
            name = "fake_image_core"

            def generate(self, request):
                with Image.open(request.source_path) as opened:
                    output = opened.convert("L")
                for y in range(24, 32):
                    for x in range(30, 38):
                        output.putpixel((x, y), 45)
                output.save(request.output_path, format="PNG")
                return {"adapter": self.name}

        with patch("anomaly_factory.pipeline.create_adapter", return_value=LocalEditAdapter()):
            first = pipeline.generate_sample(rows[0]["id"])
            self.assertEqual(first["workflow"], "anomaly_review")
            second = pipeline.generate_sample(rows[1]["id"])
        self.assertIn(rows[0]["id"], second["qc"]["agent"]["base_dependencies"])
        pipeline.db.review(rows[0]["id"], "anomaly", "rejected", ["WRONG_STRUCTURE"], "重做前序ROI")
        self.assertEqual(pipeline.db.get_sample(rows[1]["id"])["workflow"], "regen_queued")

    def test_intelligence_planner_is_appended_to_core_prompt(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()

        class FakeIntelligence:
            def plan(self, source_path, roi_path, labels, shapes, base_prompt, references, attempt_dir, focus_mask_path=None, failed_candidate_path=None):
                build_roi_context(source_path, roi_path, attempt_dir / "intelligence_roi_context.png", focus_mask_path)
                return {
                    "edit_instruction": "只移除当前ROI内可见螺栓本体，保留安装板并露出原有圆孔。",
                    "target_description": "螺栓", "expected_background": "圆孔与安装板",
                    "must_preserve": ["相邻零件"], "anomaly_strength": "clear",
                    "mask_assessment": "可用", "warnings": [],
                    "generation_mode": "broad_context", "edit_context_scale": "wide",
                    "selected_reference_indices": [1], "retry_action": "switch_reference",
                    "strategy_summary": "扩大上下文并重建被遮挡背景",
                }

        pipeline.config["intelligence"] = {"enabled": True, "planner": True, "critic": False, "fail_open": True}
        pipeline.intelligence = FakeIntelligence()
        row = pipeline.db.list_samples()[0]
        pipeline.generate_sample(row["id"])
        attempt = pipeline.db.active_attempt(row["id"])
        prompt = Path(attempt["prompt_path"]).read_text(encoding="utf-8")
        self.assertIn("视觉LLM生成策略总控", prompt)
        self.assertIn("露出原有圆孔", prompt)
        job = json.loads((Path(attempt["candidate_path"]).parent / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["mask_relationship"]["strategy_scale"], "wide")
        self.assertEqual(job["references"], [job["reference_candidates"][1]])

    def test_intelligence_critic_rejects_and_writes_next_round_feedback(self) -> None:
        pipeline = Pipeline(load_config(self.config_path))
        pipeline.scan()
        pipeline.config["generation"]["local_tone_match"] = False
        pipeline.config["intelligence"] = {
            "enabled": True, "planner": True, "critic": True, "critic_gate": True, "fail_open": True,
        }

        class FakeIntelligence:
            def plan(self, source_path, roi_path, labels, shapes, base_prompt, references, attempt_dir, focus_mask_path=None, failed_candidate_path=None):
                build_roi_context(source_path, roi_path, attempt_dir / "intelligence_roi_context.png", focus_mask_path)
                return {
                    "edit_instruction": "移除当前螺栓。", "generation_mode": "focused_context",
                    "edit_context_scale": "normal", "selected_reference_indices": [],
                    "retry_action": "initial", "strategy_summary": "首次生成",
                }

            def critique(self, source_path, candidate_path, roi_context_path, labels, plan, attempt_dir, references=()):
                return {
                    "pass": False, "severity": "major", "reason_codes": ["WRONG_STRUCTURE"],
                    "diagnosis": "移除后出现悬空金属块。", "revision_instruction": "保留安装板，只恢复被螺栓遮挡的圆孔。",
                }

        class FakeAdapter:
            name = "fake_image_core"

            def generate(self, request):
                with Image.open(request.source_path) as opened:
                    output = opened.convert("L")
                for y in range(24, 34):
                    for x in range(30, 42):
                        output.putpixel((x, y), 45)
                output.save(request.output_path, format="PNG")
                return {"adapter": self.name}

        pipeline.intelligence = FakeIntelligence()
        row = pipeline.db.list_samples()[0]
        with patch("anomaly_factory.pipeline.create_adapter", return_value=FakeAdapter()):
            result = pipeline.generate_sample(row["id"])
        self.assertEqual(result["workflow"], "qc_failed")
        self.assertIn("LLM_SEMANTIC_QC_FAILED", result["qc"]["failures"])
        updated = pipeline.db.get_sample(row["id"])
        self.assertEqual(updated["anomaly_reason_codes"], ["WRONG_STRUCTURE"])
        self.assertIn("只恢复被螺栓遮挡的圆孔", updated["anomaly_comment"])


if __name__ == "__main__":
    unittest.main()
