"""AI 测试分工：gys 8 项、zyc 8 项；缺陷用例保留在对应功能文件中。"""

CASES = [
    {'id': 'T01', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T01_wire_request_contains_source_reference_and_instruction'},
    {'id': 'T02', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T02_batch_plan_maps_every_roi_and_audits_references'},
    {'id': 'T03', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T03_missing_roi_in_model_response_is_rejected'},
    {'id': 'T04', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T04_extra_roi_in_model_response_is_rejected'},
    {'id': 'T05', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T05_non_json_response_is_rejected'},
    {'id': 'T06', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T06_critic_sees_source_candidate_context_and_reference'},
    {'id': 'T07', 'role': 'gys', 'test': 'TEST.test_ai.test_vision_contracts.VisionContractCases.test_T07_candidate_comparison_includes_all_candidates'},
 ]
