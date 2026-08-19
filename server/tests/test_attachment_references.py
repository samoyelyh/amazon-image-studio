from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.models.attachment_planning import AttachmentWorkbenchModulePlan
from app.models.content import Asset
from app.models.identity import User
from app.models.listing_workflow import (
    CategorySkill,
    ListingGenerationSession,
    ListingImageProject,
    ListingVersion,
    ProductCategory,
)
from app.services.attachment_planning_service import build_attachment_module_context
from app.services.attachment_reference_service import (
    SLOT_DEFINITIONS,
    build_reference_analysis_input,
    parse_reference_understanding,
)


def _asset(org_id: str, user_id: str, suffix: str, category: str = "product_reference") -> Asset:
    return Asset(
        organization_id=org_id, category=category, storage_key=f"tests/attachment/{suffix}.png",
        filename=f"{suffix}.png", mime_type="image/png", size=128, width=100, height=100,
        sha256=(suffix * 64)[:64], created_by=user_id, updated_by=user_id,
    )


async def _project_with_assets(context: dict[str, object]) -> tuple[str, dict[str, str]]:
    async with context["session_factory"]() as db:
        user = await db.scalar(select(User).where(User.account == "first-admin"))
        category = ProductCategory(category_code="football_jersey", category_name="橄榄球衣")
        db.add(category)
        await db.flush()
        skill = CategorySkill(
            category_id=category.id, skill_name="默认Skill", skill_code="reference-test", version=1,
            analysis_prompt="analysis", listing_title_prompt="title", bullet_points_prompt="bullets",
            a_plus_prompt="a+", image_prompt_template="image", image_types_config=[], prompt_rules={},
        )
        db.add(skill)
        await db.flush()
        product = _asset(context["first_org"], user.id, "product")
        template = _asset(context["first_org"], user.id, "template", "model_template")
        template2 = _asset(context["first_org"], user.id, "template2", "model_template")
        template3 = _asset(context["first_org"], user.id, "template3", "model_template")
        db.add_all([product, template, template2, template3])
        await db.flush()
        workflow = ListingGenerationSession(
            organization_id=context["first_org"], category_id=category.id, skill_id=skill.id,
            category_skill_snapshot={"category_code": "football_jersey", "category_name": "橄榄球衣", "skill_name": "默认Skill", "skill_version": 1},
            status="confirmed", source_asset_ids=[product.id], primary_asset_id=product.id,
            listing_content={"title": {"zh": "红色测试球衣"}}, confirmed_at=datetime.now(timezone.utc),
            confirmed_by=user.id, created_by=user.id, updated_by=user.id,
        )
        db.add(workflow)
        await db.flush()
        version = ListingVersion(
            organization_id=context["first_org"], session_id=workflow.id, version_number=1,
            listing_snapshot={"title": {"zh": "红色测试球衣"}}, analysis_snapshot={"main_color": "红色"},
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
        return project.id, {
            "product": product.id, "template": template.id,
            "template2": template2.id, "template3": template3.id,
        }


def test_slot_definitions_are_module_specific() -> None:
    assert [item["slot_type"] for item in SLOT_DEFINITIONS["pure_white"]] == ["PRODUCT", "OTHER"]
    assert [item["slot_type"] for item in SLOT_DEFINITIONS["gift_scene"]] == [
        "PRODUCT", "TEMPLATE", "SCENE", "PRINT", "OTHER",
    ]


def test_reference_analysis_keeps_roles_and_priority_structured() -> None:
    _, prompt, references = build_reference_analysis_input("gift_scene", {
        "PRODUCT": ["red-product"], "TEMPLATE": ["blue-template"],
        "SCENE": [], "PRINT": ["outlined-11"], "OTHER": [],
    })
    assert references == ["red-product", "outlined-11", "blue-template"]
    assert '"slot_type": "PRODUCT"' in prompt
    assert '"slot_type": "PRINT"' in prompt


def test_reference_understanding_requires_structured_summary() -> None:
    parsed = parse_reference_understanding(
        '{"product":{"summary":"红色球衣","constraints":[]},'
        '"template":{"summary":"蓝衣仅作构图","layout_constraints":[]},'
        '"scene":{"summary":"","style_cues":[]},'
        '"print":{"summary":"描边数字11","fidelity_constraints":["不得改成普通字体"]},'
        '"other":{"summary":""},"combined_summary_cn":"商品保持红色，模板蓝衣不得继承。"}'
    )
    assert parsed["combined_summary_cn"].startswith("商品保持红色")
    with pytest.raises(AppError):
        parse_reference_understanding('{"combined_summary_cn":"缺少角色结构"}')


def test_planning_context_accepts_reference_understanding_without_flattening() -> None:
    understanding = {
        "product": {"summary": "红色球衣"},
        "template": {"summary": "蓝色衣服只参考摆放"},
        "print": {"summary": "描边数字11按高保真素材处理"},
        "combined_summary_cn": "保持红色商品，不继承模板蓝色。",
    }
    context = build_attachment_module_context(
        module_key="gift_scene", analysis_snapshot={"main_color": "红色"},
        listing_snapshot={}, skill_snapshot={}, aspect_ratio="4:5",
        operator_requirement_cn="", reference_understanding=understanding,
    )
    assert context["reference_understanding"] == understanding
    assert context["reference_priority"][0:2] == ["PRODUCT", "PRINT"]


@pytest.mark.asyncio
async def test_reference_api_inherits_product_validates_slots_limits_and_protects_asset(identity_test_context) -> None:
    project_id, assets = await _project_with_assets(identity_test_context)
    client = identity_test_context["client"]
    login = await client.post("/api/v1/auth/login", json={"account": "first-admin", "password": "correct-password"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    initial = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/references", headers=headers)
    assert initial.status_code == 200, initial.text
    assert initial.json()["product_references"][0]["asset"]["id"] == assets["product"]
    gift = next(item for item in initial.json()["modules"] if item["module_key"] == "gift_scene")
    assert [item["slot_type"] for item in gift["slot_definitions"]] == ["PRODUCT", "TEMPLATE", "SCENE", "PRINT", "OTHER"]

    promoted = await client.put(
        f"/api/v1/attachment-workbench/projects/{project_id}/product-references/front",
        headers=headers,
        json={
            "asset_id": assets["product"], "source_asset_id": assets["product"],
            "view_role": "front", "transform_metadata": {"source": "same-asset-test"},
        },
    )
    assert promoted.status_code == 200, promoted.text
    reloaded = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/references", headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    assert len([item for item in reloaded.json()["product_references"] if item["view_role"] == "front"]) == 1

    added = await client.post(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/gift_scene/references",
        headers=headers, json={"slot_type": "TEMPLATE", "asset_id": assets["template"], "metadata": {}},
    )
    assert added.status_code == 200, added.text
    gift = next(item for item in added.json()["modules"] if item["module_key"] == "gift_scene")
    assert gift["reference_context_dirty"] is True
    assert gift["references"][0]["asset"]["id"] == assets["template"]

    unsupported = await client.post(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/pure_white/references",
        headers=headers, json={"slot_type": "TEMPLATE", "asset_id": assets["template"], "metadata": {}},
    )
    assert unsupported.status_code == 422

    for key in ("template2",):
        response = await client.post(
            f"/api/v1/attachment-workbench/projects/{project_id}/modules/gift_scene/references",
            headers=headers, json={"slot_type": "TEMPLATE", "asset_id": assets[key], "metadata": {}},
        )
        assert response.status_code == 200
    limited = await client.post(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/gift_scene/references",
        headers=headers, json={"slot_type": "TEMPLATE", "asset_id": assets["template3"], "metadata": {}},
    )
    assert limited.status_code == 422

    protected = await client.delete(f"/api/v1/assets/{assets['template']}", headers=headers)
    assert protected.status_code == 409

    second_login = await client.post("/api/v1/auth/login", json={"account": "second-admin", "password": "second-password"})
    isolated = await client.get(
        f"/api/v1/attachment-workbench/projects/{project_id}/references",
        headers={"Authorization": f"Bearer {second_login.json()['access_token']}"},
    )
    assert isolated.status_code == 404
