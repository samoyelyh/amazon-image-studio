from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from collections import defaultdict

from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.tasks import (
    ApiKey, ApiKeyStatus, ModelCapability, OperationResourcePool, Provider, ProviderModel,
    ResourcePool, ResourcePoolKey,
)
from app.providers.urls import normalize_base_url
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
    model_id: str
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
    operation_code: str, model_code: str, capability: str,
    additional_capabilities: set[str] | None = None,
    excluded_key_ids: set[str] | None = None,
) -> ResourceLease:
    now = datetime.now(UTC)
    excluded_key_ids = excluded_key_ids or set()
    rows = list((await session.execute(
        select(ResourcePool, ProviderModel, Provider, ResourcePoolKey, ApiKey)
        .join(OperationResourcePool, OperationResourcePool.resource_pool_id == ResourcePool.id)
        .join(ProviderModel, ResourcePool.model_id == ProviderModel.id)
        .join(Provider, ProviderModel.provider_id == Provider.id)
        .join(ResourcePoolKey, ResourcePoolKey.resource_pool_id == ResourcePool.id)
        .join(ApiKey, ResourcePoolKey.api_key_id == ApiKey.id)
        .where(
            ResourcePool.enabled.is_(True), ProviderModel.enabled.is_(True), Provider.enabled.is_(True),
            OperationResourcePool.enabled.is_(True),
            OperationResourcePool.operation_code == operation_code,
            OperationResourcePool.required_capability == capability,
            ResourcePoolKey.enabled.is_(True), ApiKey.enabled.is_(True),
            ProviderModel.code == model_code,
            or_(ResourcePool.organization_id == organization_id, ResourcePool.organization_id.is_(None)),
            or_(OperationResourcePool.organization_id == organization_id, OperationResourcePool.organization_id.is_(None)),
            or_(ApiKey.organization_id == organization_id, ApiKey.organization_id.is_(None)),
            ApiKey.status != ApiKeyStatus.DISABLED.value,
        )
        .order_by(
            OperationResourcePool.organization_id.desc(), OperationResourcePool.priority.asc(),
            ResourcePool.organization_id.desc(), ResourcePool.priority.asc(), ResourcePoolKey.priority.asc(),
            ApiKey.consecutive_failures.asc(), ResourcePoolKey.weight.desc(), ApiKey.last_used_at.asc(), ApiKey.id.asc(),
        )
    )).all())
    inflight_keys = {
        key.id: _redis_keys(key.id, now)[0]
        for _, _, _, _, key in rows
    }
    if inflight_keys and hasattr(redis, "mget"):
        inflight_values = await redis.mget(list(inflight_keys.values()))
    else:
        inflight_values = [await redis.get(redis_key) for redis_key in inflight_keys.values()]
    inflight_by_key = {
        key_id: int(value or 0)
        for key_id, value in zip(inflight_keys, inflight_values, strict=False)
    }
    rows.sort(key=lambda row: (
        row[4].consecutive_failures,
        row[0].priority,
        row[3].priority,
        -row[3].weight,
        inflight_by_key.get(row[4].id, 0) / max(1, row[4].max_concurrency),
        _aware(row[4].last_used_at) or datetime.min.replace(tzinfo=UTC),
        row[4].id,
    ))
    required_capabilities = {capability, *(additional_capabilities or set())}
    capabilities_by_model: dict[str, set[str]] = defaultdict(set)
    model_ids = {model.id for _, model, _, _, _ in rows}
    if model_ids:
        for model_id, model_capability in (await session.execute(select(
            ModelCapability.model_id, ModelCapability.capability,
        ).where(ModelCapability.model_id.in_(model_ids)))).all():
            capabilities_by_model[model_id].add(model_capability)
    for pool, model, provider, link, key in rows:
        if not required_capabilities.issubset(capabilities_by_model[model.id]) or key.id in excluded_key_ids:
            continue
        cooldown_until = _aware(key.cooldown_until)
        if cooldown_until and cooldown_until > now:
            continue
        if key.remaining_balance is not None and key.remaining_balance <= 0:
            continue
        keys = _redis_keys(key.id, now)
        day_ttl = int((datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC) - now).total_seconds()) + 60
        # Recover a previously failing channel with one canary request. A
        # successful request clears consecutive_failures and restores the
        # configured capacity; another failure cools the key again without
        # sending a full wave into an unhealthy upstream.
        effective_max_concurrency = 1 if key.consecutive_failures > 0 else key.max_concurrency
        acquired = int(await redis.eval(
            ACQUIRE_SCRIPT, 4, *keys, effective_max_concurrency, key.rpm_limit or 0,
            key.daily_limit or 0, settings.resource_lease_ttl_seconds, day_ttl,
        ))
        if acquired < 0:
            continue
        key.status = ApiKeyStatus.ACTIVE.value
        key.cooldown_until = None
        key.last_used_at = now
        await session.flush()
        return ResourceLease(
            pool.id, key.id, provider.id, model.id, provider.provider_type, normalize_base_url(provider.base_url),
            provider.config_json, model.upstream_model, model.config_json,
            decrypt_api_key(settings, key.secret_ciphertext),
        )
    raise AppError("resource_pool.no_available_key", "当前业务操作没有可用的模型资源池或 API Key", 503, {
        "operation_code": operation_code, "model_code": model_code, "capability": capability,
    })


async def validate_operation_binding(
    session: AsyncSession, *, organization_id: str, operation_code: str,
    model_code: str, capability: str, additional_capabilities: set[str] | None = None,
) -> ProviderModel:
    model = await session.scalar(
        select(ProviderModel)
        .select_from(OperationResourcePool)
        .join(ResourcePool, OperationResourcePool.resource_pool_id == ResourcePool.id)
        .join(ProviderModel, ResourcePool.model_id == ProviderModel.id)
        .where(
            OperationResourcePool.operation_code == operation_code,
            OperationResourcePool.required_capability == capability,
            OperationResourcePool.enabled.is_(True), ResourcePool.enabled.is_(True),
            ProviderModel.enabled.is_(True), ProviderModel.code == model_code,
            or_(OperationResourcePool.organization_id == organization_id, OperationResourcePool.organization_id.is_(None)),
            or_(ResourcePool.organization_id == organization_id, ResourcePool.organization_id.is_(None)),
        )
        .limit(1)
    )
    required_capabilities = {capability, *(additional_capabilities or set())}
    model_id = model.id if model else None
    available_capabilities = set((await session.scalars(select(ModelCapability.capability).where(
        ModelCapability.model_id == model_id,
    ))).all()) if model_id else set()
    missing_capabilities = sorted(required_capabilities - available_capabilities)
    if model_id is None or missing_capabilities:
        raise AppError(
            "resource_pool.operation_not_bound",
            "当前功能未绑定支持该能力的模型资源池，请联系管理员检查业务操作绑定",
            422,
            {"operation_code": operation_code, "model_code": model_code, "capability": capability,
             "missing_capabilities": missing_capabilities},
        )
    return model


async def resolve_operation_model_code(
    session: AsyncSession, *, organization_id: str, operation_code: str,
    capability: str, additional_capabilities: set[str] | None = None,
) -> str:
    """Resolve an enabled, keyed model from the same bindings used at execution time."""
    rows = (await session.execute(
        select(ProviderModel)
        .select_from(OperationResourcePool)
        .join(ResourcePool, OperationResourcePool.resource_pool_id == ResourcePool.id)
        .join(ProviderModel, ResourcePool.model_id == ProviderModel.id)
        .join(Provider, ProviderModel.provider_id == Provider.id)
        .join(ResourcePoolKey, ResourcePoolKey.resource_pool_id == ResourcePool.id)
        .join(ApiKey, ResourcePoolKey.api_key_id == ApiKey.id)
        .where(
            OperationResourcePool.operation_code == operation_code,
            OperationResourcePool.required_capability == capability,
            OperationResourcePool.enabled.is_(True), ResourcePool.enabled.is_(True),
            ProviderModel.enabled.is_(True), Provider.enabled.is_(True),
            ResourcePoolKey.enabled.is_(True), ApiKey.enabled.is_(True),
            ApiKey.status != ApiKeyStatus.DISABLED.value,
            or_(OperationResourcePool.organization_id == organization_id, OperationResourcePool.organization_id.is_(None)),
            or_(ResourcePool.organization_id == organization_id, ResourcePool.organization_id.is_(None)),
            or_(ApiKey.organization_id == organization_id, ApiKey.organization_id.is_(None)),
        )
        .order_by(
            OperationResourcePool.organization_id.desc(), OperationResourcePool.priority,
            ResourcePool.organization_id.desc(), ResourcePool.priority, ResourcePoolKey.priority,
        )
    )).scalars().unique().all()
    required = {capability, *(additional_capabilities or set())}
    for model in rows:
        capabilities = set((await session.scalars(select(ModelCapability.capability).where(
            ModelCapability.model_id == model.id,
        ))).all())
        if required.issubset(capabilities):
            return model.code
    raise AppError(
        "resource_pool.operation_not_bound",
        "当前功能没有绑定具备所需能力且含可用密钥的模型资源池，请联系管理员。",
        422,
        {"operation_code": operation_code, "capability": capability, "required": sorted(required)},
    )


async def release_resource(redis: Redis, lease: ResourceLease) -> None:
    key = _redis_keys(lease.key_id, datetime.now(UTC))[0]
    await redis.eval(RELEASE_SCRIPT, 1, key)


async def renew_resource_lease(redis: Redis, settings: Settings, lease: ResourceLease) -> None:
    """Renew only an existing inflight lease; never recreate a lost counter."""
    key = _redis_keys(lease.key_id, datetime.now(UTC))[0]
    if await redis.exists(key):
        await redis.expire(key, settings.resource_lease_ttl_seconds)


async def cool_down_key(
    session: AsyncSession, redis: Redis, settings: Settings, key_id: str, *, seconds: int | None = None,
) -> None:
    key = await session.get(ApiKey, key_id, with_for_update=True)
    if key is None:
        return
    if seconds is not None:
        duration = seconds
    else:
        # Keep the adaptive multiplier configurable, but cap it so deployments
        # that need fast recovery probes can enforce a short maximum wait.
        multiplier = 2 ** min(key.consecutive_failures, 4)
        duration = min(
            settings.resource_key_cooldown_max_seconds,
            settings.resource_key_cooldown_seconds * multiplier,
        )
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


def key_recovery_state(key: ApiKey, active: int, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    cooldown_until = _aware(key.cooldown_until)
    if not key.enabled or key.status == ApiKeyStatus.DISABLED.value:
        return "disabled"
    if key.consecutive_failures > 0 and active > 0:
        return "probing"
    if cooldown_until and cooldown_until > now:
        return "cooling"
    if key.consecutive_failures > 0:
        return "waiting_probe"
    return "healthy"


def key_effective_capacity(key: ApiKey, active: int, now: datetime | None = None) -> int:
    state = key_recovery_state(key, active, now)
    if state in {"disabled", "cooling"}:
        return 0
    if state in {"probing", "waiting_probe"}:
        return 1
    return key.max_concurrency


async def current_concurrency(redis: Redis, key_id: str) -> int:
    value = await redis.get(_redis_keys(key_id, datetime.now(UTC))[0])
    return int(value or 0)
