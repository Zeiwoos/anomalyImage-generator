"""批量规划响应校验：使用预设模型回复检查区域 ID 的唯一性。
"""
from unittest.mock import Mock
from anomaly_factory.intelligence import VisionLLMClient
from TEST._shared.fixtures import LocalHttpTest


class BatchPlanningCases(LocalHttpTest):
    def test_T11_empty_batch_does_not_call_model(self):
        """T11：没有待规划区域时，应直接返回空结果。

        准备：使用空区域列表，并监视模型调用。
        执行：调用真实批量规划方法。
        预期：返回空字典，不请求模型，也不创建规划输出目录。
        """
        client = VisionLLMClient.__new__(VisionLLMClient)
        client.config = {'model': 'fixture', 'reasoning_effort': 'low'}
        client._call_json = Mock()
        folder = self.root / 'empty_batch'
        result = client.plan_batch(self.annotation.with_suffix('.png'), [], folder)
        self.assertEqual(result, {})
        client._call_json.assert_not_called()
        self.assertFalse(folder.exists())

    def test_D04_duplicate_roi_response_is_not_silently_discarded(self):
        """D04：同一区域返回相互冲突的重复规划时，应拒绝响应。

        准备：先为每个区域准备一份规划，再给第一个区域追加不同的第二份规划。
        执行：用 Mock 返回上述响应，调用真实批量规划方法。
        预期：抛出 ValueError；若静默接受或丢弃冲突项，则暴露缺陷。
        """
        client = VisionLLMClient.__new__(VisionLLMClient)
        client.config = {'model': 'fixture', 'reasoning_effort': 'low'}
        items = [{'roi_id': row['id'], 'labels': row['labels'], 'shapes': row['shapes'],
                  'source_path': row['image_path'],
                  'roi_mask_path': self.pipeline.db.active_attempt(row['id'])['mask_path'],
                  'references': [], 'base_prompt': 'Do not modify unselected targets.'}
                 for row in self.rows]
        plans = [{'roi_id': item['roi_id'], 'edit_instruction': 'plan-one'} for item in items]
        plans.append({'roi_id': items[0]['roi_id'], 'edit_instruction': 'conflicting-plan-two'})
        client._call_json = Mock(return_value=({'roi_plans': plans}, {}))
        with self.assertRaises(ValueError, msg='Conflicting duplicate ROI was silently accepted'):
            client.plan_batch(self.annotation.with_suffix('.png'), items, self.root / 'duplicate_plan')

    def test_D05_duplicate_input_ids_are_rejected_before_request(self):
        """D05：两个不同区域共用 ID 时，应在调用模型前拒绝输入。

        准备：两个位置不同的区域使用相同 ID，预设模型只返回该 ID 的一份规划。
        执行：调用真实批量规划方法，并记录是否调用模型封装方法。
        预期：抛出明确的重复 ID 错误；不能发送模型请求或将两个任务合并。
        """
        client = VisionLLMClient.__new__(VisionLLMClient)
        client.config = {'model': 'fixture', 'reasoning_effort': 'low'}
        items = [{'roi_id': 'SAME_ID', 'labels': row['labels'], 'shapes': row['shapes'],
                  'source_path': row['image_path'],
                  'roi_mask_path': self.pipeline.db.active_attempt(row['id'])['mask_path'],
                  'references': [], 'base_prompt': '仅修改指定区域。'} for row in self.rows]
        client._call_json = Mock(return_value=({'roi_plans': [
            {'roi_id': 'SAME_ID', 'edit_instruction': '只保留一个任务'}]}, {}))
        with self.assertRaisesRegex(ValueError, '重复|duplicate'):
            client.plan_batch(self.annotation.with_suffix('.png'), items, self.root / 'duplicate_input')
        client._call_json.assert_not_called()
