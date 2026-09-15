import json

from PIL import Image

from anomaly_factory.labelme import build_edit_context_mask, parse_labelme
from TEST._shared.fixtures import IsolatedPipelineTest, write_sample


class InputCases(IsolatedPipelineTest):
    def test_A01_distinct_roi_ids_for_repeated_labels(self):
        """A01: two shapes with the same label remain independent; repeated scan is idempotent."""
        write_sample(self.dataset / "same_label", labels=("DS_LS", "DS_LS"))
        self.pipeline.scan()
        first = {r["id"] for r in self.pipeline.db.list_samples()}
        self.pipeline.scan()
        self.assertEqual(len(first), 4)
        self.assertEqual(first, {r["id"] for r in self.pipeline.db.list_samples()})

    def test_A02_unknown_label_is_held(self):
        """A02: unknown label is retained for inspection and held from generation."""
        write_sample(self.dataset / "unknown", labels=("NOT_A_LABEL",))
        result = self.pipeline.scan()
        row = next(r for r in self.pipeline.db.list_samples() if "NOT_A_LABEL" in r["labels"])
        self.assertEqual(result["unknown_labels"], 1)
        self.assertEqual(row["workflow"], "hold")

    def test_A03_empty_annotation_is_held(self):
        """A03: an empty shape list produces a held record, not an editable full image."""
        write_sample(self.dataset / "empty", labels=())
        result = self.pipeline.scan()
        empty = next(r for r in self.pipeline.db.list_samples() if not r["shapes"])
        self.assertEqual(result["empty_shapes"], 1)
        self.assertEqual(empty["workflow"], "hold")

    def test_A04_bad_json_does_not_hide_valid_samples(self):
        """A04: corrupt JSON yields a diagnostic while valid ROIs are scanned."""
        (self.dataset / "broken.json").write_text("{", encoding="utf-8")
        result = self.pipeline.scan()
        self.assertEqual(result["samples"], 2)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("broken.json", result["errors"][0])

    def test_A05_actual_image_dimensions_win(self):
        """A05: wrong LabelMe dimensions produce a warning; true image dimensions are used."""
        payload = json.loads(self.annotation.read_text())
        payload["imageWidth"] = 999
        self.annotation.write_text(json.dumps(payload))
        sample = parse_labelme(self.annotation, self.dataset, [".png"])
        self.assertEqual((sample.width, sample.height), (128, 96))
        self.assertTrue(sample.warnings)

    def test_A06_focus_is_inside_larger_edit_context(self):
        """A06: focus is semantic anchor; editable context extends beyond it without losing focus."""
        sample = self.pipeline._sample_from_row(self.rows[0])
        focus, allowed, _ = build_edit_context_mask(sample, 8, 0)
        self.assertGreater(allowed.histogram()[255], focus.histogram()[255])
        from PIL import ImageChops
        self.assertIsNone(ImageChops.subtract(focus, allowed).getbbox())

    def test_A07_missing_image_is_reported(self):
        """A07: missing source yields a scan error containing the annotation path."""
        bad = write_sample(self.dataset / "missing", labels=("LY",))
        bad.with_suffix(".png").unlink()
        result = self.pipeline.scan()
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("missing", result["errors"][0])
