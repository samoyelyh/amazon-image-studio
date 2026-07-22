from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.content import Asset, GeneratedOutput
from app.models.tasks import BatchTryOnReviewItem, BatchTryOnVersion, Job, JobBatch
from app.schemas.batch_tryon_review import (
    BatchTryOnRegenerateRequest,
    BatchTryOnReviewDetailResponse,
    BatchTryOnVersionResponse,
    ReviewAssetResponse,
)
from app.schemas.tasks import JobSubmitRequest
from app.services.asset_service import asset_content_url


UTC = timezone.utc
REVIEW_CORRECTION_HEADER = "REVIEW CORRECTION REQUIREMENTS:"


def append_batch_try_on_review_requirements(base_prompt: str, review_notes: str | None) -> str:
    notes = (review_notes or "").strip()
    if not notes:
        return base_prompt
    return f"""{base_prompt.rstrip()}

{REVIEW_CORRECTION_HEADER}

The previous generated result did not pass manual review.

Correct the following issues:
{notes}

These correction instructions are additional requirements only.
They must not replace or weaken the mandatory garment fidelity requirements.

Continue to preserve:
- the original model identity and face
- hairstyle
- pose
- body proportions
- camera angle
- background
- lighting
- garment color
- graphics
- text
- numbers, including leading zeros
- logos
- stripes
- stitching
- panel structure
- neckline
- sleeves
- hem
- garment silhouette
- fabric appearance
- print-versus-embroidery characteristics"""


async def ensure_batch_try_on_review_records(
    session: AsyncSession, batch: JobBatch,
) -> list[BatchTryOnReviewItem]:
    if batch.workspace_type != "batch_tryon":
        return []
    jobs = list((await session.scalars(
        select(Job).where(Job.batch_id == batch.id).order_by(Job.created_at, Job.id)
    )).all())
    existing = {
        item.client_item_id: item for item in (await session.scalars(
            select(BatchTryOnReviewItem).where(BatchTryOnReviewItem.batch_id == batch.id)
        )).all()
    }
    grouped: dict[str, list[Job]] = {}
    for job in jobs:
        if job.client_item_id:
            grouped.setdefault(job.client_item_id, []).append(job)

    for client_item_id, item_jobs in grouped.items():
        item = existing.get(client_item_id)
        references = [str(value) for value in item_jobs[0].input_json.get("reference_asset_ids", []) or []]
        if item is None:
            if len(references) < 2:
                continue
            item = BatchTryOnReviewItem(
                organization_id=batch.organization_id,
                batch_id=batch.id,
                client_item_id=client_item_id,
                model_asset_id=references[0],
                garment_asset_id=references[1],
                review_status="pending",
                regeneration_count=0,
                created_by=item_jobs[0].created_by,
                updated_by=item_jobs[0].updated_by,
            )
            session.add(item)
            await session.flush()
            existing[client_item_id] = item

        versions = list((await session.scalars(
            select(BatchTryOnVersion).where(BatchTryOnVersion.item_id == item.id)
            .order_by(BatchTryOnVersion.version_number)
        )).all())
        versions_by_task = {version.task_id: version for version in versions if version.task_id}
        parent = versions[-1] if versions else None
        for job in item_jobs:
            if job.id in versions_by_task:
                parent = versions_by_task[job.id]
                continue
            generated_asset_id = await session.scalar(
                select(GeneratedOutput.asset_id).where(GeneratedOutput.job_id == job.id)
                .order_by(GeneratedOutput.sequence_number).limit(1)
            )
            metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
            version = BatchTryOnVersion(
                organization_id=batch.organization_id,
                item_id=item.id,
                version_number=(parent.version_number + 1) if parent else 1,
                parent_version_id=parent.id if parent else None,
                generated_asset_id=generated_asset_id,
                task_id=job.id,
                prompt_snapshot=str(job.input_json.get("prompt") or ""),
                review_notes=str(metadata.get("review_notes") or "").strip() or None,
                retry_mode=str(metadata.get("retry_mode") or ("initial" if parent is None else "direct")),
                generation_status=job.status,
                review_status="pending",
                created_at=job.created_at or datetime.now(UTC),
                completed_at=job.finished_at,
            )
            session.add(version)
            await session.flush()
            metadata = {
                **metadata,
                "batch_tryon_review_item_id": item.id,
                "batch_tryon_version_id": version.id,
            }
            job.input_json = {**job.input_json, "metadata": metadata}
            versions.append(version)
            versions_by_task[job.id] = version
            parent = version

        if versions and item.current_version_id is None:
            latest = versions[-1]
            item.current_version_id = latest.id
            item.regeneration_count = max(0, latest.version_number - 1)
            item.review_status = _item_status_for_version(latest)
    await session.flush()
    return list(existing.values())


def _item_status_for_version(version: BatchTryOnVersion) -> str:
    if version.review_status == "approved":
        return "approved"
    if version.generation_status == "succeeded":
        return "pending"
    if version.generation_status in {"failed", "cancelled"}:
        return "generation_failed"
    return "regenerating" if version.version_number > 1 else "pending"


async def get_review_item(
    session: AsyncSession, organization_id: str, item_id: str, *, lock: bool = False,
) -> BatchTryOnReviewItem:
    statement = select(BatchTryOnReviewItem).where(
        BatchTryOnReviewItem.id == item_id,
        BatchTryOnReviewItem.organization_id == organization_id,
    )
    if lock:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise AppError("batch_tryon.review_item_not_found", "批量套图审核任务不存在", 404)
    return item


def _asset_response(asset: Asset) -> ReviewAssetResponse:
    return ReviewAssetResponse(
        id=asset.id,
        filename=asset.filename,
        preview_url=asset_content_url(asset.id),
        width=asset.width,
        height=asset.height,
        mime_type=asset.mime_type,
        size=asset.size,
    )


async def review_detail(
    session: AsyncSession, organization_id: str, item_id: str,
) -> BatchTryOnReviewDetailResponse:
    item = await get_review_item(session, organization_id, item_id)
    garment = await session.scalar(select(Asset).where(
        Asset.id == item.garment_asset_id, Asset.organization_id == organization_id, Asset.deleted_at.is_(None),
    ))
    model = await session.scalar(select(Asset).where(
        Asset.id == item.model_asset_id, Asset.organization_id == organization_id, Asset.deleted_at.is_(None),
    ))
    if garment is None or model is None:
        raise AppError("batch_tryon.review_asset_missing", "审核所需的原始图片不存在", 409)
    versions = list((await session.scalars(
        select(BatchTryOnVersion).where(
            BatchTryOnVersion.organization_id == organization_id,
            BatchTryOnVersion.item_id == item.id,
        ).order_by(BatchTryOnVersion.version_number.desc())
    )).all())
    asset_ids = {version.generated_asset_id for version in versions if version.generated_asset_id}
    task_ids = {version.task_id for version in versions if version.task_id}
    jobs = {
        job.id: job for job in (await session.scalars(
            select(Job).where(Job.organization_id == organization_id, Job.id.in_(task_ids))
        )).all()
    } if task_ids else {}
    assets = {
        asset.id: asset for asset in (await session.scalars(
            select(Asset).where(Asset.organization_id == organization_id, Asset.id.in_(asset_ids), Asset.deleted_at.is_(None))
        )).all()
    } if asset_ids else {}
    version_responses = [
        BatchTryOnVersionResponse(
            id=version.id,
            version_number=version.version_number,
            parent_version_id=version.parent_version_id,
            generated_asset_id=version.generated_asset_id,
            task_id=version.task_id,
            prompt_snapshot=version.prompt_snapshot,
            review_notes=version.review_notes,
            retry_mode=version.retry_mode,
            generation_status=version.generation_status,
            review_status=version.review_status,
            generated_asset=_asset_response(assets[version.generated_asset_id])
            if version.generated_asset_id in assets else None,
            created_at=version.created_at,
            completed_at=version.completed_at,
            reviewed_by=version.reviewed_by,
            reviewed_at=version.reviewed_at,
            generation_duration_ms=jobs[version.task_id].generation_duration_ms
            if version.task_id in jobs else None,
        ) for version in versions
    ]
    current = next((version for version in version_responses if version.id == item.current_version_id), None)
    return BatchTryOnReviewDetailResponse(
        item_id=item.id,
        batch_id=item.batch_id,
        client_item_id=item.client_item_id,
        review_status=item.review_status,
        current_version_id=item.current_version_id,
        approved_version_id=item.approved_version_id,
        regeneration_count=item.regeneration_count,
        garment_asset=_asset_response(garment),
        model_asset=_asset_response(model),
        current_version=current,
        versions=version_responses,
    )


async def approve_version(
    session: AsyncSession, *, organization_id: str, item_id: str, version_id: str, user_id: str,
) -> BatchTryOnReviewItem:
    item = await get_review_item(session, organization_id, item_id, lock=True)
    version = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == version_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.organization_id == organization_id,
    ).with_for_update())
    if version is None:
        raise AppError("batch_tryon.version_not_found", "审核版本不存在", 404)
    if item.current_version_id != version.id:
        raise AppError("batch_tryon.version_not_current", "只能审核当前最新版本，请刷新后重试", 409)
    if version.generation_status != "succeeded" or not version.generated_asset_id:
        raise AppError("batch_tryon.version_not_reviewable", "当前版本尚未生成成功，不能审核通过", 409)
    now = datetime.now(UTC)
    version.review_status = "approved"
    version.reviewed_by = user_id
    version.reviewed_at = now
    item.review_status = "approved"
    item.approved_version_id = version.id
    item.updated_by = user_id
    await session.flush()
    return item


async def regenerate_version(
    session: AsyncSession, settings: Settings, *, organization_id: str, item_id: str,
    payload: BatchTryOnRegenerateRequest, user_id: str,
) -> tuple[BatchTryOnReviewItem, BatchTryOnVersion, Job, bool]:
    from app.services.task_service import refresh_batch_status, submit_job

    item = await get_review_item(session, organization_id, item_id, lock=True)
    source = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == payload.source_version_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.organization_id == organization_id,
    ).with_for_update())
    if source is None:
        raise AppError("batch_tryon.version_not_found", "来源版本不存在", 404)
    if source.generation_status not in {"succeeded", "failed", "cancelled"} or not source.task_id:
        raise AppError("batch_tryon.version_not_regenerable", "当前版本仍在生成或等待调度，暂时不能重新生成", 409)

    source_job = await session.scalar(select(Job).where(
        Job.id == source.task_id, Job.organization_id == organization_id,
    ))
    if source_job is None:
        raise AppError("batch_tryon.source_job_missing", "来源生成任务不存在", 409)
    job_key = f"batch-review:{sha256(f'{item.id}:{payload.idempotency_key}'.encode()).hexdigest()}"
    version_id = str(uuid5(NAMESPACE_URL, job_key))
    input_json = deepcopy(source_job.input_json)
    input_json["prompt"] = append_batch_try_on_review_requirements(
        source.prompt_snapshot, payload.review_notes if payload.retry_mode == "with_review_notes" else None,
    )
    metadata = input_json.get("metadata") if isinstance(input_json.get("metadata"), dict) else {}
    input_json["metadata"] = {
        **metadata,
        "batch_tryon_review_item_id": item.id,
        "batch_tryon_version_id": version_id,
        "retry_mode": payload.retry_mode,
        "review_notes": payload.review_notes,
    }
    job_payload = JobSubmitRequest(
        operation_code="batch_tryon.generate",
        workspace_type="batch_tryon",
        queue_name="batch_tryon_queue",
        capability=source_job.capability,
        model_code=source_job.model_code,
        idempotency_key=job_key,
        project_id=source_job.project_id,
        client_item_id=item.client_item_id,
        input=input_json,
    )
    existing_job = await session.scalar(select(Job).where(
        Job.organization_id == organization_id, Job.idempotency_key == job_key,
    ))
    if existing_job is None and item.current_version_id != source.id:
        raise AppError("batch_tryon.version_not_current", "当前任务已有更新版本，请刷新后重试", 409)
    job, created = await submit_job(
        session, settings, organization_id=organization_id, user_id=user_id,
        payload=job_payload, batch_id=item.batch_id,
    )
    if not created:
        existing_version = await session.scalar(select(BatchTryOnVersion).where(
            BatchTryOnVersion.task_id == job.id,
            BatchTryOnVersion.organization_id == organization_id,
        ))
        if existing_version is None:
            raise AppError("batch_tryon.version_initializing", "重新生成版本正在初始化，请稍后重试", 409)
        return item, existing_version, job, False

    next_number = int(await session.scalar(select(func.max(BatchTryOnVersion.version_number)).where(
        BatchTryOnVersion.item_id == item.id,
    )) or 0) + 1
    now = datetime.now(UTC)
    version = BatchTryOnVersion(
        id=version_id,
        organization_id=organization_id,
        item_id=item.id,
        version_number=next_number,
        parent_version_id=source.id,
        generated_asset_id=None,
        task_id=job.id,
        prompt_snapshot=str(input_json["prompt"]),
        review_notes=payload.review_notes,
        retry_mode=payload.retry_mode,
        generation_status=job.status,
        review_status="pending",
        created_at=now,
    )
    session.add(version)
    source.review_status = "rejected"
    source.review_notes = payload.review_notes
    source.reviewed_by = user_id
    source.reviewed_at = now
    item.current_version_id = version.id
    if item.approved_version_id == source.id:
        item.approved_version_id = None
    item.review_status = "regenerating"
    item.regeneration_count += 1
    item.updated_by = user_id
    await refresh_batch_status(session, item.batch_id)
    await session.flush()
    return item, version, job, True


async def sync_batch_try_on_version_for_job(
    session: AsyncSession, job: Job, *, generated_asset_id: str | None = None,
) -> None:
    if job.workspace_type != "batch_tryon":
        return
    metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
    version_id = str(metadata.get("batch_tryon_version_id") or "")
    version = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == version_id,
        BatchTryOnVersion.organization_id == job.organization_id,
    )) if version_id else None
    if version is None:
        version = await session.scalar(select(BatchTryOnVersion).where(
            BatchTryOnVersion.task_id == job.id,
            BatchTryOnVersion.organization_id == job.organization_id,
        ))
    if version is None:
        return
    item = await session.get(BatchTryOnReviewItem, version.item_id, with_for_update=True)
    version.generation_status = job.status
    if generated_asset_id:
        version.generated_asset_id = generated_asset_id
    if job.status == "succeeded":
        version.review_status = "pending"
        version.completed_at = job.finished_at or datetime.now(UTC)
    elif job.status in {"failed", "cancelled"}:
        version.completed_at = job.finished_at or datetime.now(UTC)
    if item is not None and item.current_version_id == version.id:
        item.review_status = _item_status_for_version(version)
        item.updated_by = job.updated_by
    await session.flush()
