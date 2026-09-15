"""Executable case index; no historical results are stored here."""

CASES = [
    {
        "id": "A01",
        "role": "gys",
        "test": "TEST.manual_tests.test_inputs.InputCases.test_A01_distinct_roi_ids_for_repeated_labels"
    },
    {
        "id": "A02",
        "role": "gys",
        "test": "TEST.manual_tests.test_inputs.InputCases.test_A02_unknown_label_is_held"
    },
    {
        "id": "A03",
        "role": "gys",
        "test": "TEST.manual_tests.test_inputs.InputCases.test_A03_empty_annotation_is_held"
    },
    {
        "id": "A04",
        "role": "gys",
        "test": "TEST.manual_tests.test_inputs.InputCases.test_A04_bad_json_does_not_hide_valid_samples"
    },
    {
        "id": "A05",
        "role": "gys",
        "test": "TEST.manual_tests.test_inputs.InputCases.test_A05_actual_image_dimensions_win"
    },
    {
        "id": "A06",
        "role": "gys",
        "test": "TEST.manual_tests.test_inputs.InputCases.test_A06_focus_is_inside_larger_edit_context"
    },
    {
        "id": "A07",
        "role": "gys",
        "test": "TEST.manual_tests.test_inputs.InputCases.test_A07_missing_image_is_reported"
    },
    {
        "id": "A08",
        "role": "gys",
        "test": "TEST.manual_tests.test_prompt_core.PromptCases.test_A08_feedback_and_target_identity_reach_prompt"
    },
    {
        "id": "A09",
        "role": "gys",
        "test": "TEST.manual_tests.test_prompt_core.PromptCases.test_A09_reference_matching_and_root_boundary"
    },
    {
        "id": "A10",
        "role": "gys",
        "test": "TEST.manual_tests.test_prompt_core.PromptCases.test_A10_core_packet_preserves_image_order_mask_and_prompt"
    },
    {
        "id": "A11",
        "role": "gys",
        "test": "TEST.manual_tests.test_prompt_core.PromptCases.test_A11_core_rejects_mismatched_mask_before_request"
    },
    {
        "id": "A12",
        "role": "gys",
        "test": "TEST.manual_tests.test_prompt_core.ConfigurationApiCases.test_A12_api_settings_redact_key_and_persist_locally"
    },
    {
        "id": "A13",
        "role": "gys",
        "test": "TEST.manual_tests.test_prompt_core.ConfigurationApiCases.test_A13_invalid_quality_rejected_without_config_change"
    },
    {
        "id": "A14",
        "role": "gys",
        "test": "TEST.manual_tests.test_prompt_core.ConfigurationApiCases.test_A14_prompt_preview_endpoint_is_read_only"
    },
    {
        "id": "A15",
        "role": "gys",
        "test": "TEST.manual_tests.test_prompt_core.ConfigurationApiCases.test_A15_api_probe_dispatch_and_validation"
    },
    {
        "id": "B01",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_B01_health_items_worker_routes"
    },
    {
        "id": "B02",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_B02_reject_only_selected_roi_and_save_feedback"
    },
    {
        "id": "B03",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_B03_approval_reaches_completed_after_mask_only"
    },
    {
        "id": "B04",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_B04_mask_review_before_anomaly_approval_fails"
    },
    {
        "id": "B05",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_B05_bad_batch_prevalidation_has_no_partial_approval"
    },
    {
        "id": "B06",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_B06_mask_save_binary_backup_and_size_validation"
    },
    {
        "id": "B07",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_B07_image_bytes_and_unknown_image"
    },
    {
        "id": "B08",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_B08_csv_includes_independent_roi_outcomes"
    },
    {
        "id": "B09",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_B09_bad_json_and_unknown_routes"
    },
    {
        "id": "B10",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_B10_delete_requires_confirmation_and_is_recoverable"
    },
    {
        "id": "B11",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_B11_export_requires_all_roi_approvals"
    },
    {
        "id": "B12",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_queue_masks.QueueMaskCases.test_B12_queue_duplicate_start_and_completion"
    },
    {
        "id": "B13",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_queue_masks.QueueMaskCases.test_B13_persisted_review_survives_database_reopen"
    },
    {
        "id": "B14",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_queue_masks.QueueMaskCases.test_B14_difference_mask_does_not_escape_allowed_area"
    },
    {
        "id": "B15",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_queue_masks.QueueMaskCases.test_B15_empty_or_border_changes_fail_qc"
    },
    {
        "id": "B16",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_speed_api.SpeedApiCases.test_B16_speed_config_history_and_result"
    },
    {
        "id": "B17",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_speed_api.SpeedApiCases.test_B17_speed_invalid_kind_and_unconfirmed_cost"
    },
    {
        "id": "B18",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_speed_api.SpeedApiCases.test_B18_speed_dispatch_history_and_busy"
    },
    {
        "id": "D01",
        "role": "gys",
        "test": "TEST.manual_tests.test_prompt_core.ConfigurationApiCases.test_D01_explicit_zero_transport_job_retries_survives_save"
    },
    {
        "id": "D02",
        "role": "gys",
        "test": "TEST.manual_tests.test_feedback.FeedbackCases.test_D02_feedback_batch_error_leaves_all_members_unchanged"
    },
    {
        "id": "D02b",
        "role": "gys",
        "test": "TEST.manual_tests.test_feedback.FeedbackCases.test_D02b_feedback_batch_wrong_workflow_is_also_atomic"
    },
    {
        "id": "D03",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_D03_anomaly_cannot_use_normal_stage_to_skip_mask_review"
    },
    {
        "id": "D03b",
        "role": "zyc",
        "test": "TEST.manual_tests.zyc.test_review_flow.ReviewFlowCases.test_D03b_normal_cannot_use_anomaly_stage"
    }
]

def resolved_cases(root=None):
    """Prefer flattened test files when present; otherwise use role subfolders.

    The project and TEST/_shared remain required. Only the role files are movable.
    """
    from pathlib import Path
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    result = []
    for case in CASES:
        item = dict(case)
        module, class_name, method = item["test"].rsplit(".", 2)
        filename = module.rsplit(".", 1)[-1]
        if (root / (filename + ".py")).is_file():
            item["test"] = ".".join(("TEST.manual_tests", filename, class_name, method))
        result.append(item)
    return result
