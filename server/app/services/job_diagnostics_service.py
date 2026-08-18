from collections import Counter
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.tasks import (
    ApiKey, ApiKeyStatus, Job, JobAttempt, JobBatch, JobStatus,
    OperationResourcePool, Provider, ProviderModel, ResourcePool, ResourcePoolKey,
)
from app.schemas.tasks import JobBatchDiagnosticsResponse
from app.services.resource_pool_service import key_effective_capacity, key_recovery_state
from app.services.task_service import effective_batch_jobs


UTC = timezone.utc


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _actual_max_concurrency(executions: list[object], now: datetime) -> int:
    events: list[tuple[datetime, int]] = []
    for execution in executions:
        started = _aware(getattr(execution, "started_at", None))
        if started is None:
            continue
        finished = _aware(getattr(execution, "finished_at", None)) or now
        events.append((started, 1))
        events.append((finished, -1))
    active = 0
    peak = 0
    # End events are applied before start events at the same timestamp.
    for _, change in sorted(events, key=lambda item: (item[0], item[1])):
        active += change
        peak = max(peak, active)
    return peak


def _resource_capacity_summary(
    rows: list[tuple[str, str, int, datetime | None, object | None]],
    now: datetime,
) -> tuple[int, int, list[str], list[str]]:
    keys: dict[str, tuple[int, datetime | None, object | None]] = {}
    pool_ids: set[str] = set()
    for pool_id, key_id, max_concurrency, cooldown_until, remaining_balance in rows:
        pool_ids.add(pool_id)
        keys[key_id] = (max_concurrency, _aware(cooldown_until), remaining_balance)
    configured = sum(value[0] for value in keys.values())
    available = sum(
        max_concurrency
        for max_concurrency, cooldown_until, remaining_balance in keys.values()
        if (cooldown_until is None or cooldown_until <= now)
        and (remaining_balance is None or remaining_balance > 0)
    )
    cooling = sum(
        cooldown_until is not None and cooldown_until > now
        for _, cooldown_until, _ in keys.values()
    )
    depleted = sum(
        remaining_balance is not None and remaining_balance <= 0
        for _, _, remaining_balance in keys.values()
    )
    availability_reasons: list[str] = []
    if cooling:
        availability_reasons.append(
            f"{cooling} 个资源 Key 因上游错误临时冷却，恢复后将自动重试"
        )
    if depleted:
        availability_reasons.append(f"{depleted} 个资源 Key 可用余额不足")
    return configured, available, sorted(pool_ids), availability_reasons


async def batch_diagnostics(
    session: AsyncSession,
    settings: Settings,
    *,
    batch: JobBatch,
) -> JobBatchDiagnosticsResponse:
    jobs, _ = await effective_batch_jobs(session, batch)
    job_ids = [job.id for job in jobs]
    status_counts = Counter(job.status for job in jobs)
    active_jobs = sum(
        job.status == JobStatus.RUNNING.value
        and job.started_at is not None
        and job.finished_at is None
        for job in jobs
    )
    stale_threshold = datetime.now(UTC) - timedelta(seconds=settings.job_heartbeat_timeout_seconds)
    stale_jobs = sum(
        job.status == JobStatus.RUNNING.value
        and (_aware(job.heartbeat_at) is None or _aware(job.heartbeat_at) < stale_threshold)
        for job in jobs
    )
    attempts = list((await session.scalars(
        select(JobAttempt).where(JobAttempt.job_id.in_(job_ids)).order_by(JobAttempt.started_at)
    )).all()) if job_ids else []
    now = datetime.now(UTC)
    capacity_rows = (await session.execute(
        select(
            ResourcePool.id,
            ApiKey.id,
            ApiKey.max_concurrency,
            ApiKey.cooldown_until,
            ApiKey.remaining_balance,
        )
        .select_from(OperationResourcePool)
        .join(ResourcePool, OperationResourcePool.resource_pool_id == ResourcePool.id)
        .join(ProviderModel, ResourcePool.model_id == ProviderModel.id)
        .join(ResourcePoolKey, ResourcePoolKey.resource_pool_id == ResourcePool.id)
        .join(ApiKey, ResourcePoolKey.api_key_id == ApiKey.id)
        .where(
            OperationResourcePool.operation_code == batch.operation_code,
            OperationResourcePool.required_capability == batch.capability,
            OperationResourcePool.enabled.is_(True),
            ResourcePool.enabled.is_(True),
            ResourcePoolKey.enabled.is_(True),
            ProviderModel.enabled.is_(True),
            ProviderModel.code == batch.model_code,
            ApiKey.enabled.is_(True),
            ApiKey.status != ApiKeyStatus.DISABLED.value,
            or_(
                OperationResourcePool.organization_id == batch.organization_id,
                OperationResourcePool.organization_id.is_(None),
            ),
            or_(ResourcePool.organization_id == batch.organization_id, ResourcePool.organization_id.is_(None)),
            or_(ApiKey.organization_id == batch.organization_id, ApiKey.organization_id.is_(None)),
        )
    )).all()
    key_capacity, available_key_capacity, resource_pool_ids, availability_reasons = (
        _resource_capacity_summary(list(capacity_rows), now)
    )
    channel_rows = (await session.execute(
        select(Provider, ApiKey)
        .select_from(OperationResourcePool)
        .join(ResourcePool, OperationResourcePool.resource_pool_id == ResourcePool.id)
        .join(ProviderModel, ResourcePool.model_id == ProviderModel.id)
        .join(Provider, ProviderModel.provider_id == Provider.id)
        .join(ResourcePoolKey, ResourcePoolKey.resource_pool_id == ResourcePool.id)
        .join(ApiKey, ResourcePoolKey.api_key_id == ApiKey.id)
        .where(
            OperationResourcePool.operation_code == batch.operation_code,
            OperationResourcePool.required_capability == batch.capability,
            OperationResourcePool.enabled.is_(True),
            ResourcePool.enabled.is_(True),
            ResourcePoolKey.enabled.is_(True),
            ProviderModel.enabled.is_(True),
            ProviderModel.code == batch.model_code,
            ApiKey.enabled.is_(True),
            ApiKey.status != ApiKeyStatus.DISABLED.value,
            or_(
                OperationResourcePool.organization_id == batch.organization_id,
                OperationResourcePool.organization_id.is_(None),
            ),
            or_(ResourcePool.organization_id == batch.organization_id, ResourcePool.organization_id.is_(None)),
            or_(ApiKey.organization_id == batch.organization_id, ApiKey.organization_id.is_(None)),
        )
    )).all()
    channels_by_key = {key.id: (provider, key) for provider, key in channel_rows}
    active_by_key = dict((await session.execute(
        select(JobAttempt.api_key_id, func.count())
        .join(Job, Job.id == JobAttempt.job_id)
        .where(
            JobAttempt.api_key_id.in_(list(channels_by_key)),
            JobAttempt.status == "running",
            JobAttempt.provider_requested_at.is_not(None),
            JobAttempt.finished_at.is_(None),
            Job.status == JobStatus.RUNNING.value,
        )
        .group_by(JobAttempt.api_key_id)
    )).all()) if channels_by_key else {}
    resource_channels = []
    for provider, key in channels_by_key.values():
        active = int(active_by_key.get(key.id, 0))
        state = key_recovery_state(key, active, now)
        cooldown_until = _aware(key.cooldown_until)
        resource_channels.append({
            "provider_id": provider.id,
            "provider_name": provider.name,
            "provider_code": provider.code,
            "key_id": key.id,
            "key_label": key.label,
            "recovery_state": state,
            "configured_capacity": key.max_concurrency,
            "effective_capacity": key_effective_capacity(key, active, now),
            "active": active,
            "consecutive_failures": key.consecutive_failures,
            "cooldown_until": key.cooldown_until,
            "cooldown_remaining_seconds": (
                max(0, int((cooldown_until - now).total_seconds()))
                if cooldown_until and cooldown_until > now else 0
            ),
            "probe_active": state == "probing",
        })

    broker = Redis.from_url(settings.resolved_celery_broker_url, decode_responses=True)
    runtime_redis = Redis.from_url(settings.redis_url.get_secret_value(), decode_responses=True)
    queue_name = jobs[0].queue_name if jobs else {
        "listing": "listing_queue", "batch_tryon": "batch_tryon_queue", "aplus": "aplus_queue",
    }.get(batch.workspace_type, "default")
    try:
        broker_queue_length = int(await broker.llen(queue_name))
        worker_keys = await runtime_redis.keys("worker:heartbeat:*")
        online_workers = sorted(key.rsplit(":", 1)[-1] for key in worker_keys)
    finally:
        await broker.aclose()
        await runtime_redis.aclose()

    first_attempt_started_at: dict[str, datetime] = {}
    for attempt in attempts:
        started_at = _aware(attempt.started_at)
        if started_at is None:
            continue
        previous = first_attempt_started_at.get(attempt.job_id)
        if previous is None or started_at < previous:
            first_attempt_started_at[attempt.job_id] = started_at
    queue_waits = [
        max(0, int((first_attempt_started_at[job.id] - _aware(job.created_at)).total_seconds() * 1000))
        for job in jobs if job.id in first_attempt_started_at and job.created_at
    ]
    generation_times = [int(job.generation_duration_ms or 0) for job in jobs if job.generation_duration_ms]
    errors = [attempt for attempt in attempts if attempt.error_code]
    latest_error = errors[-1] if errors else None
    completed = [_aware(job.finished_at) for job in jobs if job.finished_at]
    effective_limits = {
        "Worker": settings.celery_worker_concurrency,
        "单用户": settings.job_user_max_concurrency,
        "团队": settings.job_organization_max_concurrency,
        "系统": settings.job_system_max_concurrency,
        "资源池": key_capacity,
    }
    effective_concurrency = min(batch.concurrency, *effective_limits.values())
    limitation_reasons = [
        f"{name}并发上限为 {capacity}"
        for name, capacity in effective_limits.items()
        if capacity < batch.concurrency
    ]
    if not online_workers:
        limitation_reasons.append("当前没有可用 Worker 心跳")
    return JobBatchDiagnosticsResponse(
        batch_id=batch.id,
        status_counts=dict(status_counts),
        configured_concurrency=batch.concurrency,
        effective_concurrency=effective_concurrency,
        actual_max_concurrency=_actual_max_concurrency(list(attempts), now),
        worker_concurrency=settings.celery_worker_concurrency,
        active_jobs=active_jobs,
        stale_jobs=stale_jobs,
        queue_name=queue_name,
        broker_queue_length=broker_queue_length,
        online_workers=online_workers,
        resource_pool_ids=resource_pool_ids,
        resource_key_capacity=key_capacity,
        resource_available_capacity=available_key_capacity,
        attempts=len(attempts),
        retries=sum(attempt.attempt_number > 1 for attempt in attempts),
        http_status_counts=dict(Counter(str(item.http_status) for item in attempts if item.http_status)),
        error_code_counts=dict(Counter(item.error_code for item in attempts if item.error_code)),
        average_queue_wait_ms=round(sum(queue_waits) / len(queue_waits)) if queue_waits else None,
        average_generation_ms=round(sum(generation_times) / len(generation_times)) if generation_times else None,
        latest_completed_at=max(completed) if completed else None,
        latest_error_code=latest_error.error_code if latest_error else None,
        latest_error_message=latest_error.error_message if latest_error else None,
        limitation_reasons=limitation_reasons,
        availability_reasons=availability_reasons,
        resource_channels=resource_channels,
    )
