from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.content import Project
from app.models.tasks import Job, JobAttempt, JobStatus
from app.schemas.tasks import JobPage, JobResponse, JobSubmitRequest
from app.services.billing_service import release_reservation, reserve_quota


UTC = timezone.utc
TERMINAL_JOB_STATUSES = {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}


def request_hash(payload: JobSubmitRequest) -> str:
    encoded = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


async def submit_job(
    session: AsyncSession, settings: Settings, *, organization_id: str, user_id: str, payload: JobSubmitRequest,
) -> tuple[Job, bool]:
    fingerprint = request_hash(payload)
    existing = await session.scalar(select(Job).where(
        Job.organization_id == organization_id, Job.idempotency_key == payload.idempotency_key,
    ).with_for_update())
    if existing:
        if existing.request_hash != fingerprint:
            raise AppError("job.idempotency_conflict", "Idempotency key was already used with different job input", 409)
        return existing, False
    if payload.project_id:
        project = await session.scalar(select(Project.id).where(
            Project.id == payload.project_id, Project.organization_id == organization_id, Project.deleted_at.is_(None),
        ))
        if project is None:
            raise AppError("project.not_found", "Project was not found", 404)
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
        organization_id=organization_id, project_id=payload.project_id,
        quota_reservation_id=reservation.id, operation_code=payload.operation_code,
        workspace_type=payload.workspace_type, queue_name=payload.queue_name,
        capability=payload.capability, model_code=payload.model_code, input_json=payload.input,
        idempotency_key=payload.idempotency_key, request_hash=fingerprint,
        max_attempts=settings.job_max_attempts, created_by=user_id, updated_by=user_id,
    )
    session.add(job)
    await session.flush()
    reservation.reference_type = "job"
    reservation.reference_id = job.id
    return job, True


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
    await release_reservation(
        session, organization_id=job.organization_id, reservation_id=job.quota_reservation_id,
        user_id=job.updated_by, idempotency_key=f"job-cancel:{job.id}",
    )


async def claim_job(session: AsyncSession, settings: Settings, job_id: str) -> Job | None:
    job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None or job.status in TERMINAL_JOB_STATUSES:
        return None
    now = datetime.now(UTC)
    if job.cancel_requested_at:
        await finalize_cancelled_job(session, job)
        return None
    heartbeat = _aware(job.heartbeat_at)
    if job.status == JobStatus.RUNNING.value and heartbeat and heartbeat > now - timedelta(seconds=settings.job_heartbeat_timeout_seconds):
        return None
    job.status = JobStatus.RUNNING.value
    job.progress = max(job.progress, 1)
    job.started_at = job.started_at or now
    job.heartbeat_at = now
    job.error_code = None
    job.error_message = None
    await session.flush()
    return job


def create_attempt(job: Job, *, provider_id: str | None = None, pool_id: str | None = None, key_id: str | None = None) -> JobAttempt:
    job.attempts += 1
    job.heartbeat_at = datetime.now(UTC)
    return JobAttempt(
        organization_id=job.organization_id, job_id=job.id, attempt_number=job.attempts,
        provider_id=provider_id, resource_pool_id=pool_id, api_key_id=key_id,
        status="running", started_at=datetime.now(UTC),
    )


async def schedule_retry_or_fail(session: AsyncSession, job: Job, *, code: str, message: str) -> None:
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
        job.next_retry_at = datetime.now(UTC) + timedelta(seconds=min(300, 2 ** max(job.attempts, 1) * 5))
    else:
        job.status = JobStatus.FAILED.value
        job.finished_at = datetime.now(UTC)
        await release_reservation(
            session, organization_id=job.organization_id, reservation_id=job.quota_reservation_id,
            user_id=job.updated_by, idempotency_key=f"job-failed:{job.id}",
        )
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
    for job in jobs:
        await schedule_retry_or_fail(session, job, code="job.worker_lost", message="Worker heartbeat expired; job recovered")
    return len(jobs)


async def due_jobs(session: AsyncSession, limit: int = 100) -> list[Job]:
    now = datetime.now(UTC)
    return list((await session.scalars(select(Job).where(
        Job.dispatched_at.is_(None),
        or_(Job.status == JobStatus.QUEUED.value,
            (Job.status == JobStatus.RETRY_WAITING.value) & (Job.next_retry_at <= now)),
    ).order_by(Job.created_at).limit(limit).with_for_update(skip_locked=True))).all())


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
