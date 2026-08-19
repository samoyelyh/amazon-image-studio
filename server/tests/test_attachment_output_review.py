from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.models.attachment_planning import AttachmentModuleResultState, AttachmentWorkbenchModulePlan, AttachmentWorkbenchPlan
from app.models.content import Asset, GeneratedOutput
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject, ListingVersion
from app.models.tasks import Job
from app.services.attachment_generation_service import build_attachment_generation_preview, create_attachment_generation
from app.services.attachment_result_service import (
    discard_attachment_results,
    ensure_attachment_result_states,
    reset_attachment_module,
    result_state_response,
    retry_attachment_job,
    review_attachment_output,
    set_attachment_final,
)
from tests.test_attachment_generation import _seed_generation_context


UTC = timezone.utc


async def _seed_outputs(context):
    settings, user_id, project_id, session_id, version_id, plan_id, module_id = await _seed_generation_context(context)
    async with context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        session = await db.get(ListingGenerationSession, session_id)
        version = await db.get(ListingVersion, version_id)
        plan = await db.get(AttachmentWorkbenchPlan, plan_id)
        module = await db.get(AttachmentWorkbenchModulePlan, module_id)
        preview = await build_attachment_generation_preview(
            db, project=project, session=session, version=version, plan=plan,
            modules=[module], selected_module_keys=["gift_scene"],
        )
        _, batch, jobs, _, _ = await create_attachment_generation(
            db, settings, project=project, session=session, version=version, plan=plan,
            modules=[module], selected_module_keys=["gift_scene"], snapshot_signature=preview.snapshot_signature,
            idempotency_key="attachment-output-review-seed", user_id=user_id,
        )
        asset = await db.scalar(select(Asset).where(Asset.organization_id == project.organization_id))
        outputs = []
        for index, job in enumerate(jobs):
            output = GeneratedOutput(
                organization_id=project.organization_id, project_id=session.project_id,
                asset_id=asset.id, job_id=job.id, batch_id=batch.id, sequence_number=index,
                output_type="listing_output", module_key="gift_scene", metadata_json={"slot_index": index + 1},
                created_by=user_id, created_at=datetime.now(UTC),
            )
            db.add(output); outputs.append(output)
        await ensure_attachment_result_states(db, project=project, module_keys=["gift_scene"], user_id=user_id)
        await db.commit()
        return settings, user_id, project_id, module_id, [item.id for item in outputs]


@pytest.mark.asyncio
async def test_output_review_and_final_are_output_scoped(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        first = await set_attachment_final(db, project=project, output_id=output_ids[0], user_id=user_id)
        assert first.review_status == "approved" and first.is_final is True
        second = await review_attachment_output(
            db, project=project, output_id=output_ids[1], status="approved",
            expected_review_state_version=0, clear_final_if_rejected=False, user_id=user_id,
        )
        assert second.is_final is False
        state = await db.scalar(select(AttachmentModuleResultState).where(
            AttachmentModuleResultState.listing_image_project_id == project_id,
            AttachmentModuleResultState.module_key == "gift_scene",
        ))
        assert state.current_final_output_id == output_ids[0]
        second = await set_attachment_final(db, project=project, output_id=output_ids[1], user_id=user_id)
        assert second.is_final is True
        first_row = await db.get(GeneratedOutput, output_ids[0])
        assert first_row.review_status == "approved"
        assert state.current_final_output_id == output_ids[1]


@pytest.mark.asyncio
async def test_rejecting_final_requires_explicit_clear(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        await set_attachment_final(db, project=project, output_id=output_ids[0], user_id=user_id)
        with pytest.raises(AppError) as error:
            await review_attachment_output(
                db, project=project, output_id=output_ids[0], status="rejected",
                expected_review_state_version=1, clear_final_if_rejected=False, user_id=user_id,
            )
        assert error.value.code == "attachment_result.final_reject_confirmation_required"
        result = await review_attachment_output(
            db, project=project, output_id=output_ids[0], status="rejected",
            expected_review_state_version=1, clear_final_if_rejected=True, user_id=user_id,
        )
        assert result.review_status == "rejected" and result.is_final is False


@pytest.mark.asyncio
async def test_discard_is_non_destructive_and_reset_preserves_history(identity_test_context) -> None:
    _, user_id, project_id, module_id, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        plan = await db.scalar(select(AttachmentWorkbenchPlan).where(AttachmentWorkbenchPlan.listing_image_project_id == project_id))
        module = await db.get(AttachmentWorkbenchModulePlan, module_id)
        await set_attachment_final(db, project=project, output_id=output_ids[0], user_id=user_id)
        changed = await discard_attachment_results(db, project=project, module_keys=["gift_scene"], user_id=user_id)
        assert changed == 2
        assert await db.scalar(select(func.count()).select_from(GeneratedOutput).where(GeneratedOutput.id.in_(output_ids))) == 2
        summary = await result_state_response(db, project=project, user_id=user_id)
        gift = next(item for item in summary.modules if item.module_key == "gift_scene")
        assert gift.visible_output_count == 0 and gift.history_output_count == 2
        await reset_attachment_module(db, project=project, plan=plan, module=module, user_id=user_id)
        assert module.prompt_cn == "" and module.plan_summary_cn == "" and module.current_version_number == 0
        assert await db.scalar(select(func.count()).select_from(GeneratedOutput).where(GeneratedOutput.id.in_(output_ids))) == 2


@pytest.mark.asyncio
async def test_failed_slot_retry_uses_original_job_snapshot(identity_test_context) -> None:
    settings, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        output = await db.get(GeneratedOutput, output_ids[1])
        source_job = await db.get(Job, output.job_id)
        source_job.status = "failed"
        original_prompt = source_job.input_json["prompt"]
        original_references = list(source_job.input_json["reference_asset_ids"])
        original_slot = source_job.input_json["metadata"]["slot_index"]

        _, retry_jobs, retry_group, created = await retry_attachment_job(
            db,
            settings,
            project=project,
            source_job_id=source_job.id,
            idempotency_key="attachment-output-retry-001",
            user_id=user_id,
        )

        assert created is True
        assert len(retry_jobs) == 1
        assert retry_group.source_task_group_id is not None
        assert retry_jobs[0].input_json["prompt"] == original_prompt
        assert retry_jobs[0].input_json["reference_asset_ids"] == original_references
        assert retry_jobs[0].input_json["metadata"]["slot_index"] == original_slot
        assert retry_jobs[0].input_json["metadata"]["source_job_id"] == source_job.id
