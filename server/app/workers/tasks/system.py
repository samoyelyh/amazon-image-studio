from datetime import datetime, timezone

import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import get_engine
from app.models.quota import QuotaReservation, QuotaReservationStatus
from app.services.billing_service import release_reservation
from app.services.task_service import dispatch_job, due_jobs, recover_stale_jobs as recover_jobs
from app.workers.celery_app import celery_app


@celery_app.task(name="system.heartbeat", ignore_result=False)
def heartbeat() -> dict[str, str]:
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@celery_app.task(name="system.dispatch_due_jobs", ignore_result=False)
def dispatch_due_jobs() -> dict[str, int]:
    return asyncio.run(_dispatch_due_jobs())


async def _dispatch_due_jobs() -> dict[str, int]:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    dispatched = 0
    async with session_factory() as session:
        for job in await due_jobs(session):
            try:
                dispatch_job(job)
                await session.commit()
                dispatched += 1
            except Exception:
                await session.rollback()
    return {"dispatched": dispatched}


@celery_app.task(name="system.recover_stale_jobs", ignore_result=False)
def recover_stale_jobs() -> dict[str, int]:
    return asyncio.run(_recover_stale_jobs())


async def _recover_stale_jobs() -> dict[str, int]:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        recovered = await recover_jobs(session, get_settings())
        await session.commit()
    return {"recovered": recovered}


@celery_app.task(name="system.release_expired_reservations", ignore_result=False)
def release_expired_reservations() -> dict[str, int]:
    return asyncio.run(_release_expired_reservations())


async def _release_expired_reservations() -> dict[str, int]:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    released = 0
    async with session_factory() as session:
        reservations = list((await session.scalars(select(QuotaReservation).where(
            QuotaReservation.status == QuotaReservationStatus.RESERVED.value,
            QuotaReservation.expires_at < datetime.now(timezone.utc),
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
