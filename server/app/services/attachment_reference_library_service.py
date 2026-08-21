from __future__ import annotations

import json
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.attachment_planning import AttachmentReferenceLibraryItem, AttachmentReferenceLibraryUnderstanding
from app.models.tasks import Job, JobStatus
from app.schemas.tasks import JobSubmitRequest
from app.services.ai_task_model_policy_service import next_analysis_retry, resolve_ai_task_route
from app.services.task_service import submit_job


PROMPT_VERSION = "reference-library-v1"
SYSTEM_PROMPT = """你是电商参考图库图片理解器。只提取图片本身可复用的构图、镜头、摆放、光线、背景、道具和空间关系。
Role为TEMPLATE或SCENE时，严禁把模板中的旧商品颜色、Logo、号码、文字、印花或商品身份当作可复用规则。
只返回JSON：{"role":"...","summary_cn":"...","composition":"...","camera_angle":"...","subject_placement":"...","lighting":"...","background":"...","props":[],"reusable_rules":[],"forbidden_inheritance":[]}。不要Markdown，不要解释。"""


def library_input_hash(item: AttachmentReferenceLibraryItem) -> str:
    return sha256(json.dumps({
        "asset_id": item.asset_id, "role": item.reference_role, "guidance": item.guidance,
        "tags": list(item.tags or []), "state_version": item.state_version, "prompt_version": PROMPT_VERSION,
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def parse_library_understanding(text: str) -> dict[str, object]:
    try:
        payload = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
    except json.JSONDecodeError as error:
        raise AppError("reference_library.analysis_invalid", "参考图库分析结果不是有效JSON", 422) from error
    required = {"role", "summary_cn", "composition", "camera_angle", "lighting", "reusable_rules", "forbidden_inheritance"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise AppError("reference_library.analysis_invalid", "参考图库分析结构不完整", 422)
    if not isinstance(payload["reusable_rules"], list) or not isinstance(payload["forbidden_inheritance"], list):
        raise AppError("reference_library.analysis_invalid", "参考图库规则字段必须是列表", 422)
    return payload


async def latest_library_understanding(
    db: AsyncSession, item_id: str, *, ready_only: bool = False,
) -> AttachmentReferenceLibraryUnderstanding | None:
    query = select(AttachmentReferenceLibraryUnderstanding).where(
        AttachmentReferenceLibraryUnderstanding.library_item_id == item_id,
    )
    if ready_only:
        query = query.where(AttachmentReferenceLibraryUnderstanding.status == "ready")
    return await db.scalar(query.order_by(AttachmentReferenceLibraryUnderstanding.version_number.desc()).limit(1))


async def start_library_analysis(
    db: AsyncSession, settings: Settings, *, item: AttachmentReferenceLibraryItem, user_id: str, force: bool = False,
) -> tuple[AttachmentReferenceLibraryUnderstanding, Job, bool]:
    input_hash = library_input_hash(item)
    if not force:
        current = await db.scalar(select(AttachmentReferenceLibraryUnderstanding).where(
            AttachmentReferenceLibraryUnderstanding.library_item_id == item.id,
            AttachmentReferenceLibraryUnderstanding.input_hash == input_hash,
            AttachmentReferenceLibraryUnderstanding.status.in_(["analyzing", "ready"]),
        ).order_by(AttachmentReferenceLibraryUnderstanding.version_number.desc()).limit(1))
        if current and current.ai_job_id:
            job = await db.get(Job, current.ai_job_id)
            if job:
                return current, job, False
    route = await resolve_ai_task_route(
        db, organization_id=item.organization_id, task_type="REFERENCE_LIBRARY_ANALYSIS", capability="text_generation",
    )
    number = int(await db.scalar(select(func.max(AttachmentReferenceLibraryUnderstanding.version_number)).where(
        AttachmentReferenceLibraryUnderstanding.library_item_id == item.id,
    )) or 0) + 1
    job, created = await submit_job(db, settings, organization_id=item.organization_id, user_id=user_id, payload=JobSubmitRequest(
        operation_code=route.operation_code, workspace_type="listing", queue_name="planning_queue",
        capability="text_generation", model_code=route.model_code,
        idempotency_key=f"reference-library:{item.id}:{input_hash}:{number if force else 0}", project_id=None,
        input={"system_prompt": SYSTEM_PROMPT,
               "user_prompt": json.dumps({"role": item.reference_role, "module_key": item.module_key, "guidance": item.guidance, "tags": item.tags}, ensure_ascii=False),
               "response_format": "json_object", "reference_asset_ids": [item.asset_id],
               "metadata": {"workflow": "attachment_reference_library_analysis", "library_item_id": item.id,
                            "input_hash": input_hash, "analysis_task_type": route.task_type,
                            "analysis_attempt": 1, "analysis_fallback": route.used_fallback_binding}},
        billing_factors={"workspace": "attachment_reference_library", "stage": "analysis"},
        client_item_id=f"reference-library:{item.id}:v{number}",
    ))
    row = AttachmentReferenceLibraryUnderstanding(
        organization_id=item.organization_id, library_item_id=item.id, version_number=number,
        status="analyzing", structured_json={}, input_hash=input_hash, analysis_model=route.model_code,
        analysis_model_config={"operation_code": route.operation_code, "fallback_binding": route.used_fallback_binding},
        analysis_prompt_version=PROMPT_VERSION, ai_job_id=job.id, created_by=user_id,
    )
    db.add(row); await db.flush()
    return row, job, created


async def reconcile_library_understanding(
    db: AsyncSession, settings: Settings, item: AttachmentReferenceLibraryItem,
) -> int:
    retry_jobs_created = 0
    rows = list((await db.scalars(select(AttachmentReferenceLibraryUnderstanding).where(
        AttachmentReferenceLibraryUnderstanding.library_item_id == item.id,
        AttachmentReferenceLibraryUnderstanding.status == "analyzing",
    ))).all())
    for row in rows:
        job = await db.get(Job, row.ai_job_id) if row.ai_job_id else None
        if job is None or job.status not in {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}:
            continue
        if row.input_hash != library_input_hash(item):
            row.status = "stale"
            continue
        metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
        metadata = metadata if isinstance(metadata, dict) else {}
        attempt = int(metadata.get("analysis_attempt") or 1)
        fallback_used = bool(metadata.get("analysis_fallback"))
        retry_reason: str | None = None
        if job.status == JobStatus.SUCCEEDED.value:
            try:
                row.structured_json = parse_library_understanding(str((job.result_json or {}).get("metadata", {}).get("text") or ""))
                row.status = "ready"
            except AppError as error:
                retry_reason = error.message
        else:
            retry_reason = job.error_message or "参考图库分析失败，可重试"
        if retry_reason:
            decision = next_analysis_retry(attempt=attempt, fallback_used=fallback_used)
            if decision is not None:
                next_attempt = decision.attempt
                use_fallback = decision.use_fallback
                route = await resolve_ai_task_route(
                    db, organization_id=item.organization_id,
                    task_type="MODULE_PLANNING" if use_fallback else "REFERENCE_LIBRARY_ANALYSIS",
                    capability="text_generation",
                )
                retry_job, created = await submit_job(
                    db, settings, organization_id=item.organization_id, user_id=row.created_by,
                    payload=JobSubmitRequest(
                        operation_code=route.operation_code, workspace_type="listing", queue_name="planning_queue",
                        capability="text_generation", model_code=route.model_code,
                        idempotency_key=f"reference-library:{row.id}:attempt:{next_attempt}", project_id=None,
                        input={
                            "system_prompt": SYSTEM_PROMPT,
                            "user_prompt": json.dumps({"role": item.reference_role, "module_key": item.module_key, "guidance": item.guidance, "tags": item.tags}, ensure_ascii=False),
                            "response_format": "json_object", "reference_asset_ids": [item.asset_id],
                            "metadata": {
                                "workflow": "attachment_reference_library_analysis", "library_item_id": item.id,
                                "input_hash": row.input_hash, "analysis_task_type": "REFERENCE_LIBRARY_ANALYSIS",
                                "analysis_attempt": next_attempt, "analysis_fallback": use_fallback,
                                "retry_reason": retry_reason[:300],
                            },
                        },
                        billing_factors={"workspace": "attachment_reference_library", "stage": "analysis"},
                        client_item_id=f"reference-library:{item.id}:v{row.version_number}:a{next_attempt}",
                    ),
                )
                row.ai_job_id = retry_job.id
                row.analysis_model = route.model_code
                row.analysis_model_config = {
                    **dict(row.analysis_model_config or {}), "last_operation_code": route.operation_code,
                    "attempt": next_attempt, "fallback": use_fallback,
                }
                row.error_message = retry_reason
                retry_jobs_created += int(created)
                continue
            row.status = "failed"
            row.error_message = retry_reason
    return retry_jobs_created
