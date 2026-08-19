from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.models.attachment_planning import AttachmentWorkbenchModulePlan
from app.models.identity import User
from app.models.listing_workflow import (
    CategorySkill,
    ListingGenerationSession,
    ListingImageProject,
    ListingVersion,
    ProductCategory,
)
from app.schemas.attachment_planning import AttachmentPlanningModuleInput
from app.services.attachment_planning_service import (
    build_attachment_module_context,
    build_suite_planning_input,
    parse_module_planning_result,
    parse_suite_planning_result,
)


def _snapshots() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    analysis = {
        "product_name": "定制橄榄球衣", "main_color": "红色", "secondary_color": "白色",
        "collar_type": "V领", "fabric_texture": "网眼", "customizable": True,
        "custom_fields": ["姓名", "背号"], "target_customer": "橄榄球爱好者",
        "usage_scenarios": ["比赛日", "日常穿搭"],
    }
    listing = {
        "title": {"en": "Custom Football Jersey", "zh": "定制橄榄球衣"},
        "bullet_points": [{"en": "Visible V-neck", "zh": "V领结构"}],
        "selling_points": {"zh": "支持姓名与背号定制"},
    }
    skill = {
        "category_code": "football_jersey", "category_name": "橄榄球衣",
        "skill_name": "橄榄球衣默认Skill", "skill_version": 3,
    }
    return analysis, listing, skill


def test_attachment_context_is_module_scoped_and_includes_aspect_ratio() -> None:
    analysis, listing, skill = _snapshots()
    gift = build_attachment_module_context(
        module_key="gift_scene", analysis_snapshot=analysis, listing_snapshot=listing,
        skill_snapshot=skill, aspect_ratio="4:5", operator_requirement_cn="突出生日礼物氛围",
    )
    detail = build_attachment_module_context(
        module_key="detail_display", analysis_snapshot=analysis, listing_snapshot=listing,
        skill_snapshot=skill, aspect_ratio="1:1", operator_requirement_cn="突出领口",
    )
    assert gift["module_objective"] != detail["module_objective"]
    assert gift["aspect_ratio"] == "4:5"
    assert gift["operator_requirement_cn"] == "突出生日礼物氛围"
    assert "target_customer" in gift["product_context"]
    assert "fabric_texture" in detail["product_context"]


def test_suite_builder_only_contains_selected_modules() -> None:
    analysis, listing, skill = _snapshots()
    version = ListingVersion(
        organization_id="org", session_id="session", version_number=1,
        listing_snapshot=listing, analysis_snapshot=analysis, category_skill_snapshot=skill,
        confirmed_at=datetime.now(timezone.utc), confirmed_by="user", created_by="user",
    )
    _, user_prompt, contexts = build_suite_planning_input(
        version=version,
        modules=[
            AttachmentPlanningModuleInput(module_key="pure_white", aspect_ratio="1:1"),
            AttachmentPlanningModuleInput(module_key="gift_scene", aspect_ratio="4:5"),
        ],
        visual_direction_cn="统一使用干净商业光线",
    )
    assert set(contexts) == {"pure_white", "gift_scene"}
    assert "casual_scene" not in user_prompt
    assert '"aspect_ratio": "4:5"' in user_prompt


def test_suite_reanalysis_includes_current_operator_edited_prompt() -> None:
    analysis, listing, skill = _snapshots()
    version = ListingVersion(
        organization_id="org", session_id="session", version_number=1,
        listing_snapshot=listing, analysis_snapshot=analysis, category_skill_snapshot=skill,
        confirmed_at=datetime.now(timezone.utc), confirmed_by="user", created_by="user",
    )
    current = AttachmentWorkbenchModulePlan(
        organization_id="org", workbench_plan_id="plan", module_key="gift_scene",
        plan_summary_cn="运营确认的礼品画面", prompt_cn="运营修改后的礼品图提示词",
        operator_requirement_cn="", aspect_ratio="4:5", updated_by="user",
    )
    _, user_prompt, _ = build_suite_planning_input(
        version=version,
        modules=[AttachmentPlanningModuleInput(module_key="gift_scene", aspect_ratio="4:5")],
        visual_direction_cn="统一真实商业质感",
        current_modules={"gift_scene": current},
    )
    assert "运营确认的礼品画面" in user_prompt
    assert "运营修改后的礼品图提示词" in user_prompt


def test_structured_suite_result_requires_exact_module_whitelist() -> None:
    valid = """{
      "visual_direction_cn": "统一真实商品质感与干净商业光线。",
      "modules": [
        {"module_key":"pure_white","plan_summary_cn":"居中白底展示。","prompt_cn":"以1:1比例居中展示真实商品。"},
        {"module_key":"gift_scene","plan_summary_cn":"温馨礼品场景。","prompt_cn":"以4:5比例构建礼品场景并保持商品真实。"}
      ]
    }"""
    visual, modules = parse_suite_planning_result(valid, ["pure_white", "gift_scene"])
    assert visual.startswith("统一")
    assert set(modules) == {"pure_white", "gift_scene"}
    with pytest.raises(AppError) as error:
        parse_suite_planning_result(valid, ["pure_white"])
    assert error.value.code == "attachment_planning.module_result_mismatch"


def test_prompt_optimizer_result_does_not_require_or_replace_plan() -> None:
    value = parse_module_planning_result(
        '{"module_key":"gift_scene","prompt_cn":"优化后的完整中文礼品图提示词"}',
        "gift_scene", optimize_only=True,
    )
    assert value["plan_summary_cn"] == ""
    assert value["prompt_cn"].startswith("优化后")


async def _create_project(context: dict[str, object]) -> str:
    session_factory = context["session_factory"]
    async with session_factory() as db:
        user = await db.scalar(select(User).where(User.account == "first-admin"))
        category = ProductCategory(category_code="football_jersey", category_name="橄榄球衣")
        db.add(category)
        await db.flush()
        skill = CategorySkill(
            category_id=category.id, skill_name="默认Skill", skill_code="default", version=1,
            analysis_prompt="analysis", listing_title_prompt="title", bullet_points_prompt="bullets",
            a_plus_prompt="a+", image_prompt_template="image", image_types_config=[], prompt_rules={},
        )
        db.add(skill)
        await db.flush()
        workflow = ListingGenerationSession(
            organization_id=context["first_org"], category_id=category.id, skill_id=skill.id,
            category_skill_snapshot={"category_code": "football_jersey", "category_name": "橄榄球衣", "skill_name": "默认Skill", "skill_version": 1},
            status="confirmed", source_asset_ids=[], listing_content={"title": {"zh": "测试球衣"}},
            confirmed_at=datetime.now(timezone.utc), confirmed_by=user.id,
            created_by=user.id, updated_by=user.id,
        )
        db.add(workflow)
        await db.flush()
        version = ListingVersion(
            organization_id=context["first_org"], session_id=workflow.id, version_number=1,
            listing_snapshot={"title": {"zh": "测试球衣"}}, analysis_snapshot={"main_color": "红色"},
            category_skill_snapshot=dict(workflow.category_skill_snapshot or {}),
            confirmed_at=datetime.now(timezone.utc), confirmed_by=user.id, created_by=user.id,
        )
        db.add(version)
        await db.flush()
        workflow.current_listing_version_id = version.id
        project = ListingImageProject(
            organization_id=context["first_org"], session_id=workflow.id, listing_version_id=version.id,
            status="editing", prompt_config={}, created_by=user.id, updated_by=user.id,
        )
        db.add(project)
        await db.commit()
        return project.id


@pytest.mark.asyncio
async def test_planning_api_is_org_isolated_versioned_and_conflict_safe(identity_test_context) -> None:
    client = identity_test_context["client"]
    project_id = await _create_project(identity_test_context)
    login = await client.post("/api/v1/auth/login", json={"account": "first-admin", "password": "correct-password"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/planning", headers=headers)
    assert response.status_code == 200, response.text
    planning = response.json()
    assert len(planning["modules"]) == 6
    assert planning["visual_direction_version"] == 0

    edited = await client.patch(
        f"/api/v1/attachment-workbench/projects/{project_id}/visual-direction", headers=headers,
        json={"visual_direction_cn": "统一真实商品质感与干净商业光线", "expected_state_version": planning["state_version"]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["visual_direction_version"] == 1

    conflict = await client.patch(
        f"/api/v1/attachment-workbench/projects/{project_id}/visual-direction", headers=headers,
        json={"visual_direction_cn": "覆盖其他修改", "expected_state_version": planning["state_version"]},
    )
    assert conflict.status_code == 409

    versions = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/versions", headers=headers)
    assert versions.status_code == 200
    assert versions.json()[0]["action"] == "manual_edit"

    module = edited.json()["modules"][0]
    module_edit = await client.patch(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/{module['module_key']}", headers=headers,
        json={
            "plan_summary_cn": "居中展示真实商品",
            "prompt_cn": "以1:1比例居中展示真实商品，并保留全部商品细节。",
            "operator_requirement_cn": "保持纯白背景",
            "aspect_ratio": "1:1",
            "expected_state_version": module["state_version"],
        },
    )
    assert module_edit.status_code == 200, module_edit.text
    saved_module = next(item for item in module_edit.json()["modules"] if item["module_key"] == module["module_key"])
    assert saved_module["current_version_number"] == 1
    assert saved_module["prompt_cn"].startswith("以1:1比例")

    module_versions = await client.get(
        f"/api/v1/attachment-workbench/projects/{project_id}/versions?module_key={module['module_key']}",
        headers=headers,
    )
    assert module_versions.status_code == 200
    assert module_versions.json()[0]["action"] == "manual_edit"
    assert module_versions.json()[0]["operator_requirement_cn"] == "保持纯白背景"

    second_login = await client.post("/api/v1/auth/login", json={"account": "second-admin", "password": "second-password"})
    second_headers = {"Authorization": f"Bearer {second_login.json()['access_token']}"}
    isolated = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/planning", headers=second_headers)
    assert isolated.status_code == 404
