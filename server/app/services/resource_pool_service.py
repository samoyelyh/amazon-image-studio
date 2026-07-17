from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.tasks import ApiKey, ApiKeyStatus, ModelCapability, Provider, ProviderModel, ResourcePool, ResourcePoolKey
from app.security.api_keys import api_key_fingerprint, decrypt_api_key, encrypt_api_key


UTC = timezone.utc
ACQUIRE_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 1 then return -4 end
local active = tonumber(redis.call('GET', KEYS[1]) or '0')
if active >= tonumber(ARGV[1]) then return -1 end
local rpm = tonumber(redis.call('GET', KEYS[3]) or '0')
if tonumber(ARGV[2]) > 0 and rpm >= tonumber(ARGV[2]) then return -2 end
local daily = tonumber(redis.call('GET', KEYS[4]) or '0')
if tonumber(ARGV[3]) > 0 and daily >= tonumber(ARGV[3]) then return -3 end
active = redis.call('INCR', KEYS[1]); redis.call('EXPIRE', KEYS[1], ARGV[4])
rpm = redis.call('INCR', KEYS[3]); redis.call('EXPIRE', KEYS[3], 60)
daily = redis.call('INCR', KEYS[4]); redis.call('EXPIRE', KEYS[4], ARGV[5])
return active
"""
RELEASE_SCRIPT = """
local active = tonumber(redis.call('GET', KEYS[1]) or '0')
if active <= 1 then redis.call('DEL', KEYS[1]); return 0 end
return redis.call('DECR', KEYS[1])
"""


@dataclass(frozen=True)
class ResourceLease:
    pool_id: str
    key_id: str
    provider_id: str
    provider_type: str
    base_url: str
    provider_config: dict[str, object]
    upstream_model: str
    model_config: dict[str, object]
    api_key: str


def _redis_keys(key_id: str, now: datetime) -> tuple[str, str, str, str]:
    prefix = f"resource:key:{key_id}"
    return f"{prefix}:inflight", f"{prefix}:cooldown", f"{prefix}:rpm", f"{prefix}:daily:{now:%Y%m%d}"


async def acquire_resource(
    session: AsyncSession, redis: Redis, settings: Settings, *, organization_id: str,
    model_code: str, capability: str, excluded_key_ids: set[str] | None = None,
) -> ResourceLease:
    now = datetime.now(UTC)
    excluded_key_ids = excluded_key_ids or set()
    rows = (await session.execute(
        select(ResourcePool, ProviderModel, Provider, ResourcePoolKey, ApiKey)
        .join(ProviderModel, ResourcePool.model_id == ProviderModel.id)
        .join(Provider, ProviderModel.provider_id == Provider.id)
        .join(ResourcePoolKey, ResourcePoolKey.resource_pool_id == ResourcePool.id)
        .join(ApiKey, ResourcePoolKey.api_key_id == ApiKey.id)
        .where(
            ResourcePool.enabled.is_(True), ProviderModel.enabled.is_(True), Provider.enabled.is_(True),
            ResourcePoolKey.enabled.is_(True), ApiKey.enabled.is_(True),
            ProviderModel.code == model_code,
            or_(ResourcePool.organization_id == organization_id, ResourcePool.organization_id.is_(None)),
            or_(ApiKey.organization_id == organization_id, ApiKey.organization_id.is_(None)),
            ApiKey.status != ApiKeyStatus.DISABLED.value,
        )
        .order_by(
            ResourcePool.organization_id.desc(), ResourcePool.priority.asc(), ResourcePoolKey.priority.asc(),
            ApiKey.consecutive_failures.asc(), ResourcePoolKey.weight.desc(), ApiKey.last_used_at.asc(), ApiKey.id.asc(),
        )
    )).all()
    capable_models = set((await session.scalars(select(ModelCapability.model_id).where(ModelCapability.capability == capability))).all())
    for pool, model, provider, link, key in rows:
        if model.id not in capable_models or key.id in excluded_key_ids:
            continue
        cooldown_until = _aware(key.cooldown_until)
        if cooldown_until and cooldown_until > now:
            continue
        if key.remaining_balance is not None and key.remaining_balance <= 0:
            continue
        keys = _redis_keys(key.id, now)
        day_ttl = int((datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC) - now).total_seconds()) + 60
        acquired = int(await redis.eval(
            ACQUIRE_SCRIPT, 4, *keys, key.max_concurrency, key.rpm_limit or 0,
            key.daily_limit or 0, settings.resource_lease_ttl_seconds, day_ttl,
        ))
        if acquired < 0:
            continue
        key.status = ApiKeyStatus.ACTIVE.value
        key.cooldown_until = None
        key.last_used_at = now
        await session.flush()
        return ResourceLease(
            pool.id, key.id, provider.id, provider.provider_type, provider.base_url,
            provider.config_json, model.upstream_model, model.config_json,
            decrypt_api_key(settings, key.secret_ciphertext),
        )
    raise AppError("resource_pool.no_available_key", "No API key is currently available for this model and capability", 503, {
        "model_code": model_code, "capability": capability,
    })


async def release_resource(redis: Redis, lease: ResourceLease) -> None:
    key = _redis_keys(lease.key_id, datetime.now(UTC))[0]
    await redis.eval(RELEASE_SCRIPT, 1, key)


async def cool_down_key(
    session: AsyncSession, redis: Redis, settings: Settings, key_id: str, *, seconds: int | None = None,
) -> None:
    duration = seconds or settings.resource_key_cooldown_seconds
    key = await session.get(ApiKey, key_id, with_for_update=True)
    if key is None:
        return
    key.status = ApiKeyStatus.COOLING.value
    key.cooldown_until = datetime.now(UTC) + timedelta(seconds=duration)
    key.consecutive_failures += 1
    await redis.set(_redis_keys(key_id, datetime.now(UTC))[1], "1", ex=duration)
    await session.flush()


async def mark_key_success(session: AsyncSession, key_id: str) -> None:
    key = await session.get(ApiKey, key_id, with_for_update=True)
    if key:
        key.status = ApiKeyStatus.ACTIVE.value
        key.cooldown_until = None
        key.consecutive_failures = 0
        await session.flush()


def create_api_key(settings: Settings, *, provider_id: str, label: str, secret: str, organization_id: str | None,
                   max_concurrency: int, rpm_limit: int | None, daily_limit: int | None, user_id: str) -> ApiKey:
    value = secret.strip()
    return ApiKey(
        provider_id=provider_id, organization_id=organization_id, label=label.strip(),
        secret_ciphertext=encrypt_api_key(settings, value), fingerprint=api_key_fingerprint(value),
        secret_suffix=value[-4:], max_concurrency=max_concurrency, rpm_limit=rpm_limit, daily_limit=daily_limit,
        created_by=user_id, updated_by=user_id,
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def masked_key(key: ApiKey) -> str:
    return f"****{key.secret_suffix}"


async def current_concurrency(redis: Redis, key_id: str) -> int:
    value = await redis.get(_redis_keys(key_id, datetime.now(UTC))[0])
    return int(value or 0)
