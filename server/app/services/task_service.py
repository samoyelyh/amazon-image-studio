from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.content import Asset, GeneratedOutput, Project
from app.models.tasks import (
    ApiKey, ApiKeyStatus, BatchStatus, BatchTryOnReviewItem, BatchTryOnVersion, Job, JobAttempt,
    JobBatch, JobStatus, OperationResourcePool, ProviderModel, ResourcePool, ResourcePoolKey,
)
from app.schemas.tasks import JobBatchSubmitRequest, JobOutputResponse, JobPage, JobResponse, JobSubmitRequest
from app.services.billing_service import reactivate_job_reservation, release_reservation, reserve_quota
from app.services.asset_service import signed_asset_response
from app.services.storage_service import StorageService
from app.services.resource_pool_service import validate_operation_binding
from app.services.image_size_service import validate_submission_dimensions


UTC = timezone.utc
logger = logging.getLogger(__name__)
TERMINAL_JOB_STATUSES = {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}
ACTIVE_SLOT_STATUSES = {JobStatus.DISPATCHING.value, JobStatus.RUNNING.value}


def request_hash(payload: JobSubmitRequest) -> str:
    encoded = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


async def submit_job(
    session: AsyncSession, settings: Settings, *, organization_id: str, user_id: str, payload: JobSubmitRequest,
    batch_id: str | None = None,
) -> tuple[Job, bool]:
    fingerprint = request_hash(payload)
    existing = await session.scalar(select(Job).where(
        Job.organization_id == organization_id, Job.idempotency_key == payload.idempotency_key,
    ).with_for_update())
    if existing:
        if existing.request_hash != fingerprint:
            raise AppError("job.idempotency_conflict", "Idempotency key was already used with different job input", 409)
        return existing, False
    bound_model = await validate_operation_binding(
        session, organization_id=organization_id, operation_code=payload.operation_code,
        model_code=payload.model_code, capability=payload.capability,
        additional_capabilities={"vision_input"} if payload.operation_code.endswith(".plan")
        and bool(payload.input.get("reference_asset_ids")) else set(),
    )
    if payload.capability in {"image_generation", "image_edit", "multi_image_reference", "mask_edit"}:
        try:
            validate_submission_dimensions(payload.input, bound_model.config_json or {}, capability=payload.capability)
        except Exception as error:
            if isinstance(error, AppError):
                raise
            code = getattr(error, "code", "provider.unsupported_size")
            message = getattr(error, "message", str(error))
            raise AppError(code, message, 422) from error
    if payload.project_id:
        project = await session.scalar(select(Project.id).where(
            Project.id == payload.project_id, Project.organization_id == organization_id, Project.deleted_at.is_(None),
        ))
        if project is None:
            raise AppError("project.not_found", "Project was not found", 404)
    asset_ids = [str(item) for item in payload.input.get("reference_asset_ids", []) or []]
    if payload.input.get("mask_asset_id"):
        asset_ids.append(str(payload.input["mask_asset_id"]))
    if asset_ids:
        found = set((await session.scalars(select(Asset.id).where(
            Asset.organization_id == organization_id, Asset.id.in_(set(asset_ids)), Asset.deleted_at.is_(None),
        ))).all())
        if found != set(asset_ids):
            raise AppError("asset.not_found", "One or more task assets were not found", 404)
    factors = dict(payload.billing_factors)
    factors["model"] = payload.model_code
    factors["resource_pool"] = "platform"
    reservation = await reserve_quota(
        session, settings, organization_id=organization_id, user_id=user_id,
        operation_code=payload.operation_code, quantity=1, factors=factors,
        idempotency_key=f"job:{payload.idempotency_key}", reference_type="job_submission",
        reference_id=payload.idempotency_key,
    )
    job = Job(
        organization_id=organization_id, project_id=payload.project_id, batch_id=batch_id,
        quota_reservation_id=reservation.id, operation_code=payload.operation_code,
        workspace_type=payload.workspace_type, queue_name=payload.queue_name,
        capability=payload.capability, model_code=payload.model_code, input_json=payload.input,
        client_item_id=payload.client_item_id,
        idempotency_key=payload.idempotency_key, request_hash=fingerprint,
        max_attempts=settings.job_max_attempts, created_by=user_id, updated_by=user_id,
    )
    session.add(job)
    await session.flush()
    reservation.reference_type = "job"
    reservation.reference_id = job.id
    return job, True


async def job_response(
    session: AsyncSession, storage: StorageService, settings: Settings, job: Job,
) -> JobResponse:
    rows = (await session.execute(
        select(GeneratedOutput, Asset)
        .join(Asset, GeneratedOutput.asset_id == Asset.id)
        .where(GeneratedOutput.organization_id == job.organization_id, GeneratedOutput.job_id == job.id)
        .order_by(GeneratedOutput.sequence_number)
    )).all()
    outputs: list[JobOutputResponse] = []
    for generated, asset in rows:
        signed = await signed_asset_response(asset, storage, settings)
        outputs.append(JobOutputResponse(
            id=generated.id, asset_id=asset.id, filename=asset.filename,
            display_filename=asset.filename, download_filename=asset.filename,
            download_url=f"/api/v1/assets/{asset.id}/download", mime_type=asset.mime_type,
            width=asset.width, height=asset.height, size=asset.size,
            sequence_number=generated.sequence_number, url=signed.url or "",
            url_expires_at=signed.url_expires_at,
        ))
    snapshot = job.input_json
    review_item = None
    review_version = None
    if job.workspace_type == "batch_tryon" and job.batch_id and job.client_item_id:
        review_item = await session.scalar(select(BatchTryOnReviewItem).where(
            BatchTryOnReviewItem.organization_id == job.organization_id,
            BatchTryOnReviewItem.batch_id == job.batch_id,
            BatchTryOnReviewItem.client_item_id == job.client_item_id,
        ))
        if review_item:
            review_version = await session.scalar(select(BatchTryOnVersion).where(
                BatchTryOnVersion.organization_id == job.organization_id,
                BatchTryOnVersion.item_id == review_item.id,
                BatchTryOnVersion.task_id == job.id,
            ))
            if review_version and rows:
                from app.services.batch_tryon_review_service import ensure_batch_try_on_version_filenames

                _, display_filename, _, _ = await ensure_batch_try_on_version_filenames(
                    session,
                    review_item,
                    review_version,
                    job=job,
                    generated_asset=rows[0][1],
                )
                outputs = [
                    output.model_copy(update={
                        "filename": display_filename,
                        "display_filename": display_filename,
                        "download_filename": display_filename,
                    })
                    for output in outputs
                ]
    actual_width = outputs[0].width if outputs else None
    actual_height = outputs[0].height if outputs else None
    requested_width = snapshot.get("requested_width")
    requested_height = snapshot.get("requested_height")
    return JobResponse.model_validate(job).model_copy(update={
        "outputs": outputs,
        "generation_duration_ms": job.generation_duration_ms,
        "requested_aspect_ratio": snapshot.get("aspect_ratio"),
        "requested_width": requested_width,
        "requested_height": requested_height,
        "resolved_provider_size": snapshot.get("provider_size") or snapshot.get("size"),
        "actual_width": actual_width,
        "actual_height": actual_height,
        "size_mismatch": bool(
            requested_width and requested_height and actual_width and actual_height
            and (requested_width != actual_width or requested_height != actual_height)
        ),
        "review_item_id": review_item.id if review_item else None,
        "review_status": review_item.review_status if review_item else None,
        "current_version_id": review_item.current_version_id if review_item else None,
        "approved_version_id": review_item.approved_version_id if review_item else None,
        "regeneration_count": review_item.regeneration_count if review_item else 0,
        "review_version_id": review_version.id if review_version else None,
        "review_version_number": review_version.version_number if review_version else None,
        "is_current_review_version": bool(
            review_item and review_version and review_item.current_version_id == review_version.id
        ),
    })


def _batch_hash(payload: JobBatchSubmitRequest) -> str:
    value = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(value.encode("utf-8")).hexdigest()


async def submit_batch(
    session: AsyncSession, settings: Settings, *, organization_id: str, user_id: str,
    payload: JobBatchSubmitRequest,
) -> tuple[JobBatch, list[Job], bool]:
    fingerprint = _batch_hash(payload)
    existing = await session.scalar(select(JobBatch).where(
        JobBatch.organization_id == organization_id, JobBatch.idempotency_key == payload.idempotency_key,
    ).with_for_update())
    if existing:
        if existing.request_hash != fingerprint:
            raise AppError("job.batch_idempotency_conflict", "Idempotency key was already used with different batch input", 409)
        jobs = list((await session.scalars(select(Job).where(Job.batch_id == existing.id).order_by(Job.created_at))).all())
        return existing, jobs, False
    batch = JobBatch(
        organization_id=organization_id, project_id=payload.project_id,
        workspace_type=payload.workspace_type, operation_code=payload.operation_code,
        name=payload.name.strip(), model_code=payload.model_code, capability=payload.capability,
        idempotency_key=payload.idempotency_key, request_hash=fingerprint,
        concurrency=payload.concurrency, admin_test_mode=payload.admin_test_mode,
        status=BatchStatus.QUEUED.value,
        total_jobs=len(payload.items), created_by=user_id, updated_by=user_id,
    )
    session.add(batch)
    await session.flush()
    queue_name = {
        "listing": "listing_queue", "batch_tryon": "batch_tryon_queue", "aplus": "aplus_queue",
    }[payload.workspace_type]
    jobs: list[Job] = []
    for index, item in enumerate(payload.items):
        job_payload = JobSubmitRequest(
            operation_code=payload.operation_code, workspace_type=payload.workspace_type,
            queue_name=queue_name, capability=payload.capability, model_code=payload.model_code,
            idempotency_key=f"batch:{batch.id}:{index + 1}",
            project_id=payload.project_id, client_item_id=item.client_item_id,
            input={
                "prompt": item.prompt, "n": 1, "size": item.size, "aspect_ratio": item.aspect_ratio,
                "requested_width": item.requested_width, "requested_height": item.requested_height,
                "quality": item.quality, "output_format": item.output_format,
                "output_compression": item.output_compression, "reference_asset_ids": item.reference_asset_ids,
                "mask_asset_id": item.mask_asset_id, "metadata": item.metadata,
            },
        )
        job, _ = await submit_job(
            session, settings, organization_id=organization_id, user_id=user_id,
            payload=job_payload, batch_id=batch.id,
        )
        jobs.append(job)
    if payload.workspace_type == "batch_tryon":
        from app.services.batch_tryon_review_service import ensure_batch_try_on_review_records

        await ensure_batch_try_on_review_records(session, batch)
    await session.flush()
    return batch, jobs, True


async def get_batch(session: AsyncSession, organization_id: str, batch_id: str, *, lock: bool = False) -> JobBatch:
    statement = select(JobBatch).where(JobBatch.id == batch_id, JobBatch.organization_id == organization_id)
    if lock:
        statement = statement.with_for_update()
    batch = await session.scalar(statement)
    if batch is None:
        raise AppError("job.batch_not_found", "Job batch was not found", 404)
    return batch


async def effective_batch_jobs(session: AsyncSession, batch: JobBatch) -> tuple[list[Job], int]:
    """Return the jobs that represent the batch's current business items.

    Batch try-on regeneration creates immutable historical jobs. Those jobs remain
    available through the review/version APIs, but must not increase task-center
    totals or keep a completed batch open.
    """
    if batch.workspace_type == "batch_tryon":
        item_count = int(await session.scalar(
            select(func.count()).select_from(BatchTryOnReviewItem).where(
                BatchTryOnReviewItem.batch_id == batch.id,
            )
        ) or 0)
        if item_count:
            jobs = list((await session.scalars(
                select(Job)
                .join(BatchTryOnVersion, BatchTryOnVersion.task_id == Job.id)
                .join(
                    BatchTryOnReviewItem,
                    (BatchTryOnReviewItem.id == BatchTryOnVersion.item_id)
                    & (BatchTryOnReviewItem.current_version_id == BatchTryOnVersion.id),
                )
                .where(BatchTryOnReviewItem.batch_id == batch.id)
                .order_by(Job.created_at, Job.id)
            )).all())
            return jobs, item_count

    jobs = list((await session.scalars(
        select(Job).where(Job.batch_id == batch.id).order_by(Job.created_at, Job.id)
    )).all())
    return jobs, len(jobs)


async def refresh_batch_status(session: AsyncSession, batch_id: str) -> JobBatch | None:
    batch = await session.get(JobBatch, batch_id, with_for_update=True)
    if batch is None:
        return None
    jobs, total_jobs = await effective_batch_jobs(session, batch)
    batch.total_jobs = total_jobs
    batch.succeeded_jobs = sum(item.status == JobStatus.SUCCEEDED.value for item in jobs)
    batch.failed_jobs = sum(item.status == JobStatus.FAILED.value for item in jobs)
    batch.cancelled_jobs = sum(item.status == JobStatus.CANCELLED.value for item in jobs)
    terminal = batch.succeeded_jobs + batch.failed_jobs + batch.cancelled_jobs
    was_paused = batch.status == BatchStatus.PAUSED.value
    if total_jobs > 0 and terminal == total_jobs and batch.succeeded_jobs == total_jobs:
        batch.status = BatchStatus.SUCCEEDED.value
        batch.finished_at = datetime.now(UTC)
    elif total_jobs > 0 and terminal == total_jobs and batch.cancelled_jobs == total_jobs:
        batch.status = BatchStatus.CANCELLED.value
        batch.finished_at = datetime.now(UTC)
    elif total_jobs > 0 and terminal == total_jobs and batch.succeeded_jobs:
        batch.status = BatchStatus.PARTIALLY_SUCCEEDED.value
        batch.finished_at = datetime.now(UTC)
    elif total_jobs > 0 and terminal == total_jobs:
        batch.status = BatchStatus.FAILED.value
        batch.finished_at = datetime.now(UTC)
    elif was_paused:
        batch.status = BatchStatus.PAUSED.value
        batch.finished_at = None
    elif any(item.status == JobStatus.RUNNING.value for item in jobs):
        batch.status = BatchStatus.RUNNING.value
        batch.started_at = batch.started_at or datetime.now(UTC)
        batch.finished_at = None
    else:
        batch.status = BatchStatus.QUEUED.value
        batch.finished_at = None
    await session.flush()
    return batch


def dispatch_job(job: Job) -> str:
    from app.workers.celery_app import celery_app

    task_id = str(uuid4())
    celery_app.send_task("jobs.execute", args=[job.id], queue=job.queue_name, task_id=task_id)
    job.celery_task_id = task_id
    job.dispatched_at = datetime.now(UTC)
    job.status = JobStatus.DISPATCHING.value
    return task_id


async def get_job(session: AsyncSession, organization_id: str, job_id: str, *, lock: bool = False) -> Job:
    statement = select(Job).where(Job.id == job_id, Job.organization_id == organization_id)
    if lock:
        statement = statement.with_for_update()
    job = await session.scalar(statement)
    if job is None:
        raise AppError("job.not_found", "Job was not found", 404)
    return job


async def list_jobs(
    session: AsyncSession, organization_id: str, *, status: str | None, limit: int, offset: int,
) -> JobPage:
    filters = [Job.organization_id == organization_id]
    if status:
        filters.append(Job.status == status)
    total = int(await session.scalar(select(func.count()).select_from(Job).where(*filters)) or 0)
    jobs = list((await session.scalars(select(Job).where(*filters).order_by(Job.created_at.desc()).limit(limit).offset(offset))).all())
    return JobPage(items=[JobResponse.model_validate(item) for item in jobs], total=total, limit=limit, offset=offset)


async def cancel_job(session: AsyncSession, *, organization_id: str, job_id: str, user_id: str) -> Job:
    job = await get_job(session, organization_id, job_id, lock=True)
    if job.status in TERMINAL_JOB_STATUSES:
        return job
    now = datetime.now(UTC)
    job.cancel_requested_at = now
    job.updated_by = user_id
    if job.status in {JobStatus.QUEUED.value, JobStatus.DISPATCHING.value, JobStatus.RETRY_WAITING.value}:
        await finalize_cancelled_job(session, job)
    await session.flush()
    return job


async def finalize_cancelled_job(session: AsyncSession, job: Job) -> None:
    job.status = JobStatus.CANCELLED.value
    job.finished_at = datetime.now(UTC)
    job.next_retry_at = None
    job.dispatched_at = None
    await _release_job_reservation(session, job, idempotency_key=f"job-cancel:{job.id}")
    from app.services.batch_tryon_review_service import sync_batch_try_on_version_for_job

    await sync_batch_try_on_version_for_job(session, job)


async def claim_job(session: AsyncSession, settings: Settings, job_id: str) -> Job | None:
    job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None or job.status in TERMINAL_JOB_STATUSES:
        return None
    now = datetime.now(UTC)
    if job.batch_id:
        batch = await session.scalar(select(JobBatch).where(JobBatch.id == job.batch_id).with_for_update())
        if batch and batch.status == BatchStatus.PAUSED.value:
            job.status = JobStatus.QUEUED.value
            job.dispatched_at = None
            job.celery_task_id = None
            await session.flush()
            return None
        if batch:
            running_count = int(await session.scalar(select(func.count()).select_from(Job).where(
                Job.batch_id == batch.id, Job.status == JobStatus.RUNNING.value, Job.id != job.id,
            )) or 0)
            if running_count >= batch.concurrency:
                job.status = JobStatus.QUEUED.value
                job.dispatched_at = None
                job.celery_task_id = None
                await session.flush()
                return None
            batch.status = BatchStatus.RUNNING.value
            batch.started_at = batch.started_at or now
    if job.cancel_requested_at:
        await finalize_cancelled_job(session, job)
        return None
    heartbeat = _aware(job.heartbeat_at)
    if job.status == JobStatus.RUNNING.value and heartbeat and heartbeat > now - timedelta(seconds=settings.job_heartbeat_timeout_seconds):
        return None
    await reactivate_job_reservation(session, settings, job=job)
    job.status = JobStatus.RUNNING.value
    job.progress = max(job.progress, 1)
    job.heartbeat_at = now
    job.error_code = None
    job.error_message = None
    job.next_retry_at = None
    await session.flush()
    return job


async def create_attempt(
    session: AsyncSession,
    job: Job,
    *,
    provider_id: str | None = None,
    pool_id: str | None = None,
    key_id: str | None = None,
) -> JobAttempt:
    job.attempts += 1
    job.heartbeat_at = datetime.now(UTC)
    historical_attempt = int(await session.scalar(select(func.max(JobAttempt.attempt_number)).where(
        JobAttempt.job_id == job.id,
    )) or 0)
    return JobAttempt(
        organization_id=job.organization_id, job_id=job.id, attempt_number=historical_attempt + 1,
        provider_id=provider_id, resource_pool_id=pool_id, api_key_id=key_id,
        status="running", started_at=datetime.now(UTC),
    )


async def schedule_retry_or_fail(
    session: AsyncSession,
    job: Job,
    *,
    code: str,
    message: str,
    retry_delay_seconds: int | None = None,
) -> None:
    if job.cancel_requested_at:
        await finalize_cancelled_job(session, job)
        return
    job.error_code = code
    job.error_message = message[:1000]
    job.heartbeat_at = datetime.now(UTC)
    job.dispatched_at = None
    job.celery_task_id = None
    if job.attempts < job.max_attempts and not job.cancel_requested_at:
        job.status = JobStatus.RETRY_WAITING.value
        delay = retry_delay_seconds if retry_delay_seconds is not None else min(300, 2 ** max(job.attempts, 1) * 5)
        job.next_retry_at = datetime.now(UTC) + timedelta(seconds=max(1, min(900, delay)))
    else:
        job.status = JobStatus.FAILED.value
        job.finished_at = datetime.now(UTC)
        await _release_job_reservation(session, job, idempotency_key=f"job-failed:{job.id}")
    await session.flush()


async def recover_stale_jobs(session: AsyncSession, settings: Settings) -> int:
    now = datetime.now(UTC)
    threshold = now - timedelta(seconds=settings.job_heartbeat_timeout_seconds)
    jobs = list((await session.scalars(select(Job).where(
        or_(
            (Job.status == JobStatus.RUNNING.value) & or_(Job.heartbeat_at < threshold, Job.heartbeat_at.is_(None)),
            (Job.status == JobStatus.DISPATCHING.value) & (Job.dispatched_at < threshold),
        ),
    ).with_for_update())).all())
    recovered = 0
    for job in jobs:
        try:
            async with session.begin_nested():
                await schedule_retry_or_fail(
                    session, job, code="job.worker_lost", message="Worker heartbeat expired; job recovered",
                )
                from app.services.batch_tryon_review_service import sync_batch_try_on_version_for_job

                await sync_batch_try_on_version_for_job(session, job)
                if job.batch_id:
                    await refresh_batch_status(session, job.batch_id)
            recovered += 1
        except Exception as error:
            logger.exception(
                "stale_job_recovery_failed job_id=%s error_type=%s",
                job.id, type(error).__name__,
            )
    return recovered


async def due_jobs(
    session: AsyncSession,
    settings: Settings,
    limit: int = 100,
    *,
    batch_id: str | None = None,
) -> list[Job]:
    now = datetime.now(UTC)
    candidate_filters = [
        Job.dispatched_at.is_(None),
        ~select(JobBatch.id).where(
            JobBatch.id == Job.batch_id,
            JobBatch.status == BatchStatus.PAUSED.value,
        ).exists(),
        or_(Job.status == JobStatus.QUEUED.value,
            (Job.status == JobStatus.RETRY_WAITING.value) & (Job.next_retry_at <= now)),
    ]
    if batch_id:
        candidate_filters.append(Job.batch_id == batch_id)
    candidates = list((await session.scalars(
        select(Job).where(*candidate_filters).order_by(
            case((Job.status == JobStatus.QUEUED.value, 0), else_=1),
            Job.attempts,
            Job.created_at,
        ).limit(max(limit * 5, 100))
        .with_for_update(skip_locked=True)
    )).all())
    if not candidates:
        return []

    active_rows = (await session.execute(select(
        Job.organization_id, Job.created_by, Job.batch_id,
        Job.operation_code, Job.model_code, Job.capability,
    ).where(Job.status.in_(ACTIVE_SLOT_STATUSES)))).all()
    system_active = len(active_rows)
    organization_active: dict[str, int] = {}
    user_active: dict[str, int] = {}
    batch_active: dict[str, int] = {}
    resource_active: dict[tuple[str, str, str, str], int] = {}
    for (
        organization_id, user_id, active_batch_id, operation_code, model_code, capability,
    ) in active_rows:
        organization_active[organization_id] = organization_active.get(organization_id, 0) + 1
        user_active[user_id] = user_active.get(user_id, 0) + 1
        if active_batch_id:
            batch_active[active_batch_id] = batch_active.get(active_batch_id, 0) + 1
        resource_key = (organization_id, operation_code, model_code, capability)
        resource_active[resource_key] = resource_active.get(resource_key, 0) + 1

    batch_ids = {job.batch_id for job in candidates if job.batch_id}
    batches = {
        item.id: item
        for item in (await session.scalars(select(JobBatch).where(JobBatch.id.in_(batch_ids)))).all()
    } if batch_ids else {}
    resource_capacity: dict[tuple[str, str, str, str], int] = {}
    selected: list[Job] = []
    for job in candidates:
        if len(selected) >= limit or system_active >= settings.job_system_max_concurrency:
            break
        if organization_active.get(job.organization_id, 0) >= settings.job_organization_max_concurrency:
            continue
        if user_active.get(job.created_by, 0) >= settings.job_user_max_concurrency:
            continue
        if job.batch_id:
            batch = batches.get(job.batch_id)
            if batch and batch_active.get(job.batch_id, 0) >= batch.concurrency:
                continue
        resource_key = (job.organization_id, job.operation_code, job.model_code, job.capability)
        if resource_key not in resource_capacity:
            rows = (await session.execute(
                select(ApiKey.id, ApiKey.max_concurrency)
                .select_from(OperationResourcePool)
                .join(ResourcePool, OperationResourcePool.resource_pool_id == ResourcePool.id)
                .join(ProviderModel, ResourcePool.model_id == ProviderModel.id)
                .join(ResourcePoolKey, ResourcePoolKey.resource_pool_id == ResourcePool.id)
                .join(ApiKey, ResourcePoolKey.api_key_id == ApiKey.id)
                .where(
                    OperationResourcePool.operation_code == job.operation_code,
                    OperationResourcePool.required_capability == job.capability,
                    OperationResourcePool.enabled.is_(True),
                    ResourcePool.enabled.is_(True),
                    ResourcePoolKey.enabled.is_(True),
                    ProviderModel.enabled.is_(True),
                    ProviderModel.code == job.model_code,
                    ApiKey.enabled.is_(True),
                    ApiKey.status != ApiKeyStatus.DISABLED.value,
                    or_(ApiKey.cooldown_until.is_(None), ApiKey.cooldown_until <= now),
                    or_(ApiKey.remaining_balance.is_(None), ApiKey.remaining_balance > 0),
                    or_(
                        OperationResourcePool.organization_id == job.organization_id,
                        OperationResourcePool.organization_id.is_(None),
                    ),
                    or_(ResourcePool.organization_id == job.organization_id, ResourcePool.organization_id.is_(None)),
                    or_(ApiKey.organization_id == job.organization_id, ApiKey.organization_id.is_(None)),
                )
            )).all()
            resource_capacity[resource_key] = sum(dict(rows).values())
        capacity = resource_capacity[resource_key]
        if capacity < 1 or resource_active.get(resource_key, 0) >= capacity:
            continue
        selected.append(job)
        system_active += 1
        organization_active[job.organization_id] = organization_active.get(job.organization_id, 0) + 1
        user_active[job.created_by] = user_active.get(job.created_by, 0) + 1
        if job.batch_id:
            batch_active[job.batch_id] = batch_active.get(job.batch_id, 0) + 1
        resource_active[resource_key] = resource_active.get(resource_key, 0) + 1
    return selected


async def _release_job_reservation(session: AsyncSession, job: Job, *, idempotency_key: str) -> None:
    try:
        await release_reservation(
            session,
            organization_id=job.organization_id,
            reservation_id=job.quota_reservation_id,
            user_id=job.updated_by or job.created_by,
            idempotency_key=idempotency_key,
        )
    except AppError as error:
        if error.code != "quota.reservation_already_settled":
            raise


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
