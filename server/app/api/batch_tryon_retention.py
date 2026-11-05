from fastapi import APIRouter, Depends, Request
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.core.errors import AppError
from app.db.session import get_db_session
from app.security.principal import Principal, require_permissions
from app.api.batch_tryon_review import organization_id
from app.models.batch_tryon_queue_policy import BatchTryOnQueuePolicy
from app.schemas.batch_tryon_queue_policy import RetentionRule, RetentionSettings, RetentionSave, RetentionRun
from app.services.batch_tryon_retention_service import (
    read_policy, settings_response, preview_retention, execute_retention, restore_retained_batch,
)
from app.services.audit_service import add_audit_log
from app.services.storage_service import StorageService, get_storage_service

router = APIRouter(prefix="/batch-tryon/queue", tags=["batch-tryon-queue-settings"])


def can_manage(principal):
    return {"organizations.write", "jobs.cancel", "assets.delete"}.issubset(principal.permissions)


@router.get("/retention", response_model=RetentionSettings)
async def get_retention(session: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.read"))):
    return settings_response(await read_policy(session, organization_id(principal)), can_manage(principal))


@router.put("/retention", response_model=RetentionSettings)
async def save_retention(payload: RetentionSave, request: Request, session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("organizations.write", "jobs.cancel", "assets.delete"))):
    org = organization_id(principal)
    policy = await read_policy(session, org, lock=True)
    if (policy.revision if policy else 0) != payload.expected_revision:
        raise AppError("queue.policy_changed", "设置已被其他管理员修改，请重新读取。", 409)
    if payload.enabled and payload.action == "delete" and payload.confirmation != "PERMANENT_DELETE":
        raise AppError("queue.delete_confirmation_required", "永久清理会删除批次和结果图片，请明确确认。", 422)
    if policy is None:
        policy = BatchTryOnQueuePolicy(organization_id=org, revision=0)
        session.add(policy)
    policy.enabled, policy.days, policy.age_basis, policy.action = payload.enabled, payload.days, payload.age_basis, payload.action
    policy.revision += 1
    policy.updated_by = principal.user.id
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org,
        action="batch_tryon.queue.policy_save", resource_type="organization", resource_id=org,
        metadata={**payload.model_dump(exclude={"confirmation", "expected_revision"}), "revision": policy.revision})
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise AppError("queue.policy_changed", "设置已被其他管理员保存，请重新读取。", 409) from error
    return settings_response(policy, True)


@router.post("/retention/preview")
async def preview(payload: RetentionRule, session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("organizations.write", "jobs.cancel", "assets.delete"))):
    org = organization_id(principal)
    policy = await read_policy(session, org)
    return await preview_retention(session, org, payload, policy.revision if policy else 0)


@router.post("/retention/run", status_code=202)
async def run(payload: RetentionRun, session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("organizations.write", "jobs.cancel", "assets.delete"))):
    org = organization_id(principal)
    policy = await read_policy(session, org, lock=True)
    if not policy or not policy.enabled:
        raise AppError("queue.policy_disabled", "请先启用并保存清理规则。", 409)
    if payload.expected_revision != policy.revision:
        raise AppError("queue.policy_changed", "清理设置已变化，请重新预览。", 409)
    if policy and policy.action == "delete" and payload.confirmation != "PERMANENT_DELETE":
        raise AppError("queue.delete_confirmation_required", "请确认永久删除。", 422)
    now = datetime.now(timezone.utc)
    from app.services.batch_tryon_retention_service import aware
    if (policy.last_run_summary or {}).get("queued") and policy.last_run_at and aware(policy.last_run_at) > now - timedelta(minutes=5):
        raise AppError("queue.cleanup_already_queued", "本团队已有清理请求在维护队列中，请稍后查看处理结果。", 409)
    rule = RetentionRule(enabled=policy.enabled, days=policy.days, age_basis=policy.age_basis, action=policy.action)
    current = await preview_retention(session, org, rule, policy.revision)
    if current["preview_token"] != payload.preview_token:
        raise AppError("queue.preview_changed", "队列已变化，请重新预览后再执行。", 409)
    policy.last_run_at, policy.last_run_summary = now, {"queued": 1}
    await session.commit()
    from app.workers.celery_app import celery_app
    task_id = str(uuid4())
    try:
        celery_app.send_task("system.batch_queue_retention", kwargs={"organization_id": org,
            "expected_revision": policy.revision, "preview_token": payload.preview_token}, task_id=task_id, queue="queue_retention")
    except Exception as error:
        policy.last_run_summary = {"queued": 0, "errors": 1}
        await session.commit()
        raise AppError("queue.cleanup_publish_failed", "清理请求未能进入维护队列，请稍后重试。", 503) from error
    return {"submitted": True, "task_id": task_id}


@router.post("/{batch_id}/restore")
async def restore(batch_id: str, session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit"))):
    return await restore_retained_batch(session, organization_id(principal), batch_id, principal.user.id, can_manage(principal))
