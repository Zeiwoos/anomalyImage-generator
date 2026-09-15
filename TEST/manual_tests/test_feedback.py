"""Generation feedback: validate batch inputs before saving any changes."""
from TEST._shared.fixtures import LocalHttpTest


class FeedbackCases(LocalHttpTest):
    def test_D02_feedback_batch_error_leaves_all_members_unchanged(self):
        """批量提交包含无效样本时，接口应拒绝整个请求，且不能偷偷修改其中的有效样本"""
        target = self.rows[0]['id']
        self.pipeline.db.set_workflow(target, 'regen_queued')
        before = self.pipeline.db.get_sample(target)
        code, result = self.request('POST', '/api/generation-feedback', {
            'sample_ids': [target, 'does-not-exist'], 'comment': 'D02_PARTIAL_WRITE'})
        self.assertEqual(code, 400, result)
        after = self.pipeline.db.get_sample(target)
        self.assertEqual(after['anomaly_comment'], before['anomaly_comment'],
                         '400 response still saved feedback for the first ROI')

    def test_D02b_feedback_batch_wrong_workflow_is_also_atomic(self):
        """D02 boundary: a present but ineligible sibling must not cause partial write."""
        first, second = self.rows[0]['id'], self.rows[1]['id']
        self.pipeline.db.set_workflow(first, 'regen_queued')
        before = self.pipeline.db.get_sample(first)
        code, _ = self.request('POST', '/api/generation-feedback', {
            'sample_ids': [first, second], 'comment': 'D02_INELIGIBLE'})
        self.assertEqual(code, 400)
        self.assertEqual(self.pipeline.db.get_sample(first)['anomaly_comment'], before['anomaly_comment'])

