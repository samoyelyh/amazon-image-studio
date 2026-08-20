from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.models.attachment_planning import (
    AttachmentWorkbenchModulePlan,
    AttachmentWorkbenchPlan,
    AttachmentWorkbenchPlanVersion,
)
from app.models.content import Asset, GeneratedOutput
from app.models.identity import User
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject, ListingVersion
from app.services.attachment_creative_service import parse_creative_directions
from app.services.attachment_generation_service import (
    build_attachment_execution_prompt,
    build_attachment_generation_preview,
    create_attachment_generation,
)
from app.services.attachment_result_service import adopt_attachment_creative_direction
from app.services.listing_image_module_service import STANDARD_LISTING_IMAGE_MODULES
from tests.test_attachment_generation import _seed_generation_context


UTC = timezone.utc


def test_creative_module_capabilities_are_owned_by_definitions() -> None:
    values = {str(item["code"]): bool(item.get("supports_creative")) for item in STANDARD_LISTING_IMAGE_MODULES}
    assert values == {
        "pure_white": False,
        "custom_process": False,
        "stadium_scene": True,
        "gift_scene": True,
        "detail_display": True,
        "casual_scene": True,
    }


def test_creative_parser_requires_distinct_one_to_one_directions() -> None:
    result = parse_creative_directions(
        '{"modules":[{"module_key":"gift_scene","directions":['
        '{"direction_index":1,"plan_summary_cn":"暖色礼盒俯拍","prompt_cn":"使用暖色礼盒俯拍构图"},'
        '{"direction_index":2,"plan_summary_cn":"夜景拆礼互动","prompt_cn":"使用夜景人物拆礼互动构图"}'
        ']}]}',
        {"gift_scene": 2},
    )
    assert [item["direction_index"] for item in result["gift_scene"]] == [1, 2]
    with pytest.raises(AppError) as error:
        parse_creative_directions(
            '{"modules":[{"module_key":"gift_scene","directions":['
            '{"direction_index":1,"plan_summary_cn":"同一方向","prompt_cn":"同一Prompt"},'
            '{"direction_index":2,"plan_summary_cn":"同一方向","prompt_cn":"同一Prompt"}'
            ']}]}',
            {"gift_scene": 2},
        )
    assert error.value.code == "attachment_creative.directions_not_distinct"


@pytest.mark.asyncio
async def test_creative_jobs_bind_individual_versions_and_adopt_creates_standard_lineage(identity_test_context) -> None:
    settings, user_id, project_id, session_id, version_id, plan_id, module_id = await _seed_generation_context(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        listing_session = await db.get(ListingGenerationSession, session_id)
        listing_version = await db.get(ListingVersion, version_id)
        plan = await db.get(AttachmentWorkbenchPlan, plan_id)
        module = await db.get(AttachmentWorkbenchModulePlan, module_id)

        standard_preview = await build_attachment_generation_preview(
            db, project=project, session=listing_session, version=listing_version, plan=plan,
            modules=[module], selected_module_keys=["gift_scene"],
        )
        _, _, planning_jobs, _, _ = await create_attachment_generation(
            db, settings, project=project, session=listing_session, version=listing_version, plan=plan,
            modules=[module], selected_module_keys=["gift_scene"],
            snapshot_signature=standard_preview.snapshot_signature,
            idempotency_key="creative-test-planning-job", user_id=user_id,
        )
        planning_job_id = planning_jobs[0].id
        config = dict(project.prompt_config or {})
        workbench = dict(config.get("attachment_workbench") or {})
        drafts = dict(workbench.get("modules") or {})
        drafts["gift_scene"] = {**dict(drafts.get("gift_scene") or {}), "generationMode": "creative", "imageCount": 2}
        workbench["modules"] = drafts
        config["attachment_workbench"] = workbench
        project.prompt_config = config

        creative_versions = []
        for index, (plan_text, prompt_text) in enumerate((
            ("暖色礼盒俯拍", "以暖色礼盒俯拍展示真实商品"),
            ("夜景拆礼互动", "以夜景人物拆礼互动展示真实商品"),
        ), 1):
            row = AttachmentWorkbenchPlanVersion(
                organization_id=project.organization_id, workbench_plan_id=plan.id,
                module_plan_id=module.id, version_scope=f"creative:gift_scene:{planning_job_id}",
                module_key="gift_scene", version_number=index, action="ai_creative_plan",
                generation_mode="creative", creative_direction_index=index,
                plan_summary_cn=plan_text, prompt_cn=prompt_text, aspect_ratio="4:5",
                selected_module_keys=["gift_scene"], source_version_id=(await db.scalar(select(
                    AttachmentWorkbenchPlanVersion.id,
                ).where(
                    AttachmentWorkbenchPlanVersion.module_plan_id == module.id,
                    AttachmentWorkbenchPlanVersion.version_scope == "module:gift_scene",
                ))),
                ai_job_id=planning_job_id, reference_understanding_id=module.reference_analysis_job_id,
                created_by=user_id,
            )
            db.add(row)
            creative_versions.append(row)
        await db.flush()

        preview = await build_attachment_generation_preview(
            db, project=project, session=listing_session, version=listing_version, plan=plan,
            modules=[module], selected_module_keys=["gift_scene"],
            creative_planning_job_id=planning_job_id,
        )
        assert preview.total_images == 2
        assert [item.plan_version.id for item in preview.modules[0].directions] == [item.id for item in creative_versions]
        assert len({item.execution_prompt for item in preview.modules[0].directions}) == 2
        _, batch, jobs, _, _ = await create_attachment_generation(
            db, settings, project=project, session=listing_session, version=listing_version, plan=plan,
            modules=[module], selected_module_keys=["gift_scene"],
            snapshot_signature=preview.snapshot_signature,
            idempotency_key="creative-test-generation", user_id=user_id,
            creative_planning_job_id=planning_job_id,
        )
        assert [job.input_json["metadata"]["creative_direction_index"] for job in jobs] == [1, 2]
        assert [job.input_json["metadata"]["plan_version_id"] for job in jobs] == [item.id for item in creative_versions]

        user = await db.scalar(select(User).where(User.id == user_id))
        output_asset = Asset(
            organization_id=project.organization_id, category="generated", storage_key="tests/creative-output.png",
            filename="creative-output.png", mime_type="image/png", size=128, width=100, height=100,
            sha256="9" * 64, created_by=user.id, updated_by=user.id,
        )
        db.add(output_asset)
        await db.flush()
        output = GeneratedOutput(
            organization_id=project.organization_id, asset_id=output_asset.id,
            job_id=jobs[1].id, batch_id=batch.id, sequence_number=0,
            output_type="image", module_key="gift_scene", metadata_json={},
            created_by=user_id, created_at=datetime.now(UTC),
        )
        db.add(output)
        await db.flush()
        original_creative_id = creative_versions[1].id
        await adopt_attachment_creative_direction(
            db, project=project, plan=plan, version=listing_version, modules=[module],
            output_id=output.id, expected_state_version=module.state_version, user_id=user_id,
        )
        await db.flush()
        assert module.current_version_number == 2
        assert module.source == "derived_from_creative"
        assert module.derived_from_output_id == output.id
        assert project.prompt_config["attachment_workbench"]["modules"]["gift_scene"]["generationMode"] == "standard"
        derived = await db.scalar(select(AttachmentWorkbenchPlanVersion).where(
            AttachmentWorkbenchPlanVersion.module_plan_id == module.id,
            AttachmentWorkbenchPlanVersion.version_scope == "module:gift_scene",
            AttachmentWorkbenchPlanVersion.version_number == 2,
        ))
        assert derived.generation_mode == "standard"
        assert derived.source_version_id == original_creative_id
        assert derived.derived_from_output_id == output.id
        derived_execution_prompt = build_attachment_execution_prompt(
            module=module,
            plan=plan,
            version=derived,
            understanding=standard_preview.modules[0].understanding,
            grouped_references=standard_preview.modules[0].grouped_references,
            aspect_ratio=standard_preview.modules[0].aspect_ratio,
            generation_mode="standard",
        )
        derived_heading = "CURRENT DERIVED MODULE DIRECTION (primary; overrides global style details)"
        global_heading = "GLOBAL VISUAL DIRECTION (soft context only; never erase the derived module direction above)"
        assert derived_heading in derived_execution_prompt
        assert global_heading in derived_execution_prompt
        assert derived_execution_prompt.index(derived_heading) < derived_execution_prompt.index(global_heading)
        original = await db.get(AttachmentWorkbenchPlanVersion, original_creative_id)
        assert original.generation_mode == "creative"
