from datetime import datetime, timezone
import logging
import socket

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import get_engine
from app.infrastructure.redis import get_redis_client
from app.models.quota import QuotaReservation, QuotaReservationStatus
from app.models.listing_workflow import ListingGenerationSession
from app.models.tasks import Job, JobStatus
from app.services.billing_service import release_reservation
from app.services.batch_tryon_review_service import continue_detailed_review_auto_regeneration
from app.services.task_service import dispatch_jobs, due_jobs, recover_stale_jobs as recover_jobs
from app.services.quick_listing_service import continue_quick_listing_generation, quick_job_metadata
from app.workers.celery_app import celery_app
from app.workers.runtime import run_worker_coroutine


logger = logging.getLogger(__name__)


@celery_app.task(name="system.heartbeat", ignore_result=False)
def heartbeat() -> dict[str, str]:
    return run_worker_coroutine(_heartbeat)


async def _heartbeat() -> dict[str, str]:
    timestamp = datetime.now(timezone.utc).isoformat()
    worker_name = socket.gethostname()
    try:
        await get_redis_client().set(f"worker:heartbeat:{worker_name}", timestamp, ex=180)
    except Exception:
        # Heartbeat reporting must never make the maintenance queue unhealthy.
        pass
    return {
        "status": "ok",
        "timestamp": timestamp,
        "worker": worker_name,
    }


@celery_app.task(name="system.dispatch_due_jobs", ignore_result=False)
def dispatch_due_jobs() -> dict[str, int]:
    return run_worker_coroutine(_dispatch_due_jobs)


async def _dispatch_due_jobs() -> dict[str, int]:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    dispatched = 0
    async with session_factory() as session:
        jobs = await due_jobs(session, get_settings())
        dispatched = await dispatch_jobs(session, jobs)
    return {"dispatched": dispatched}


@celery_app.task(name="system.continue_quick_listings", ignore_result=False)
def continue_quick_listings() -> dict[str, int]:
    return run_worker_coroutine(_continue_quick_listings)


async def _continue_quick_listings() -> dict[str, int]:
    """Recover quick flows if a Worker stopped after committing analysis."""
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    continued = 0
    async with session_factory() as session:
        jobs = list((await session.scalars(
            select(Job)
            .where(Job.operation_code == "listing.plan", Job.status == JobStatus.SUCCEEDED.value)
            .order_by(Job.finished_at.desc())
            .limit(100)
        )).all())
        for job in jobs:
            metadata = quick_job_metadata(job)
            if metadata is None:
                continue
            workflow = await session.get(ListingGenerationSession, str(metadata.get("listing_session_id") or ""))
            if workflow is None or workflow.image_batch_id or workflow.status == "failed":
                continue
            group = await continue_quick_listing_generation(session, get_settings(), planning_job=job)
            if group is not None:
                continued += 1
    return {"continued": continued}


@celery_app.task(name="system.continue_batch_review_luna", ignore_result=False)
def continue_batch_review_luna() -> dict[str, int]:
    return run_worker_coroutine(_continue_batch_review_luna)


async def _continue_batch_review_luna() -> dict[str, int]:
    """Recover Luna auto-regeneration after a Worker restart between both stages."""
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    continued = 0
    async with session_factory() as session:
        jobs = list((await session.scalars(
            select(Job)
            .where(
                Job.operation_code == "batch_tryon.prompt_analyze_detailed",
                Job.status == JobStatus.SUCCEEDED.value,
            )
            .order_by(Job.finished_at.desc())
            .limit(200)
        )).all())
        for job in jobs:
            metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
            result_metadata = job.result_json.get("metadata") if isinstance(job.result_json, dict) else None
            if not isinstance(metadata, dict) or not metadata.get("auto_regenerate"):
                continue
            if isinstance(result_metadata, dict) and result_metadata.get("auto_regeneration_job_id"):
                continue
            try:
                image_job, created = await continue_detailed_review_auto_regeneration(
                    session, get_settings(), analysis_job=job,
                )
                await session.commit()
                if image_job is not None and created:
                    await dispatch_jobs(session, [image_job])
                continued += 1
            except Exception as error:
                await session.rollback()
                logger.exception(
                    "batch_review_luna_recovery_failed analysis_job_id=%s error_type=%s",
                    job.id,
                    type(error).__name__,
                )
    return {"continued": continued}


@celery_app.task(name="system.recover_stale_jobs", ignore_result=False)
def recover_stale_jobs() -> dict[str, int]:
    return run_worker_coroutine(_recover_stale_jobs)


async def _recover_stale_jobs() -> dict[str, int]:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        recovered = await recover_jobs(session, get_settings())
        reconciled = await _reconcile_resource_leases(session)
        await session.commit()
    return {"recovered": recovered, "resource_leases_reconciled": reconciled}


async def _reconcile_resource_leases(session: AsyncSession) -> int:
    """Repair only counters that have not been renewed for a heartbeat window.

    A fresh Redis lease may briefly exist before the worker commits selected_key_id,
    so fresh counters must never be rewritten by reconciliation.
    """
    redis = get_redis_client()
    settings = get_settings()
    reconciled = 0
    for raw_key in await redis.keys("resource:key:*:inflight"):
        key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
        parts = key.split(":")
        if len(parts) != 4:
            continue
        key_id = parts[2]
        running = int(await session.scalar(select(func.count()).select_from(Job).where(
            Job.selected_key_id == key_id,
            Job.status == JobStatus.RUNNING.value,
        )) or 0)
        inflight = int(await redis.get(key) or 0)
        ttl = int(await redis.ttl(key))
        stale_lease = 0 <= ttl <= max(
            1,
            settings.resource_lease_ttl_seconds - settings.job_heartbeat_timeout_seconds,
        )
        if stale_lease and inflight != running:
            if running > 0:
                await redis.set(key, running, ex=settings.resource_lease_ttl_seconds)
            else:
                await redis.delete(key)
            reconciled += 1
    return reconciled


@celery_app.task(name="system.release_expired_reservations", ignore_result=False)
def release_expired_reservations() -> dict[str, int]:
    return run_worker_coroutine(_release_expired_reservations)


async def _release_expired_reservations() -> dict[str, int]:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    released = 0
    async with session_factory() as session:
        reservations = list((await session.scalars(select(QuotaReservation).where(
            QuotaReservation.status == QuotaReservationStatus.RESERVED.value,
            QuotaReservation.expires_at < datetime.now(timezone.utc),
            ~select(Job.id).where(
                Job.quota_reservation_id == QuotaReservation.id,
                Job.status.in_([
                    JobStatus.QUEUED.value,
                    JobStatus.WAITING_FOR_RESOURCE.value,
                    JobStatus.DISPATCHING.value,
                    JobStatus.RUNNING.value,
                    JobStatus.RETRY_WAITING.value,
                ]),
            ).exists(),
        ).with_for_update(skip_locked=True).limit(200))).all())
        for reservation in reservations:
            await release_reservation(
                session, organization_id=reservation.organization_id, reservation_id=reservation.id,
                user_id=reservation.created_by or reservation.updated_by,
                idempotency_key=f"reservation-expired:{reservation.id}", expired=True,
            )
            released += 1
        await session.commit()
    return {"released": released}
