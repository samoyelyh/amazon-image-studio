from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.content import Asset, Project
from app.models.tasks import (
    BatchStatus, BatchTryOnTemplatePrompt, Job, JobBatch, JobStatus,
)
from app.schemas.batch_tryon_workflow import (
    BatchTryOnWorkflowAnalysisJob,
    BatchTryOnWorkflowCreateRequest,
    BatchTryOnWorkflowResponse,
    BatchTryOnTemplatePromptResponse,
)
from app.schemas.tasks import BatchJobItemRequest, JobBatchSubmitRequest, JobSubmitRequest
from app.services.batch_tryon_analysis_service import (
    AnalysisResultError,
    GARMENT_ANALYSIS_SYSTEM_PROMPT,
    GARMENT_ANALYSIS_USER_PROMPT,
    TEMPLATE_ANALYSIS_SYSTEM_PROMPT,
    build_template_analysis_prompt,
    normalize_garment_profile,
    normalize_template_profile,
    parse_analysis_text,
    validate_garment_profile,
    validate_template_profile,
)
from app.services.batch_tryon_prompt_service import (
    build_batch_try_on_prompt,
    build_template_prompt_composed_prompt,
)
from app.services.batch_tryon_prompt_template_service import (
    effective_prompt_text,
    prompt_analysis_preset_only,
    resolve_prompt_preset,
    template_prompt_response,
    validate_generated_final_prompt,
)
from app.services.billing_service import release_reservation, reserve_quota
from app.services.resource_pool_service import resolve_operation_model_code
from app.services.task_service import (
    dispatch_jobs, refresh_batch_status, request_hash as job_request_hash, submit_batch, submit_job,
    transition_job_status,
)


WORKFLOW_NAME = "batch_tryon_server_workflow"
TERMINAL = {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}
def _record(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _value(item: object, key: str, default: object = None) -> object:
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def _effective_garment_references(template: object, garment: object) -> tuple[list[str], str]:
    """Resolve ordinary reference images. These are never Provider edit masks."""
    original = str(_value(garment, "asset_id") or "")
    requested = str(_value(template, "garment_view", "auto") or "auto")
    front = str(_value(garment, "front_reference_asset_id") or "")
    back = str(_value(garment, "back_reference_asset_id") or "")
    detail = str(_value(garment, "detail_reference_asset_id") or "")
    if requested == "front":
        return [front or original], "front" if front else "original_fallback"
    if requested == "back":
        return [back or original], "back" if back else "original_fallback"
    if requested == "detail":
        return [detail or front or back or original], "detail" if detail else "original_fallback"
    if requested == "front_back":
        references = list(dict.fromkeys(value for value in (front, back) if value))
        return (references or [original]), "front_back" if len(references) == 2 else "original_fallback"
    return [original], "original"


def _job_reference_snapshot(
    *, template: object, garment: object, font_reference_asset_id: str | None,
) -> tuple[list[str], dict[str, object]]:
    garment_references, resolved_view = _effective_garment_references(template, garment)
    original = str(_value(garment, "asset_id") or "")
    references = [str(_value(template, "asset_id")), garment_references[0]]
    if font_reference_asset_id:
        references.append(font_reference_asset_id)
    references.extend(garment_references[1:])
    return references, {
        "garment_asset_id": original,
        "effective_garment_reference_asset_ids": garment_references,
        "effective_garment_view": resolved_view,
        "font_reference_asset_id": font_reference_asset_id,
    }


async def _effective_reference_filename_metadata(
    session: AsyncSession, reference_metadata: dict[str, object],
) -> dict[str, object]:
    """Expose the actual derived filenames used by Luna/provider without changing reference order."""
    reference_ids = [
        str(value) for value in reference_metadata.get("effective_garment_reference_asset_ids", []) or [] if value
    ]
    if not reference_ids:
        return {"effective_garment_reference_filenames": []}
    rows = (await session.execute(select(Asset.id, Asset.filename).where(Asset.id.in_(reference_ids)))).all()
    filenames_by_id = {str(asset_id): str(filename) for asset_id, filename in rows}
    filenames = [filenames_by_id.get(asset_id, asset_id) for asset_id in reference_ids]
    return {
        "effective_garment_reference_filename": filenames[0],
        "effective_garment_reference_filenames": filenames,
    }


def _workflow_request(root: Job) -> dict[str, Any]:
    metadata = _record(root.input_json.get("metadata"))
    request = metadata.get("workflow_request")
    if not isinstance(request, dict):
        raise AppError("batch_tryon.workflow_input_missing", "批量套图工作流输入不存在。", 409)
    return request


def _result_metadata(job: Job) -> dict[str, Any]:
    return _record(_record(job.result_json).get("metadata"))


def _analysis_text(job: Job) -> str:
    return str(_result_metadata(job).get("text") or "")


def _workflow_state(root: Job) -> dict[str, Any]:
    state = _result_metadata(root).get("workflow_state")
    return deepcopy(state) if isinstance(state, dict) else {}


def _set_workflow_state(root: Job, state: dict[str, Any]) -> None:
    result = deepcopy(root.result_json or {})
    metadata = _record(result.get("metadata"))
    result["metadata"] = {**metadata, "workflow_state": deepcopy(state)}
    root.result_json = result


async def _validate_inputs(
    session: AsyncSession, *, organization_id: str, user_id: str,
    payload: BatchTryOnWorkflowCreateRequest,
) -> None:
    project = await session.scalar(select(Project).where(
        Project.id == payload.project_id,
        Project.organization_id == organization_id,
        Project.project_type == "batch_tryon",
        Project.deleted_at.is_(None),
        Project.created_by == user_id,
    ))
    if project is None:
        raise AppError("project.not_found", "批量套图项目不存在。", 404)
    if payload.workspace_batch_id:
        workspace = await session.scalar(select(JobBatch).where(
            JobBatch.id == payload.workspace_batch_id,
            JobBatch.organization_id == organization_id,
            JobBatch.project_id == payload.project_id,
            JobBatch.batch_kind == "workspace",
            JobBatch.created_by == user_id,
        ))
        if workspace is None:
            raise AppError("batch_tryon.workspace_not_found", "批次工作台不存在或不属于当前项目。", 404)
    asset_ids = {item.asset_id for item in payload.templates} | {item.asset_id for item in payload.garments}
    asset_ids.update(item.font_reference_asset_id for item in payload.garments if item.font_reference_asset_id)
    for item in payload.garments:
        asset_ids.update(filter(None, (
            item.front_reference_asset_id, item.back_reference_asset_id, item.detail_reference_asset_id,
        )))
    asset_ids.update(item.font_reference_asset_id for item in (payload.combinations or []) if item.font_reference_asset_id)
    found = set((await session.scalars(select(Asset.id).where(
        Asset.organization_id == organization_id,
        Asset.id.in_(asset_ids),
        Asset.deleted_at.is_(None),
    ))).all())
    if found != asset_ids:
        raise AppError("asset.not_found", "一个或多个模板图或服装图不存在。", 404)
    reference_ids = {
        reference_id
        for garment in payload.garments
        for reference_id in (
            garment.front_reference_asset_id, garment.back_reference_asset_id, garment.detail_reference_asset_id,
        ) if reference_id
    }
    if reference_ids:
        references = list((await session.scalars(select(Asset).where(
            Asset.organization_id == organization_id,
            Asset.id.in_(reference_ids),
            Asset.deleted_at.is_(None),
        ))).all())
        by_id = {asset.id: asset for asset in references}
        for garment in payload.garments:
            for reference_id in (
                garment.front_reference_asset_id, garment.back_reference_asset_id, garment.detail_reference_asset_id,
            ):
                if not reference_id:
                    continue
                reference = by_id.get(reference_id)
                if reference is None or reference.category != "garment_reference" or reference.source_asset_id != garment.asset_id:
                    raise AppError(
                        "batch_tryon.invalid_garment_reference",
                        "服装参考图必须是由当前服装原图生成的派生参考图。", 422,
                    )


async def create_batch_tryon_workflow(
    session: AsyncSession, settings: Settings, *, organization_id: str, user_id: str,
    payload: BatchTryOnWorkflowCreateRequest,
) -> tuple[Job, list[Job], bool]:
    await _validate_inputs(
        session, organization_id=organization_id, user_id=user_id, payload=payload,
    )
    # The workflow anchor is completed locally. It is never dispatched to
    # Celery or a Provider, and its temporary quota reservation is released.
    first = sorted(payload.garments, key=lambda item: (item.order, item.garment_id))[0]
    request = payload.model_dump(mode="json")
    ordered_templates = sorted(payload.templates, key=lambda item: (item.order, item.template_id))
    if payload.prompt_mode == "ai_detailed":
        model_code = await resolve_operation_model_code(
            session,
            organization_id=organization_id,
            operation_code="batch_tryon.prompt_analyze_detailed",
            capability="text_generation",
            additional_capabilities={"vision_input"},
        )
        templates_by_id = {item.template_id: item for item in ordered_templates}
        garments_by_id = {item.garment_id: item for item in payload.garments}
        combinations = list(payload.combinations or []) or [
            {
                "client_item_id": f"{template.template_id}:{garment.garment_id}",
                "template_id": template.template_id,
                "garment_id": garment.garment_id,
                "order": index,
            }
            for index, (template, garment) in enumerate(
                (template, garment) for template in ordered_templates for garment in payload.garments
            )
        ]
        combinations.sort(key=lambda item: (
            int(item.order if hasattr(item, "order") else item["order"]),
            str(item.client_item_id if hasattr(item, "client_item_id") else item["client_item_id"]),
        ))
        created_jobs: list[Job] = []
        analysis_root: Job | None = None
        analysis_root_created = False
        preset_cache: dict[str, object] = {}
        for index, combination in enumerate(combinations):
            client_item_id = str(combination.client_item_id if hasattr(combination, "client_item_id") else combination["client_item_id"])
            template_id = str(combination.template_id if hasattr(combination, "template_id") else combination["template_id"])
            garment_id = str(combination.garment_id if hasattr(combination, "garment_id") else combination["garment_id"])
            template = templates_by_id[template_id]
            garment = garments_by_id[garment_id]
            font_reference_asset_id = combination.font_reference_asset_id or garment.font_reference_asset_id
            reference_asset_ids, reference_metadata = _job_reference_snapshot(
                template=template, garment=garment, font_reference_asset_id=font_reference_asset_id,
            )
            reference_metadata.update(await _effective_reference_filename_metadata(session, reference_metadata))
            preset = preset_cache.get(template_id)
            if preset is None:
                preset = await resolve_prompt_preset(
                    session,
                    organization_id=organization_id,
                    user_id=user_id,
                    preset_id=template.prompt_preset_id,
                    template_type=template.template_type,
                )
                preset_cache[template_id] = preset
            # Luna detailed analysis must execute the selected/edited preset verbatim.
            # Do not prepend or append language, role, image-order, or analysis instructions.
            analysis_prompt = (template.analysis_prompt or preset.analysis_prompt_template).strip()
            metadata: dict[str, object] = {
                "workflow": WORKFLOW_NAME,
                "workflow_role": "detailed_prompt_analysis" if index == 0 else "detailed_prompt_analysis_child",
                "template_id": template_id,
                "garment_id": garment_id,
                "client_item_id": client_item_id,
                "template_type": template.template_type,
                "prompt_preset_id": preset.id,
                "template_asset_id": template.asset_id,
                "garment_asset_id": garment.asset_id,
                "template_name": template.name,
                "garment_filename": garment.filename,
                "font_reference_asset_id": font_reference_asset_id,
                "prompt_mode": "ai_detailed",
                **reference_metadata,
            }
            if index == 0:
                metadata["workflow_request"] = request
            elif analysis_root is not None:
                metadata["workflow_root_job_id"] = analysis_root.id
            job, created = await submit_job(
                session,
                settings,
                organization_id=organization_id,
                user_id=user_id,
                payload=JobSubmitRequest(
                    operation_code="batch_tryon.prompt_analyze_detailed",
                    workspace_type="batch_tryon",
                    queue_name="planning_queue",
                    capability="text_generation",
                    model_code=model_code,
                    idempotency_key=(
                        f"batch-workflow-detailed:{payload.idempotency_key}"
                        if index == 0 else f"batch-workflow-detailed:{payload.idempotency_key}:item:{client_item_id}"
                    ),
                    project_id=payload.project_id,
                    client_item_id=f"prompt-detail:{client_item_id}",
                    input={
                        "system_prompt": analysis_prompt,
                        "user_prompt": "",
                        "response_format": "text",
                        "reference_asset_ids": reference_asset_ids,
                        "metadata": metadata,
                    },
                    billing_factors={"quality": "detailed", "resolution": "text"},
                ),
            )
            if index == 0:
                analysis_root = job
                analysis_root_created = created
            if created:
                created_jobs.append(job)
                session.add(BatchTryOnTemplatePrompt(
                    organization_id=organization_id,
                    workflow_job_id=analysis_root.id,
                    template_id=template_id,
                    garment_id=garment_id,
                    client_item_id=client_item_id,
                    template_type=template.template_type,
                    preset_id=preset.id,
                    template_asset_id=template.asset_id,
                    first_garment_asset_id=str(reference_metadata["effective_garment_reference_asset_ids"][0]),
                    font_reference_asset_id=font_reference_asset_id,
                    analysis_job_id=job.id,
                    analysis_prompt_used=analysis_prompt,
                    generated_final_prompt=None,
                    edited_final_prompt=None,
                    prompt_status="analyzing",
                    prompt_version=1,
                    created_by=user_id,
                    updated_by=user_id,
                ))
        if analysis_root is None:
            raise AppError("batch_tryon.workflow_input_invalid", "批量套图工作流缺少组合。", 422)
        await session.flush()
        return analysis_root, created_jobs, analysis_root_created
    if payload.prompt_mode == "ai_analysis":
        model_code = await resolve_operation_model_code(
            session,
            organization_id=organization_id,
            operation_code="batch_tryon.prompt_analyze",
            capability="text_generation",
            additional_capabilities={"vision_input"},
        )
        created_jobs: list[Job] = []
        analysis_root: Job | None = None
        analysis_root_created = False
        garments_by_id = {item.garment_id: item for item in payload.garments}
        for index, template in enumerate(ordered_templates):
            preset = await resolve_prompt_preset(
                session,
                organization_id=organization_id,
                user_id=user_id,
                preset_id=template.prompt_preset_id,
                template_type=template.template_type,
            )
            first_combination = next((item for item in (payload.combinations or []) if (
                item.template_id == template.template_id
            )), None)
            analysis_garment = garments_by_id.get(first_combination.garment_id) if first_combination else first
            analysis_garment = analysis_garment or first
            font_reference_asset_id = (
                first_combination.font_reference_asset_id if first_combination and first_combination.font_reference_asset_id
                else analysis_garment.font_reference_asset_id
            )
            reference_asset_ids, reference_metadata = _job_reference_snapshot(
                template=template, garment=analysis_garment, font_reference_asset_id=font_reference_asset_id,
            )
            reference_metadata.update(await _effective_reference_filename_metadata(session, reference_metadata))
            # The selected/edited preset is the complete and only text instruction.
            analysis_prompt = (template.analysis_prompt or preset.analysis_prompt_template).strip()
            metadata: dict[str, object] = {
                "workflow": WORKFLOW_NAME,
                "workflow_role": "prompt_analysis" if index == 0 else "prompt_analysis_child",
                "template_id": template.template_id,
                "template_type": template.template_type,
                "prompt_preset_id": preset.id,
                "template_asset_id": template.asset_id,
                "first_garment_asset_id": analysis_garment.asset_id,
                "template_name": template.name,
                "garment_filename": analysis_garment.filename,
                "font_reference_asset_id": font_reference_asset_id,
                "prompt_mode": "ai_analysis",
                **reference_metadata,
            }
            if index == 0:
                metadata["workflow_request"] = request
            elif analysis_root is not None:
                metadata["workflow_root_job_id"] = analysis_root.id
            job, created = await submit_job(
                session,
                settings,
                organization_id=organization_id,
                user_id=user_id,
                payload=JobSubmitRequest(
                    operation_code="batch_tryon.prompt_analyze",
                    workspace_type="batch_tryon",
                    queue_name="planning_queue",
                    capability="text_generation",
                    model_code=model_code,
                    idempotency_key=(
                        f"batch-workflow:{payload.idempotency_key}"
                        if index == 0 else f"batch-workflow:{payload.idempotency_key}:template:{template.template_id}"
                    ),
                    project_id=payload.project_id,
                    client_item_id=f"prompt:{template.template_id}",
                    input={
                        "system_prompt": analysis_prompt,
                        "user_prompt": "",
                        "response_format": "text",
                        "reference_asset_ids": reference_asset_ids,
                        "metadata": metadata,
                    },
                    billing_factors={"quality": "standard", "resolution": "text"},
                ),
            )
            if index == 0:
                analysis_root = job
                analysis_root_created = created
            if created:
                created_jobs.append(job)
                session.add(BatchTryOnTemplatePrompt(
                    organization_id=organization_id,
                    workflow_job_id=analysis_root.id,
                    template_id=template.template_id,
                    garment_id=analysis_garment.garment_id,
                    client_item_id=f"template:{template.template_id}",
                    template_type=template.template_type,
                    preset_id=preset.id,
                    template_asset_id=template.asset_id,
                    first_garment_asset_id=str(reference_metadata["effective_garment_reference_asset_ids"][0]),
                    font_reference_asset_id=font_reference_asset_id,
                    analysis_job_id=job.id,
                    analysis_prompt_used=analysis_prompt,
                    generated_final_prompt=None,
                    edited_final_prompt=None,
                    prompt_status="analyzing",
                    prompt_version=1,
                    created_by=user_id,
                    updated_by=user_id,
                ))
        if analysis_root is None:
            raise AppError("batch_tryon.workflow_input_invalid", "批量套图工作流缺少模板。", 422)
        await session.flush()
        return analysis_root, created_jobs, analysis_root_created

    first_template = ordered_templates[0]
    root_payload = JobSubmitRequest(
        operation_code="batch_tryon.prompt_analyze",
        workspace_type="batch_tryon",
        queue_name="planning_queue",
        capability="text_generation",
        model_code="direct-prompt",
        idempotency_key=f"batch-workflow:{payload.idempotency_key}",
        project_id=payload.project_id,
        client_item_id=f"prompt-direct:{first_template.template_id}",
        input={"metadata": {
            "workflow": WORKFLOW_NAME,
            "workflow_role": "direct_prompt",
            "workflow_request": request,
            "prompt_mode": "direct_preset",
        }},
        billing_factors={"quality": "standard", "resolution": "text"},
    )
    fingerprint = job_request_hash(root_payload)
    root = await session.scalar(select(Job).where(
        Job.organization_id == organization_id,
        Job.idempotency_key == root_payload.idempotency_key,
    ).with_for_update())
    if root is not None:
        if root.request_hash != fingerprint:
            raise AppError("job.idempotency_conflict", "Idempotency key was already used with different job input", 409)
        return root, [], False
    reservation_reference = root_payload.idempotency_key
    if len(reservation_reference) > 100:
        reservation_reference = f"idempotency:{sha256(reservation_reference.encode('utf-8')).hexdigest()}"
    reservation = await reserve_quota(
        session,
        settings,
        organization_id=organization_id,
        user_id=user_id,
        operation_code=root_payload.operation_code,
        quantity=1,
        factors={
            **root_payload.billing_factors,
            "model": root_payload.model_code,
            "resource_pool": "platform",
        },
        idempotency_key=f"job:{root_payload.idempotency_key}",
        reference_type="job_submission",
        reference_id=reservation_reference,
    )
    root = Job(
        organization_id=organization_id,
        project_id=root_payload.project_id,
        quota_reservation_id=reservation.id,
        operation_code=root_payload.operation_code,
        workspace_type=root_payload.workspace_type,
        queue_name=root_payload.queue_name,
        capability=root_payload.capability,
        model_code=root_payload.model_code,
        input_json=root_payload.input,
        client_item_id=root_payload.client_item_id,
        idempotency_key=root_payload.idempotency_key,
        request_hash=fingerprint,
        max_attempts=settings.job_max_attempts,
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(root)
    await session.flush()
    reservation.reference_type = "job"
    reservation.reference_id = root.id
    root_created = True

    for template in ordered_templates:
        preset = await resolve_prompt_preset(
            session,
            organization_id=organization_id,
            user_id=user_id,
            preset_id=template.prompt_preset_id,
            template_type=template.template_type,
        )
        direct_prompt = validate_generated_final_prompt(
            (template.analysis_prompt or preset.analysis_prompt_template).strip()
        )
        session.add(BatchTryOnTemplatePrompt(
            organization_id=organization_id,
            workflow_job_id=root.id,
            template_id=template.template_id,
            garment_id=first.garment_id,
            client_item_id=f"template:{template.template_id}",
            template_type=template.template_type,
            preset_id=preset.id,
            template_asset_id=template.asset_id,
            first_garment_asset_id=first.asset_id,
            font_reference_asset_id=first.font_reference_asset_id,
            analysis_job_id=None,
            analysis_prompt_used=direct_prompt,
            generated_final_prompt=direct_prompt,
            edited_final_prompt=None,
            prompt_status="effective",
            prompt_version=1,
            created_by=user_id,
            updated_by=user_id,
        ))
    transition_job_status(root, JobStatus.SUCCEEDED.value, reason="direct_prompt_snapshot_created")
    root.progress = 100
    root.finished_at = datetime.now(timezone.utc)
    root.result_json = {"metadata": {
        "prompt_mode": "direct_preset",
        "workflow_state": {
            "status": "awaiting_prompt_confirmation",
            "error_code": None,
            "error_message": None,
        },
    }}
    await release_reservation(
        session,
        organization_id=organization_id,
        reservation_id=root.quota_reservation_id,
        user_id=user_id,
        idempotency_key=f"direct-prompt:{root.id}",
    )
    if root is None:
        raise AppError("batch_tryon.workflow_input_invalid", "批量套图工作流缺少模板。", 422)
    await session.flush()
    return root, [], root_created


async def _root_for_planning_job(session: AsyncSession, planning_job: Job, *, lock: bool) -> Job | None:
    metadata = _record(planning_job.input_json.get("metadata"))
    if metadata.get("workflow") != WORKFLOW_NAME:
        return None
    root_id = planning_job.id if metadata.get("workflow_role") in {
        "garment_analysis", "prompt_analysis", "detailed_prompt_analysis", "direct_prompt",
    } else str(metadata.get("workflow_root_job_id") or "")
    statement = select(Job).where(Job.id == root_id, Job.organization_id == planning_job.organization_id)
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def _continue_legacy_batch_tryon_workflow(
    session: AsyncSession, settings: Settings, *, planning_job: Job,
) -> JobBatch | None:
    root = await _root_for_planning_job(session, planning_job, lock=True)
    if root is None:
        return None
    request = _workflow_request(root)
    state = _workflow_state(root)
    if state.get("batch_id"):
        return await session.get(JobBatch, str(state["batch_id"]))
    if root.status != JobStatus.SUCCEEDED.value:
        return None

    templates = sorted(list(request.get("templates") or []), key=lambda item: (int(item.get("order") or 0), str(item.get("template_id") or "")))
    garments = sorted(list(request.get("garments") or []), key=lambda item: (int(item.get("order") or 0), str(item.get("garment_id") or "")))
    if not templates or not garments:
        raise AppError("batch_tryon.workflow_input_invalid", "批量套图工作流缺少模板或服装。", 409)

    try:
        garment_profile = normalize_garment_profile(
            parse_analysis_text(_analysis_text(root)),
            source_asset_id=str(garments[0]["asset_id"]),
            model_code=root.model_code,
        )
        validate_garment_profile(garment_profile)
    except AnalysisResultError as error:
        state.update({
            "status": "failed",
            "error_code": error.code,
            "error_message": error.message,
        })
        _set_workflow_state(root, state)
        await session.commit()
        return None
    template_job_ids = [str(item) for item in state.get("template_job_ids") or []]
    if not template_job_ids:
        created_jobs: list[Job] = []
        for template in templates:
            template_key = sha256(f"{root.id}:{template['template_id']}".encode()).hexdigest()
            job, created = await submit_job(
                session,
                settings,
                organization_id=root.organization_id,
                user_id=root.created_by,
                payload=JobSubmitRequest(
                    operation_code="batch_tryon.style_analyze",
                    workspace_type="batch_tryon",
                    queue_name="planning_queue",
                    capability="text_generation",
                    model_code=root.model_code,
                    idempotency_key=f"batch-template:{template_key}",
                    project_id=root.project_id,
                    client_item_id=f"template:{template['template_id']}",
                    input={
                        "system_prompt": TEMPLATE_ANALYSIS_SYSTEM_PROMPT,
                        "user_prompt": build_template_analysis_prompt(
                            mode=str(request.get("generation_mode") or "normal_tryon"),
                            requested=template,
                        ),
                        "reference_asset_ids": [str(template["asset_id"])],
                        "metadata": {
                            "workflow": WORKFLOW_NAME,
                            "workflow_role": "template_analysis",
                            "workflow_root_job_id": root.id,
                            "template_id": template["template_id"],
                            "template_request": template,
                        },
                    },
                ),
            )
            template_job_ids.append(job.id)
            if created:
                created_jobs.append(job)
        state.update({
            "status": "analyzing_templates",
            "template_job_ids": template_job_ids,
            "garment_profile": garment_profile,
        })
        _set_workflow_state(root, state)
        await session.flush()
        if created_jobs:
            await dispatch_jobs(session, created_jobs)
        return None

    jobs = list((await session.scalars(select(Job).where(
        Job.organization_id == root.organization_id,
        Job.id.in_(template_job_ids),
    ))).all())
    failed = next((job for job in jobs if job.status in {JobStatus.FAILED.value, JobStatus.CANCELLED.value}), None)
    if failed:
        state.update({
            "status": "failed",
            "error_code": failed.error_code or "batch_tryon.template_analysis_failed",
            "error_message": failed.error_message or "模板分析失败。",
        })
        _set_workflow_state(root, state)
        await session.commit()
        return None
    if len(jobs) != len(template_job_ids) or any(job.status != JobStatus.SUCCEEDED.value for job in jobs):
        state["status"] = "analyzing_templates"
        _set_workflow_state(root, state)
        await session.commit()
        return None

    job_by_template = {
        str(_record(job.input_json.get("metadata")).get("template_id")): job for job in jobs
    }
    template_profiles: dict[str, dict[str, object]] = {}
    for template in templates:
        template_id = str(template["template_id"])
        try:
            profile = normalize_template_profile(
                parse_analysis_text(_analysis_text(job_by_template[template_id])), requested=template,
            )
            validate_template_profile(profile)
            template_profiles[template_id] = profile
        except AnalysisResultError as error:
            state.update({
                "status": "failed",
                "error_code": error.code,
                "error_message": f"模板“{template['name']}”分析结果无效，请重新生成组合。",
            })
            _set_workflow_state(root, state)
            await session.commit()
            return None

    image_model = await resolve_operation_model_code(
        session,
        organization_id=root.organization_id,
        operation_code="batch_tryon.generate",
        capability="image_edit",
    )
    items: list[BatchJobItemRequest] = []
    mode = str(request.get("generation_mode") or "normal_tryon")
    template_count = len(templates)
    preset_selection = _record(request.get("preset_selection"))
    templates_by_id = {str(item["template_id"]): item for item in templates}
    garments_by_id = {str(item["garment_id"]): item for item in garments}
    template_order = {str(item["template_id"]): index for index, item in enumerate(templates)}
    garment_order = {str(item["garment_id"]): index for index, item in enumerate(garments)}
    combinations = list(request.get("combinations") or [])
    if not combinations:
        combinations = [
            {
                "client_item_id": f"{template['template_id']}:{garment['garment_id']}",
                "template_id": template["template_id"],
                "garment_id": garment["garment_id"],
                "order": len(garments) * template_order[str(template["template_id"])] + garment_order[str(garment["garment_id"])],
            }
            for template in templates for garment in garments
        ]
    combinations.sort(key=lambda item: (int(item.get("order") or 0), str(item.get("client_item_id") or "")))
    for combination in combinations:
            template_id = str(combination["template_id"])
            garment_id = str(combination["garment_id"])
            template = templates_by_id[template_id]
            garment = garments_by_id[garment_id]
            template_index = template_order[template_id]
            garment_index = garment_order[garment_id]
            profile = template_profiles[template_id]
            reference_asset_ids, reference_metadata = _job_reference_snapshot(
                template=template, garment=garment, font_reference_asset_id=None,
            )
            prompt = build_batch_try_on_prompt(
                mode=mode,
                garment_filename=str(garment["filename"]),
                template_name=str(template["name"]),
                garment_profile=garment_profile,
                template_profile=profile,
                preset_selection=preset_selection,
                extra_requirements=str(request.get("extra_requirements") or ""),
            )
            client_item_id = str(combination["client_item_id"])
            items.append(BatchJobItemRequest(
                client_item_id=client_item_id,
                prompt=prompt.effective_prompt,
                reference_asset_ids=reference_asset_ids,
                size=str(combination.get("size") or request.get("size") or "2048x2048"),
                aspect_ratio=str(combination.get("aspect_ratio") or request.get("aspect_ratio") or "1:1"),
                requested_width=combination.get("requested_width") or request.get("requested_width"),
                requested_height=combination.get("requested_height") or request.get("requested_height"),
                quality=str(request.get("quality") or "high"),
                output_format=str(request.get("output_format") or "png"),
                output_compression=request.get("output_compression"),
                metadata={
                    "workflow": WORKFLOW_NAME,
                    "workflow_root_job_id": root.id,
                    "generation_mode": mode,
                    "garment_filename": garment["filename"],
                    "source_filename": garment["filename"],
                    "garment_id": garment["garment_id"],
                    "garment_asset_id": garment["asset_id"],
                    **reference_metadata,
                    "qc_reference_asset_id": reference_metadata["effective_garment_reference_asset_ids"][0],
                    "template_id": record.template_id,
                    "template_name": template["name"],
                    "template_index": template_index,
                    "template_count": template_count,
                    "garment_index": garment_index,
                    "preset_codes": preset_selection,
                    "preset_summary": "; ".join(f"{key}={value}" for key, value in preset_selection.items() if value),
                    "batch_style_profile": garment_profile,
                    "first_sample_observation": garment_profile.get("observation") or {},
                    "template_analysis": profile,
                    "business_prompt": prompt.business_prompt,
                    "technical_delivery_contract": prompt.technical_delivery_contract,
                    "effective_prompt": prompt.effective_prompt,
                    "index": len(items),
                },
            ))

    state["status"] = "submitting_batch"
    _set_workflow_state(root, state)
    batch, image_jobs, created = await submit_batch(
        session,
        settings,
        organization_id=root.organization_id,
        user_id=root.created_by,
        payload=JobBatchSubmitRequest(
            name=str(request.get("name") or "批量套图"),
            workspace_type="batch_tryon",
            operation_code="batch_tryon.generate",
            capability="image_edit",
            model_code=image_model,
            idempotency_key=f"batch-workflow-images:{root.id}",
            project_id=root.project_id,
            concurrency=int(request.get("concurrency") or 12),
            admin_test_mode=bool(request.get("admin_test_mode")),
            items=items,
        ),
    )
    state.update({
        "status": "generating",
        "batch_id": batch.id,
        "garment_profile": garment_profile,
        "template_profiles": template_profiles,
    })
    _set_workflow_state(root, state)
    await session.commit()
    if created:
        await dispatch_jobs(session, image_jobs[:batch.concurrency])
    return batch


async def _create_detailed_streaming_batch(
    session: AsyncSession, settings: Settings, *, root: Job,
    records: list[BatchTryOnTemplatePrompt],
) -> tuple[JobBatch, list[Job], bool]:
    """Create the production batch while Luna analyses are still running.

    Image jobs are durable placeholders in ``waiting_for_resource`` until their
    own Luna record becomes effective. This preserves the existing JobBatch and
    review/version systems while allowing each combination to enter image
    generation independently.
    """
    state = _workflow_state(root)
    if state.get("batch_id"):
        batch = await session.get(JobBatch, str(state["batch_id"]))
        if batch is None:
            raise AppError("batch_tryon.batch_missing", "工作流关联的图片批次不存在。", 409)
        jobs = list((await session.scalars(
            select(Job).where(Job.batch_id == batch.id).order_by(Job.created_at, Job.id)
        )).all())
        return batch, jobs, False

    request = _workflow_request(root)
    templates = sorted(list(request.get("templates") or []), key=lambda item: (
        int(item.get("order") or 0), str(item.get("template_id") or ""),
    ))
    garments = sorted(list(request.get("garments") or []), key=lambda item: (
        int(item.get("order") or 0), str(item.get("garment_id") or ""),
    ))
    templates_by_id = {str(item["template_id"]): item for item in templates}
    garments_by_id = {str(item["garment_id"]): item for item in garments}
    template_order = {str(item["template_id"]): index for index, item in enumerate(templates)}
    garment_order = {str(item["garment_id"]): index for index, item in enumerate(garments)}
    record_by_item = {str(record.client_item_id): record for record in records if record.client_item_id}
    combinations = list(request.get("combinations") or []) or [
        {
            "client_item_id": f"{template['template_id']}:{garment['garment_id']}",
            "template_id": template["template_id"],
            "garment_id": garment["garment_id"],
            "order": len(garments) * template_order[str(template["template_id"])] + garment_order[str(garment["garment_id"])],
        }
        for template in templates for garment in garments
    ]
    combinations.sort(key=lambda item: (int(item.get("order") or 0), str(item.get("client_item_id") or "")))
    missing = [str(item.get("client_item_id") or "") for item in combinations if str(item.get("client_item_id") or "") not in record_by_item]
    if missing:
        raise AppError(
            "batch_tryon.prompts_missing",
            "Luna 逐图任务缺少对应的提示词记录。",
            409,
            {"missing_prompt_keys": missing},
        )

    image_model = await resolve_operation_model_code(
        session,
        organization_id=root.organization_id,
        operation_code="batch_tryon.generate",
        capability="image_edit",
    )
    items: list[BatchJobItemRequest] = []
    for combination in combinations:
        client_item_id = str(combination["client_item_id"])
        template_id = str(combination["template_id"])
        garment_id = str(combination["garment_id"])
        template = templates_by_id[template_id]
        garment = garments_by_id[garment_id]
        record = record_by_item[client_item_id]
        font_reference_asset_id = str(
            combination.get("font_reference_asset_id") or garment.get("font_reference_asset_id") or ""
        ).strip() or None
        reference_asset_ids, reference_metadata = _job_reference_snapshot(
            template=template,
            garment=garment,
            font_reference_asset_id=font_reference_asset_id,
        )
        items.append(BatchJobItemRequest(
            client_item_id=client_item_id,
            prompt="Luna detailed analysis is pending for this image.",
            reference_asset_ids=reference_asset_ids,
            size=str(combination.get("size") or request.get("size") or "2048x2048"),
            aspect_ratio=str(combination.get("aspect_ratio") or request.get("aspect_ratio") or "1:1"),
            requested_width=combination.get("requested_width") or request.get("requested_width"),
            requested_height=combination.get("requested_height") or request.get("requested_height"),
            quality=str(request.get("quality") or "high"),
            output_format=str(request.get("output_format") or "png"),
            output_compression=request.get("output_compression"),
            metadata={
                "workflow": WORKFLOW_NAME,
                "workflow_root_job_id": root.id,
                "generation_mode": str(request.get("generation_mode") or "normal_tryon"),
                "template_prompt_id": record.id,
                "prompt_preset_id": record.preset_id,
                "prompt_version": record.prompt_version,
                "analysis_prompt_snapshot": record.analysis_prompt_used,
                "template_type": record.template_type,
                "luna_analysis_job_id": record.analysis_job_id,
                "awaiting_luna": True,
                "garment_filename": garment["filename"],
                "source_filename": garment["filename"],
                "garment_id": garment_id,
                "garment_asset_id": garment["asset_id"],
                "font_reference_asset_id": font_reference_asset_id,
                **reference_metadata,
                "qc_reference_asset_id": reference_metadata["effective_garment_reference_asset_ids"][0],
                "template_id": template_id,
                "template_name": template["name"],
                "template_index": template_order[template_id],
                "template_count": len(templates),
                "garment_index": garment_order[garment_id],
                "index": len(items),
            },
        ))

    batch, image_jobs, created = await submit_batch(
        session,
        settings,
        organization_id=root.organization_id,
        user_id=root.created_by,
        payload=JobBatchSubmitRequest(
            name=str(request.get("name") or "批量套图"),
            workspace_type="batch_tryon",
            operation_code="batch_tryon.generate",
            capability="image_edit",
            model_code=image_model,
            idempotency_key=f"batch-workflow-streaming-images:{root.id}",
            project_id=root.project_id,
            concurrency=int(request.get("concurrency") or 12),
            admin_test_mode=bool(request.get("admin_test_mode")),
            items=items,
        ),
    )
    batch.parent_batch_id = str(request.get("workspace_batch_id") or "") or None
    batch.batch_kind = "production"
    if created:
        hold_until = datetime.now(timezone.utc) + timedelta(days=3650)
        for job in image_jobs:
            transition_job_status(job, JobStatus.WAITING_FOR_RESOURCE.value, reason="batch_tryon.luna_analysis_pending")
            job.next_dispatch_at = hold_until
            job.error_code = "batch_tryon.luna_analysis_pending"
            job.error_message = "Luna 正在分析该图片，完成后会立即进入生图。"
    if batch.parent_batch_id:
        workspace = await session.get(JobBatch, batch.parent_batch_id)
        if workspace:
            workspace.status = "queued"
            workspace.updated_by = root.created_by
    state.update({"status": "generating", "batch_id": batch.id, "streaming_luna": True})
    _set_workflow_state(root, state)
    await session.flush()
    return batch, image_jobs, created


async def _activate_ready_detailed_image_jobs(
    session: AsyncSession, *, root: Job, batch: JobBatch,
    records: list[BatchTryOnTemplatePrompt], image_jobs: list[Job],
) -> list[Job]:
    request = _workflow_request(root)
    templates = {str(item["template_id"]): item for item in list(request.get("templates") or [])}
    garments = {str(item["garment_id"]): item for item in list(request.get("garments") or [])}
    template_order = {template_id: index for index, template_id in enumerate(templates)}
    garment_order = {garment_id: index for index, garment_id in enumerate(garments)}
    record_by_item = {str(record.client_item_id): record for record in records if record.client_item_id}
    jobs_by_item = {str(job.client_item_id): job for job in image_jobs if job.client_item_id}
    ready_jobs: list[Job] = []
    for client_item_id, record in record_by_item.items():
        job = jobs_by_item.get(client_item_id)
        if job is None or job.status in TERMINAL or job.status in {JobStatus.RUNNING.value, JobStatus.DISPATCHING.value}:
            continue
        if record.prompt_status == "failed":
            transition_job_status(job, JobStatus.FAILED.value, reason=record.error_code or "batch_tryon.prompt_analysis_failed")
            job.error_code = record.error_code or "batch_tryon.prompt_analysis_failed"
            job.error_message = record.error_message or "Luna 精细分析失败。"
            job.finished_at = datetime.now(timezone.utc)
            job.next_dispatch_at = None
            await release_reservation(
                session,
                organization_id=job.organization_id,
                reservation_id=job.quota_reservation_id,
                user_id=job.updated_by,
                idempotency_key=f"luna-analysis-failed:{job.id}",
            )
            continue
        reusable_prompt = effective_prompt_text(record)
        if record.prompt_status != "effective" or not reusable_prompt:
            continue
        metadata = _record(job.input_json.get("metadata"))
        if not metadata.get("awaiting_luna"):
            continue
        template_id = str(metadata.get("template_id") or "")
        garment_id = str(metadata.get("garment_id") or "")
        template = templates[template_id]
        garment = garments[garment_id]
        font_reference_asset_id = str(metadata.get("font_reference_asset_id") or "").strip() or None
        reference_asset_ids, reference_metadata = _job_reference_snapshot(
            template=template,
            garment=garment,
            font_reference_asset_id=font_reference_asset_id,
        )
        composed = build_template_prompt_composed_prompt(
            template_type=record.template_type,
            reusable_final_prompt=reusable_prompt,
            garment_filename=str(garment["filename"]),
            template_name=str(template["name"]),
            extra_requirements=str(request.get("extra_requirements") or ""),
            has_font_reference=bool(font_reference_asset_id),
            garment_reference_count=len(reference_metadata["effective_garment_reference_asset_ids"]),
        )
        next_metadata = {
            **metadata,
            "awaiting_luna": False,
            "effective_prompt_snapshot": reusable_prompt,
            "prompt_version": record.prompt_version,
            "analysis_prompt_snapshot": record.analysis_prompt_used,
            "business_prompt": composed.business_prompt,
            "technical_delivery_contract": composed.technical_delivery_contract,
            "effective_prompt": composed.effective_prompt,
            "template_index": template_order.get(template_id, 0),
            "template_count": len(templates),
            "garment_index": garment_order.get(garment_id, 0),
        }
        job.input_json = {
            **job.input_json,
            "prompt": composed.effective_prompt,
            "reference_asset_ids": reference_asset_ids,
            "metadata": next_metadata,
        }
        transition_job_status(job, JobStatus.QUEUED.value, reason="batch_tryon.luna_analysis_ready")
        job.next_dispatch_at = None
        job.error_code = None
        job.error_message = None
        ready_jobs.append(job)
    await refresh_batch_status(session, batch.id)
    await session.flush()
    return ready_jobs


async def _continue_prompt_analysis_workflow(
    session: AsyncSession, settings: Settings, *, root: Job,
) -> tuple[JobBatch | None, list[Job]]:
    detailed = str(_record(root.input_json.get("metadata")).get("workflow_role") or "") == "detailed_prompt_analysis"
    existing_state = _workflow_state(root)
    request = _workflow_request(root)
    streaming_detailed = detailed and request.get("submission_kind") == "production"
    if existing_state.get("batch_id") and not streaming_detailed:
        return None, []
    records = list((await session.scalars(
        select(BatchTryOnTemplatePrompt)
        .where(
            BatchTryOnTemplatePrompt.organization_id == root.organization_id,
            BatchTryOnTemplatePrompt.workflow_job_id == root.id,
        )
        .order_by(BatchTryOnTemplatePrompt.created_at, BatchTryOnTemplatePrompt.id)
        .with_for_update()
    )).all())
    if not records:
        raise AppError(
            "batch_tryon.template_prompts_missing",
            "当前批量套图工作流缺少模板提示词记录。",
            409,
        )
    job_ids = [record.analysis_job_id for record in records if record.analysis_job_id]
    jobs = list((await session.scalars(select(Job).where(
        Job.organization_id == root.organization_id,
        Job.id.in_(job_ids),
    ))).all()) if job_ids else []
    job_by_id = {job.id: job for job in jobs}
    has_pending = False
    has_failed = False
    first_error_code: str | None = None
    first_error_message: str | None = None
    for record in records:
        job = job_by_id.get(str(record.analysis_job_id or ""))
        if job is None:
            record.prompt_status = "failed"
            record.error_code = "batch_tryon.prompt_analysis_job_missing"
            record.error_message = "提示词分析任务不存在。"
            has_failed = True
        elif job.status == JobStatus.SUCCEEDED.value and record.prompt_status in {"ready", "effective"} and record.generated_final_prompt:
            record.error_code = None
            record.error_message = None
        elif job.status == JobStatus.SUCCEEDED.value:
            try:
                generated = validate_generated_final_prompt(_analysis_text(job))
            except AppError as error:
                record.prompt_status = "failed"
                record.error_code = error.code
                record.error_message = error.message
                has_failed = True
            else:
                if record.generated_final_prompt != generated:
                    record.generated_final_prompt = generated
                    record.edited_final_prompt = None
                record.prompt_status = "effective" if detailed else "ready"
                record.error_code = None
                record.error_message = None
        elif job.status in {JobStatus.FAILED.value, JobStatus.CANCELLED.value}:
            record.prompt_status = "failed"
            record.error_code = job.error_code or "batch_tryon.prompt_analysis_failed"
            record.error_message = job.error_message or "提示词分析失败，请重新分析。"
            has_failed = True
        else:
            record.prompt_status = "analyzing"
            has_pending = True
        record.updated_by = root.created_by
        if record.prompt_status == "failed" and first_error_code is None:
            first_error_code = record.error_code
            first_error_message = record.error_message

    state = _workflow_state(root)
    if streaming_detailed:
        batch, image_jobs, _ = await _create_detailed_streaming_batch(
            session,
            settings,
            root=root,
            records=records,
        )
        ready_jobs = await _activate_ready_detailed_image_jobs(
            session,
            root=root,
            batch=batch,
            records=records,
            image_jobs=image_jobs,
        )
        state = _workflow_state(root)
        state.update({
            "status": "generating",
            "batch_id": batch.id,
            "streaming_luna": True,
            "analysis_total": len(records),
            "analysis_ready": sum(record.prompt_status == "effective" for record in records),
            "analysis_failed": sum(record.prompt_status == "failed" for record in records),
            "analysis_pending": sum(record.prompt_status == "analyzing" for record in records),
            "error_code": first_error_code if has_failed else None,
            "error_message": first_error_message if has_failed else None,
        })
        _set_workflow_state(root, state)
        await session.commit()
        return batch, ready_jobs

    if has_failed:
        state.update({
            "status": "failed",
            "error_code": first_error_code or "batch_tryon.prompt_analysis_failed",
            "error_message": first_error_message or "提示词分析失败，请重新分析。",
        })
    elif has_pending:
        state.update({"status": "analyzing_prompts", "error_code": None, "error_message": None})
    else:
        state.update({"status": "awaiting_prompt_confirmation", "error_code": None, "error_message": None})
    _set_workflow_state(root, state)
    await session.commit()
    return None, []


async def continue_batch_tryon_workflow(
    session: AsyncSession, settings: Settings, *, planning_job: Job,
) -> JobBatch | None:
    root = await _root_for_planning_job(session, planning_job, lock=True)
    if root is None:
        return None
    root_role = str(_record(root.input_json.get("metadata")).get("workflow_role") or "")
    if root_role == "direct_prompt":
        return None
    if root_role in {"prompt_analysis", "detailed_prompt_analysis"}:
        continued_batch, ready_jobs = await _continue_prompt_analysis_workflow(
            session,
            settings,
            root=root,
        )
        if continued_batch is not None and ready_jobs:
            active_jobs = list((await session.scalars(select(Job).where(
                Job.batch_id == continued_batch.id,
                Job.status.in_({JobStatus.DISPATCHING.value, JobStatus.RUNNING.value}),
            ))).all())
            available_slots = max(0, int(continued_batch.concurrency or 1) - len(active_jobs))
            if available_slots:
                await dispatch_jobs(session, ready_jobs[:available_slots])
        if continued_batch is not None and root_role == "detailed_prompt_analysis":
            return continued_batch
        await session.refresh(root)
        request = _workflow_request(root)
        state = _workflow_state(root)
        if (
            request.get("submission_kind") == "validation"
            and state.get("status") == "awaiting_prompt_confirmation"
            and not state.get("batch_id")
        ):
            records = list((await session.scalars(select(BatchTryOnTemplatePrompt).where(
                BatchTryOnTemplatePrompt.organization_id == root.organization_id,
                BatchTryOnTemplatePrompt.workflow_job_id == root.id,
            ).with_for_update())).all())
            if records and all(
                record.prompt_status in {"ready", "effective"} and effective_prompt_text(record)
                for record in records
            ):
                for record in records:
                    if record.prompt_status == "ready":
                        record.prompt_status = "effective"
                        record.updated_by = root.created_by
                await session.flush()
                batch, image_jobs, created = await submit_confirmed_batch_tryon_workflow(
                    session,
                    settings,
                    organization_id=root.organization_id,
                    user_id=root.created_by,
                    workflow_job_id=root.id,
                    idempotency_key=f"auto-validation:{root.id}",
                )
                await session.commit()
                if created:
                    await dispatch_jobs(session, image_jobs[:batch.concurrency])
                return batch
        return None
    return await _continue_legacy_batch_tryon_workflow(session, settings, planning_job=planning_job)


async def get_template_prompt(
    session: AsyncSession, *, organization_id: str, workflow_job_id: str, template_id: str,
    lock: bool = False,
) -> BatchTryOnTemplatePrompt:
    statement = select(BatchTryOnTemplatePrompt).where(
        BatchTryOnTemplatePrompt.organization_id == organization_id,
        BatchTryOnTemplatePrompt.workflow_job_id == workflow_job_id,
        BatchTryOnTemplatePrompt.id == template_id,
    )
    if lock:
        statement = statement.with_for_update()
    record = await session.scalar(statement)
    if record is None:
        statement = select(BatchTryOnTemplatePrompt).where(
            BatchTryOnTemplatePrompt.organization_id == organization_id,
            BatchTryOnTemplatePrompt.workflow_job_id == workflow_job_id,
            BatchTryOnTemplatePrompt.template_id == template_id,
        ).order_by(BatchTryOnTemplatePrompt.created_at).limit(1)
        if lock:
            statement = statement.with_for_update()
        record = await session.scalar(statement)
    if record is None:
        raise AppError("batch_tryon.template_prompt_not_found", "当前模板的提示词分析记录不存在。", 404)
    return record


async def save_template_prompt(
    session: AsyncSession, *, organization_id: str, user_id: str,
    workflow_job_id: str, template_id: str, edited_final_prompt: str | None,
) -> BatchTryOnTemplatePrompt:
    owned_root = await session.scalar(select(Job.id).where(
        Job.id == workflow_job_id,
        Job.organization_id == organization_id,
        Job.created_by == user_id,
    ))
    if owned_root is None:
        raise AppError("batch_tryon.workflow_not_found", "批量套图提示词工作流不存在。", 404)
    record = await get_template_prompt(
        session, organization_id=organization_id, workflow_job_id=workflow_job_id,
        template_id=template_id, lock=True,
    )
    if record.prompt_status not in {"ready", "effective"}:
        raise AppError(
            "batch_tryon.prompt_not_ready",
            "AI 提示词尚未分析完成，暂时不能确认。",
            409,
        )
    edited = str(edited_final_prompt or "").strip()
    if edited:
        edited = validate_generated_final_prompt(edited)
    elif not str(record.generated_final_prompt or "").strip():
        raise AppError("batch_tryon.prompt_empty", "最终换衣提示词不能为空。", 422)
    if record.edited_final_prompt != (edited or None):
        record.prompt_version += 1
    record.edited_final_prompt = edited or None
    record.prompt_status = "effective"
    record.error_code = None
    record.error_message = None
    record.updated_by = user_id
    await session.flush()
    return record


async def reanalyze_template_prompt(
    session: AsyncSession, settings: Settings, *, organization_id: str, user_id: str,
    workflow_job_id: str, template_id: str, analysis_prompt: str | None,
) -> tuple[BatchTryOnTemplatePrompt, Job, bool]:
    root = await session.scalar(select(Job).where(
        Job.id == workflow_job_id,
        Job.organization_id == organization_id,
        Job.created_by == user_id,
    ).with_for_update())
    if root is None or _record(root.input_json.get("metadata")).get("workflow_role") not in {
        "prompt_analysis", "detailed_prompt_analysis", "direct_prompt",
    }:
        raise AppError("batch_tryon.workflow_not_found", "批量套图提示词工作流不存在。", 404)
    if _workflow_state(root).get("batch_id"):
        raise AppError("batch_tryon.workflow_already_submitted", "该工作流已创建图片批次，不能重新分析。", 409)
    record = await get_template_prompt(
        session, organization_id=organization_id, workflow_job_id=workflow_job_id,
        template_id=template_id, lock=True,
    )
    prompt = str(analysis_prompt or record.analysis_prompt_used).strip()
    if len(prompt) < 20:
        raise AppError("batch_tryon.analysis_prompt_too_short", "AI 分析提示词至少需要 20 个字符。", 422)
    next_version = record.prompt_version + 1
    root_role = str(_record(root.input_json.get("metadata")).get("workflow_role") or "")
    if root_role == "detailed_prompt_analysis":
        prompt = prompt_analysis_preset_only(prompt)
    if root_role == "direct_prompt":
        direct_prompt = validate_generated_final_prompt(prompt)
        record.analysis_job_id = None
        record.analysis_prompt_used = direct_prompt
        record.generated_final_prompt = direct_prompt
        record.edited_final_prompt = None
        record.prompt_status = "effective"
        record.prompt_version = next_version
        record.error_code = None
        record.error_message = None
        record.updated_by = user_id
        await session.flush()
        return record, root, False
    detailed = root_role == "detailed_prompt_analysis"
    operation_code = "batch_tryon.prompt_analyze_detailed" if detailed else "batch_tryon.prompt_analyze"
    previous_analysis = await session.get(Job, record.analysis_job_id) if record.analysis_job_id else None
    previous_references = list(previous_analysis.input_json.get("reference_asset_ids", []) or []) if previous_analysis else []
    reference_asset_ids = previous_references or [record.template_asset_id, record.first_garment_asset_id]
    if record.font_reference_asset_id and record.font_reference_asset_id not in reference_asset_ids:
        reference_asset_ids.append(record.font_reference_asset_id)
    job, created = await submit_job(
        session,
        settings,
        organization_id=organization_id,
        user_id=user_id,
        payload=JobSubmitRequest(
            operation_code=operation_code,
            workspace_type="batch_tryon",
            queue_name="planning_queue",
            capability="text_generation",
            model_code=root.model_code,
            idempotency_key=f"batch-prompt-reanalyze:{root.id}:{template_id}:v{next_version}",
            project_id=root.project_id,
            client_item_id=f"prompt:{record.client_item_id or record.template_id}:v{next_version}",
            input={
                "system_prompt": prompt,
                "user_prompt": "",
                "response_format": "text",
                "reference_asset_ids": reference_asset_ids,
                "metadata": {
                    "workflow": WORKFLOW_NAME,
                    "workflow_role": "detailed_prompt_analysis_child" if detailed else "prompt_analysis_child",
                    "workflow_root_job_id": root.id,
                    "template_id": record.template_id,
                    "garment_id": record.garment_id,
                    "client_item_id": record.client_item_id,
                    "template_type": record.template_type,
                    "prompt_preset_id": record.preset_id,
                    "template_asset_id": record.template_asset_id,
                    "first_garment_asset_id": record.first_garment_asset_id,
                    "font_reference_asset_id": record.font_reference_asset_id,
                    "prompt_version": next_version,
                },
            },
            billing_factors={"quality": "standard", "resolution": "text"},
        ),
    )
    record.analysis_job_id = job.id
    record.analysis_prompt_used = prompt
    record.generated_final_prompt = None
    record.edited_final_prompt = None
    record.prompt_status = "analyzing"
    record.prompt_version = next_version
    record.error_code = None
    record.error_message = None
    record.updated_by = user_id
    state = _workflow_state(root)
    state.update({"status": "analyzing_prompts", "error_code": None, "error_message": None})
    _set_workflow_state(root, state)
    await session.flush()
    return record, job, created


async def submit_confirmed_batch_tryon_workflow(
    session: AsyncSession, settings: Settings, *, organization_id: str, user_id: str,
    workflow_job_id: str, idempotency_key: str,
) -> tuple[JobBatch, list[Job], bool]:
    root = await session.scalar(select(Job).where(
        Job.id == workflow_job_id,
        Job.organization_id == organization_id,
        Job.created_by == user_id,
    ).with_for_update())
    if root is None or _record(root.input_json.get("metadata")).get("workflow_role") not in {
        "prompt_analysis", "detailed_prompt_analysis", "direct_prompt",
    }:
        raise AppError("batch_tryon.workflow_not_found", "批量套图提示词工作流不存在。", 404)
    state = _workflow_state(root)
    if state.get("batch_id"):
        batch = await session.get(JobBatch, str(state["batch_id"]))
        if batch is None:
            raise AppError("batch_tryon.batch_missing", "工作流关联的图片批次不存在。", 409)
        jobs = list((await session.scalars(select(Job).where(Job.batch_id == batch.id))).all())
        return batch, jobs, False
    request = _workflow_request(root)
    templates = sorted(list(request.get("templates") or []), key=lambda item: (int(item.get("order") or 0), str(item.get("template_id") or "")))
    garments = sorted(list(request.get("garments") or []), key=lambda item: (int(item.get("order") or 0), str(item.get("garment_id") or "")))
    prompt_records = list((await session.scalars(
        select(BatchTryOnTemplatePrompt).where(
            BatchTryOnTemplatePrompt.organization_id == organization_id,
            BatchTryOnTemplatePrompt.workflow_job_id == root.id,
        ).with_for_update()
    )).all())
    detailed_prompt_mode = str(request.get("prompt_mode") or "direct") == "ai_detailed"
    prompt_by_template = {record.template_id: record for record in prompt_records}
    prompt_by_item = {
        str(record.client_item_id): record for record in prompt_records if record.client_item_id
    }
    expected_combinations = list(request.get("combinations") or []) or [
        {"client_item_id": f"{template['template_id']}:{garment['garment_id']}"}
        for template in templates for garment in garments
    ]
    missing = (
        [
            str(item["client_item_id"]) for item in expected_combinations
            if str(item["client_item_id"]) not in prompt_by_item
        ]
        if detailed_prompt_mode
        else [str(item["template_id"]) for item in templates if str(item["template_id"]) not in prompt_by_template]
    )
    unconfirmed = [
        str(record.client_item_id or record.template_id) for record in prompt_records
        if record.prompt_status != "effective" or not effective_prompt_text(record)
    ]
    if missing or unconfirmed:
        raise AppError(
            "batch_tryon.prompts_not_confirmed",
            "请先确认所有模板的最终换衣提示词，再开始生成。",
            409,
            {"missing_prompt_keys": missing, "unconfirmed_prompt_keys": unconfirmed},
        )
    image_model = await resolve_operation_model_code(
        session, organization_id=organization_id,
        operation_code="batch_tryon.generate", capability="image_edit",
    )
    templates_by_id = {str(item["template_id"]): item for item in templates}
    garments_by_id = {str(item["garment_id"]): item for item in garments}
    template_order = {str(item["template_id"]): index for index, item in enumerate(templates)}
    garment_order = {str(item["garment_id"]): index for index, item in enumerate(garments)}
    combinations = list(request.get("combinations") or []) or [
        {
            "client_item_id": f"{template['template_id']}:{garment['garment_id']}",
            "template_id": template["template_id"], "garment_id": garment["garment_id"],
            "order": len(garments) * template_order[str(template["template_id"])] + garment_order[str(garment["garment_id"])],
        }
        for template in templates for garment in garments
    ]
    combinations.sort(key=lambda item: (int(item.get("order") or 0), str(item.get("client_item_id") or "")))
    items: list[BatchJobItemRequest] = []
    for combination in combinations:
        template_id = str(combination["template_id"])
        garment_id = str(combination["garment_id"])
        template = templates_by_id[template_id]
        garment = garments_by_id[garment_id]
        prompt_record = (
            prompt_by_item[str(combination["client_item_id"])]
            if detailed_prompt_mode else prompt_by_template[template_id]
        )
        font_reference_asset_id = str(
            combination.get("font_reference_asset_id")
            or garment.get("font_reference_asset_id")
            or ""
        ).strip() or None
        reference_asset_ids, reference_metadata = _job_reference_snapshot(
            template=template, garment=garment, font_reference_asset_id=font_reference_asset_id,
        )
        reusable_prompt = effective_prompt_text(prompt_record)
        prompt = build_template_prompt_composed_prompt(
            template_type=prompt_record.template_type,
            reusable_final_prompt=reusable_prompt,
            garment_filename=str(garment["filename"]),
            template_name=str(template["name"]),
            extra_requirements=str(request.get("extra_requirements") or ""),
            has_font_reference=bool(font_reference_asset_id),
            garment_reference_count=len(reference_metadata["effective_garment_reference_asset_ids"]),
        )
        items.append(BatchJobItemRequest(
            client_item_id=str(combination["client_item_id"]),
            prompt=prompt.effective_prompt,
            reference_asset_ids=reference_asset_ids,
            size=str(combination.get("size") or request.get("size") or "2048x2048"),
            aspect_ratio=str(combination.get("aspect_ratio") or request.get("aspect_ratio") or "1:1"),
            requested_width=combination.get("requested_width") or request.get("requested_width"),
            requested_height=combination.get("requested_height") or request.get("requested_height"),
            quality=str(request.get("quality") or "high"),
            output_format=str(request.get("output_format") or "png"),
            output_compression=request.get("output_compression"),
            metadata={
                "workflow": WORKFLOW_NAME,
                "workflow_root_job_id": root.id,
                "generation_mode": str(request.get("generation_mode") or "normal_tryon"),
                "template_prompt_id": prompt_record.id,
                "prompt_preset_id": prompt_record.preset_id,
                "prompt_version": prompt_record.prompt_version,
                "analysis_prompt_snapshot": prompt_record.analysis_prompt_used,
                "effective_prompt_snapshot": reusable_prompt,
                "template_type": prompt_record.template_type,
                "garment_filename": garment["filename"],
                "source_filename": garment["filename"],
                "garment_id": garment_id,
                "garment_asset_id": garment["asset_id"],
                "font_reference_asset_id": font_reference_asset_id,
                **reference_metadata,
                "qc_reference_asset_id": reference_metadata["effective_garment_reference_asset_ids"][0],
                "template_id": template_id,
                "template_name": template["name"],
                "template_index": template_order[template_id],
                "template_count": len(templates),
                "garment_index": garment_order[garment_id],
                "business_prompt": prompt.business_prompt,
                "technical_delivery_contract": prompt.technical_delivery_contract,
                "effective_prompt": prompt.effective_prompt,
                "index": len(items),
            },
        ))
    state.update({"status": "submitting_batch", "error_code": None, "error_message": None})
    _set_workflow_state(root, state)
    batch, image_jobs, created = await submit_batch(
        session, settings, organization_id=organization_id, user_id=user_id,
        payload=JobBatchSubmitRequest(
            name=str(request.get("name") or "批量套图"),
            workspace_type="batch_tryon",
            operation_code="batch_tryon.generate",
            capability="image_edit",
            model_code=image_model,
            idempotency_key=f"batch-workflow-images:{root.id}:{idempotency_key}",
            project_id=root.project_id,
            concurrency=int(request.get("concurrency") or 12),
            admin_test_mode=bool(request.get("admin_test_mode")),
            items=items,
        ),
    )
    batch.parent_batch_id = str(request.get("workspace_batch_id") or "") or None
    batch.batch_kind = "validation" if request.get("submission_kind") == "validation" else "production"
    if batch.parent_batch_id:
        workspace = await session.get(JobBatch, batch.parent_batch_id)
        if workspace:
            workspace.status = "validating" if batch.batch_kind == "validation" else "queued"
            workspace.updated_by = user_id
    state.update({"status": "generating", "batch_id": batch.id})
    _set_workflow_state(root, state)
    await session.flush()
    return batch, image_jobs, created


async def get_batch_tryon_workflow(
    session: AsyncSession, settings: Settings, *, organization_id: str, workflow_job_id: str,
    user_id: str | None = None,
) -> tuple[Job, list[Job], JobBatch | None, list[BatchTryOnTemplatePrompt]]:
    filters = [
        Job.id == workflow_job_id,
        Job.organization_id == organization_id,
    ]
    if user_id:
        filters.append(Job.created_by == user_id)
    root = await session.scalar(select(Job).where(*filters))
    if root is None or _record(root.input_json.get("metadata")).get("workflow") != WORKFLOW_NAME:
        raise AppError("batch_tryon.workflow_not_found", "批量套图工作流不存在。", 404)
    if root.status == JobStatus.SUCCEEDED.value:
        await continue_batch_tryon_workflow(session, settings, planning_job=root)
        await session.refresh(root)
    state = _workflow_state(root)
    root_role = str(_record(root.input_json.get("metadata")).get("workflow_role") or "")
    prompt_records = list((await session.scalars(select(BatchTryOnTemplatePrompt).where(
        BatchTryOnTemplatePrompt.organization_id == organization_id,
        BatchTryOnTemplatePrompt.workflow_job_id == root.id,
    ).order_by(BatchTryOnTemplatePrompt.created_at, BatchTryOnTemplatePrompt.id))).all())
    analysis_ids = (
        [str(record.analysis_job_id) for record in prompt_records if record.analysis_job_id]
        if root_role in {"prompt_analysis", "detailed_prompt_analysis"}
        else [str(item) for item in state.get("template_job_ids") or []]
    )
    jobs = list((await session.scalars(select(Job).where(
        Job.organization_id == organization_id,
        Job.id.in_(analysis_ids),
    ).order_by(Job.created_at, Job.id))).all()) if analysis_ids else []
    batch = await session.get(JobBatch, str(state.get("batch_id"))) if state.get("batch_id") else None
    return root, jobs, batch, prompt_records


def workflow_response(
    root: Job, template_jobs: list[Job], batch: JobBatch | None,
    prompt_records: list[BatchTryOnTemplatePrompt] | None = None,
) -> BatchTryOnWorkflowResponse:
    request = _workflow_request(root)
    state = _workflow_state(root)
    root_role = str(_record(root.input_json.get("metadata")).get("workflow_role") or "")
    is_prompt_workflow = root_role in {"prompt_analysis", "detailed_prompt_analysis", "direct_prompt"}
    is_detailed_prompt_workflow = root_role == "detailed_prompt_analysis"
    is_direct_prompt_workflow = root_role == "direct_prompt"
    if root.status == JobStatus.FAILED.value:
        status = "failed"
    elif root.status == JobStatus.CANCELLED.value:
        status = "cancelled"
    elif root.status != JobStatus.SUCCEEDED.value:
        status = "analyzing_prompts" if is_prompt_workflow else "analyzing_garment"
    elif batch and batch.status in {BatchStatus.SUCCEEDED.value, BatchStatus.PARTIALLY_SUCCEEDED.value, BatchStatus.FAILED.value, BatchStatus.CANCELLED.value}:
        status = "completed" if batch.status == BatchStatus.SUCCEEDED.value else "failed"
    else:
        status = str(state.get("status") or "analyzing_templates")
    if is_prompt_workflow:
        analysis_jobs = [BatchTryOnWorkflowAnalysisJob(
            id=job.id,
            role="detailed_prompt_analysis" if is_detailed_prompt_workflow else "prompt_analysis",
            status=job.status,
            error_code=job.error_code,
            error_message=job.error_message,
        ) for job in template_jobs]
    else:
        analysis_jobs = [BatchTryOnWorkflowAnalysisJob(
            id=root.id,
            role="garment_analysis",
            status=root.status,
            error_code=root.error_code,
            error_message=root.error_message,
        )] + [BatchTryOnWorkflowAnalysisJob(
            id=job.id,
            role="template_analysis",
            status=job.status,
            error_code=job.error_code,
            error_message=job.error_message,
        ) for job in template_jobs]
    garment_profile = state.get("garment_profile") if isinstance(state.get("garment_profile"), dict) else None
    if not is_prompt_workflow and root.status == JobStatus.SUCCEEDED.value:
        # Re-normalize the durable raw response for old workflows as well. This
        # lets profiles created before strict JSON validation recover through
        # the compatibility mapping without rewriting historical Jobs.
        candidate = normalize_garment_profile(
            parse_analysis_text(_analysis_text(root)),
            source_asset_id=str((request.get("garments") or [{}])[0].get("asset_id") or ""),
            model_code=root.model_code,
        )
        try:
            validate_garment_profile(candidate)
            garment_profile = candidate
        except AnalysisResultError:
            pass
    template_profiles = state.get("template_profiles")
    if not isinstance(template_profiles, dict):
        template_profiles = {}
    return BatchTryOnWorkflowResponse(
        workflow_job_id=root.id,
        project_id=root.project_id,
        generation_mode=str(request.get("generation_mode") or "normal_tryon"),
        prompt_mode=str(request.get("prompt_mode") or ("ai_analysis" if root_role == "prompt_analysis" else "direct")),
        submission_kind=str(request.get("submission_kind") or "production"),
        workspace_batch_id=str(request.get("workspace_batch_id") or "") or None,
        status=status,
        analysis_call_target=(
            0 if is_direct_prompt_workflow
            else len(request.get("combinations") or []) if is_detailed_prompt_workflow
            else len(request.get("templates") or []) if is_prompt_workflow
            else 1 + len(request.get("templates") or [])
        ),
        analysis_jobs=analysis_jobs,
        templates=list(request.get("templates") or []),
        garments=list(request.get("garments") or []),
        combinations=list(request.get("combinations") or []),
        garment_profile=garment_profile,
        template_profiles=template_profiles,
        template_prompts=[template_prompt_response(item) for item in (prompt_records or [])],
        batch_id=batch.id if batch else state.get("batch_id"),
        error_code=str(state.get("error_code") or root.error_code or "") or None,
        error_message=str(state.get("error_message") or root.error_message or "") or None,
        created_at=root.created_at,
        updated_at=root.updated_at,
    )


async def get_latest_batch_tryon_workflow(
    session: AsyncSession, settings: Settings, *, organization_id: str, project_id: str,
    workspace_batch_id: str | None = None,
    user_id: str | None = None,
) -> tuple[Job, list[Job], JobBatch | None, list[BatchTryOnTemplatePrompt]]:
    filters = [
        Job.organization_id == organization_id,
        Job.project_id == project_id,
        Job.operation_code.in_({
            "batch_tryon.style_analyze", "batch_tryon.prompt_analyze", "batch_tryon.prompt_analyze_detailed",
        }),
    ]
    if user_id:
        filters.append(Job.created_by == user_id)
    candidates = list((await session.scalars(
        select(Job).where(*filters).order_by(Job.created_at.desc()).limit(100)
    )).all())
    root = next((job for job in candidates if (
        _record(job.input_json.get("metadata")).get("workflow") == WORKFLOW_NAME
        and _record(job.input_json.get("metadata")).get("workflow_role") in {
            "garment_analysis", "prompt_analysis", "detailed_prompt_analysis", "direct_prompt",
        }
        and (
            not workspace_batch_id
            or str(_record(_record(job.input_json.get("metadata")).get("workflow_request")).get("workspace_batch_id") or "")
            == workspace_batch_id
        )
    )), None)
    if root is None:
        raise AppError("batch_tryon.workflow_not_found", "该项目还没有服务端批量套图工作流。", 404)
    return await get_batch_tryon_workflow(
        session, settings, organization_id=organization_id, workflow_job_id=root.id,
        user_id=user_id,
    )
