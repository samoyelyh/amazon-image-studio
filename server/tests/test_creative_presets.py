from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.content import Asset
from app.models.attachment_planning import AttachmentWorkbenchModulePlan, AttachmentWorkbenchPlan
from app.models.creative_presets import (
    AIModelIdentityVersion,
    AIModelPreset,
    AIModelPresetReference,
    ThemePreset,
    ThemePresetVersion,
    VisualPreset,
    VisualPresetVersion,
)
from app.models.identity import User
from app.models.listing_workflow import (
    CategorySkill,
    ListingGenerationSession,
    ListingImageProject,
    ListingVersion,
    ProductCategory,
)
from app.models.tasks import Job
from app.schemas.attachment_planning import AttachmentPlanningModuleInput
from app.services.ai_model_preset_service import fail_ai_model_generation
from app.services.attachment_planning_service import (
    add_module_version,
    build_suite_planning_input,
    get_or_create_attachment_plan,
)
from app.services.creative_preset_service import creative_context_snapshot


UTC = timezone.utc


async def _login(client, account: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"account": account, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _seed_presets(context: dict[str, object]) -> tuple[str, str, str]:
    async with context["session_factory"]() as db:
        admin = await db.scalar(select(User).where(User.account == "platform-admin"))
        visual = VisualPreset(
            organization_id=None, code="amazon_conversion", name="亚马逊高转化电商",
            short_description="商品突出 · 卖点清晰", category_scope=[],
            recommended_modules=["pure_white", "gift_scene"],
            recommended_model_tags=["sports"], tags=["commerce"], sort_order=10,
            is_active=True, is_default=True, created_by=admin.id, updated_by=admin.id,
        )
        alternate = VisualPreset(
            organization_id=None, code="game_day_fan", name="比赛日球迷",
            short_description="体育赛事 · 观赛氛围", category_scope=["football_jersey"],
            recommended_modules=["stadium_scene"], recommended_model_tags=["fan", "sports"],
            tags=["sports"], sort_order=20, is_active=True, is_default=False,
            created_by=admin.id, updated_by=admin.id,
        )
        theme = ThemePreset(
            organization_id=None, code="independence_day", name="美国独立日",
            short_description="7月4日 · 夏日庆祝", tags=["holiday", "usa"],
            sort_order=10, is_active=True, created_by=admin.id, updated_by=admin.id,
        )
        db.add_all([visual, alternate, theme])
        await db.flush()
        visual_version = VisualPresetVersion(
            preset_id=visual.id, version_number=1,
            full_prompt_template="商品真实优先，商品颜色和结构严格来自PRODUCT参考图，输出完整整套策划。",
            change_summary="seed", created_by=admin.id, created_at=datetime.now(UTC),
        )
        alternate_version = VisualPresetVersion(
            preset_id=alternate.id, version_number=1,
            full_prompt_template="采用比赛日球迷视觉；人物只辅助展示，商品颜色、Logo和号码不得改变。",
            change_summary="seed", created_by=admin.id, created_at=datetime.now(UTC),
        )
        theme_version = ThemePresetVersion(
            preset_id=theme.id, version_number=1,
            full_prompt_template="加入美国独立日环境氛围，但不得把非红白蓝商品改成红白蓝。",
            change_summary="seed", created_by=admin.id, created_at=datetime.now(UTC),
        )
        db.add_all([visual_version, alternate_version, theme_version])
        await db.flush()
        visual.current_version_id = visual_version.id
        alternate.current_version_id = alternate_version.id
        theme.current_version_id = theme_version.id
        await db.commit()
        return visual.id, alternate.id, theme.id


async def _seed_project(context: dict[str, object]) -> tuple[str, str]:
    async with context["session_factory"]() as db:
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
            category_skill_snapshot={
                "category_code": "football_jersey", "category_name": "橄榄球衣",
                "skill_name": "默认Skill", "skill_version": 1,
            },
            status="confirmed", source_asset_ids=[], listing_content={"title": {"zh": "红色11号球衣"}},
            confirmed_at=datetime.now(UTC), confirmed_by=user.id, created_by=user.id, updated_by=user.id,
        )
        db.add(workflow)
        await db.flush()
        version = ListingVersion(
            organization_id=context["first_org"], session_id=workflow.id, version_number=1,
            listing_snapshot={"title": {"zh": "红色11号球衣"}},
            analysis_snapshot={"main_color": "红色", "custom_number": "11"},
            category_skill_snapshot=dict(workflow.category_skill_snapshot),
            confirmed_at=datetime.now(UTC), confirmed_by=user.id, created_by=user.id,
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
        return project.id, version.id


async def _seed_published_model(
    context: dict[str, object], *, code: str, display_name: str, status: str = "PUBLISHED",
) -> tuple[str, str]:
    async with context["session_factory"]() as db:
        user = await db.scalar(select(User).where(User.account == "platform-admin"))
        asset = Asset(
            organization_id=context["first_org"], category="ai_model_identity",
            storage_key=f"tests/models/{code}.png", filename=f"{code}.png", mime_type="image/png",
            size=128, width=100, height=150, sha256=(code[-1] * 64),
            created_by=user.id, updated_by=user.id,
        )
        db.add(asset)
        await db.flush()
        preset = AIModelPreset(
            organization_id=None, code=code, name=display_name, display_name=display_name,
            gender_presentation="male", age_range="25–30", body_type="自然运动型",
            short_description="运动生活方式模特", identity_prompt="adult identity prompt",
            generation_prompt="commercial studio identity generation prompt",
            negative_constraints="no celebrity", recommended_visual_presets=["game_day_fan"],
            recommended_modules=["stadium_scene", "gift_scene"], tags=["sports", "fan"],
            cover_asset_id=asset.id, status=status, sort_order=10,
            is_active=True, is_published=status == "PUBLISHED", created_by=user.id, updated_by=user.id,
        )
        db.add(preset)
        await db.flush()
        identity = AIModelIdentityVersion(
            organization_id=context["first_org"], model_preset_id=preset.id, version_number=1,
            status=status, identity_prompt_snapshot="immutable adult identity snapshot",
            identity_asset_id=asset.id, published_at=datetime.now(UTC) if status == "PUBLISHED" else None,
            created_by=user.id, updated_by=user.id,
        )
        db.add(identity)
        await db.flush()
        preset.current_identity_version_id = identity.id if status == "PUBLISHED" else None
        db.add(AIModelPresetReference(
            organization_id=context["first_org"], model_preset_id=preset.id,
            identity_version_id=identity.id, reference_role="FULL_BODY_FRONT", asset_id=asset.id,
            sort_order=1, created_by=user.id, updated_by=user.id,
        ))
        await db.commit()
        return preset.id, identity.id


@pytest.mark.asyncio
async def test_visual_and_theme_admin_versions_are_immutable_and_operator_cannot_edit(identity_test_context) -> None:
    visual_id, _, theme_id = await _seed_presets(identity_test_context)
    client = identity_test_context["client"]
    operator_headers = await _login(client, "first-admin", "correct-password")
    platform_headers = await _login(client, "platform-admin", "platform-password")

    public = await client.get("/api/v1/creative-presets/visual", headers=operator_headers)
    assert public.status_code == 200
    assert public.json()[0]["prompt_template"] is None
    forbidden = await client.put(
        f"/api/v1/admin/creative-presets/visual/{visual_id}", headers=operator_headers,
        json={"full_prompt_template": "普通运营不允许写入系统模板，这段文字足够通过长度校验。"},
    )
    assert forbidden.status_code == 403

    updated = await client.put(
        f"/api/v1/admin/creative-presets/visual/{visual_id}", headers=platform_headers,
        json={
            "full_prompt_template": "第二版完整视觉模板，继续严格保护PRODUCT商品颜色、结构、号码与Logo。",
            "change_summary": "测试不可变版本",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["current_version_number"] == 2
    theme_updated = await client.put(
        f"/api/v1/admin/creative-presets/themes/{theme_id}", headers=platform_headers,
        json={
            "full_prompt_template": "第二版独立日主题只调整环境氛围，不得改变PRODUCT商品的真实颜色。",
            "change_summary": "测试主题版本",
        },
    )
    assert theme_updated.status_code == 200, theme_updated.text
    assert theme_updated.json()["current_version_number"] == 2
    async with identity_test_context["session_factory"]() as db:
        visual_versions = list((await db.scalars(select(VisualPresetVersion).where(
            VisualPresetVersion.preset_id == visual_id,
        ).order_by(VisualPresetVersion.version_number))).all())
        theme_versions = list((await db.scalars(select(ThemePresetVersion).where(
            ThemePresetVersion.preset_id == theme_id,
        ).order_by(ThemePresetVersion.version_number))).all())
        assert [item.version_number for item in visual_versions] == [1, 2]
        assert [item.version_number for item in theme_versions] == [1, 2]
        assert visual_versions[0].full_prompt_template != visual_versions[1].full_prompt_template


@pytest.mark.asyncio
async def test_creative_context_stales_planning_and_snapshots_visual_theme_and_distinct_models(identity_test_context) -> None:
    _, alternate_id, theme_id = await _seed_presets(identity_test_context)
    _, identity_a = await _seed_published_model(identity_test_context, code="M01", display_name="Mason")
    _, identity_b = await _seed_published_model(identity_test_context, code="F01", display_name="Sophia")
    await _seed_published_model(identity_test_context, code="D01", display_name="Draft", status="DRAFT")
    project_id, version_id = await _seed_project(identity_test_context)
    client = identity_test_context["client"]
    headers = await _login(client, "first-admin", "correct-password")

    planning = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/planning", headers=headers)
    assert planning.status_code == 200, planning.text
    saved = await client.patch(
        f"/api/v1/attachment-workbench/projects/{project_id}/visual-direction", headers=headers,
        json={"visual_direction_cn": "原始整套方向", "expected_state_version": planning.json()["state_version"]},
    )
    assert saved.status_code == 200, saved.text
    context = await client.get(
        f"/api/v1/attachment-workbench/projects/{project_id}/creative-context", headers=headers,
    )
    assert context.status_code == 200, context.text
    changed = await client.patch(
        f"/api/v1/attachment-workbench/projects/{project_id}/creative-context", headers=headers,
        json={
            "visual_preset_id": alternate_id, "theme_preset_id": theme_id,
            "model_selection_mode": "selected",
            "selected_model_identity_version_ids": [identity_a, identity_b],
            "expected_creative_context_version": context.json()["creative_context_version"],
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["planning_stale"] is True
    assert [item["identity_version_id"] for item in changed.json()["selected_models"]] == [identity_a, identity_b]

    model_list = await client.get("/api/v1/creative-presets/models", headers=headers)
    assert model_list.status_code == 200
    assert {item["display_name"] for item in model_list.json()} == {"Mason", "Sophia"}
    second_headers = await _login(client, "second-admin", "second-password")
    isolated = await client.get("/api/v1/creative-presets/models", headers=second_headers)
    assert isolated.status_code == 200
    assert isolated.json() == []

    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        workflow = await db.get(ListingGenerationSession, project.session_id)
        listing_version = await db.get(ListingVersion, version_id)
        plan, modules = await get_or_create_attachment_plan(
            db, project=project, session=workflow, version=listing_version,
            user_id=project.created_by,
        )
        snapshot = await creative_context_snapshot(db, plan=plan)
        _, prompt_json, _ = build_suite_planning_input(
            version=listing_version,
            modules=[AttachmentPlanningModuleInput(module_key="gift_scene", aspect_ratio="4:5")],
            visual_direction_cn="", creative_context=snapshot,
        )
        planning_payload = json.loads(prompt_json)
        assert "比赛日球迷" in planning_payload["creative_context"]["visual_preset_name"]
        assert "不得把非红白蓝商品改成红白蓝" in planning_payload["creative_context"]["theme_prompt"]
        module = next(item for item in modules if item.module_key == "gift_scene")
        plan_version = await add_module_version(
            db, plan=plan, module=module, action="manual_edit", user_id=project.created_by,
            rule_snapshot={}, plan_summary_cn="礼品场景", prompt_cn="生成真实礼品场景",
            creative_context=snapshot,
        )
        await db.flush()
        assert plan_version.visual_preset_version_id == snapshot["visual_preset_version_id"]
        assert plan_version.theme_preset_version_id == snapshot["theme_preset_version_id"]
        assert [item["identity_version_id"] for item in plan_version.selected_model_snapshot] == [identity_a, identity_b]


def test_module_capability_and_prompt_contract_separate_model_identity_from_product_garment() -> None:
    from app.services.attachment_generation_service import build_attachment_execution_prompt
    from app.models.attachment_planning import AttachmentReferenceUnderstanding, AttachmentWorkbenchPlanVersion
    from app.services.listing_image_module_service import STANDARD_LISTING_IMAGE_MODULES

    rules = {item["code"]: item for item in STANDARD_LISTING_IMAGE_MODULES}
    assert rules["stadium_scene"]["supports_model"] is True
    assert rules["gift_scene"]["supports_model"] is True
    assert rules["casual_scene"]["supports_model"] is True
    assert rules["pure_white"]["supports_model"] is False
    plan = AttachmentWorkbenchPlan(
        organization_id="org", listing_image_project_id="project", session_id="session",
        listing_version_id="version", visual_direction_cn="真实比赛日商业摄影",
        updated_by="user",
    )
    module = AttachmentWorkbenchModulePlan(
        organization_id="org", workbench_plan_id="plan", module_key="stadium_scene",
        plan_summary_cn="模特穿红色球衣", prompt_cn="生成观赛场景", aspect_ratio="4:5",
        updated_by="user",
    )
    version = AttachmentWorkbenchPlanVersion(
        organization_id="org", workbench_plan_id="plan", module_plan_id="module",
        version_scope="module:stadium_scene", module_key="stadium_scene", version_number=1,
        action="manual_edit", plan_summary_cn="模特穿红色球衣", prompt_cn="生成观赛场景",
        aspect_ratio="4:5", selected_module_keys=["stadium_scene"], skill_rule_snapshot={},
        selected_model_snapshot=[], created_by="user",
    )
    understanding = AttachmentReferenceUnderstanding(
        organization_id="org", module_plan_id="module", version_number=1,
        source_snapshot_json={}, structured_json={"product": {"color": "red", "type": "football jersey"}},
        status="ready", created_by="user",
    )
    prompt = build_attachment_execution_prompt(
        module=module, plan=plan, version=version, understanding=understanding,
        grouped_references={"PRODUCT": ["product"], "MODEL": ["model"]}, aspect_ratio="4:5",
        reference_snapshot={
            "product_mode": "SINGLE",
            "execution_order": [
                {"image_index": 1, "slot_type": "PRODUCT", "asset_id": "product"},
                {"image_index": 2, "slot_type": "MODEL", "asset_id": "model"},
            ],
            "selected_models": [{"model_name": "Mason", "identity_version_id": "identity"}],
        },
    )
    assert "preserve the identity of MODEL preset: Mason" in prompt
    assert "wear the current PRODUCT garment" in prompt
    assert "never the neutral clothing visible in MODEL references" in prompt


@pytest.mark.asyncio
async def test_terminal_identity_job_failure_updates_model_workflow(identity_test_context) -> None:
    preset_id, identity_id = await _seed_published_model(
        identity_test_context,
        code="FAIL01",
        display_name="Failure Test",
        status="DRAFT",
    )
    async with identity_test_context["session_factory"]() as db:
        user = await db.scalar(select(User).where(User.account == "platform-admin"))
        job = Job(
            status="failed",
            input_json={
                "metadata": {
                    "workflow": "ai_model_identity_generation",
                    "model_preset_id": preset_id,
                    "identity_version_id": identity_id,
                },
            },
            created_by=user.id,
            updated_by=user.id,
        )
        await fail_ai_model_generation(db, job=job)
        preset = await db.get(AIModelPreset, preset_id)
        identity = await db.get(AIModelIdentityVersion, identity_id)
        assert preset.status == "FAILED"
        assert identity.status == "FAILED"
