from __future__ import annotations

import json
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.attachment_planning import AttachmentProductIdentityLockVersion, AttachmentWorkbenchPlan
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject, ListingVersion
from app.models.tasks import Job, JobStatus
from app.schemas.tasks import JobSubmitRequest
from app.services.ai_task_model_policy_service import next_analysis_retry, resolve_ai_task_route
from app.services.task_service import submit_job


PROMPT_VERSION = "product-identity-lock-v1"
SYSTEM_PROMPT = """你是电商商品事实提取器。仅根据PRODUCT/PRINT图片与已确认Listing提取不可改变的商品事实。
只返回JSON对象，不使用Markdown，不解释。字段：category, primary_color, secondary_colors, collar, sleeve_type,
garment_structure, front_text, back_text, front_number, back_number, shoulder_number, logos, print_structure,
customization_elements, material_visual_features, immutable_features, forbidden_changes, needs_confirmation。
无法确认的标量写unknown，列表可为空；禁止猜测材质、功能、授权和看不清的文字。"""


def _source_snapshot(session: ListingGenerationSession, version: ListingVersion) -> dict[str, object]:
    return {
        "session_id": session.id,
        "project_id": session.project_id,
        "listing_version_id": version.id,
        "product_asset_ids": list(session.source_asset_ids or []),
        "primary_asset_id": session.primary_asset_id,
        "analysis": dict(version.analysis_snapshot or {}),
        "listing": dict(version.listing_snapshot or {}),
    }


def _input_hash(snapshot: dict[str, object]) -> str:
    return sha256(json.dumps({"prompt_version": PROMPT_VERSION, "source": snapshot}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def parse_product_identity_lock(text: str) -> dict[str, object]:
    try:
        value = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
    except json.JSONDecodeError as error:
        raise AppError("product_identity.result_invalid", "商品事实提取结果不是有效JSON", 422) from error
    required = {"category", "primary_color", "collar", "sleeve_type", "immutable_features", "forbidden_changes", "needs_confirmation"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise AppError("product_identity.result_invalid", "商品事实提取结果结构不完整", 422)
    for key in ("secondary_colors", "logos", "customization_elements", "material_visual_features", "immutable_features", "forbidden_changes", "needs_confirmation"):
        if not isinstance(value.get(key), list):
            raise AppError("product_identity.result_invalid", f"商品事实字段 {key} 必须是列表", 422)
    return value


async def start_product_identity_lock(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject, session: ListingGenerationSession,
    version: ListingVersion, plan: AttachmentWorkbenchPlan, user_id: str, force: bool = False,
) -> tuple[AttachmentProductIdentityLockVersion, Job | None, bool]:
    snapshot = _source_snapshot(session, version)
    input_hash = _input_hash(snapshot)
    existing = await db.scalar(select(AttachmentProductIdentityLockVersion).where(
        AttachmentProductIdentityLockVersion.workbench_plan_id == plan.id,
        AttachmentProductIdentityLockVersion.input_hash == input_hash,
        AttachmentProductIdentityLockVersion.status.in_(["analyzing", "ready"]),
    ).order_by(AttachmentProductIdentityLockVersion.version_number.desc()).limit(1))
    if existing and not force:
        job = await db.get(Job, existing.ai_job_id) if existing.ai_job_id else None
        return existing, job, False
    route = await resolve_ai_task_route(
        db, organization_id=project.organization_id, task_type="PRODUCT_IDENTITY_EXTRACTION", capability="text_generation",
    )
    number = int(await db.scalar(select(func.max(AttachmentProductIdentityLockVersion.version_number)).where(
        AttachmentProductIdentityLockVersion.workbench_plan_id == plan.id,
    )) or 0) + 1
    job, created = await submit_job(db, settings, organization_id=project.organization_id, user_id=user_id, payload=JobSubmitRequest(
        operation_code=route.operation_code, workspace_type="listing", queue_name="planning_queue",
        capability="text_generation", model_code=route.model_code,
        idempotency_key=f"product-identity:{plan.id}:{input_hash}:{number if force else 0}", project_id=session.project_id,
        input={"system_prompt": SYSTEM_PROMPT, "user_prompt": json.dumps(snapshot, ensure_ascii=False),
               "response_format": "json_object", "reference_asset_ids": list(session.source_asset_ids or []),
               "metadata": {"workflow": "attachment_product_identity_lock", "plan_id": plan.id,
                            "input_hash": input_hash, "prompt_version": PROMPT_VERSION,
                            "analysis_task_type": route.task_type, "analysis_attempt": 1,
                            "analysis_fallback": route.used_fallback_binding}},
        billing_factors={"workspace": "attachment_product_identity", "stage": "analysis"},
        client_item_id=f"attachment-product-lock:v{number}",
    ))
    row = AttachmentProductIdentityLockVersion(
        organization_id=project.organization_id, workbench_plan_id=plan.id, version_number=number,
        status="analyzing", structured_json={}, input_hash=input_hash, source_snapshot_json=snapshot,
        ai_job_id=job.id, ai_model=route.model_code, created_by=user_id,
    )
    db.add(row); await db.flush()
    return row, job, created


async def reconcile_product_identity_lock(
    db: AsyncSession, settings: Settings, *, plan: AttachmentWorkbenchPlan,
) -> int:
    retry_jobs_created = 0
    pending = list((await db.scalars(select(AttachmentProductIdentityLockVersion).where(
        AttachmentProductIdentityLockVersion.workbench_plan_id == plan.id,
        AttachmentProductIdentityLockVersion.status == "analyzing",
    ))).all())
    latest_number = int(await db.scalar(select(func.max(AttachmentProductIdentityLockVersion.version_number)).where(
        AttachmentProductIdentityLockVersion.workbench_plan_id == plan.id,
    )) or 0)
    for row in pending:
        job = await db.get(Job, row.ai_job_id) if row.ai_job_id else None
        if job is None or job.status not in {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}:
            continue
        if row.version_number < latest_number:
            row.status = "stale"
            continue
        metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
        metadata = metadata if isinstance(metadata, dict) else {}
        attempt = int(metadata.get("analysis_attempt") or 1)
        fallback_used = bool(metadata.get("analysis_fallback"))
        retry_reason: str | None = None
        if job.status == JobStatus.SUCCEEDED.value:
            try:
                row.structured_json = parse_product_identity_lock(str((job.result_json or {}).get("metadata", {}).get("text") or ""))
                row.status = "ready"
                plan.current_product_identity_lock_version_id = row.id
                if plan.visual_direction_version > 0:
                    plan.planning_status = "stale"
            except AppError as error:
                retry_reason = error.message
        else:
            retry_reason = job.error_message or "商品事实提取失败，可重试"
        if retry_reason:
            decision = next_analysis_retry(attempt=attempt, fallback_used=fallback_used)
            if decision is not None:
                next_attempt = decision.attempt
                use_fallback = decision.use_fallback
                route = await resolve_ai_task_route(
                    db, organization_id=plan.organization_id,
                    task_type="MODULE_PLANNING" if use_fallback else "PRODUCT_IDENTITY_EXTRACTION",
                    capability="text_generation",
                )
                reference_asset_ids = [str(value) for value in row.source_snapshot_json.get("product_asset_ids", []) if value]
                retry_job, created = await submit_job(
                    db, settings, organization_id=plan.organization_id, user_id=row.created_by,
                    payload=JobSubmitRequest(
                        operation_code=route.operation_code, workspace_type="listing", queue_name="planning_queue",
                        capability="text_generation", model_code=route.model_code,
                        idempotency_key=f"product-identity:{row.id}:attempt:{next_attempt}",
                        project_id=str(row.source_snapshot_json.get("project_id") or "") or None,
                        input={
                            "system_prompt": SYSTEM_PROMPT,
                            "user_prompt": json.dumps(row.source_snapshot_json, ensure_ascii=False),
                            "response_format": "json_object", "reference_asset_ids": reference_asset_ids,
                            "metadata": {
                                "workflow": "attachment_product_identity_lock", "plan_id": plan.id,
                                "input_hash": row.input_hash, "prompt_version": PROMPT_VERSION,
                                "analysis_task_type": "PRODUCT_IDENTITY_EXTRACTION",
                                "analysis_attempt": next_attempt, "analysis_fallback": use_fallback,
                                "retry_reason": retry_reason[:300],
                            },
                        },
                        billing_factors={"workspace": "attachment_product_identity", "stage": "analysis"},
                        client_item_id=f"attachment-product-lock:v{row.version_number}:a{next_attempt}",
                    ),
                )
                row.ai_job_id = retry_job.id
                row.ai_model = route.model_code
                row.error_message = retry_reason
                retry_jobs_created += int(created)
                continue
            row.status = "failed"
            row.error_message = retry_reason
    return retry_jobs_created


async def current_product_identity_lock(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan,
) -> AttachmentProductIdentityLockVersion | None:
    if plan.current_product_identity_lock_version_id:
        return await db.get(AttachmentProductIdentityLockVersion, plan.current_product_identity_lock_version_id)
    return await db.scalar(select(AttachmentProductIdentityLockVersion).where(
        AttachmentProductIdentityLockVersion.workbench_plan_id == plan.id,
    ).order_by(AttachmentProductIdentityLockVersion.version_number.desc()).limit(1))
