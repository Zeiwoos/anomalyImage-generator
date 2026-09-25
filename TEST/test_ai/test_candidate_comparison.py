"""gys：候选比较的响应校验，使用固定模型回复复现 D06。"""
from pathlib import Path
from unittest.mock import Mock

from anomaly_factory.intelligence import VisionLLMClient
from TEST._shared.fixtures import IsolatedPipelineTest


class CandidateComparisonCases(IsolatedPipelineTest):
    def test_D06_scores_and_selection_match_supplied_candidates(self):
        """D06：候选评分必须与实际提交的候选一一对应，参考图不能算候选。

        准备：两张候选和一张参考，分别模拟额外、遗漏、重复、格式错误的评分及非法选择。
        执行：将各份固定响应交给真实候选比较方法。
        预期：所有非法响应均抛出 ValueError；合法响应由 T07 验证可正常返回。
        """
        self.seed_attempts()
        paths = [Path(self.pipeline.db.active_attempt(row['id'])['candidate_path']) for row in self.rows]
        source = self.annotation.with_suffix('.png')
        reference = self.references / 'pair' / '00_fault.png'
        variants = {
            '参考图被当成第三个候选': ([{'index': 0}, {'index': 1}, {'index': 2}], 1),
            '遗漏候选评分': ([{'index': 0}], 0),
            '重复候选评分': ([{'index': 0}, {'index': 0}], 0),
            '夹入非对象评分': ([{'index': 0}, {'index': 1}, 'invalid'], 1),
            '评分下标类型错误': ([{'index': False}, {'index': 1}], 1),
            '选中不存在的候选': ([{'index': 0}, {'index': 1}], 2),
            '选择下标类型错误': ([{'index': 0}, {'index': 1}], True),
        }
        for name, (scores, selected) in variants.items():
            client = VisionLLMClient.__new__(VisionLLMClient)
            client.config = {'model': 'fixture', 'reasoning_effort': 'low'}
            client._call_json = Mock(return_value=({
                'selected_index': selected, 'pass': True, 'candidate_scores': scores}, {}))
            with self.assertRaisesRegex(ValueError, '候选|candidate', msg=name):
                client.compare_candidates(source, source, paths, ['DS_LS'], {}, [], self.root, [reference])
