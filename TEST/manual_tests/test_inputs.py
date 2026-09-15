import json

from PIL import Image

from anomaly_factory.labelme import build_edit_context_mask, parse_labelme
from TEST._shared.fixtures import IsolatedPipelineTest, write_sample


class InputCases(IsolatedPipelineTest):
    def test_A01_distinct_roi_ids_for_repeated_labels(self):
        """A01：同标签的多个区域应各自独立，重复扫描不应新增重复记录。

        准备：已有图片包含两个区域；再新增一张包含两个同标签区域的图片。
        执行：连续扫描两次，分别读取数据库中的样本 ID。
        预期：共四个独立 ID，第二次扫描后的 ID 集合保持不变。
        """
        write_sample(self.dataset / "same_label", labels=("DS_LS", "DS_LS"))
        self.pipeline.scan()
        first = {r["id"] for r in self.pipeline.db.list_samples()}
        self.pipeline.scan()
        self.assertEqual(len(first), 4)
        self.assertEqual(first, {r["id"] for r in self.pipeline.db.list_samples()})

    def test_A02_unknown_label_is_held(self):
        """A02：未知标签应保留供检查，并暂停生成。

        准备：新增带 NOT_A_LABEL 未知标签的图片和标注。
        执行：扫描数据集，读取该标签对应的样本记录。
        预期：未知标签计数为 1，该样本处于 hold（暂缓）状态。
        """
        write_sample(self.dataset / "unknown", labels=("NOT_A_LABEL",))
        result = self.pipeline.scan()
        row = next(r for r in self.pipeline.db.list_samples() if "NOT_A_LABEL" in r["labels"])
        self.assertEqual(result["unknown_labels"], 1)
        self.assertEqual(row["workflow"], "hold")

    def test_A03_empty_annotation_is_held(self):
        """A03：空标注应被暂缓，不能误当作整图编辑任务。

        准备：新增一张图片，其标注中的 shapes 区域列表为空。
        执行：扫描数据集，读取没有区域的样本。
        预期：空标注计数为 1，样本处于 hold（暂缓）状态。
        """
        write_sample(self.dataset / "empty", labels=())
        result = self.pipeline.scan()
        empty = next(r for r in self.pipeline.db.list_samples() if not r["shapes"])
        self.assertEqual(result["empty_shapes"], 1)
        self.assertEqual(empty["workflow"], "hold")

    def test_A04_bad_json_does_not_hide_valid_samples(self):
        """A04：一份损坏的标注不能阻止其他有效样本被扫描。

        准备：在已有有效图片旁写入内容仅为左花括号的损坏 JSON。
        执行：调用扫描方法，读取返回的样本数量和错误列表。
        预期：仍发现两个有效区域；仅报告一个错误，且指出 broken.json。
        """
        (self.dataset / "broken.json").write_text("{", encoding="utf-8")
        result = self.pipeline.scan()
        self.assertEqual(result["samples"], 2)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("broken.json", result["errors"][0])

    def test_A05_actual_image_dimensions_win(self):
        """A05：标注尺寸错误时，应使用图片实际尺寸并给出警告。

        准备：将标注中的图片宽度改成 999，图片实际尺寸仍为 128×96。
        执行：调用 LabelMe 标注解析方法。
        预期：解析结果尺寸为 128×96，且包含警告信息。
        """
        payload = json.loads(self.annotation.read_text())
        payload["imageWidth"] = 999
        self.annotation.write_text(json.dumps(payload))
        sample = parse_labelme(self.annotation, self.dataset, [".png"])
        self.assertEqual((sample.width, sample.height), (128, 96))
        self.assertTrue(sample.warnings)

    def test_A06_focus_is_inside_larger_edit_context(self):
        """A06：扩展后的允许编辑区域应完整包含原目标区域。

        准备：取一个样本，以 8 像素边距生成目标掩膜和允许编辑掩膜。
        执行：比较两张掩膜的白色像素数量，并计算目标超出允许区域的部分。
        预期：允许区域更大，且没有目标像素落在允许区域之外。
        """
        sample = self.pipeline._sample_from_row(self.rows[0])
        focus, allowed, _ = build_edit_context_mask(sample, 8, 0)
        self.assertGreater(allowed.histogram()[255], focus.histogram()[255])
        from PIL import ImageChops
        self.assertIsNone(ImageChops.subtract(focus, allowed).getbbox())

    def test_A07_missing_image_is_reported(self):
        """A07：标注引用的图片缺失时，应报告可定位的错误。

        准备：先生成图片和标注，再删除图片、保留标注。
        执行：重新扫描数据集。
        预期：仅有一个错误，错误信息包含 missing，便于找到对应标注。
        """
        bad = write_sample(self.dataset / "missing", labels=("LY",))
        bad.with_suffix(".png").unlink()
        result = self.pipeline.scan()
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("missing", result["errors"][0])
