from datetime import datetime, timezone
import socket

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import get_engine
from app.infrastructure.redis import get_redis_client
from app.models.quota import QuotaReservation, QuotaReservationStatus
from app.models.tasks import Job, JobStatus
from app.services.billing_service import release_reservation
from app.services.task_service import dispatch_job, due_jobs, recover_stale_jobs as recover_jobs
from app.workers.celery_app import celery_app
from app.workers.runtime import run_worker_coroutine


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
        for job in await due_jobs(session, get_settings()):
            try:
                dispatch_job(job)
                await session.commit()
                dispatched += 1
            except Exception:
                await session.rollback()
    return {"dispatched": dispatched}


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
    """Remove Redis inflight counters that no running DB job can own."""
    redis = get_redis_client()
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
        if running == 0:
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
