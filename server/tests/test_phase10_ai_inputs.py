from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.services.ai_task_model_policy_service import TASK_OPERATION_CODES, next_analysis_retry
from app.services.attachment_planning_service import attachment_module_rule
from app.services.attachment_product_identity_service import parse_product_identity_lock
from app.services.attachment_reference_library_service import parse_library_understanding


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
