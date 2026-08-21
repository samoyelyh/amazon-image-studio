from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.attachment_planning import (
    AttachmentModuleReference,
    AttachmentModuleResultState,
    AttachmentWorkbenchModulePlan,
    AttachmentWorkbenchPlan,
    AttachmentWorkbenchPlanVersion,
)
from app.models.content import GeneratedOutput
from app.models.listing_workflow import ListingImageProject, ListingImageTaskGroup, ListingVersion
from app.models.tasks import Job, JobBatch
from app.schemas.attachment_planning import (
    AttachmentModuleResultStateResponse,
    AttachmentOutputStateResponse,
    AttachmentResultStateResponse,
)
from app.schemas.tasks import BatchJobItemRequest, JobBatchSubmitRequest
from app.services.attachment_planning_service import MODULE_INDEX
from app.services.attachment_planning_service import add_module_version, attachment_module_rule
from app.services.attachment_reference_service import effective_reference_snapshot, latest_reference_understanding
from app.services.listing_image_task_group_service import create_group_for_batch
from app.services.task_service import submit_batch


UTC = timezone.utc
REVIEW_STATUSES = {"pending_review", "approved", "rejected"}


async def ensure_attachment_result_states(
    db: AsyncSession, *, project: ListingImageProject, module_keys: list[str], user_id: str,
) -> list[AttachmentModuleResultState]:
    rows = list((await db.scalars(select(AttachmentModuleResultState).where(
        AttachmentModuleResultState.organization_id == project.organization_id,
        AttachmentModuleResultState.listing_image_project_id == project.id,
    ))).all())
    indexed = {item.module_key: item for item in rows}
    for module_key in module_keys:
        if module_key in indexed:
            continue
        item = AttachmentModuleResultState(
            organization_id=project.organization_id,
            listing_image_project_id=project.id,
            module_key=module_key,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(item)
        indexed[module_key] = item
    await db.flush()
    return [indexed[key] for key in module_keys]


async def _locked_state(
    db: AsyncSession, *, project: ListingImageProject, module_key: str,
) -> AttachmentModuleResultState:
    state = await db.scalar(select(AttachmentModuleResultState).where(
        AttachmentModuleResultState.organization_id == project.organization_id,
        AttachmentModuleResultState.listing_image_project_id == project.id,
        AttachmentModuleResultState.module_key == module_key,
    ).with_for_update())
    if state is None:
        raise AppError("attachment_result.state_missing", "结果状态尚未初始化，请刷新页面后重试", 409)
    return state


async def _output_context(
    db: AsyncSession, *, project: ListingImageProject, output_id: str, lock: bool = False,
) -> tuple[GeneratedOutput, Job, ListingImageTaskGroup, str]:
    statement = (
        select(GeneratedOutput, Job, ListingImageTaskGroup)
        .join(Job, GeneratedOutput.job_id == Job.id)
        .join(ListingImageTaskGroup, GeneratedOutput.batch_id == ListingImageTaskGroup.job_batch_id)
        .where(
            GeneratedOutput.id == output_id,
            GeneratedOutput.organization_id == project.organization_id,
            ListingImageTaskGroup.organization_id == project.organization_id,
            ListingImageTaskGroup.listing_image_project_id == project.id,
        )
    )
    if lock:
        statement = statement.with_for_update()
    row = (await db.execute(statement)).first()
    if row is None:
        raise AppError("attachment_result.output_not_found", "附图结果不存在或无权访问", 404)
    output, job, group = row
    metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    module_key = str(metadata.get("item_code") or output.module_key or "")
    if metadata.get("workflow") not in {"attachment_workbench_generation", "attachment_output_edit"} or module_key not in MODULE_INDEX:
        raise AppError("attachment_result.output_invalid", "该图片不是附图生成工作台结果", 422)
    return output, job, group, module_key


def _output_response(output: GeneratedOutput, state: AttachmentModuleResultState) -> AttachmentOutputStateResponse:
    return AttachmentOutputStateResponse(
        output_id=output.id,
        module_key=state.module_key,
        review_status=output.review_status,
        review_state_version=output.review_state_version,
        reviewed_at=output.reviewed_at,
        discarded_at=output.discarded_at,
        is_final=state.current_final_output_id == output.id,
        module_state_version=state.state_version,
    )


async def review_attachment_output(
    db: AsyncSession, *, project: ListingImageProject, output_id: str, status: str,
    expected_review_state_version: int, clear_final_if_rejected: bool, user_id: str,
) -> AttachmentOutputStateResponse:
    if status not in {"approved", "rejected"}:
        raise AppError("attachment_result.review_status_invalid", "审核状态无效", 422)
    output, _, _, module_key = await _output_context(db, project=project, output_id=output_id, lock=True)
    state = await _locked_state(db, project=project, module_key=module_key)
    if output.review_state_version != expected_review_state_version:
        raise AppError(
            "attachment_result.review_version_conflict", "该图片审核状态已变化，请刷新后重试", 409,
            {"expected": expected_review_state_version, "actual": output.review_state_version},
        )
    if status == "rejected" and state.current_final_output_id == output.id:
        if not clear_final_if_rejected:
            raise AppError("attachment_result.final_reject_confirmation_required", "当前图片是最终采用版本，打回前需要确认清除最终采用状态", 409)
        state.current_final_output_id = None
        state.state_version += 1
        state.updated_by = user_id
    output.review_status = status
    output.review_state_version += 1
    output.reviewed_by = user_id
    output.reviewed_at = datetime.now(UTC)
    await db.flush()
    return _output_response(output, state)


async def set_attachment_final(
    db: AsyncSession, *, project: ListingImageProject, output_id: str, user_id: str,
) -> AttachmentOutputStateResponse:
    output, _, _, module_key = await _output_context(db, project=project, output_id=output_id, lock=True)
    state = await _locked_state(db, project=project, module_key=module_key)
    now = datetime.now(UTC)
    if output.review_status != "approved":
        output.review_status = "approved"
        output.review_state_version += 1
        output.reviewed_by = user_id
        output.reviewed_at = now
    if output.discarded_at is not None:
        output.discarded_at = None
        output.discarded_by = None
    if state.current_final_output_id != output.id:
        state.current_final_output_id = output.id
        state.state_version += 1
        state.updated_by = user_id
    await db.flush()
    return _output_response(output, state)


async def clear_attachment_final(
    db: AsyncSession, *, project: ListingImageProject, module_key: str, user_id: str,
) -> AttachmentModuleResultState:
    state = await _locked_state(db, project=project, module_key=module_key)
    if state.current_final_output_id is not None:
        state.current_final_output_id = None
        state.state_version += 1
        state.updated_by = user_id
    await db.flush()
    return state


async def adopt_attachment_creative_direction(
    db: AsyncSession, *, project: ListingImageProject, plan: AttachmentWorkbenchPlan,
    version: ListingVersion, modules: list[AttachmentWorkbenchModulePlan], output_id: str,
    expected_state_version: int, user_id: str,
) -> AttachmentWorkbenchModulePlan:
    output, job, _, module_key = await _output_context(
        db, project=project, output_id=output_id, lock=True,
    )
    metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    if metadata.get("generation_mode") != "creative":
        raise AppError("attachment_creative.adopt_source_invalid", "只有创意生成结果可以沿用方向", 422)
    source_version_id = str(metadata.get("plan_version_id") or "")
    source = await db.scalar(select(AttachmentWorkbenchPlanVersion).where(
        AttachmentWorkbenchPlanVersion.id == source_version_id,
        AttachmentWorkbenchPlanVersion.organization_id == project.organization_id,
        AttachmentWorkbenchPlanVersion.workbench_plan_id == plan.id,
        AttachmentWorkbenchPlanVersion.module_key == module_key,
        AttachmentWorkbenchPlanVersion.generation_mode == "creative",
    ))
    if source is None or not source.plan_summary_cn or not source.prompt_cn:
        raise AppError("attachment_creative.source_version_missing", "创意结果缺少可追溯的方案或Prompt版本", 409)
    module = next((item for item in modules if item.module_key == module_key), None)
    if module is None or module.id != source.module_plan_id:
        raise AppError("attachment_creative.module_mismatch", "创意结果与当前模块不匹配", 422)
    if module.state_version != expected_state_version:
        raise AppError(
            "attachment_planning.state_version_conflict", "该模块已被更新，请刷新后再沿用创意方向", 409,
            {"expected": expected_state_version, "actual": module.state_version},
        )
    grouped, reference_snapshot = await effective_reference_snapshot(db, plan=plan, module=module)
    if not grouped.get("PRODUCT"):
        raise AppError("attachment_creative.product_required", "当前模块缺少有效商品参考图，不能沿用方向", 409)
    if module.reference_context_dirty:
        raise AppError("attachment_creative.reference_stale", "当前商品或参考素材已更新，请先重新分析", 409)
    current_understanding = await latest_reference_understanding(db, module.id, ready_only=True)
    if current_understanding is None:
        raise AppError("attachment_creative.reference_analysis_required", "请先完成当前商品组合的参考素材分析", 409)

    module.aspect_ratio = str(source.aspect_ratio or module.aspect_ratio)
    await add_module_version(
        db, plan=plan, module=module, action="derived_from_creative", user_id=user_id,
        rule_snapshot=attachment_module_rule(dict(version.category_skill_snapshot or {}), module_key),
        plan_summary_cn=str(source.plan_summary_cn), prompt_cn=str(source.prompt_cn),
        reference_understanding_id=current_understanding.id,
        product_composition_version_id=(
            str(reference_snapshot.get("product_composition_version_id") or "") or None
        ),
        source_version_id=source.id, derived_from_output_id=output.id,
    )
    module.derived_from_output_id = output.id
    module.source = "derived_from_creative"
    module.status = "ready"
    module.error_message = None
    module.state_version += 1
    module.updated_by = user_id
    module.last_saved_at = datetime.now(UTC)

    config = dict(project.prompt_config or {})
    workbench = dict(config.get("attachment_workbench") or {})
    drafts = dict(workbench.get("modules") or {})
    current = dict(drafts.get(module_key) or {})
    drafts[module_key] = {
        **current,
        "generationMode": "standard",
        "aspectRatio": module.aspect_ratio,
    }
    workbench["modules"] = drafts
    config["attachment_workbench"] = workbench
    project.prompt_config = config
    project.state_version += 1
    project.last_saved_at = datetime.now(UTC)
    project.updated_by = user_id
    await db.flush()
    return module


async def attachment_outputs(
    db: AsyncSession, *, project: ListingImageProject, module_keys: list[str] | None = None,
) -> list[tuple[GeneratedOutput, Job, ListingImageTaskGroup, str]]:
    statement = (
        select(GeneratedOutput, Job, ListingImageTaskGroup)
        .join(Job, GeneratedOutput.job_id == Job.id)
        .join(ListingImageTaskGroup, GeneratedOutput.batch_id == ListingImageTaskGroup.job_batch_id)
        .where(
            GeneratedOutput.organization_id == project.organization_id,
            ListingImageTaskGroup.organization_id == project.organization_id,
            ListingImageTaskGroup.listing_image_project_id == project.id,
        )
        .order_by(GeneratedOutput.created_at.desc())
    )
    rows: list[tuple[GeneratedOutput, Job, ListingImageTaskGroup, str]] = []
    for output, job, group in (await db.execute(statement)).all():
        metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
        metadata = metadata if isinstance(metadata, dict) else {}
        module_key = str(metadata.get("item_code") or output.module_key or "")
        if metadata.get("workflow") != "attachment_workbench_generation" or module_key not in MODULE_INDEX:
            continue
        if module_keys is not None and module_key not in module_keys:
            continue
        rows.append((output, job, group, module_key))
    return rows


async def discard_attachment_results(
    db: AsyncSession, *, project: ListingImageProject, module_keys: list[str], user_id: str,
) -> int:
    invalid = sorted(set(module_keys) - set(MODULE_INDEX))
    if invalid:
        raise AppError("attachment_result.module_invalid", "包含不支持的附图模块", 422, {"invalid": invalid})
    rows = await attachment_outputs(db, project=project, module_keys=module_keys)
    now = datetime.now(UTC)
    changed = 0
    for output, _, _, _ in rows:
        if output.discarded_at is None:
            output.discarded_at = now
            output.discarded_by = user_id
            changed += 1
    for module_key in module_keys:
        state = await _locked_state(db, project=project, module_key=module_key)
        state.current_final_output_id = None
        state.results_cleared_at = now
        state.state_version += 1
        state.updated_by = user_id
    await db.flush()
    return changed


async def result_state_response(
    db: AsyncSession, *, project: ListingImageProject, user_id: str,
) -> AttachmentResultStateResponse:
    states = await ensure_attachment_result_states(
        db, project=project, module_keys=list(MODULE_INDEX), user_id=user_id,
    )
    rows = await attachment_outputs(db, project=project)
    by_module: dict[str, list[GeneratedOutput]] = {key: [] for key in MODULE_INDEX}
    for output, _, _, module_key in rows:
        by_module[module_key].append(output)
    modules: list[AttachmentModuleResultStateResponse] = []
    total = reviewed = finals = 0
    for state in states:
        outputs = by_module[state.module_key]
        total += len(outputs)
        reviewed += sum(item.review_status in {"approved", "rejected"} for item in outputs)
        finals += int(state.current_final_output_id is not None)
        visible = [item for item in outputs if item.discarded_at is None]
        modules.append(AttachmentModuleResultStateResponse(
            module_key=state.module_key,
            current_final_output_id=state.current_final_output_id,
            results_cleared_at=state.results_cleared_at,
            state_version=state.state_version,
            visible_output_count=len(visible),
            history_output_count=len(outputs) - len(visible),
            pending_review_count=sum(item.review_status == "pending_review" for item in visible),
            approved_count=sum(item.review_status == "approved" for item in visible),
            rejected_count=sum(item.review_status == "rejected" for item in visible),
        ))
    return AttachmentResultStateResponse(
        project_id=project.id, total_outputs=total, reviewed_outputs=reviewed,
        final_module_count=finals, modules=modules,
    )


async def reset_attachment_module(
    db: AsyncSession, *, project: ListingImageProject, plan: AttachmentWorkbenchPlan,
    module: AttachmentWorkbenchModulePlan, user_id: str,
) -> None:
    await discard_attachment_results(db, project=project, module_keys=[module.module_key], user_id=user_id)
    await db.execute(delete(AttachmentModuleReference).where(AttachmentModuleReference.module_plan_id == module.id))
    default_ratio = str(MODULE_INDEX[module.module_key].get("recommended_aspect_ratio") or "1:1")
    module.plan_summary_cn = ""
    module.prompt_cn = ""
    module.operator_requirement_cn = ""
    module.aspect_ratio = default_ratio
    module.source = "none"
    module.derived_from_output_id = None
    module.current_version_number = 0
    module.planning_job_id = None
    module.status = "draft"
    module.error_message = None
    module.reference_context_dirty = True
    module.reference_state_version += 1
    module.reference_analysis_job_id = None
    module.state_version += 1
    module.last_saved_at = datetime.now(UTC)
    module.updated_by = user_id

    config = dict(project.prompt_config or {})
    workbench = dict(config.get("attachment_workbench") or {})
    modules = dict(workbench.get("modules") or {})
    old_draft = dict(modules.get(module.module_key) or {})
    modules[module.module_key] = {
        **old_draft,
        "aspectRatio": default_ratio,
        "imageCount": 1,
        "generationMode": "standard",
    }
    workbench["modules"] = modules
    config["attachment_workbench"] = workbench
    project.prompt_config = config
    project.state_version += 1
    project.last_saved_at = datetime.now(UTC)
    project.updated_by = user_id
    await db.flush()


async def retry_attachment_job(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject,
    source_job_id: str, idempotency_key: str, user_id: str,
) -> tuple[JobBatch, list[Job], ListingImageTaskGroup, bool]:
    source_job = await db.scalar(select(Job).where(
        Job.id == source_job_id,
        Job.organization_id == project.organization_id,
    ).with_for_update())
    if source_job is None or source_job.status not in {"failed", "cancelled"}:
        raise AppError("attachment_result.retry_job_invalid", "仅失败或已停止的附图槽位可以重试", 409)
    source_group = await db.scalar(select(ListingImageTaskGroup).where(
        ListingImageTaskGroup.organization_id == project.organization_id,
        ListingImageTaskGroup.listing_image_project_id == project.id,
        ListingImageTaskGroup.job_batch_id == source_job.batch_id,
    ))
    metadata = source_job.input_json.get("metadata") if isinstance(source_job.input_json, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    if source_group is None or metadata.get("workflow") != "attachment_workbench_generation":
        raise AppError("attachment_result.retry_job_invalid", "该任务不是当前附图项目的正式生成槽位", 422)
    value = dict(source_job.input_json or {})
    item = BatchJobItemRequest(
        client_item_id=f"{source_job.client_item_id}:retry:{idempotency_key[-8:]}",
        prompt=str(value.get("prompt") or ""),
        reference_asset_ids=[str(asset_id) for asset_id in value.get("reference_asset_ids") or []],
        size=str(value.get("size") or "2048x2048"),
        aspect_ratio=str(value.get("aspect_ratio") or "1:1"),
        requested_width=value.get("requested_width"), requested_height=value.get("requested_height"),
        quality=str(value.get("quality") or "high"), output_format=str(value.get("output_format") or "png"),
        output_compression=value.get("output_compression"),
        metadata={**metadata, "source_job_id": source_job.id},
    )
    source_batch = await db.get(JobBatch, source_job.batch_id)
    version = await db.get(ListingVersion, source_group.listing_version_id)
    if source_batch is None or version is None:
        raise AppError("attachment_result.retry_context_missing", "原任务快照不完整，无法安全重试", 409)
    batch, jobs, created = await submit_batch(
        db, settings, organization_id=project.organization_id, user_id=user_id,
        payload=JobBatchSubmitRequest(
            name=f"附图失败槽位重试 · {metadata.get('module_name') or metadata.get('item_code')} #{metadata.get('slot_index') or '-'}",
            workspace_type="listing", operation_code=source_job.operation_code,
            capability=source_job.capability, model_code=source_job.model_code,
            idempotency_key=idempotency_key, project_id=source_batch.project_id,
            concurrency=1, items=[item],
        ),
    )
    group = await create_group_for_batch(
        db, project=project, batch=batch, version=version,
        selected_image_types=[str(metadata.get("item_code") or "")],
        product_asset_ids=list(source_group.product_image_asset_ids or []),
        reference_asset_ids=list(source_group.reference_asset_ids or []),
        template_asset_ids=list(source_group.template_asset_ids or []),
        input_asset_snapshot=dict(source_group.input_asset_snapshot or {}),
        user_id=user_id, source_task_group_id=source_group.id,
    )
    group.group_name = f"附图失败槽位重试任务组 #{group.group_number}"
    for job in jobs:
        job_metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
        job.input_json = {**job.input_json, "metadata": {
            **(job_metadata if isinstance(job_metadata, dict) else {}),
            "listing_image_task_group_id": group.id,
        }}
    await db.flush()
    return batch, jobs, group, created
