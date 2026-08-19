from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.content import Asset
from app.models.listing_workflow import (
    CategorySkillVersion, ImagePromptItem, ListingImageProject, ListingImageTaskGroup,
    ListingVersion,
)
from app.models.tasks import Job, JobBatch
from app.schemas.listing_workflow import (
    ListingImageTaskAssetResponse, ListingImageTaskGroupResponse, ListingImageTaskGroupStatistics,
    ListingImageTaskResponse,
)
from app.services.asset_service import asset_content_url
from app.services.storage_service import StorageService
from app.services.task_service import job_response


ACTIVE_JOB_STATUSES = {"queued", "waiting_for_resource", "dispatching", "running", "retry_waiting"}
QUEUED_JOB_STATUSES = {"queued", "waiting_for_resource", "dispatching", "retry_waiting"}


def _job_item_code(job: Job) -> str:
    metadata = job.input_json.get("metadata")
    if isinstance(metadata, dict) and metadata.get("item_code"):
        return str(metadata["item_code"])
    parts = (job.client_item_id or "").split(":")
    return parts[-2] if len(parts) >= 3 else parts[-1] if parts else ""


def aggregate_group_status(jobs: list[Job]) -> tuple[str, ListingImageTaskGroupStatistics, int]:
    counts = Counter(job.status for job in jobs)
    queued = sum(counts[item] for item in QUEUED_JOB_STATUSES)
    running = counts["running"]
    succeeded = counts["succeeded"]
    failed = counts["failed"]
    cancelled = counts["cancelled"]
    total = len(jobs)
    cancel_requested = any(job.cancel_requested_at and job.status in ACTIVE_JOB_STATUSES for job in jobs)
    if not total:
        status = "draft"
    elif cancel_requested:
        status = "cancel_requested"
    elif queued or running:
        status = "running"
    elif succeeded == total:
        status = "succeeded"
    elif cancelled == total:
        status = "cancelled"
    elif failed == total:
        status = "failed"
    elif succeeded and failed + cancelled:
        status = "partially_succeeded"
    else:
        status = "failed"
    progress = round(100 * (succeeded + failed + cancelled) / total) if total else 0
    return status, ListingImageTaskGroupStatistics(
        total=total, queued=queued, running=running, succeeded=succeeded, failed=failed, cancelled=cancelled,
    ), progress


async def build_input_asset_snapshot(
    db: AsyncSession, *, organization_id: str, product_asset_ids: list[str],
    reference_asset_ids: list[str], template_asset_ids: list[str], primary_asset_id: str | None = None,
) -> dict[str, object]:
    ordered = list(dict.fromkeys(product_asset_ids + reference_asset_ids + template_asset_ids))
    assets = list((await db.scalars(select(Asset).where(
        Asset.organization_id == organization_id, Asset.id.in_(ordered), Asset.deleted_at.is_(None),
    ))).all()) if ordered else []
    indexed = {asset.id: asset for asset in assets}

    def rows(ids: list[str], default_role: str) -> list[dict[str, object]]:
        values: list[dict[str, object]] = []
        for asset_id in ids:
            asset = indexed.get(asset_id)
            if asset is None:
                values.append({"asset_id": asset_id, "file_name": "素材已删除或不可用", "role": default_role, "width": 0, "height": 0, "mime_type": ""})
                continue
            role = "primary" if primary_asset_id == asset.id else default_role
            values.append({
                "asset_id": asset.id, "file_name": asset.filename, "role": role,
                "width": asset.width, "height": asset.height, "mime_type": asset.mime_type,
            })
        return values

    return {
        "product_images": rows(product_asset_ids, "product"),
        "reference_images": rows(reference_asset_ids, "reference"),
        "template_images": rows(template_asset_ids, "template"),
    }


def _snapshot_rows(snapshot: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key in ("product_images", "reference_images", "template_images"):
        value = snapshot.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict) and item.get("asset_id"))
    return rows


async def _asset_responses(
    db: AsyncSession, *, organization_id: str, snapshot: dict[str, object], asset_ids: list[str] | None = None,
) -> list[ListingImageTaskAssetResponse]:
    rows = _snapshot_rows(snapshot)
    if asset_ids is not None:
        wanted = set(asset_ids)
        rows = [item for item in rows if str(item.get("asset_id")) in wanted]
    ids = [str(item["asset_id"]) for item in rows]
    assets = list((await db.scalars(select(Asset).where(
        Asset.organization_id == organization_id, Asset.id.in_(ids), Asset.deleted_at.is_(None),
    ))).all()) if ids else []
    indexed = {asset.id: asset for asset in assets}
    return [ListingImageTaskAssetResponse(
        asset_id=str(item["asset_id"]), role=str(item.get("role") or "reference"),
        filename=(indexed[str(item["asset_id"])].filename if str(item["asset_id"]) in indexed else str(item.get("file_name") or "素材不可用")),
        mime_type=(indexed[str(item["asset_id"])].mime_type if str(item["asset_id"]) in indexed else str(item.get("mime_type") or "")),
        width=(indexed[str(item["asset_id"])].width if str(item["asset_id"]) in indexed else int(item.get("width") or 0)),
        height=(indexed[str(item["asset_id"])].height if str(item["asset_id"]) in indexed else int(item.get("height") or 0)),
        url=asset_content_url(str(item["asset_id"])) if str(item["asset_id"]) in indexed else None,
        available=str(item["asset_id"]) in indexed,
    ) for item in rows]


async def next_group_number(db: AsyncSession, project_id: str) -> int:
    return int(await db.scalar(select(func.max(ListingImageTaskGroup.group_number)).where(
        ListingImageTaskGroup.listing_image_project_id == project_id,
    )) or 0) + 1


async def create_group_for_batch(
    db: AsyncSession, *, project: ListingImageProject, batch: JobBatch, version: ListingVersion,
    selected_image_types: list[str], product_asset_ids: list[str], reference_asset_ids: list[str],
    template_asset_ids: list[str], input_asset_snapshot: dict[str, object], user_id: str,
    source_task_group_id: str | None = None, historical: bool = False,
) -> ListingImageTaskGroup:
    existing = await db.scalar(select(ListingImageTaskGroup).where(ListingImageTaskGroup.job_batch_id == batch.id))
    if existing:
        return existing
    number = await next_group_number(db, project.id)
    group = ListingImageTaskGroup(
        organization_id=project.organization_id, listing_image_project_id=project.id,
        session_id=project.session_id, listing_version_id=version.id,
        category_id=str(version.category_skill_snapshot.get("category_id")),
        category_skill_version_id=version.category_skill_snapshot.get("skill_version_id"),
        job_batch_id=batch.id, source_task_group_id=source_task_group_id,
        group_number=number, group_name=("历史任务组" if historical else "任务组") + f" #{number}",
        status=batch.status, product_image_asset_ids=product_asset_ids,
        reference_asset_ids=reference_asset_ids, template_asset_ids=template_asset_ids,
        input_asset_snapshot=input_asset_snapshot, selected_image_types=selected_image_types,
        created_by=user_id, updated_by=user_id,
    )
    if historical:
        group.created_at = batch.created_at
        group.updated_at = batch.updated_at
    db.add(group)
    await db.flush()
    return group


async def ensure_legacy_groups(db: AsyncSession, *, project: ListingImageProject) -> None:
    grouped_batch_ids = set((await db.scalars(select(ListingImageTaskGroup.job_batch_id).where(
        ListingImageTaskGroup.listing_image_project_id == project.id,
        ListingImageTaskGroup.job_batch_id.is_not(None),
    ))).all())
    rows = (await db.execute(select(JobBatch, Job).join(Job, Job.batch_id == JobBatch.id).where(
        JobBatch.organization_id == project.organization_id,
        JobBatch.workspace_type == "listing", JobBatch.operation_code == "listing.generate",
    ).order_by(JobBatch.created_at, Job.created_at))).all()
    seen: set[str] = set()
    for batch, job in rows:
        if batch.id in grouped_batch_ids or batch.id in seen:
            continue
        metadata = job.input_json.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("workflow") != "listing_image" or metadata.get("output_project_id") != project.id:
            continue
        seen.add(batch.id)
        version = await db.get(ListingVersion, str(metadata.get("listing_version_id") or project.listing_version_id))
        if version is None:
            continue
        batch_jobs = list((await db.scalars(select(Job).where(Job.batch_id == batch.id).order_by(Job.created_at))).all())
        refs = list(dict.fromkeys(str(asset_id) for item in batch_jobs for asset_id in (item.input_json.get("reference_asset_ids") or [])))
        product_ids = [asset_id for asset_id in refs if asset_id in set((await db.scalars(select(Asset.id).where(Asset.id.in_(refs), Asset.category == "product_reference"))).all())]
        other_ids = [asset_id for asset_id in refs if asset_id not in product_ids]
        snapshot = await build_input_asset_snapshot(
            db, organization_id=project.organization_id, product_asset_ids=product_ids,
            reference_asset_ids=other_ids, template_asset_ids=[],
        )
        await create_group_for_batch(
            db, project=project, batch=batch, version=version,
            selected_image_types=[_job_item_code(item) for item in batch_jobs],
            product_asset_ids=product_ids, reference_asset_ids=other_ids, template_asset_ids=[],
            input_asset_snapshot=snapshot, user_id=batch.created_by, historical=True,
        )


async def task_group_response(
    db: AsyncSession, storage: StorageService, settings: Settings, group: ListingImageTaskGroup,
) -> ListingImageTaskGroupResponse:
    # Updating the aggregate status can trigger an autoflush before the later
    # SELECT statements. MySQL then supplies ``updated_at`` via the server-side
    # on-update expression and SQLAlchemy expires that attribute. Cache both
    # timestamps while they are loaded so response serialization never causes
    # an implicit async lazy-load (MissingGreenlet).
    created_at = group.created_at
    updated_at = group.updated_at
    jobs = list((await db.scalars(select(Job).where(Job.batch_id == group.job_batch_id).order_by(Job.created_at))).all()) if group.job_batch_id else []
    status, statistics, progress = aggregate_group_status(jobs)
    if group.status != status:
        group.status = status
    version = await db.get(ListingVersion, group.listing_version_id)
    skill_version = await db.get(CategorySkillVersion, group.category_skill_version_id) if group.category_skill_version_id else None
    prompt_items = list((await db.scalars(select(ImagePromptItem).where(
        ImagePromptItem.organization_id == group.organization_id,
        ImagePromptItem.project_type == "listing_image",
        ImagePromptItem.project_id == group.listing_image_project_id,
    ))).all())
    prompt_status = {item.item_code: item.status for item in prompt_items}
    job_metadata = [
        item.input_json.get("metadata") if isinstance(item.input_json.get("metadata"), dict) else {}
        for item in jobs
    ]
    variation_jobs = [item for item in job_metadata if item.get("workflow") == "smart_image_variation"]
    attachment_jobs = [item for item in job_metadata if item.get("workflow") == "attachment_workbench_generation"]
    workflow_mode = "attachment_standard" if attachment_jobs else "smart_image_variation" if variation_jobs else "standard"
    variation_types = list(dict.fromkeys(
        str(item.get("variation_type_name") or item.get("variation_type_code") or "")
        for item in variation_jobs if item.get("variation_type_name") or item.get("variation_type_code")
    ))
    variation_plan_count = len({
        (str(item.get("variation_type_code") or ""), str(item.get("variation_plan_code") or ""))
        for item in variation_jobs
    })
    snapshot = dict(group.input_asset_snapshot or {})
    all_assets = await _asset_responses(db, organization_id=group.organization_id, snapshot=snapshot)
    tasks: list[ListingImageTaskResponse] = []
    for job in jobs:
        response = await job_response(db, storage, settings, job)
        code = _job_item_code(job)
        metadata = job.input_json.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        job_asset_ids = [str(item) for item in (job.input_json.get("reference_asset_ids") or [])]
        tasks.append(ListingImageTaskResponse(
            id=job.id, batch_id=job.batch_id, image_type=code,
            prompt_status=prompt_status.get(code, "submitted"), status=job.status,
            progress=job.progress, final_prompt=str(job.input_json.get("prompt") or ""),
            model_code=job.model_code, error_code=job.error_code, error_message=job.error_message,
            created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at,
            input_assets=await _asset_responses(db, organization_id=group.organization_id, snapshot=snapshot, asset_ids=job_asset_ids),
            outputs=response.outputs,
            variation_type_code=str(metadata.get("variation_type_code") or "") or None,
            variation_type_name=str(metadata.get("variation_type_name") or "") or None,
            variation_plan_code=str(metadata.get("variation_plan_code") or "") or None,
            variation_plan_name=str(metadata.get("variation_plan_name") or "") or None,
            variation_version=int(metadata.get("variation_version") or 0) or None,
            chinese_prompt=str(metadata.get("chinese_prompt") or ""),
            slot_index=int(metadata.get("slot_index") or 0) or None,
            generation_mode=str(metadata.get("generation_mode") or "") or None,
            requested_aspect_ratio=str(metadata.get("requested_aspect_ratio") or job.input_json.get("aspect_ratio") or "") or None,
            requested_width=int(metadata.get("requested_width") or job.input_json.get("requested_width") or 0) or None,
            requested_height=int(metadata.get("requested_height") or job.input_json.get("requested_height") or 0) or None,
            plan_version_id=str(metadata.get("plan_version_id") or "") or None,
            prompt_version_id=str(metadata.get("prompt_version_id") or "") or None,
            reference_understanding_id=str(metadata.get("reference_understanding_id") or "") or None,
        ))
    return ListingImageTaskGroupResponse(
        id=group.id, batch_id=group.job_batch_id, listing_image_project_id=group.listing_image_project_id,
        session_id=group.session_id, listing_version_id=group.listing_version_id,
        listing_version_number=version.version_number if version else 0,
        category_skill_version_id=group.category_skill_version_id,
        skill_version_number=skill_version.version_number if skill_version else int((version.category_skill_snapshot if version else {}).get("skill_version") or 0) or None,
        category_name=str((version.category_skill_snapshot if version else {}).get("category_name") or ""),
        skill_name=str((version.category_skill_snapshot if version else {}).get("skill_name") or ""),
        listing_summary=dict(version.listing_snapshot or {}) if version else {},
        workflow_mode=workflow_mode, variation_types=variation_types, variation_plan_count=variation_plan_count,
        source_task_group_id=group.source_task_group_id, group_number=group.group_number,
        group_name=group.group_name, status=status, selected_image_types=list(group.selected_image_types or []),
        input_assets=all_assets, tasks=tasks, statistics=statistics, progress=progress,
        created_by=group.created_by, created_at=created_at, updated_at=updated_at,
    )
