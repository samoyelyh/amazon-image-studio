from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.errors import AppError
from app.services.ai_task_model_policy_service import TASK_OPERATION_CODES, next_analysis_retry
from app.services.attachment_planning_service import attachment_module_rule
from app.services import attachment_planning_service
from app.models.attachment_planning import AttachmentWorkbenchModulePlan, AttachmentWorkbenchPlan
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject, ListingVersion
from app.schemas.attachment_planning import AttachmentPlanningModuleInput
from app.services.attachment_reference_service import (
    REFERENCE_ANALYSIS_POLICY_VERSION,
    REFERENCE_ANALYSIS_PROMPT_VERSION,
)
from app.services.attachment_product_identity_service import parse_product_identity_lock
from app.services.attachment_reference_library_service import parse_library_understanding
from app.schemas.tasks import JobSubmitRequest


def test_analysis_retry_is_exactly_two_mini_attempts_then_one_luna_fallback() -> None:
    second = next_analysis_retry(attempt=1, fallback_used=False)
    assert second and (second.attempt, second.use_fallback) == (2, False)
    third = next_analysis_retry(attempt=2, fallback_used=False)
    assert third and (third.attempt, third.use_fallback) == (3, True)
    assert next_analysis_retry(attempt=3, fallback_used=True) is None
    assert next_analysis_retry(attempt=1, fallback_used=True) is None


def test_phase10_ai_tasks_have_dedicated_operation_codes() -> None:
    assert TASK_OPERATION_CODES["REFERENCE_ANALYSIS"] == "listing.reference_analyze"
    assert TASK_OPERATION_CODES["REFERENCE_LIBRARY_ANALYSIS"] == "listing.reference_library_analyze"
    assert TASK_OPERATION_CODES["PRODUCT_IDENTITY_EXTRACTION"] == "listing.product_identity_extract"
    assert TASK_OPERATION_CODES["MODEL_REFERENCE_ANALYSIS"] == "listing.model_reference_analyze"
    assert TASK_OPERATION_CODES["MODULE_PLANNING"] == "listing.plan"


def test_reference_understanding_hash_contract_has_explicit_policy_versions() -> None:
    assert REFERENCE_ANALYSIS_PROMPT_VERSION == "attachment-reference-v3"
    assert REFERENCE_ANALYSIS_POLICY_VERSION == "phase10-reference-routing-v1"


@pytest.mark.asyncio
async def test_suite_planning_persists_one_backend_dependency_intent(monkeypatch) -> None:
    plan = AttachmentWorkbenchPlan(
        id="plan", organization_id="org", listing_image_project_id="image-project",
        session_id="session", listing_version_id="version", pending_planning_json={},
        planning_status="ready", visual_direction_cn="", created_by="user", updated_by="user",
    )
    module = AttachmentWorkbenchModulePlan(
        id="module", organization_id="org", workbench_plan_id="plan", module_key="gift_scene",
        plan_summary_cn="", prompt_cn="", operator_requirement_cn="", aspect_ratio="4:5",
        reference_context_dirty=True, reference_state_version=3, status="draft", updated_by="user",
    )
    monkeypatch.setattr(
        attachment_planning_service, "_start_planning_dependencies",
        AsyncMock(return_value=({"gift_scene": "understanding"}, "identity", 2)),
    )
    monkeypatch.setattr(
        attachment_planning_service, "_continue_pending_for_loaded_context",
        AsyncMock(return_value=(None, False)),
    )
    from app.services import creative_preset_service
    monkeypatch.setattr(
        creative_preset_service, "creative_context_snapshot",
        AsyncMock(return_value={"visual_preset_version_id": "visual-v1"}),
    )
    _, created_count = await attachment_planning_service.request_suite_planning(
        AsyncMock(), None,
        project=ListingImageProject(id="image-project", organization_id="org"),
        session=ListingGenerationSession(id="session", organization_id="org"),
        version=ListingVersion(id="version", organization_id="org", session_id="session", version_number=1),
        plan=plan, module_rows=[module],
        modules=[AttachmentPlanningModuleInput(
            module_key="gift_scene", aspect_ratio="4:5", operator_requirement_cn="暖色礼品氛围",
        )],
        visual_direction_cn="统一真实商品质感", idempotency_key="suite-intent-001", user_id="user",
    )
    assert created_count == 2
    assert plan.planning_status == "preparing"
    assert module.status == "preparing"
    assert plan.pending_planning_json["reference_understanding_ids"] == {"gift_scene": "understanding"}
    assert plan.pending_planning_json["modules"][0]["operator_requirement_cn"] == "暖色礼品氛围"


@pytest.mark.asyncio
async def test_module_dependency_preparation_does_not_replace_suite_status(monkeypatch) -> None:
    plan = AttachmentWorkbenchPlan(
        id="plan", organization_id="org", listing_image_project_id="image-project",
        session_id="session", listing_version_id="version", pending_planning_json={},
        planning_status="ready", visual_direction_cn="整套方向", created_by="user", updated_by="user",
    )
    module = AttachmentWorkbenchModulePlan(
        id="module", organization_id="org", workbench_plan_id="plan", module_key="gift_scene",
        plan_summary_cn="礼品方案", prompt_cn="礼品Prompt", operator_requirement_cn="", aspect_ratio="4:5",
        reference_context_dirty=True, reference_state_version=4, status="ready", updated_by="user",
    )
    monkeypatch.setattr(
        attachment_planning_service, "_start_planning_dependencies",
        AsyncMock(return_value=({"gift_scene": "understanding"}, "identity", 1)),
    )
    monkeypatch.setattr(
        attachment_planning_service, "_continue_pending_for_loaded_context",
        AsyncMock(return_value=(None, False)),
    )
    await attachment_planning_service.request_module_planning(
        AsyncMock(), None,
        project=ListingImageProject(id="image-project", organization_id="org"),
        session=ListingGenerationSession(id="session", organization_id="org"),
        version=ListingVersion(id="version", organization_id="org", session_id="session", version_number=1),
        plan=plan, module_rows=[module], module=module, action="module_replan",
        aspect_ratio="4:5", operator_requirement_cn="减少道具",
        idempotency_key="module-intent-001", user_id="user",
    )
    assert plan.planning_status == "ready"
    assert module.status == "preparing"
    assert plan.pending_planning_json["scope"] == "module"


@pytest.mark.parametrize("operation_code", [
    "listing.reference_analyze",
    "listing.reference_library_analyze",
    "listing.product_identity_extract",
    "listing.model_reference_analyze",
])
def test_phase10_listing_text_operations_pass_job_request_validation(operation_code: str) -> None:
    request = JobSubmitRequest(
        operation_code=operation_code,
        workspace_type="listing",
        queue_name="planning_queue",
        capability="text_generation",
        model_code="gpt-5.4-mini",
        idempotency_key=f"phase10-{operation_code.replace('.', '-')}",
        input={"system_prompt": "system", "user_prompt": "user"},
    )
    assert request.operation_code == operation_code


def test_reference_library_schema_rejects_explanatory_or_partial_results() -> None:
    parsed = parse_library_understanding(
        '{"role":"TEMPLATE","summary_cn":"参考礼盒布局、俯拍关系和暖色商业光线。",'
        '"composition":"礼盒与折叠商品形成对角平衡","camera_angle":"45度俯拍",'
        '"subject_placement":"商品居中","lighting":"暖色柔光","background":"礼品场景",'
        '"props":["丝带"],"reusable_rules":["复用礼盒位置"],'
        '"forbidden_inheritance":["模板商品颜色","模板Logo"]}'
    )
    assert "模板商品颜色" in parsed["forbidden_inheritance"]
    with pytest.raises(AppError):
        parse_library_understanding('{"summary_cn":"我分析了这张图片。"}')


def test_product_identity_lock_accepts_unknown_without_inventing_facts() -> None:
    parsed = parse_product_identity_lock(
        '{"category":"Football Jersey","primary_color":"black","secondary_colors":[],'
        '"collar":"V-neck","sleeve_type":"short sleeves","garment_structure":"athletic jersey",'
        '"front_text":"TEAM NAME","back_text":"unknown","front_number":"00","back_number":"00",'
        '"shoulder_number":"unknown","logos":[],"print_structure":["outlined block number"],'
        '"customization_elements":["name","number"],"material_visual_features":[],'
        '"immutable_features":["black body","TEAM NAME","00","V-neck"],'
        '"forbidden_changes":["do not recolor"],"needs_confirmation":["fabric composition"]}'
    )
    assert parsed["primary_color"] == "black"
    assert "fabric composition" in parsed["needs_confirmation"]


def test_six_modules_expose_distinct_buyer_questions_and_sales_objectives() -> None:
    module_keys = ("pure_white", "custom_process", "stadium_scene", "gift_scene", "detail_display", "casual_scene")
    rules = [attachment_module_rule({}, module_key) for module_key in module_keys]
    assert len({rule["buyer_question"] for rule in rules}) == 6
    assert len({rule["image_sales_objective"] for rule in rules}) == 6
    assert all(rule["required_information"] for rule in rules)
    assert all(rule["avoid_duplication"] for rule in rules)
