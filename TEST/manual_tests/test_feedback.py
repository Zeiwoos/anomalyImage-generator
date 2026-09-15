from TEST._shared.fixtures import LocalHttpTest


class FeedbackCases(LocalHttpTest):
    def test_D02_feedback_batch_error_leaves_all_members_unchanged(self):
        """D02：批量反馈含不存在的样本时，所有有效样本也应保持原样。

        准备：将第一个样本设为允许反馈的状态，并保存修改前的记录。
        执行：提交一个有效 ID 和一个不存在的 ID，随后重新读取有效样本。
        预期：接口返回 400，反馈意见与提交前相同；不能先写入第一个再报错。
        """
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
        """D02b：批量反馈含状态不允许的样本时，不能部分保存。

        准备：两个样本都存在，但只有第一个处于允许反馈的状态。
        执行：对两个样本一起提交反馈，再读取第一个样本的意见。
        预期：返回 400，第一个样本的意见也必须保持原样。
        """
        first, second = self.rows[0]['id'], self.rows[1]['id']
        self.pipeline.db.set_workflow(first, 'regen_queued')
        before = self.pipeline.db.get_sample(first)
        code, _ = self.request('POST', '/api/generation-feedback', {
            'sample_ids': [first, second], 'comment': 'D02_INELIGIBLE'})
        self.assertEqual(code, 400)
        self.assertEqual(self.pipeline.db.get_sample(first)['anomaly_comment'], before['anomaly_comment'])

