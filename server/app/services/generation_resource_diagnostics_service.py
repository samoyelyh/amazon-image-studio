from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from math import ceil
from urllib.parse import urlsplit

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.tasks import (
    ApiKey,
    ApiKeyUsageStat,
    Job,
    JobAttempt,
    JobStatus,
    OperationResourcePool,
    Provider,
    ProviderModel,
    ResourcePool,
    ResourcePoolKey,
)
from app.services.resource_pool_service import (
    current_concurrency,
    key_effective_capacity,
    key_recovery_state,
    masked_key,
)


UTC = timezone.utc


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, ceil(len(ordered) * percentile) - 1))]


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.hostname or ''}{f':{parsed.port}' if parsed.port else ''}"


def _stats(rows: list[ApiKeyUsageStat]) -> dict[str, object]:
    successes = [row for row in rows if row.status == "succeeded"]
    failures = [row for row in rows if row.status != "succeeded"]
    latencies = [int(row.latency_ms) for row in rows if row.latency_ms is not None]
    http = Counter(int(row.http_status) for row in rows if row.http_status is not None)
    timeout_count = sum("timeout" in (row.error_code or "").lower() for row in rows)
    auth_count = sum("auth" in (row.error_code or "").lower() for row in rows)
    last_success = max((row.created_at for row in successes), default=None)
    last_failure = max((row.created_at for row in failures), default=None)
    latest_failure = max(failures, key=lambda row: row.created_at, default=None)
    return {
        "requests": len(rows),
        "successes": len(successes),
        "failures": len(failures),
        "success_rate": round(len(successes) * 100 / len(rows), 2) if rows else None,
        "average_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "p90_latency_ms": _percentile(latencies, 0.90),
        "hourly_successes": len(successes),
        "http_429": http[429],
        "http_524": http[524],
        "http_5xx": sum(value for code, value in http.items() if 500 <= code <= 599),
        "timeouts": timeout_count,
        "auth_errors": auth_count,
        "last_success_at": last_success,
        "last_failure_at": last_failure,
        "latest_error": latest_failure.error_code if latest_failure else None,
    }


async def generation_resource_diagnostics(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
) -> dict[str, object]:
    now = datetime.now(UTC)
    since = now - timedelta(hours=1)
    providers = list((await session.scalars(select(Provider).order_by(Provider.name))).all())
    models = list((await session.scalars(select(ProviderModel))).all())
    pools = list((await session.scalars(select(ResourcePool).order_by(ResourcePool.priority, ResourcePool.name))).all())
    keys = list((await session.scalars(select(ApiKey).order_by(ApiKey.provider_id, ApiKey.label))).all())
    pool_links = list((await session.execute(
        select(ResourcePoolKey.resource_pool_id, ResourcePoolKey.api_key_id)
        .where(ResourcePoolKey.enabled.is_(True))
    )).all())
    bindings = list((await session.execute(
        select(
            OperationResourcePool.resource_pool_id,
            OperationResourcePool.operation_code,
            OperationResourcePool.required_capability,
        ).where(OperationResourcePool.enabled.is_(True))
    )).all())
    usage = list((await session.scalars(
        select(ApiKeyUsageStat).where(ApiKeyUsageStat.created_at >= since)
    )).all())
    status_counts = dict((await session.execute(
        select(Job.status, func.count()).group_by(Job.status)
    )).all())
    true_active = int(await session.scalar(
        select(func.count()).select_from(JobAttempt).where(
            JobAttempt.status == "running",
            JobAttempt.provider_requested_at.is_not(None),
            JobAttempt.finished_at.is_(None),
        )
    ) or 0)
    attempt_active_by_key = dict((await session.execute(
        select(JobAttempt.api_key_id, func.count())
        .where(
            JobAttempt.api_key_id.is_not(None),
            JobAttempt.status == "running",
            JobAttempt.provider_requested_at.is_not(None),
            JobAttempt.finished_at.is_(None),
        )
        .group_by(JobAttempt.api_key_id)
    )).all())

    key_by_id = {item.id: item for item in keys}
    model_by_id = {item.id: item for item in models}
    provider_by_id = {item.id: item for item in providers}
    pool_key_ids: dict[str, set[str]] = defaultdict(set)
    for pool_id, key_id in pool_links:
        pool_key_ids[pool_id].add(key_id)
    pool_bindings: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for pool_id, operation_code, capability in bindings:
        pool_bindings[pool_id].append((operation_code, capability))
    usage_by_key: dict[str, list[ApiKeyUsageStat]] = defaultdict(list)
    for row in usage:
        usage_by_key[row.api_key_id].append(row)
    usage_by_provider: dict[str, list[ApiKeyUsageStat]] = defaultdict(list)
    for key_id, rows in usage_by_key.items():
        key = key_by_id.get(key_id)
        if key:
            usage_by_provider[key.provider_id].extend(rows)

    key_active = {item.id: await current_concurrency(redis, item.id) for item in keys}
    redis_inflight = sum(key_active.values())
    worker_keys = await redis.keys("worker:heartbeat:*") if hasattr(redis, "keys") else []
    worker_names = sorted(
        (raw.decode() if isinstance(raw, bytes) else str(raw)).rsplit(":", 1)[-1]
        for raw in worker_keys
    )

    remaining = sum(
        int(status_counts.get(status, 0))
        for status in (
            JobStatus.QUEUED.value,
            JobStatus.WAITING_FOR_RESOURCE.value,
            JobStatus.DISPATCHING.value,
            JobStatus.RUNNING.value,
            JobStatus.RETRY_WAITING.value,
        )
    )
    recent_successes = int(await session.scalar(
        select(func.count()).select_from(Job).where(
            Job.status == JobStatus.SUCCEEDED.value,
            Job.finished_at >= since,
        )
    ) or 0)
    eta_minutes = ceil(remaining * 60 / recent_successes) if recent_successes else None

    pool_rows: list[dict[str, object]] = []
    for pool in pools:
        pool_keys = [key_by_id[key_id] for key_id in pool_key_ids[pool.id] if key_id in key_by_id]
        pool_usage = [row for key in pool_keys for row in usage_by_key.get(key.id, [])]
        metrics = _stats(pool_usage)
        operations = sorted({operation for operation, _ in pool_bindings[pool.id]})
        waiting = 0
        if operations:
            waiting = int(await session.scalar(
                select(func.count()).select_from(Job).where(
                    Job.operation_code.in_(operations),
                    Job.status.in_([
                        JobStatus.QUEUED.value,
                        JobStatus.WAITING_FOR_RESOURCE.value,
                        JobStatus.RETRY_WAITING.value,
                    ]),
                )
            ) or 0)
        configured = sum(key.max_concurrency for key in pool_keys if key.enabled)
        active = sum(key_active.get(key.id, 0) for key in pool_keys)
        pool_rows.append({
            "id": pool.id,
            "name": pool.name,
            "code": pool.code,
            "operation_codes": operations,
            "model_code": model_by_id.get(pool.model_id).code if model_by_id.get(pool.model_id) else None,
            "configured_capacity": configured,
            "active": active,
            "idle": max(0, configured - active),
            "waiting_jobs": waiting,
            "enabled": pool.enabled,
            "health": "degraded" if metrics["success_rate"] is not None and metrics["success_rate"] < 95 else "healthy",
            **metrics,
        })

    provider_rows: list[dict[str, object]] = []
    for provider in providers:
        provider_keys = [key for key in keys if key.provider_id == provider.id]
        configured = sum(key.max_concurrency for key in provider_keys if key.enabled)
        active = sum(int(attempt_active_by_key.get(key.id, 0)) for key in provider_keys)
        redis_active = sum(key_active.get(key.id, 0) for key in provider_keys)
        cooling = sum(
            bool(key.cooldown_until and _aware(key.cooldown_until) > now)
            for key in provider_keys
        )
        recovery_states = {
            key_recovery_state(key, key_active.get(key.id, 0), now)
            for key in provider_keys
        }
        provider_state = (
            "probing" if "probing" in recovery_states
            else "cooling" if "cooling" in recovery_states
            else "waiting_probe" if "waiting_probe" in recovery_states
            else "healthy" if "healthy" in recovery_states
            else "disabled"
        )
        next_probe_at = min(
            (
                _aware(key.cooldown_until)
                for key in provider_keys
                if key.cooldown_until and _aware(key.cooldown_until) > now
            ),
            default=None,
        )
        metrics = _stats(usage_by_provider.get(provider.id, []))
        provider_rows.append({
            "id": provider.id,
            "name": provider.name,
            "code": provider.code,
            "base_url": _safe_base_url(provider.base_url),
            "enabled": provider.enabled,
            "configured_capacity": configured,
            "effective_capacity": sum(
                key_effective_capacity(key, key_active.get(key.id, 0), now)
                for key in provider_keys
            ),
            "active": active,
            "redis_active": redis_active,
            "idle": max(0, configured - active),
            "cooling_keys": cooling,
            "recovering_keys": sum(
                key_recovery_state(key, key_active.get(key.id, 0), now)
                in {"cooling", "waiting_probe", "probing"}
                for key in provider_keys
            ),
            "probe_active": sum(
                key_recovery_state(key, key_active.get(key.id, 0), now) == "probing"
                for key in provider_keys
            ),
            "recovery_state": provider_state,
            "next_probe_at": next_probe_at,
            "cooldown_remaining_seconds": (
                max(0, ceil((next_probe_at - now).total_seconds()))
                if next_probe_at else 0
            ),
            "account_visibility": "上游账号明细不可见，由 New API 内部管理",
            **metrics,
        })

    key_rows: list[dict[str, object]] = []
    for key in keys:
        metrics = _stats(usage_by_key.get(key.id, []))
        active = int(attempt_active_by_key.get(key.id, 0))
        redis_active = key_active.get(key.id, 0)
        recovery_state = key_recovery_state(key, active, now)
        cooldown_until = _aware(key.cooldown_until)
        key_rows.append({
            "id": key.id,
            "provider_id": key.provider_id,
            "provider_name": provider_by_id.get(key.provider_id).name if provider_by_id.get(key.provider_id) else None,
            "label": key.label,
            "masked_secret": masked_key(key),
            "enabled": key.enabled,
            "status": key.status,
            "configured_capacity": key.max_concurrency,
            "effective_capacity": key_effective_capacity(key, active, now),
            "active": active,
            "redis_active": redis_active,
            "cooldown_until": key.cooldown_until,
            "cooldown_remaining_seconds": (
                max(0, ceil((cooldown_until - now).total_seconds()))
                if cooldown_until and cooldown_until > now else 0
            ),
            "next_probe_at": (
                key.cooldown_until if recovery_state == "cooling" else None
            ),
            "consecutive_failures": key.consecutive_failures,
            "recovery_state": recovery_state,
            "probe_active": recovery_state == "probing",
            "last_used_at": key.last_used_at,
            **metrics,
        })

    return {
        "checked_at": now,
        "system": {
            "configured_concurrency": settings.job_system_max_concurrency,
            "true_active_requests": true_active,
            "database_running": int(status_counts.get(JobStatus.RUNNING.value, 0)),
            "database_dispatching": int(status_counts.get(JobStatus.DISPATCHING.value, 0)),
            "redis_inflight": redis_inflight,
            "worker_active_estimate": true_active,
            "worker_names": worker_names,
            "queued": int(status_counts.get(JobStatus.QUEUED.value, 0)),
            "waiting_for_resource": int(status_counts.get(JobStatus.WAITING_FOR_RESOURCE.value, 0)),
            "retry_waiting": int(status_counts.get(JobStatus.RETRY_WAITING.value, 0)),
            "recent_hour_successes": recent_successes,
            "remaining_jobs": remaining,
            "eta_minutes": eta_minutes,
            "slot_mismatch": not (
                true_active == int(status_counts.get(JobStatus.RUNNING.value, 0)) == redis_inflight
            ),
        },
        "resource_pools": pool_rows,
        "providers": provider_rows,
        "keys": key_rows,
    }


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
