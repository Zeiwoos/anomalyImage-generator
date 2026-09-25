"""全部 AI 离线用例：gys、zyc 各 8 项，均位于当前目录。"""

CASES = [
    {'id': 'T01', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T01_wire_request_contains_source_reference_and_instruction'},
    {'id': 'T02', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T02_batch_plan_maps_every_roi_and_audits_references'},
    {'id': 'T03', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T03_missing_roi_in_model_response_is_rejected'},
    {'id': 'T04', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T04_extra_roi_in_model_response_is_rejected'},
    {'id': 'T05', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T05_non_json_response_is_rejected'},
    {'id': 'T06', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T06_critic_sees_source_candidate_context_and_reference'},
    {'id': 'T07', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T07_candidate_comparison_includes_all_candidates'},
    {'id': 'T08', 'role': 'zyc',
     'test': 'TEST.test_ai.test_output_metrics.OutputMetricsCases.test_T08_pixel_pass_requires_human_realism_review'},
    {'id': 'T09', 'role': 'zyc',
     'test': 'TEST.test_ai.test_output_metrics.OutputMetricsCases.test_T09_outside_single_pixel_change_is_detected'},
    {'id': 'T10', 'role': 'zyc',
     'test': 'TEST.test_ai.test_output_metrics.OutputMetricsCases.test_T10_human_rejection_overrides_numerical_pass'},
    {'id': 'D04', 'role': 'zyc',
     'test': 'TEST.test_ai.test_batch_planning.BatchPlanningCases.test_D04_duplicate_roi_response_is_not_silently_discarded'},
    {'id': 'D05', 'role': 'zyc',
     'test': 'TEST.test_ai.test_batch_planning.BatchPlanningCases.test_D05_duplicate_input_ids_are_rejected_before_request'},
    {'id': 'D06', 'role': 'gys',
     'test': 'TEST.test_ai.test_candidate_comparison.CandidateComparisonCases.test_D06_scores_and_selection_match_supplied_candidates'},
    {'id': 'T11', 'role': 'zyc',
     'test': 'TEST.test_ai.test_batch_planning.BatchPlanningCases.test_T11_empty_batch_does_not_call_model'},
    {'id': 'T12', 'role': 'zyc',
     'test': 'TEST.test_ai.test_output_metrics.OutputMetricsCases.test_T12_human_approval_completes_valid_result'},
    {'id': 'T13', 'role': 'zyc',
     'test': 'TEST.test_ai.test_output_metrics.OutputMetricsCases.test_T13_human_approval_does_not_override_pixel_failure'}

]
