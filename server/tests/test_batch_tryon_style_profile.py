from app.schemas.tasks import JobSubmitRequest
from app.services.batch_tryon_style_profile_service import (
    sanitize_first_sample_observation,
    sanitize_style_profile_snapshot,
)


def test_style_profile_keeps_structure_and_removes_first_sample_visual_values() -> None:
    value = sanitize_style_profile_snapshot({
        "profile_key": "football-1",
        "source_sample_asset_id": "asset-1",
        "category": "football_jersey",
        "garment_structure": {
            "neckline": "v_neck",
            "sleeve_type": "short_sleeve",
            "fit": "cropped",
            "main_color": "black",
        },
        "view_rules": {"front_back_must_not_swap": True},
        "design_rules": {"preserve_text": True, "preserve_numbers": True},
        "structure_rules": {"preserve_neckline": True, "preserve_sleeves": True},
        "main_color": "black",
        "specific_number": "99",
        "specific_text": "USA",
    })

    assert value["category"] == "football_jersey"
    assert value["garment_structure"] == {
        "neckline": "v_neck",
        "sleeve_type": "short_sleeve",
        "fit": "cropped",
    }
    serialized = str(value).lower()
    assert "black" not in serialized
    assert "99" not in serialized
    assert "usa" not in serialized
    assert value["design_rules"]["preserve_text"] is True
    assert value["design_rules"]["preserve_numbers"] is True


def test_batch_tryon_style_analysis_job_requires_text_operation_and_accepts_vision_reference() -> None:
    request = JobSubmitRequest(
        operation_code="batch_tryon.style_analyze",
        workspace_type="batch_tryon",
        queue_name="planning_queue",
        capability="text_generation",
        model_code="analysis-model",
        idempotency_key="batch-style:test-1",
        input={
            "system_prompt": "Return JSON.",
            "user_prompt": "Analyze structure.",
            "reference_asset_ids": ["asset-1"],
        },
    )
    assert request.operation_code == "batch_tryon.style_analyze"
    assert request.input["reference_asset_ids"] == ["asset-1"]


def test_first_sample_observation_is_bounded_debug_data() -> None:
    value = sanitize_first_sample_observation({
        "main_color": "black",
        "specific_number": "99",
        "nested": {"notes": "x" * 800},
    })
    assert value["main_color"] == "black"
    assert value["specific_number"] == "99"
    assert len(value["nested"]["notes"]) == 500
