from fastapi import APIRouter, Depends, Request, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.infrastructure.redis import get_redis_client
from app.models.tasks import ApiKey, ModelCapability, OperationResourcePool, Provider, ProviderModel, ResourcePool, ResourcePoolKey
from app.schemas.tasks import (
    ApiKeyCreateRequest, ApiKeyResponse, OperationPoolAttachRequest, PoolKeyAttachRequest, ProviderCreateRequest,
    ProviderModelCreateRequest, ProviderModelResponse, ProviderResponse,
    ResourcePoolCreateRequest, ResourcePoolResponse,
)
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.resource_pool_service import create_api_key, current_concurrency, masked_key


router = APIRouter(prefix="/resource-pools", tags=["resource-pools"])


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(
    session: AsyncSession = Depends(get_db_session),
    _: Principal = Depends(require_permissions("resource_pools.read")),
) -> list[ProviderResponse]:
    items = list((await session.scalars(select(Provider).where(Provider.enabled.is_(True)).order_by(Provider.code))).all())
    return [ProviderResponse.model_validate(item) for item in items]


@router.post("/providers", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
async def add_provider(
    payload: ProviderCreateRequest, request: Request, session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("resource_pools.manage")),
) -> ProviderResponse:
    if await session.scalar(select(Provider.id).where(Provider.code == payload.code)):
        raise AppError("resource_pool.provider_exists", "Provider code already exists", 409)
    provider = Provider(
        code=payload.code, name=payload.name.strip(), provider_type=payload.provider_type,
        base_url=str(payload.base_url).rstrip("/"), config_json=payload.config,
        created_by=principal.user.id, updated_by=principal.user.id,
    )
    session.add(provider)
    await session.flush()
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="provider.create", resource_type="provider", resource_id=provider.id)
    await session.commit()
    return ProviderResponse.model_validate(provider)


@router.post("/providers/{provider_id}/models", response_model=ProviderModelResponse, status_code=status.HTTP_201_CREATED)
async def add_model(
    provider_id: str, payload: ProviderModelCreateRequest, request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("resource_pools.manage")),
) -> ProviderModelResponse:
    if await session.get(Provider, provider_id) is None:
        raise AppError("resource_pool.provider_not_found", "Provider was not found", 404)
    if await session.scalar(select(ProviderModel.id).where(ProviderModel.provider_id == provider_id, ProviderModel.code == payload.code)):
        raise AppError("resource_pool.model_exists", "Model code already exists for this provider", 409)
    model = ProviderModel(
        provider_id=provider_id, code=payload.code, upstream_model=payload.upstream_model,
        name=payload.name.strip(), config_json=payload.config,
        created_by=principal.user.id, updated_by=principal.user.id,
    )
    session.add(model)
    await session.flush()
    for capability in payload.capabilities:
        session.add(ModelCapability(model_id=model.id, capability=capability, created_by=principal.user.id))
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="provider.model.create", resource_type="model", resource_id=model.id)
    await session.commit()
    return _model_response(model, payload.capabilities)


@router.post("", response_model=ResourcePoolResponse, status_code=status.HTTP_201_CREATED)
async def add_pool(
    payload: ResourcePoolCreateRequest, request: Request, session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("resource_pools.manage")),
) -> ResourcePoolResponse:
    model = await session.get(ProviderModel, payload.model_id)
    if model is None:
        raise AppError("resource_pool.model_not_found", "Model was not found", 404)
    if await session.scalar(select(ResourcePool.id).where(ResourcePool.organization_id == payload.organization_id, ResourcePool.code == payload.code)):
        raise AppError("resource_pool.pool_exists", "Resource pool code already exists in this scope", 409)
    pool = ResourcePool(
        model_id=payload.model_id, organization_id=payload.organization_id, code=payload.code,
        name=payload.name.strip(), priority=payload.priority, weight=payload.weight,
        created_by=principal.user.id, updated_by=principal.user.id,
    )
    session.add(pool)
    await session.flush()
    capabilities = list((await session.scalars(select(ModelCapability.capability).where(ModelCapability.model_id == model.id))).all())
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=payload.organization_id,
                  action="resource_pool.create", resource_type="resource_pool", resource_id=pool.id)
    await session.commit()
    return _pool_response(pool, model.code, capabilities, 0, {})


@router.get("", response_model=list[ResourcePoolResponse])
async def list_pools(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("resource_pools.read")),
) -> list[ResourcePoolResponse]:
    organization_id = principal.organization.id if principal.organization else None
    pools = list((await session.scalars(select(ResourcePool).where(
        ResourcePool.enabled.is_(True),
        (ResourcePool.organization_id == organization_id) | ResourcePool.organization_id.is_(None),
    ).order_by(ResourcePool.priority, ResourcePool.code))).all())
    responses = []
    for pool in pools:
        model = await session.get(ProviderModel, pool.model_id)
        capabilities = list((await session.scalars(select(ModelCapability.capability).where(ModelCapability.model_id == pool.model_id))).all())
        count = int(await session.scalar(select(func.count()).select_from(ResourcePoolKey).where(
            ResourcePoolKey.resource_pool_id == pool.id, ResourcePoolKey.enabled.is_(True),
        )) or 0)
        bindings: dict[str, list[str]] = {}
        rows = (await session.execute(select(
            OperationResourcePool.operation_code, OperationResourcePool.required_capability,
        ).where(
            OperationResourcePool.resource_pool_id == pool.id,
            OperationResourcePool.enabled.is_(True),
            (OperationResourcePool.organization_id == organization_id) | OperationResourcePool.organization_id.is_(None),
        ).order_by(OperationResourcePool.priority))).all()
        for operation_code, required_capability in rows:
            bindings.setdefault(operation_code, []).append(required_capability)
        responses.append(_pool_response(pool, model.code, capabilities, count, bindings))
    return responses


@router.post("/keys", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def add_api_key(
    payload: ApiKeyCreateRequest, request: Request, session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), redis: Redis = Depends(get_redis_client),
    principal: Principal = Depends(require_permissions("resource_pools.manage")),
) -> ApiKeyResponse:
    if await session.get(Provider, payload.provider_id) is None:
        raise AppError("resource_pool.provider_not_found", "Provider was not found", 404)
    key = create_api_key(
        settings, provider_id=payload.provider_id, label=payload.label, secret=payload.secret,
        organization_id=payload.organization_id, max_concurrency=payload.max_concurrency,
        rpm_limit=payload.rpm_limit, daily_limit=payload.daily_limit, user_id=principal.user.id,
    )
    if await session.scalar(select(ApiKey.id).where(ApiKey.fingerprint == key.fingerprint)):
        raise AppError("resource_pool.key_exists", "This API key is already registered", 409)
    session.add(key)
    await session.flush()
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=payload.organization_id,
                  action="api_key.create", resource_type="api_key", resource_id=key.id,
                  metadata={"fingerprint": key.fingerprint[:12], "suffix": key.secret_suffix})
    await session.commit()
    return await _key_response(redis, key)


@router.get("/keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    session: AsyncSession = Depends(get_db_session), redis: Redis = Depends(get_redis_client),
    _: Principal = Depends(require_permissions("resource_pools.manage")),
) -> list[ApiKeyResponse]:
    keys = list((await session.scalars(select(ApiKey).order_by(ApiKey.created_at.desc()))).all())
    return [await _key_response(redis, key) for key in keys]


@router.post("/{pool_id}/keys", status_code=status.HTTP_204_NO_CONTENT)
async def attach_key(
    pool_id: str, payload: PoolKeyAttachRequest, request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("resource_pools.manage")),
) -> None:
    pool = await session.get(ResourcePool, pool_id)
    key = await session.get(ApiKey, payload.api_key_id)
    if pool is None or key is None:
        raise AppError("resource_pool.not_found", "Resource pool or API key was not found", 404)
    model = await session.get(ProviderModel, pool.model_id)
    if key.provider_id != model.provider_id:
        raise AppError("resource_pool.provider_mismatch", "API key provider does not match the pool model provider", 422)
    existing = await session.scalar(select(ResourcePoolKey).where(
        ResourcePoolKey.resource_pool_id == pool_id, ResourcePoolKey.api_key_id == key.id,
    ))
    if existing is None:
        session.add(ResourcePoolKey(
            resource_pool_id=pool_id, api_key_id=key.id, priority=payload.priority, weight=payload.weight,
            created_by=principal.user.id, updated_by=principal.user.id,
        ))
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=pool.organization_id,
                  action="resource_pool.key.attach", resource_type="resource_pool", resource_id=pool.id,
                  metadata={"api_key_id": key.id})
    await session.commit()


@router.post("/{pool_id}/operations", status_code=status.HTTP_204_NO_CONTENT)
async def attach_operation(
    pool_id: str, payload: OperationPoolAttachRequest, request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("resource_pools.manage")),
) -> None:
    pool = await session.get(ResourcePool, pool_id)
    if pool is None:
        raise AppError("resource_pool.not_found", "Resource pool was not found", 404)
    capabilities = set((await session.scalars(select(ModelCapability.capability).where(
        ModelCapability.model_id == pool.model_id,
    ))).all())
    if payload.required_capability not in capabilities:
        raise AppError("resource_pool.capability_mismatch", "模型未声明该能力，不能创建业务绑定", 422)
    existing = await session.scalar(select(OperationResourcePool).where(
        OperationResourcePool.organization_id == payload.organization_id,
        OperationResourcePool.operation_code == payload.operation_code,
        OperationResourcePool.resource_pool_id == pool.id,
        OperationResourcePool.required_capability == payload.required_capability,
    ))
    if existing:
        existing.priority = payload.priority
        existing.enabled = True
        existing.updated_by = principal.user.id
    else:
        session.add(OperationResourcePool(
            organization_id=payload.organization_id, operation_code=payload.operation_code,
            resource_pool_id=pool.id, required_capability=payload.required_capability,
            priority=payload.priority, created_by=principal.user.id, updated_by=principal.user.id,
        ))
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=payload.organization_id,
                  action="resource_pool.operation.attach", resource_type="resource_pool", resource_id=pool.id,
                  metadata={"operation_code": payload.operation_code, "required_capability": payload.required_capability})
    await session.commit()


def _model_response(model: ProviderModel, capabilities: list[str]) -> ProviderModelResponse:
    return ProviderModelResponse(id=model.id, provider_id=model.provider_id, code=model.code,
        upstream_model=model.upstream_model, name=model.name, enabled=model.enabled,
        capabilities=capabilities, config=model.config_json)


def _pool_response(
    pool: ResourcePool, model_code: str, capabilities: list[str], key_count: int,
    operation_bindings: dict[str, list[str]],
) -> ResourcePoolResponse:
    return ResourcePoolResponse(id=pool.id, organization_id=pool.organization_id, model_id=pool.model_id,
        model_code=model_code, code=pool.code, name=pool.name, enabled=pool.enabled,
        priority=pool.priority, weight=pool.weight, capabilities=capabilities,
        operation_bindings=operation_bindings, key_count=key_count)


async def _key_response(redis: Redis, key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(id=key.id, provider_id=key.provider_id, organization_id=key.organization_id,
        label=key.label, fingerprint=key.fingerprint, masked_secret=masked_key(key), enabled=key.enabled,
        status=key.status, max_concurrency=key.max_concurrency, rpm_limit=key.rpm_limit,
        daily_limit=key.daily_limit, cooldown_until=key.cooldown_until,
        consecutive_failures=key.consecutive_failures, current_concurrency=await current_concurrency(redis, key.id))
