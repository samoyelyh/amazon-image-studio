from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.models.attachment_planning import (
    AttachmentModuleReference,
    AttachmentProductReferenceGroup,
    AttachmentProductReferenceItem,
    AttachmentReferenceUnderstanding,
    AttachmentWorkbenchModulePlan,
    AttachmentWorkbenchPlan,
    AttachmentWorkbenchPlanVersion,
)
from app.models.content import Asset
from app.models.identity import User
from app.models.listing_workflow import CategorySkill, ListingGenerationSession, ListingImageProject, ListingVersion, ProductCategory
from app.models.tasks import ModelCapability, OperationResourcePool, Provider, ProviderModel, ResourcePool, ResourcePoolKey
from app.schemas.tasks import BatchJobItemRequest, JobBatchSubmitRequest
from app.services.attachment_generation_service import (
    build_attachment_execution_prompt,
    build_attachment_generation_preview,
    create_attachment_generation,
)
from app.services.attachment_product_composition_service import (
    add_secondary_product,
    current_composition_version,
    ensure_product_composition,
    set_product_mode,
)
from app.services.attachment_reference_service import effective_reference_snapshot
from app.services.resource_pool_service import create_api_key


UTC = timezone.utc


def _batch_items(count: int, *, attachment: bool) -> list[BatchJobItemRequest]:
    workflow = "attachment_workbench_generation" if attachment else "listing_image"
    return [BatchJobItemRequest(
        client_item_id=f"item-{index}", prompt="prompt", metadata={"workflow": workflow},
    ) for index in range(count)]


def test_attachment_batch_allows_six_modules_with_four_candidates() -> None:
    payload = JobBatchSubmitRequest(
        name="attachment", workspace_type="listing", operation_code="listing.generate",
        capability="image_edit", model_code="image-2", idempotency_key="attachment-batch-24",
        items=_batch_items(24, attachment=True),
    )
    assert len(payload.items) == 24
    with pytest.raises(ValueError):
        JobBatchSubmitRequest(
            name="legacy", workspace_type="listing", operation_code="listing.generate",
            capability="image_edit", model_code="image-2", idempotency_key="legacy-batch-11",
            items=_batch_items(11, attachment=False),
        )


def test_execution_prompt_maps_reference_roles_without_template_product_leakage() -> None:
    module = AttachmentWorkbenchModulePlan(
        organization_id="org", workbench_plan_id="plan", module_key="gift_scene",
        plan_summary_cn="礼品构图", prompt_cn="保留真实红色球衣", aspect_ratio="4:5", updated_by="user",
    )
    plan = AttachmentWorkbenchPlan(
        organization_id="org", listing_image_project_id="project", session_id="session",
        listing_version_id="version", visual_direction_cn="统一商业光线", created_by="user", updated_by="user",
    )
    version = AttachmentWorkbenchPlanVersion(
        organization_id="org", workbench_plan_id="plan", module_plan_id="module",
        version_scope="module:gift_scene", module_key="gift_scene", version_number=2,
        action="manual_edit", plan_summary_cn="礼品构图", prompt_cn="只使用商品真实设计",
        created_by="user",
    )
    understanding = AttachmentReferenceUnderstanding(
        organization_id="org", module_plan_id="module", version_number=3, status="ready",
        structured_json={"combined_summary_cn": "模板蓝色衣服不得继承"}, source_snapshot_json={}, created_by="user",
    )
    prompt = build_attachment_execution_prompt(
        module=module, plan=plan, version=version, understanding=understanding,
        grouped_references={
            "PRODUCT": ["product"], "PRINT": ["print"], "TEMPLATE": ["template"],
            "SCENE": ["scene"], "OTHER": [],
        }, aspect_ratio="4:5",
    )
    assert prompt.index("Image 1 = PRODUCT") < prompt.index("Image 2 = PRINT") < prompt.index("Image 3 = TEMPLATE")
    assert "never inherit the template's old product design" in prompt
    assert "Required aspect ratio: 4:5" in prompt


async def _seed_generation_context(context: dict[str, object]):
    settings = Settings(_env_file=None)
    async with context["session_factory"]() as db:
        user = await db.scalar(select(User).where(User.account == "first-admin"))
        category = ProductCategory(category_code="attachment_generation", category_name="附图生成测试")
        db.add(category)
        await db.flush()
        skill = CategorySkill(
            category_id=category.id, skill_name="默认Skill", skill_code="attachment-generation", version=1,
            analysis_prompt="analysis", listing_title_prompt="title", bullet_points_prompt="bullets",
            a_plus_prompt="a+", image_prompt_template="image", image_types_config=[], prompt_rules={},
        )
        db.add(skill)
        await db.flush()
        product = Asset(
            organization_id=context["first_org"], category="product_reference", storage_key="tests/product.png",
            filename="product.png", mime_type="image/png", size=128, width=100, height=100,
            sha256="1" * 64, created_by=user.id, updated_by=user.id,
        )
        template = Asset(
            organization_id=context["first_org"], category="model_template", storage_key="tests/template.png",
            filename="template.png", mime_type="image/png", size=128, width=100, height=100,
            sha256="2" * 64, created_by=user.id, updated_by=user.id,
        )
        db.add_all([product, template])
        await db.flush()
        snapshot = {
            "category_id": category.id, "category_code": "football_jersey", "category_name": "橄榄球衣",
            "skill_name": "默认Skill", "skill_version": 1,
        }
        listing_session = ListingGenerationSession(
            organization_id=context["first_org"], category_id=category.id, skill_id=skill.id,
            category_skill_snapshot=snapshot, status="confirmed", source_asset_ids=[product.id],
            primary_asset_id=product.id, listing_content={"title": {"zh": "测试球衣"}},
            confirmed_at=datetime.now(UTC), confirmed_by=user.id, created_by=user.id, updated_by=user.id,
        )
        db.add(listing_session)
        await db.flush()
        listing_version = ListingVersion(
            organization_id=context["first_org"], session_id=listing_session.id, version_number=1,
            listing_snapshot={"title": {"zh": "测试球衣"}}, analysis_snapshot={"main_color": "红色"},
            category_skill_snapshot=snapshot, confirmed_at=datetime.now(UTC), confirmed_by=user.id, created_by=user.id,
        )
        db.add(listing_version)
        await db.flush()
        listing_session.current_listing_version_id = listing_version.id
        project = ListingImageProject(
            organization_id=context["first_org"], session_id=listing_session.id,
            listing_version_id=listing_version.id, status="editing",
            prompt_config={"attachment_workbench": {"modules": {"gift_scene": {
                "selected": True, "aspectRatio": "4:5", "imageCount": 2, "generationMode": "standard",
            }}}}, created_by=user.id, updated_by=user.id,
        )
        db.add(project)
        await db.flush()
        plan = AttachmentWorkbenchPlan(
            organization_id=context["first_org"], listing_image_project_id=project.id,
            session_id=listing_session.id, listing_version_id=listing_version.id,
            visual_direction_cn="统一真实商业光线", visual_direction_version=1,
            created_by=user.id, updated_by=user.id,
        )
        db.add(plan)
        await db.flush()
        module = AttachmentWorkbenchModulePlan(
            organization_id=context["first_org"], workbench_plan_id=plan.id, module_key="gift_scene",
            plan_summary_cn="温馨礼品构图", prompt_cn="保留商品真实设计并置于礼盒场景",
            aspect_ratio="4:5", current_version_number=1, status="ready",
            reference_context_dirty=False, reference_state_version=1, updated_by=user.id,
        )
        db.add(module)
        await db.flush()
        group = AttachmentProductReferenceGroup(
            organization_id=context["first_org"], workbench_plan_id=plan.id,
            state_version=1, created_by=user.id, updated_by=user.id,
        )
        db.add(group)
        await db.flush()
        db.add(AttachmentProductReferenceItem(
            organization_id=context["first_org"], product_group_id=group.id, asset_id=product.id,
            view_role="front", sort_order=0, source="session", created_by=user.id, updated_by=user.id,
        ))
        roles = {"PRODUCT": [product.id], "PRINT": [], "TEMPLATE": [], "SCENE": [], "OTHER": []}
        understanding = AttachmentReferenceUnderstanding(
            organization_id=context["first_org"], module_plan_id=module.id, version_number=1,
            status="ready", structured_json={"combined_summary_cn": "保持商品真实"},
            source_snapshot_json={"module_key": "gift_scene", "reference_state_version": 1,
                                  "roles": roles, "priority": ["PRODUCT", "PRINT", "TEMPLATE", "SCENE", "OTHER"]},
            created_by=user.id,
        )
        db.add(understanding)
        await db.flush()
        plan_version = AttachmentWorkbenchPlanVersion(
            organization_id=context["first_org"], workbench_plan_id=plan.id, module_plan_id=module.id,
            version_scope="module:gift_scene", module_key="gift_scene", version_number=1,
            action="manual_edit", plan_summary_cn=module.plan_summary_cn, prompt_cn=module.prompt_cn,
            aspect_ratio="4:5", selected_module_keys=["gift_scene"],
            reference_understanding_id=understanding.id, created_by=user.id,
        )
        db.add(plan_version)

        provider = Provider(
            code="attachment-provider", name="Attachment Provider", provider_type="openai_compatible",
            base_url="https://provider.test/v1", config_json={},
        )
        db.add(provider)
        await db.flush()
        model = ProviderModel(
            provider_id=provider.id, code="attachment-image-2", upstream_model="image-2",
            name="Attachment Image 2", config_json={
                "supported_edit_aspect_ratios": ["1:1", "3:4", "4:5"],
                "verified_edit_output_sizes": {"1:1": "1024x1024", "3:4": "1024x1536", "4:5": "1024x1280"},
            },
        )
        db.add(model)
        await db.flush()
        db.add(ModelCapability(model_id=model.id, capability="image_edit"))
        pool = ResourcePool(model_id=model.id, code="attachment-pool", name="Attachment Pool")
        db.add(pool)
        await db.flush()
        db.add(OperationResourcePool(
            operation_code="listing.generate", resource_pool_id=pool.id,
            required_capability="image_edit", priority=1,
        ))
        key = create_api_key(
            settings, provider_id=provider.id, label="Attachment test key", secret="attachment-test-secret",
            organization_id=None, max_concurrency=12, rpm_limit=None, daily_limit=None, user_id=None,
        )
        db.add(key)
        await db.flush()
        db.add(ResourcePoolKey(resource_pool_id=pool.id, api_key_id=key.id, priority=1))
        await db.commit()
        return settings, user.id, project.id, listing_session.id, listing_version.id, plan.id, module.id


@pytest.mark.asyncio
async def test_generation_snapshots_versions_roles_slots_and_idempotency(identity_test_context) -> None:
    settings, user_id, project_id, session_id, version_id, plan_id, module_id = await _seed_generation_context(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        listing_session = await db.get(ListingGenerationSession, session_id)
        version = await db.get(ListingVersion, version_id)
        plan = await db.get(AttachmentWorkbenchPlan, plan_id)
        module = await db.get(AttachmentWorkbenchModulePlan, module_id)
        preview = await build_attachment_generation_preview(
            db, project=project, session=listing_session, version=version, plan=plan,
            modules=[module], selected_module_keys=["gift_scene"],
        )
        assert preview.total_images == 2
        assert preview.modules[0].aspect_ratio == "4:5"
        assert preview.modules[0].width == 1536 and preview.modules[0].height == 1920

        created = await create_attachment_generation(
            db, settings, project=project, session=listing_session, version=version, plan=plan,
            modules=[module], selected_module_keys=["gift_scene"], snapshot_signature=preview.snapshot_signature,
            idempotency_key="attachment-generation-idempotent", user_id=user_id,
        )
        _, batch, jobs, group, was_created = created
        await db.commit()
        assert was_created is True
        assert batch.total_jobs == 2
        assert [job.input_json["metadata"]["slot_index"] for job in jobs] == [1, 2]
        assert all(job.input_json["metadata"]["plan_version_id"] for job in jobs)
        assert group.input_asset_snapshot["workflow"] == "attachment_workbench_generation"

        repeated = await create_attachment_generation(
            db, settings, project=project, session=listing_session, version=version, plan=plan,
            modules=[module], selected_module_keys=["gift_scene"], snapshot_signature=preview.snapshot_signature,
            idempotency_key="attachment-generation-idempotent", user_id=user_id,
        )
        assert repeated[-1] is False
        assert repeated[1].id == batch.id

        with pytest.raises(AppError) as error:
            await create_attachment_generation(
                db, settings, project=project, session=listing_session, version=version, plan=plan,
                modules=[module], selected_module_keys=["gift_scene"], snapshot_signature="0" * 64,
                idempotency_key="attachment-generation-stale", user_id=user_id,
            )
        assert error.value.code == "attachment_generation.snapshot_changed"


@pytest.mark.asyncio
async def test_multi_product_generation_uses_stable_identity_order_and_snapshot(identity_test_context) -> None:
    settings, user_id, project_id, session_id, version_id, plan_id, module_id = await _seed_generation_context(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        listing_session = await db.get(ListingGenerationSession, session_id)
        version = await db.get(ListingVersion, version_id)
        plan = await db.get(AttachmentWorkbenchPlan, plan_id)
        module = await db.get(AttachmentWorkbenchModulePlan, module_id)
        user = await db.get(User, user_id)
        secondary_asset = Asset(
            organization_id=project.organization_id, category="product_reference",
            storage_key="tests/secondary.png", filename="secondary.png", mime_type="image/png",
            size=128, width=100, height=100, sha256="3" * 64,
            created_by=user.id, updated_by=user.id,
        )
        print_asset = Asset(
            organization_id=project.organization_id, category="print_asset",
            storage_key="tests/primary-print.png", filename="primary-print.png", mime_type="image/png",
            size=128, width=100, height=100, sha256="4" * 64,
            created_by=user.id, updated_by=user.id,
        )
        template_asset = Asset(
            organization_id=project.organization_id, category="model_template",
            storage_key="tests/group-template.png", filename="group-template.png", mime_type="image/png",
            size=128, width=100, height=100, sha256="5" * 64,
            created_by=user.id, updated_by=user.id,
        )
        db.add_all([secondary_asset, print_asset, template_asset])
        await db.flush()
        secondary_session = ListingGenerationSession(
            organization_id=project.organization_id, category_id=listing_session.category_id,
            skill_id=listing_session.skill_id, category_skill_snapshot=dict(listing_session.category_skill_snapshot or {}),
            status="confirmed", primary_asset_id=secondary_asset.id, source_asset_ids=[secondary_asset.id],
            listing_content={"title": {"zh": "蓝色27号球衣"}}, confirmed_at=datetime.now(UTC),
            confirmed_by=user.id, created_by=user.id, updated_by=user.id,
        )
        db.add(secondary_session)
        await db.flush()
        product_references = list((await db.scalars(select(AttachmentProductReferenceItem).where(
            AttachmentProductReferenceItem.product_group_id == select(AttachmentProductReferenceGroup.id).where(
                AttachmentProductReferenceGroup.workbench_plan_id == plan.id,
            ).scalar_subquery(),
        ))).all())
        composition = await ensure_product_composition(
            db, module=module, session=listing_session,
            product_references=product_references, user_id=user.id,
        )
        await set_product_mode(
            db, module=module, mode="MULTI", expected_state_version=composition.state_version,
            user_id=user.id, supports_multi_product=True,
        )
        await add_secondary_product(
            db, module=module, source_session_id=secondary_session.id,
            expected_state_version=composition.state_version, user_id=user.id,
        )
        db.add_all([
            AttachmentModuleReference(
                organization_id=project.organization_id, module_plan_id=module.id,
                slot_type="PRINT", asset_id=print_asset.id, sort_order=0,
                metadata_json={}, created_by=user.id, updated_by=user.id,
            ),
            AttachmentModuleReference(
                organization_id=project.organization_id, module_plan_id=module.id,
                slot_type="TEMPLATE", asset_id=template_asset.id, sort_order=0,
                metadata_json={}, created_by=user.id, updated_by=user.id,
            ),
        ])
        await db.flush()
        grouped, reference_snapshot = await effective_reference_snapshot(db, plan=plan, module=module)
        execution_ids = [item["asset_id"] for item in reference_snapshot["execution_order"]]
        primary_id = product_references[0].asset_id
        assert execution_ids == [primary_id, print_asset.id, secondary_asset.id, template_asset.id]
        assert reference_snapshot["product_count"] == 2
        assert reference_snapshot["model_count"] == 2

        composition_version = await current_composition_version(db, composition)
        understanding = await db.scalar(select(AttachmentReferenceUnderstanding).where(
            AttachmentReferenceUnderstanding.module_plan_id == module.id,
        ))
        understanding.structured_json = {
            "product": {"summary": "两件独立球衣", "constraints": []},
            "products": [
                {"product_role": "PRIMARY", "summary": "红色11号球衣"},
                {"product_role": "SECONDARY", "summary": "蓝色27号球衣"},
            ],
            "combined_summary_cn": "两件商品身份独立",
        }
        understanding.source_snapshot_json = reference_snapshot
        understanding.product_composition_version_id = composition_version.id
        module.reference_context_dirty = False
        plan_version = await db.scalar(select(AttachmentWorkbenchPlanVersion).where(
            AttachmentWorkbenchPlanVersion.module_plan_id == module.id,
            AttachmentWorkbenchPlanVersion.version_scope == "module:gift_scene",
        ))
        plan_version.product_composition_version_id = composition_version.id
        project.prompt_config = {"attachment_workbench": {"modules": {"gift_scene": {
            "selected": True, "aspectRatio": "4:5", "imageCount": 1, "generationMode": "standard",
        }}}}
        await db.flush()

        preview = await build_attachment_generation_preview(
            db, project=project, session=listing_session, version=version, plan=plan,
            modules=[module], selected_module_keys=["gift_scene"],
        )
        prepared = preview.modules[0]
        assert prepared.reference_snapshot["product_mode"] == "MULTI"
        assert "Model A -> PRIMARY" in prepared.execution_prompt
        assert "Model B -> SECONDARY" in prepared.execution_prompt
        assert "Never transfer or mix" in prepared.execution_prompt

        _, batch, jobs, group, created = await create_attachment_generation(
            db, settings, project=project, session=listing_session, version=version, plan=plan,
            modules=[module], selected_module_keys=["gift_scene"],
            snapshot_signature=preview.snapshot_signature,
            idempotency_key="attachment-multi-generation", user_id=user.id,
        )
        assert created is True and batch.total_jobs == 1
        assert jobs[0].input_json["reference_asset_ids"] == execution_ids
        metadata = jobs[0].input_json["metadata"]
        assert metadata["product_mode"] == "MULTI"
        assert metadata["product_count"] == 2
        assert metadata["reference_execution_order"] == reference_snapshot["execution_order"]
        assert group.input_asset_snapshot["product_mode"] == "MULTI"

        third_asset = Asset(
            organization_id=project.organization_id, category="product_reference",
            storage_key="tests/third.png", filename="third.png", mime_type="image/png",
            size=128, width=100, height=100, sha256="6" * 64,
            created_by=user.id, updated_by=user.id,
        )
        db.add(third_asset); await db.flush()
        third_session = ListingGenerationSession(
            organization_id=project.organization_id, category_id=listing_session.category_id,
            skill_id=listing_session.skill_id, category_skill_snapshot=dict(listing_session.category_skill_snapshot or {}),
            status="confirmed", primary_asset_id=third_asset.id, source_asset_ids=[third_asset.id],
            listing_content={"title": {"zh": "白色08号球衣"}}, confirmed_at=datetime.now(UTC),
            confirmed_by=user.id, created_by=user.id, updated_by=user.id,
        )
        db.add(third_session); await db.flush()
        await add_secondary_product(
            db, module=module, source_session_id=third_session.id,
            expected_state_version=composition.state_version, user_id=user.id,
        )
        _, latest_snapshot = await effective_reference_snapshot(db, plan=plan, module=module)
        latest_version = await current_composition_version(db, composition)
        understanding.source_snapshot_json = latest_snapshot
        understanding.product_composition_version_id = latest_version.id
        module.reference_context_dirty = False
        with pytest.raises(AppError) as stale_error:
            await build_attachment_generation_preview(
                db, project=project, session=listing_session, version=version, plan=plan,
                modules=[module], selected_module_keys=["gift_scene"],
            )
        assert stale_error.value.code == "attachment_generation.composition_stale"
