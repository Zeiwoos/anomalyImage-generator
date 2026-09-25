from PIL import Image

from TEST._shared.fixtures import IsolatedPipelineTest
from TEST.test_ai.evaluate_outputs import evaluate_case


class OutputMetricsCases(IsolatedPipelineTest):
    def case(self):
        source = Image.new("L", (128, 96), 120)
        candidate = source.copy()
        candidate.paste(40, (24, 30, 32, 40))
        mask = Image.new("L", source.size, 0)
        mask.paste(255, (24, 30, 32, 40))
        allowed = Image.new("L", source.size, 0)
        allowed.paste(255, (20, 20, 48, 60))
        for name, image in [("source", source), ("candidate", candidate), ("mask", mask), ("allowed", allowed)]:
            image.save(self.root / (name + ".png"))
        return {"id": "fixture", "source": "source.png", "candidate": "candidate.png",
                "mask": "mask.png", "allowed_mask": "allowed.png", "gold_mask": "mask.png"}

    def test_T08_pixel_pass_requires_human_realism_review(self):
        """T08：自动图像指标通过后，仍应等待人工判断真实性。

        准备：生成源图、仅在允许区域变化的候选图及完全匹配的掩膜。
        执行：调用图像输出评价函数。
        预期：自动检查通过，掩膜交并比为 1，但最终状态为 manual_pending（待人工评价）。
        """
        result = evaluate_case(self.case(), self.root)
        self.assertTrue(result["automatic_pass"])
        self.assertEqual(result["metrics"]["mask_iou"], 1.0)
        self.assertEqual(result["verdict"], "manual_pending")

    def test_T09_outside_single_pixel_change_is_detected(self):
        """T09：允许区域外即使只改了一个像素，也应被检测出来。

        准备：将候选图转为 RGB，再将允许区域外一个像素的绿色通道从 120 改为 119。
        执行：保存图片并执行输出评价。
        预期：报告背景变化和颜色偏移，区域外变化像素数为 1。
        """
        case = self.case()
        with Image.open(self.root / "candidate.png") as opened:
            candidate = opened.convert("RGB")
        candidate.putpixel((1, 1), (120, 119, 120))
        candidate.save(self.root / "candidate.png")
        result = evaluate_case(case, self.root)
        self.assertIn("BACKGROUND_CHANGED", result["failures"])
        self.assertIn("COLOR_SHIFT", result["failures"])
        self.assertEqual(result["metrics"]["outside_changed_pixels"], 1)

    def test_T10_human_rejection_overrides_numerical_pass(self):
        """T10：人工否决应优先于自动像素指标通过的结果。

        准备：使用能通过自动指标的图片，并设置 human_pass=False。
        执行：调用输出评价函数。
        预期：最终结论为 failed（不通过）。
        """
        case = self.case()
        case["human_pass"] = False
        self.assertEqual(evaluate_case(case, self.root)["verdict"], "failed")

    def test_T12_human_approval_completes_valid_result(self):
        """T12：自动指标合格且人工确认通过时，结果应判为通过。

        准备：使用只在允许区域变化、掩膜与真值一致的图片，设置 human_pass=True。
        执行：调用输出评价函数。
        预期：自动检查通过、无失败原因，最终状态为 passed。
        """
        case = self.case()
        case['human_pass'] = True
        result = evaluate_case(case, self.root)
        self.assertTrue(result['automatic_pass'])
        self.assertEqual(result['failures'], [])
        self.assertEqual(result['verdict'], 'passed')

    def test_T13_human_approval_does_not_override_pixel_failure(self):
        """T13：人工确认通过不能覆盖允许区域外发生变化的客观错误。

        准备：在候选图的允许区域外改动一个灰度像素，仍设置 human_pass=True。
        执行：保存图片后调用输出评价函数。
        预期：报告 BACKGROUND_CHANGED，自动检查和最终结果均不通过。
        """
        case = self.case()
        case['human_pass'] = True
        with Image.open(self.root / 'candidate.png') as opened:
            candidate = opened.copy()
        candidate.putpixel((1, 1), 119)
        candidate.save(self.root / 'candidate.png')
        result = evaluate_case(case, self.root)
        self.assertFalse(result['automatic_pass'])
        self.assertIn('BACKGROUND_CHANGED', result['failures'])
        self.assertEqual(result['verdict'], 'failed')
