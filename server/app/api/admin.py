from datetime import datetime, timezone
import base64

from fastapi import APIRouter, Depends, Query, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.infrastructure.redis import get_redis_client
from app.models.identity import AuditLog, LoginAudit, Organization, OrganizationMember, RefreshToken, Role, User
from app.models.content import Asset, GeneratedOutput
from app.models.quota import QuotaAccount
from app.models.tasks import ApiKey, Job, JobAttempt, ModelCapability, OperationResourcePool, Provider, ProviderModel, ResourcePool, ResourcePoolKey
from app.schemas.admin import (
    AdminApiKeyResponse, AdminAuditLogPage, AdminEnabledUpdateRequest, AdminJobPage,
    AdminJobResponse, AdminLoginAuditPage, AdminMembershipSummary, AdminModelResponse,
    AdminOrganizationPage, AdminOrganizationResponse, AdminOrganizationUpdateRequest,
    AdminOverviewResponse, AdminPoolResponse, AdminProviderResponse, AdminProviderTestRequest,
    AdminProviderTestResponse, AdminQueuePage,
    AdminQueueResponse, AdminQuotaAdjustmentResponse, AdminResourceInventoryResponse,
    AdminUserPage, AdminUserResponse, AdminUserUpdateRequest,
)
from app.schemas.identity import AuditLogResponse, LoginAuditResponse
from app.schemas.quota import QuotaAdjustmentRequest, QuotaTransactionResponse
from app.security.principal import Principal, require_permissions
from app.security.api_keys import decrypt_api_key
from app.services.audit_service import add_audit_log
from app.services.billing_service import account_response, adjust_balance
from app.services.resource_pool_service import current_concurrency, masked_key
from app.services.provider_test_service import probe_provider_models, probe_provider_operation
from app.services.asset_service import asset_content_url
from app.services.storage_service import StorageService, get_storage_service


router = APIRouter(prefix="/admin", tags=["platform administration"])
UTC = timezone.utc
ACTIVE_JOB_STATUSES = {"queued", "dispatching", "running", "retry_waiting"}
QUEUE_NAMES = ("planning_queue", "listing_queue", "batch_tryon_queue", "aplus_queue", "maintenance")


def _platform_admin() -> object:
    return Depends(require_permissions("platform.admin"))


async def _count(session: AsyncSession, model, *filters) -> int:
    return int(await session.scalar(select(func.count()).select_from(model).where(*filters)) or 0)


@router.get("/overview", response_model=AdminOverviewResponse)
async def overview(
    session: AsyncSession = Depends(get_db_session),
    _: Principal = _platform_admin(),
) -> AdminOverviewResponse:
    quota_balance, quota_reserved = (await session.execute(
        select(func.coalesce(func.sum(QuotaAccount.balance), 0), func.coalesce(func.sum(QuotaAccount.reserved_balance), 0))
    )).one()
    return AdminOverviewResponse(
        users_total=await _count(session, User),
        users_active=await _count(session, User, User.status == "active"),
        organizations_total=await _count(session, Organization),
        organizations_active=await _count(session, Organization, Organization.status == "active"),
        jobs_total=await _count(session, Job),
        jobs_active=await _count(session, Job, Job.status.in_(ACTIVE_JOB_STATUSES)),
        jobs_failed=await _count(session, Job, Job.status == "failed"),
        jobs_succeeded=await _count(session, Job, Job.status == "succeeded"),
        quota_balance_total=int(quota_balance),
        quota_reserved_total=int(quota_reserved),
        providers_enabled=await _count(session, Provider, Provider.enabled.is_(True)),
        pools_enabled=await _count(session, ResourcePool, ResourcePool.enabled.is_(True)),
        keys_enabled=await _count(session, ApiKey, ApiKey.enabled.is_(True), ApiKey.status == "active"),
    )


@router.get("/users", response_model=AdminUserPage)
async def users(
    search: str | None = Query(default=None, max_length=160),
    user_status: str | None = Query(default=None, alias="status", max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _: Principal = _platform_admin(),
) -> AdminUserPage:
    filters = []
    if search:
        value = f"%{search.strip()}%"
        filters.append(or_(User.email.ilike(value), User.display_name.ilike(value)))
    if user_status:
        filters.append(User.status == user_status)
    total = await _count(session, User, *filters)
    statement = (
        select(User)
        .options(
            selectinload(User.platform_role),
            selectinload(User.memberships).selectinload(OrganizationMember.role),
            selectinload(User.memberships).selectinload(OrganizationMember.organization),
        )
        .where(*filters).order_by(User.created_at.desc()).limit(limit).offset(offset)
    )
    items = list((await session.scalars(statement)).all())
    return AdminUserPage(items=[_user_response(item) for item in items], total=total, limit=limit, offset=offset)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: str, payload: AdminUserUpdateRequest, request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = _platform_admin(),
) -> AdminUserResponse:
    user = await session.scalar(
        select(User).options(
            selectinload(User.platform_role),
            selectinload(User.memberships).selectinload(OrganizationMember.role),
            selectinload(User.memberships).selectinload(OrganizationMember.organization),
        ).where(User.id == user_id)
    )
    if user is None:
        raise AppError("admin.user_not_found", "User was not found", 404)
    if user.id == principal.user.id and (payload.status == "disabled" or payload.platform_admin is False):
        raise AppError("admin.self_lockout", "You cannot disable or demote your own platform administrator account", 409)
    changes: dict[str, object] = {}
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
        changes["display_name"] = user.display_name
    if payload.status is not None:
        user.status = payload.status
        changes["status"] = payload.status
        if payload.status == "disabled":
            await session.execute(update(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            ).values(revoked_at=datetime.now(UTC)))
    if payload.platform_admin is not None:
        role = await session.scalar(select(Role).where(Role.code == "platform_admin"))
        user.platform_role_id = role.id if payload.platform_admin and role else None
        changes["platform_admin"] = payload.platform_admin
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="admin.user.update", resource_type="user", resource_id=user.id, metadata=changes)
    await session.commit()
    return _user_response(await _load_user(session, user.id))


@router.get("/organizations", response_model=AdminOrganizationPage)
async def organizations(
    search: str | None = Query(default=None, max_length=160),
    organization_status: str | None = Query(default=None, alias="status", max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _: Principal = _platform_admin(),
) -> AdminOrganizationPage:
    filters = []
    if search:
        value = f"%{search.strip()}%"
        filters.append(or_(Organization.name.ilike(value), Organization.slug.ilike(value)))
    if organization_status:
        filters.append(Organization.status == organization_status)
    total = await _count(session, Organization, *filters)
    items = list((await session.scalars(
        select(Organization).where(*filters).order_by(Organization.created_at.desc()).limit(limit).offset(offset)
    )).all())
    responses = [await _organization_response(session, item) for item in items]
    return AdminOrganizationPage(items=responses, total=total, limit=limit, offset=offset)


@router.patch("/organizations/{organization_id}", response_model=AdminOrganizationResponse)
async def update_organization(
    organization_id: str, payload: AdminOrganizationUpdateRequest, request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = _platform_admin(),
) -> AdminOrganizationResponse:
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise AppError("admin.organization_not_found", "Organization was not found", 404)
    changes: dict[str, object] = {}
    if payload.name is not None:
        organization.name = payload.name.strip()
        changes["name"] = organization.name
    if payload.status is not None:
        organization.status = payload.status
        changes["status"] = payload.status
        if payload.status == "disabled":
            await session.execute(update(RefreshToken).where(
                RefreshToken.organization_id == organization.id, RefreshToken.revoked_at.is_(None)
            ).values(revoked_at=datetime.now(UTC)))
    organization.updated_by = principal.user.id
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=organization.id,
                  action="admin.organization.update", resource_type="organization",
                  resource_id=organization.id, metadata=changes)
    await session.commit()
    return await _organization_response(session, organization)


@router.post("/organizations/{organization_id}/quota-adjustments", response_model=AdminQuotaAdjustmentResponse)
async def adjust_organization_quota(
    organization_id: str, payload: QuotaAdjustmentRequest, request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = _platform_admin(),
) -> AdminQuotaAdjustmentResponse:
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise AppError("admin.organization_not_found", "Organization was not found", 404)
    account, transaction = await adjust_balance(
        session, organization_id=organization.id, user_id=principal.user.id,
        transaction_type=payload.transaction_type, amount=payload.amount,
        idempotency_key=payload.idempotency_key, reason=payload.reason,
    )
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=organization.id,
                  action="admin.quota.adjust", resource_type="quota_account", resource_id=account.id,
                  metadata={"amount": payload.amount, "transaction_type": payload.transaction_type,
                            "transaction_id": transaction.id})
    await session.commit()
    await session.refresh(account)
    await session.refresh(transaction)
    return AdminQuotaAdjustmentResponse(
        account=account_response(account), transaction=QuotaTransactionResponse.model_validate(transaction)
    )


@router.get("/resources", response_model=AdminResourceInventoryResponse)
async def resources(
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
    _: Principal = _platform_admin(),
) -> AdminResourceInventoryResponse:
    providers = list((await session.scalars(select(Provider).order_by(Provider.code))).all())
    models = list((await session.scalars(select(ProviderModel).order_by(ProviderModel.code))).all())
    pools = list((await session.scalars(select(ResourcePool).order_by(ResourcePool.priority, ResourcePool.code))).all())
    keys = list((await session.scalars(select(ApiKey).order_by(ApiKey.created_at.desc()))).all())
    capabilities: dict[str, list[str]] = {}
    for model_id, capability in (await session.execute(
        select(ModelCapability.model_id, ModelCapability.capability).order_by(ModelCapability.capability)
    )).all():
        capabilities.setdefault(model_id, []).append(capability)
    pool_keys: dict[str, list[str]] = {}
    for pool_id, key_id in (await session.execute(select(
        ResourcePoolKey.resource_pool_id, ResourcePoolKey.api_key_id
    ).where(ResourcePoolKey.enabled.is_(True)))).all():
        pool_keys.setdefault(pool_id, []).append(key_id)
    pool_operations: dict[str, dict[str, list[str]]] = {}
    for pool_id, operation_code, required_capability in (await session.execute(select(
        OperationResourcePool.resource_pool_id, OperationResourcePool.operation_code,
        OperationResourcePool.required_capability,
    ).where(OperationResourcePool.enabled.is_(True)).order_by(OperationResourcePool.priority))).all():
        pool_operations.setdefault(pool_id, {}).setdefault(operation_code, []).append(required_capability)
    organizations = {item.id: item.name for item in (await session.scalars(select(Organization))).all()}
    model_by_id = {item.id: item for item in models}
    provider_model_counts = {provider.id: sum(1 for item in models if item.provider_id == provider.id) for provider in providers}
    provider_key_counts = {provider.id: sum(1 for item in keys if item.provider_id == provider.id) for provider in providers}
    return AdminResourceInventoryResponse(
        providers=[AdminProviderResponse(
            id=item.id, code=item.code, name=item.name, provider_type=item.provider_type,
            base_url=item.base_url, enabled=item.enabled, model_count=provider_model_counts[item.id],
            key_count=provider_key_counts[item.id],
        ) for item in providers],
        models=[AdminModelResponse(
            id=item.id, provider_id=item.provider_id, code=item.code, upstream_model=item.upstream_model,
            name=item.name, enabled=item.enabled, capabilities=capabilities.get(item.id, []),
        ) for item in models],
        pools=[AdminPoolResponse(
            id=item.id, organization_id=item.organization_id,
            organization_name=organizations.get(item.organization_id) if item.organization_id else None,
            model_id=item.model_id, model_code=model_by_id[item.model_id].code,
            code=item.code, name=item.name, enabled=item.enabled, priority=item.priority,
            weight=item.weight, key_ids=pool_keys.get(item.id, []),
            operation_bindings=pool_operations.get(item.id, {}),
        ) for item in pools],
        keys=[AdminApiKeyResponse(
            id=item.id, provider_id=item.provider_id, organization_id=item.organization_id,
            organization_name=organizations.get(item.organization_id) if item.organization_id else None,
            label=item.label, masked_secret=masked_key(item), fingerprint=item.fingerprint,
            enabled=item.enabled, status=item.status, max_concurrency=item.max_concurrency,
            rpm_limit=item.rpm_limit, daily_limit=item.daily_limit,
            current_concurrency=await current_concurrency(redis, item.id),
            consecutive_failures=item.consecutive_failures, cooldown_until=item.cooldown_until,
            last_used_at=item.last_used_at,
        ) for item in keys],
    )


@router.patch("/providers/{provider_id}", response_model=AdminProviderResponse)
async def update_provider_status(
    provider_id: str, payload: AdminEnabledUpdateRequest, request: Request,
    session: AsyncSession = Depends(get_db_session), principal: Principal = _platform_admin(),
) -> AdminProviderResponse:
    item = await session.get(Provider, provider_id)
    if item is None:
        raise AppError("admin.provider_not_found", "Provider was not found", 404)
    item.enabled = payload.enabled
    item.updated_by = principal.user.id
    await _audit_resource_toggle(session, request, principal, "provider", item.id, payload.enabled)
    await session.commit()
    return AdminProviderResponse(
        id=item.id, code=item.code, name=item.name, provider_type=item.provider_type,
        base_url=item.base_url, enabled=item.enabled,
        model_count=await _count(session, ProviderModel, ProviderModel.provider_id == item.id),
        key_count=await _count(session, ApiKey, ApiKey.provider_id == item.id),
    )


@router.post("/providers/{provider_id}/test", response_model=AdminProviderTestResponse)
async def test_provider_connection(
    provider_id: str, request: Request, payload: AdminProviderTestRequest | None = None,
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = _platform_admin(),
) -> AdminProviderTestResponse:
    payload = payload or AdminProviderTestRequest()
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise AppError("admin.provider_not_found", "Provider was not found", 404)
    key = await session.scalar(
        select(ApiKey).where(
            ApiKey.provider_id == provider.id, ApiKey.enabled.is_(True), ApiKey.status != "disabled",
        ).order_by(ApiKey.consecutive_failures.asc(), ApiKey.created_at.asc())
    )
    if key is None:
        raise AppError("admin.provider_key_missing", "Provider has no enabled API key", 409)
    secret = decrypt_api_key(settings, key.secret_ciphertext)
    model = None
    if payload.test_type == "base":
        result = await probe_provider_models(
            base_url=provider.base_url, api_key=secret,
            timeout_seconds=min(settings.provider_request_timeout_seconds, 35.0),
        )
    else:
        if payload.model_id is None:
            raise AppError("admin.provider_model_required", "请选择要测试的模型", 422)
        model = await session.get(ProviderModel, payload.model_id)
        if model is None or model.provider_id != provider.id:
            raise AppError("admin.provider_model_not_found", "所选模型不属于当前 Provider", 404)
        reference = {
            "content": base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ),
            "filename": "provider-test.png", "mime_type": "image/png",
        }
        references = [reference, {**reference, "filename": "provider-test-2.png"}] \
            if payload.test_type == "multi_image_reference" else [reference]
        result = await probe_provider_operation(
            settings=settings, provider_type=provider.provider_type, base_url=provider.base_url,
            api_key=secret, upstream_model=model.upstream_model, capability=payload.test_type,
            provider_config=provider.config_json, model_config=model.config_json,
            reference_images=references,
        )
    checked_at = datetime.now(UTC)
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=key.organization_id,
        action="admin.provider.test", resource_type="provider", resource_id=provider.id,
        metadata={
            "success": result.success, "status_code": result.status_code,
            "error_code": result.error_code, "model_count": len(result.models),
            "test_type": payload.test_type, "model_id": model.id if model else None,
        },
    )
    await session.commit()
    return AdminProviderTestResponse(
        provider_id=provider.id, test_type=payload.test_type, model_id=model.id if model else None,
        success=result.success, status_code=result.status_code,
        error_code=result.error_code, message=result.message, models=result.models, checked_at=checked_at,
    )


@router.patch("/models/{model_id}", response_model=AdminEnabledUpdateRequest)
async def update_model_status(
    model_id: str, payload: AdminEnabledUpdateRequest, request: Request,
    session: AsyncSession = Depends(get_db_session), principal: Principal = _platform_admin(),
) -> AdminEnabledUpdateRequest:
    item = await session.get(ProviderModel, model_id)
    if item is None:
        raise AppError("admin.model_not_found", "Model was not found", 404)
    item.enabled = payload.enabled
    item.updated_by = principal.user.id
    await _audit_resource_toggle(session, request, principal, "model", item.id, payload.enabled)
    await session.commit()
    return payload


@router.patch("/resource-pools/{pool_id}", response_model=AdminEnabledUpdateRequest)
async def update_pool_status(
    pool_id: str, payload: AdminEnabledUpdateRequest, request: Request,
    session: AsyncSession = Depends(get_db_session), principal: Principal = _platform_admin(),
) -> AdminEnabledUpdateRequest:
    item = await session.get(ResourcePool, pool_id)
    if item is None:
        raise AppError("admin.pool_not_found", "Resource pool was not found", 404)
    item.enabled = payload.enabled
    item.updated_by = principal.user.id
    await _audit_resource_toggle(session, request, principal, "resource_pool", item.id, payload.enabled, item.organization_id)
    await session.commit()
    return payload


@router.patch("/api-keys/{key_id}", response_model=AdminEnabledUpdateRequest)
async def update_key_status(
    key_id: str, payload: AdminEnabledUpdateRequest, request: Request,
    session: AsyncSession = Depends(get_db_session), principal: Principal = _platform_admin(),
) -> AdminEnabledUpdateRequest:
    item = await session.get(ApiKey, key_id)
    if item is None:
        raise AppError("admin.key_not_found", "API key was not found", 404)
    item.enabled = payload.enabled
    item.status = "active" if payload.enabled else "disabled"
    if payload.enabled:
        item.cooldown_until = None
        item.consecutive_failures = 0
    item.updated_by = principal.user.id
    await _audit_resource_toggle(session, request, principal, "api_key", item.id, payload.enabled, item.organization_id)
    await session.commit()
    return payload


@router.get("/jobs", response_model=AdminJobPage)
async def jobs(
    organization_id: str | None = None,
    job_status: str | None = Query(default=None, alias="status", max_length=30),
    queue_name: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session), _: Principal = _platform_admin(),
) -> AdminJobPage:
    filters = []
    if organization_id:
        filters.append(Job.organization_id == organization_id)
    if job_status:
        filters.append(Job.status == job_status)
    if queue_name:
        filters.append(Job.queue_name == queue_name)
    total = await _count(session, Job, *filters)
    rows = (await session.execute(
        select(Job, Organization.name).join(Organization, Organization.id == Job.organization_id)
        .where(*filters).order_by(Job.created_at.desc()).limit(limit).offset(offset)
    )).all()
    job_ids = [job.id for job, _ in rows]
    attempts = list((await session.scalars(
        select(JobAttempt).where(JobAttempt.job_id.in_(job_ids)).order_by(JobAttempt.job_id, JobAttempt.attempt_number.desc())
    )).all()) if job_ids else []
    latest_attempt: dict[str, JobAttempt] = {}
    for attempt in attempts:
        latest_attempt.setdefault(attempt.job_id, attempt)
    return AdminJobPage(
        items=[_job_response(job, name, latest_attempt.get(job.id)) for job, name in rows],
        total=total, limit=limit, offset=offset,
    )


@router.get("/queues", response_model=AdminQueuePage)
async def queues(
    session: AsyncSession = Depends(get_db_session), redis: Redis = Depends(get_redis_client),
    _: Principal = _platform_admin(),
) -> AdminQueuePage:
    items = []
    redis_ok = True
    for queue in QUEUE_NAMES:
        try:
            depth = int(await redis.llen(queue))
        except (AttributeError, OSError, RuntimeError, RedisError):
            depth = 0
            redis_ok = False
        counts = dict((await session.execute(
            select(Job.status, func.count()).where(Job.queue_name == queue).group_by(Job.status)
        )).all())
        items.append(AdminQueueResponse(
            name=queue, broker_depth=depth,
            queued_jobs=int(counts.get("queued", 0)) + int(counts.get("dispatching", 0)),
            running_jobs=int(counts.get("running", 0)),
            retry_waiting_jobs=int(counts.get("retry_waiting", 0)),
            failed_jobs=int(counts.get("failed", 0)),
        ))
    return AdminQueuePage(items=items, redis_ok=redis_ok, checked_at=datetime.now(UTC))


@router.get("/generated-outputs/{output_id}/diagnostics")
async def generated_output_diagnostics(
    output_id: str,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    _: Principal = _platform_admin(),
) -> dict[str, object]:
    row = (await session.execute(
        select(GeneratedOutput, Asset)
        .join(Asset, Asset.id == GeneratedOutput.asset_id)
        .where(GeneratedOutput.id == output_id)
    )).one_or_none()
    if row is None:
        raise AppError("admin.generated_output_not_found", "Generated output was not found", 404)
    generated, asset = row
    file_exists = False
    backend_can_read = False
    storage_content_type: str | None = None
    try:
        file_exists = await run_in_threadpool(storage.exists, asset.storage_key)
        if file_exists:
            metadata = await run_in_threadpool(storage.get_metadata, asset.storage_key)
            backend_can_read = True
            storage_content_type = metadata.content_type
    except Exception:
        backend_can_read = False
    path = asset_content_url(asset.id)
    return {
        "database_record_exists": True,
        "output_id": generated.id,
        "asset_id": asset.id,
        "organization_id": asset.organization_id,
        "storage_backend": type(storage).__name__,
        "storage_key": asset.storage_key,
        "image_access_mode": "authenticated_backend_stream",
        "returned_url_scheme": "relative",
        "returned_url_host": None,
        "returned_url_path": path,
        "actual_width": asset.width,
        "actual_height": asset.height,
        "content_type": storage_content_type or asset.mime_type,
        "file_exists": file_exists,
        "backend_can_read": backend_can_read,
        "permission_check": "platform_admin",
        "mixed_content": False,
    }


@router.get("/audit-logs", response_model=AdminAuditLogPage)
async def audit_logs(
    organization_id: str | None = None, action: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session), _: Principal = _platform_admin(),
) -> AdminAuditLogPage:
    filters = []
    if organization_id:
        filters.append(AuditLog.organization_id == organization_id)
    if action:
        filters.append(AuditLog.action == action)
    total = await _count(session, AuditLog, *filters)
    items = list((await session.scalars(
        select(AuditLog).where(*filters).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    )).all())
    return AdminAuditLogPage(items=[AuditLogResponse.model_validate(item) for item in items], total=total, limit=limit, offset=offset)


@router.get("/login-audits", response_model=AdminLoginAuditPage)
async def login_audits(
    organization_id: str | None = None, outcome: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session), _: Principal = _platform_admin(),
) -> AdminLoginAuditPage:
    filters = []
    if organization_id:
        filters.append(LoginAudit.organization_id == organization_id)
    if outcome:
        filters.append(LoginAudit.outcome == outcome)
    total = await _count(session, LoginAudit, *filters)
    items = list((await session.scalars(
        select(LoginAudit).where(*filters).order_by(LoginAudit.created_at.desc()).limit(limit).offset(offset)
    )).all())
    return AdminLoginAuditPage(items=[LoginAuditResponse.model_validate(item) for item in items], total=total, limit=limit, offset=offset)


async def _load_user(session: AsyncSession, user_id: str) -> User:
    user = await session.scalar(select(User).options(
        selectinload(User.platform_role),
        selectinload(User.memberships).selectinload(OrganizationMember.role),
        selectinload(User.memberships).selectinload(OrganizationMember.organization),
    ).where(User.id == user_id))
    if user is None:
        raise AppError("admin.user_not_found", "User was not found", 404)
    return user


def _user_response(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id, email=user.email, display_name=user.display_name, status=user.status,
        auth_provider=user.auth_provider, platform_role=user.platform_role.code if user.platform_role else None,
        memberships=[AdminMembershipSummary(
            id=item.id,
            organization_id=item.organization_id, organization_name=item.organization.name,
            role_code=item.role.code, status=item.status, invited_by=item.invited_by,
        ) for item in user.memberships],
        must_change_password=user.must_change_password,
        password_changed_at=user.password_changed_at,
        temporary_password_created_at=user.temporary_password_created_at,
        created_by=user.created_by,
        last_login_at=user.last_login_at, created_at=user.created_at, updated_at=user.updated_at,
    )


async def _organization_response(session: AsyncSession, organization: Organization) -> AdminOrganizationResponse:
    account = await session.scalar(select(QuotaAccount).where(QuotaAccount.organization_id == organization.id))
    return AdminOrganizationResponse(
        id=organization.id, name=organization.name, slug=organization.slug, status=organization.status,
        member_count=await _count(session, OrganizationMember, OrganizationMember.organization_id == organization.id),
        job_count=await _count(session, Job, Job.organization_id == organization.id),
        active_job_count=await _count(session, Job, Job.organization_id == organization.id, Job.status.in_(ACTIVE_JOB_STATUSES)),
        quota_balance=account.balance if account else 0, quota_reserved=account.reserved_balance if account else 0,
        created_at=organization.created_at, updated_at=organization.updated_at,
    )


def _job_response(job: Job, organization_name: str, attempt: JobAttempt | None = None) -> AdminJobResponse:
    snapshot = job.input_json or {}
    result_metadata = (job.result_json or {}).get("metadata")
    metadata = result_metadata if isinstance(result_metadata, dict) else {}
    outputs = (job.result_json or {}).get("outputs")
    first_output = outputs[0] if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict) else {}
    actual_width = metadata.get("actual_width") or first_output.get("width")
    actual_height = metadata.get("actual_height") or first_output.get("height")
    return AdminJobResponse(
        id=job.id, organization_id=job.organization_id, organization_name=organization_name,
        operation_code=job.operation_code, workspace_type=job.workspace_type, queue_name=job.queue_name,
        capability=job.capability, model_code=job.model_code, status=job.status, progress=job.progress,
        attempts=job.attempts, max_attempts=job.max_attempts, error_code=job.error_code,
        error_message=job.error_message, created_at=job.created_at, started_at=job.started_at,
        finished_at=job.finished_at,
        generation_duration_ms=int(job.generation_duration_ms or 0),
        requested_aspect_ratio=snapshot.get("aspect_ratio"),
        requested_width=snapshot.get("requested_width"), requested_height=snapshot.get("requested_height"),
        resolved_provider_size=snapshot.get("provider_size") or snapshot.get("size"),
        submitted_dimension_field=metadata.get("submitted_dimension_field"),
        submitted_dimension_value=metadata.get("submitted_dimension_value"),
        actual_width=actual_width, actual_height=actual_height,
        size_mismatch=bool(metadata.get("size_mismatch")),
        resource_pool_id=attempt.resource_pool_id if attempt else job.selected_pool_id,
        provider_id=attempt.provider_id if attempt else None,
        provider_model_id=attempt.model_id if attempt else None,
        worker_name=attempt.worker_name if attempt else None,
        upstream_request_id=attempt.upstream_request_id if attempt else (job.result_json or {}).get("provider_request_id"),
    )


async def _audit_resource_toggle(
    session: AsyncSession, request: Request, principal: Principal, resource_type: str,
    resource_id: str, enabled: bool, organization_id: str | None = None,
) -> None:
    add_audit_log(session, request=request, actor_user_id=principal.user.id,
                  organization_id=organization_id, action=f"admin.{resource_type}.toggle",
                  resource_type=resource_type, resource_id=resource_id, metadata={"enabled": enabled})
