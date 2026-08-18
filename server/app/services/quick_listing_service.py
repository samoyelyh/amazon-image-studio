from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.listing_workflow import (
    ImagePromptItem,
    ListingGenerationSession,
    ListingImageProject,
    ListingImageTaskGroup,
    ListingVersion,
    ProductAnalysisResult,
)
from app.models.tasks import Job
from app.schemas.tasks import BatchJobItemRequest, JobBatchSubmitRequest
from app.services.category_listing_service import (
    build_listing_version_image_prompts,
    listing_english_text,
    normalize_bilingual_listing_content,
    reconcile_listing_session,
    resolve_bound_model_code,
)
from app.services.listing_image_task_group_service import build_input_asset_snapshot, create_group_for_batch
from app.services.task_service import dispatch_jobs, due_jobs, submit_batch
from app.services.smart_image_variation_service import create_quick_default_variation_group


UTC = timezone.utc


def quick_job_metadata(job: Job) -> dict[str, object] | None:
    metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
    if not isinstance(metadata, dict) or metadata.get("workflow") != "category_listing_analysis" or not metadata.get("quick_mode"):
        return None
    return metadata


async def mark_quick_generation_failed(
    db: AsyncSession, *, planning_job: Job, message: str,
) -> None:
    metadata = quick_job_metadata(planning_job)
    session_id = str(metadata.get("listing_session_id") or "") if metadata else ""
    if not session_id:
        return
    workflow = await db.get(ListingGenerationSession, session_id)
    if workflow and workflow.image_batch_id is None:
        workflow.status = "failed"
        workflow.error_message = message[:1000]
        workflow.updated_by = planning_job.created_by
        await db.commit()


async def continue_quick_listing_generation(
    db: AsyncSession, settings: Settings, *, planning_job: Job,
) -> ListingImageTaskGroup | None:
    """Continue a quick Listing after its existing analysis Job succeeds.

    This function only composes existing persistent models. Repeated calls are
    safe: the planning Job, image batch and task group all use stable keys.
    """
    metadata = quick_job_metadata(planning_job)
    if metadata is None:
        return None
    session_id = str(metadata.get("listing_session_id") or "")
    if not session_id:
        raise AppError("listing.quick_session_missing", "快速生成任务缺少 Listing Session。", 409)
    workflow = await db.scalar(
        select(ListingGenerationSession)
        .where(ListingGenerationSession.id == session_id, ListingGenerationSession.organization_id == planning_job.organization_id)
        .with_for_update()
    )
    if workflow is None:
        raise AppError("listing.session_not_found", "快速生成对应的 Listing Session 不存在。", 404)
    existing_project = await db.scalar(select(ListingImageProject).where(ListingImageProject.session_id == workflow.id))
    if workflow.image_batch_id and existing_project:
        return await db.scalar(select(ListingImageTaskGroup).where(
            ListingImageTaskGroup.listing_image_project_id == existing_project.id,
            ListingImageTaskGroup.job_batch_id == workflow.image_batch_id,
        ))
    if planning_job.status == "failed":
        workflow.status = "analysis_failed"
        workflow.error_message = planning_job.error_message or "AI 商品分析失败。"
        await db.commit()
        return None
    if planning_job.status != "succeeded":
        return None

    await reconcile_listing_session(db, workflow)
    if workflow.analysis_result_id is None:
        return None
    analysis = await db.get(ProductAnalysisResult, workflow.analysis_result_id)
    listing_content = normalize_bilingual_listing_content(workflow.listing_content or analysis.listing_content or {})
    bullets = listing_content.get("bullet_points")
    if not listing_english_text(listing_content, "title") or not isinstance(bullets, list) or not any(
        isinstance(item, dict) and str(item.get("en") or "").strip() for item in bullets
    ):
        raise AppError("listing.content_incomplete", "默认 Skill 未能生成完整的 Listing 标题和五点描述。", 422)

    now = datetime.now(UTC)
    version = await db.get(ListingVersion, workflow.current_listing_version_id) if workflow.current_listing_version_id else None
    if version is None:
        version = ListingVersion(
            organization_id=workflow.organization_id,
            session_id=workflow.id,
            version_number=1,
            source_listing_version_id=None,
            listing_snapshot=listing_content,
            analysis_snapshot=dict(analysis.structured_attributes or {}),
            category_skill_snapshot=dict(workflow.category_skill_snapshot or {}),
            confirmed_at=now,
            confirmed_by=planning_job.created_by,
            created_by=planning_job.created_by,
        )
        db.add(version)
        await db.flush()
        workflow.current_listing_version_id = version.id
    workflow.listing_content = listing_content
    workflow.status = "confirmed"
    workflow.confirmed_at = workflow.confirmed_at or now
    workflow.confirmed_by = workflow.confirmed_by or planning_job.created_by
    workflow.current_step = 4
    workflow.state_version += 1
    workflow.last_saved_at = now
    workflow.updated_by = planning_job.created_by
    analysis.listing_content = listing_content
    analysis.updated_by = planning_job.created_by

    project = existing_project
    if project is None:
        project = ListingImageProject(
            organization_id=workflow.organization_id,
            session_id=workflow.id,
            listing_version_id=version.id,
            status="editing",
            selected_template=None,
            prompt_config={},
            task_count=0,
            generated_asset_ids=[],
            created_by=planning_job.created_by,
            updated_by=planning_job.created_by,
        )
        db.add(project)
        await db.flush()
    else:
        project.listing_version_id = version.id

    selected = [str(item) for item in (metadata.get("quick_selected_image_types") or [])]
    prompts = build_listing_version_image_prompts(version, selected or None)
    selected = list(prompts)
    project.prompt_config = {**dict(project.prompt_config or {}), "selected_items": selected, "prompts": prompts}
    project.updated_by = planning_job.created_by

    existing_prompt_codes = set((await db.scalars(select(ImagePromptItem.item_code).where(
        ImagePromptItem.organization_id == workflow.organization_id,
        ImagePromptItem.project_type == "listing_image",
        ImagePromptItem.project_id == project.id,
        ImagePromptItem.item_code.in_(selected),
    ))).all())
    for image_type, prompt in prompts.items():
        if image_type in existing_prompt_codes:
            continue
        db.add(ImagePromptItem(
            organization_id=workflow.organization_id,
            project_type="listing_image",
            project_id=project.id,
            session_id=workflow.id,
            category_id=workflow.category_id,
            skill_id=workflow.skill_id,
            item_code=image_type,
            image_type=image_type,
            original_english_prompt=prompt,
            chinese_editing_instruction="",
            optimized_english_prompt=prompt,
            status="draft",
            current_version_number=0,
            created_by=planning_job.created_by,
            updated_by=planning_job.created_by,
            state_version=0,
            last_saved_at=now,
        ))

    delivery = metadata.get("quick_delivery") if isinstance(metadata.get("quick_delivery"), dict) else {}
    model_code = await resolve_bound_model_code(
        db,
        organization_id=workflow.organization_id,
        operation_code="listing.generate",
        capability="image_edit",
    )
    batch, jobs, created = await submit_batch(
        db,
        settings,
        organization_id=workflow.organization_id,
        user_id=planning_job.created_by,
        payload=JobBatchSubmitRequest(
            name=f"{version.category_skill_snapshot.get('category_name') or '品类'} Listing 快速生成",
            workspace_type="listing",
            operation_code="listing.generate",
            capability="image_edit",
            model_code=model_code,
            idempotency_key=str(metadata.get("quick_image_idempotency_key") or f"quick-images:{planning_job.id}"),
            project_id=workflow.project_id,
            concurrency=min(int(delivery.get("concurrency") or 3), len(prompts)),
            items=[BatchJobItemRequest(
                client_item_id=f"{project.id}:{image_type}:v{version.version_number}",
                prompt=prompt,
                reference_asset_ids=list(workflow.source_asset_ids or []),
                size=str(delivery.get("size") or "2048x2048"),
                aspect_ratio=str(delivery.get("aspect_ratio") or "1:1"),
                requested_width=int(delivery.get("requested_width") or 2048),
                requested_height=int(delivery.get("requested_height") or 2048),
                quality=str(delivery.get("quality") or "high"),
                output_format=str(delivery.get("output_format") or "png"),
                metadata={
                    "workflow": "listing_image",
                    "quick_mode": True,
                    "output_project_id": project.id,
                    "listing_session_id": workflow.id,
                    "listing_version_id": version.id,
                    "listing_version_number": version.version_number,
                    "item_code": image_type,
                },
            ) for image_type, prompt in prompts.items()],
        ),
    )
    snapshot = await build_input_asset_snapshot(
        db,
        organization_id=workflow.organization_id,
        product_asset_ids=list(workflow.source_asset_ids or []),
        reference_asset_ids=[],
        template_asset_ids=[],
        primary_asset_id=workflow.primary_asset_id,
    )
    group = await create_group_for_batch(
        db,
        project=project,
        batch=batch,
        version=version,
        selected_image_types=selected,
        product_asset_ids=list(workflow.source_asset_ids or []),
        reference_asset_ids=[],
        template_asset_ids=[],
        input_asset_snapshot=snapshot,
        user_id=planning_job.created_by,
    )
    for job in jobs:
        job_metadata = job.input_json.get("metadata")
        job.input_json = {
            **job.input_json,
            "metadata": {
                **(job_metadata if isinstance(job_metadata, dict) else {}),
                "listing_image_task_group_id": group.id,
            },
        }
    project.last_batch_id = batch.id
    project.task_count = len(jobs)
    project.status = "generating"
    workflow.image_batch_id = batch.id
    workflow.status = "generating"
    workflow.error_message = None
    variation_jobs: list[object] = []
    variation_created = False
    if bool(delivery.get("include_default_variations")):
        _, variation_jobs, variation_created = await create_quick_default_variation_group(
            db, settings, project=project, version=version, workflow=workflow,
            user_id=planning_job.created_by, planning_job_id=planning_job.id,
        )
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=len(jobs), batch_id=batch.id))
    if variation_created and variation_jobs:
        variation_batch_id = getattr(variation_jobs[0], "batch_id", None)
        await dispatch_jobs(db, await due_jobs(
            db, settings, limit=len(variation_jobs), batch_id=variation_batch_id,
        ))
    return group
