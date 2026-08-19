from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.attachment_planning import AttachmentWorkbenchModulePlan, AttachmentWorkbenchPlan
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject, ListingVersion
from app.schemas.attachment_planning import (
    AttachmentModulePlanRequest,
    AttachmentModulePlanResponse,
    AttachmentModulePlanUpdate,
    AttachmentPlanningResponse,
    AttachmentPlanVersionResponse,
    AttachmentSkillSourceResponse,
    AttachmentSuitePlanRequest,
    AttachmentVisualDirectionUpdate,
)
from app.security.principal import Principal, require_permissions
from app.services.attachment_planning_service import (
    STANDARD_MODULE_CODES,
    add_module_version,
    add_suite_version,
    attachment_module_rule,
    get_or_create_attachment_plan,
    list_attachment_versions,
    reconcile_attachment_planning,
    start_module_planning,
    start_suite_planning,
)
from app.services.task_service import dispatch_jobs, due_jobs


router = APIRouter(prefix="/attachment-workbench", tags=["attachment-workbench"])
UTC = timezone.utc


def _organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队", 409)
    return principal.organization.id


async def _context(
    db: AsyncSession, *, organization_id: str, project_id: str, user_id: str,
) -> tuple[ListingImageProject, ListingGenerationSession, ListingVersion, AttachmentWorkbenchPlan, list[AttachmentWorkbenchModulePlan]]:
    project = await db.scalar(select(ListingImageProject).where(
        ListingImageProject.id == project_id,
        ListingImageProject.organization_id == organization_id,
    ))
    if project is None:
        raise AppError("attachment_planning.project_not_found", "附图项目不存在或无权访问", 404)
    session = await db.scalar(select(ListingGenerationSession).where(
        ListingGenerationSession.id == project.session_id,
        ListingGenerationSession.organization_id == organization_id,
    ))
    version = await db.scalar(select(ListingVersion).where(
        ListingVersion.id == project.listing_version_id,
        ListingVersion.organization_id == organization_id,
    ))
    if session is None or version is None or not session.confirmed_at:
        raise AppError("attachment_planning.context_missing", "附图项目缺少已确认的Listing上下文", 409)
    plan, modules = await get_or_create_attachment_plan(
        db, project=project, session=session, version=version, user_id=user_id,
    )
    return project, session, version, plan, modules


def _can_view_rules(principal: Principal) -> bool:
    return principal.is_platform_admin or "organization_admin" in principal.role_codes


def _response(
    *, project: ListingImageProject, version: ListingVersion, plan: AttachmentWorkbenchPlan,
    modules: list[AttachmentWorkbenchModulePlan], principal: Principal,
) -> AttachmentPlanningResponse:
    snapshot = dict(version.category_skill_snapshot or {})
    can_view = _can_view_rules(principal)
    module_names = {
        "pure_white": "纯白底图", "custom_process": "定制流程图", "stadium_scene": "观赛场景图",
        "gift_scene": "礼品场景图", "detail_display": "细节展示图", "casual_scene": "休闲场景图",
    }
    return AttachmentPlanningResponse(
        id=plan.id, project_id=project.id, session_id=plan.session_id,
        visual_direction_cn=plan.visual_direction_cn,
        visual_direction_source=plan.visual_direction_source,
        visual_direction_version=plan.visual_direction_version,
        planning_status=plan.planning_status, planning_job_id=plan.planning_job_id,
        error_message=plan.error_message, state_version=plan.state_version,
        last_saved_at=plan.last_saved_at,
        modules=[AttachmentModulePlanResponse(
            id=item.id, module_key=item.module_key, module_name=module_names.get(item.module_key, item.module_key),
            plan_summary_cn=item.plan_summary_cn, prompt_cn=item.prompt_cn,
            operator_requirement_cn=item.operator_requirement_cn, aspect_ratio=item.aspect_ratio,
            source=item.source, current_version_number=item.current_version_number,
            status=item.status, planning_job_id=item.planning_job_id, error_message=item.error_message,
            state_version=item.state_version, last_saved_at=item.last_saved_at,
            skill_source=AttachmentSkillSourceResponse(
                skill_name=str(snapshot.get("skill_name") or ""),
                skill_version_id=plan.skill_version_id,
                skill_version_number=int(snapshot.get("skill_version") or 0) or None,
                can_view_rules=can_view,
                module_rule=attachment_module_rule(snapshot, item.module_key) if can_view else None,
            ),
        ) for item in modules],
    )


async def _load_and_reconcile(
    db: AsyncSession, *, project_id: str, principal: Principal,
) -> tuple[ListingImageProject, ListingGenerationSession, ListingVersion, AttachmentWorkbenchPlan, list[AttachmentWorkbenchModulePlan]]:
    context = await _context(
        db, organization_id=_organization_id(principal), project_id=project_id, user_id=principal.user.id,
    )
    project, _, version, plan, modules = context
    await reconcile_attachment_planning(db, plan=plan, modules=modules, version=version)
    await db.commit()
    return project, context[1], version, plan, modules


@router.get("/projects/{project_id}/planning", response_model=AttachmentPlanningResponse)
async def get_planning(
    project_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> AttachmentPlanningResponse:
    project, _, version, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


@router.post("/projects/{project_id}/plan", response_model=AttachmentPlanningResponse, status_code=status.HTTP_202_ACCEPTED)
async def plan_suite(
    project_id: str, payload: AttachmentSuitePlanRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    project, session, version, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    job, created = await start_suite_planning(
        db, settings, project=project, session=session, version=version, plan=plan, module_rows=modules,
        modules=payload.modules, visual_direction_cn=payload.visual_direction_cn,
        idempotency_key=payload.idempotency_key, user_id=principal.user.id,
    )
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


async def _start_one(
    *, project_id: str, module_key: str, payload: AttachmentModulePlanRequest, action: str,
    db: AsyncSession, settings: Settings, principal: Principal,
) -> AttachmentPlanningResponse:
    if module_key not in STANDARD_MODULE_CODES:
        raise AppError("attachment_planning.module_invalid", "选择了不支持的附图模块", 422)
    project, session, version, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    if not plan.visual_direction_cn.strip():
        raise AppError("attachment_planning.visual_direction_required", "请先完成整套AI策划，再单独调整模块", 409)
    indexed = {item.module_key: item for item in modules}
    module = indexed[module_key]
    if action == "optimize_prompt" and (not module.plan_summary_cn.strip() or not module.prompt_cn.strip()):
        raise AppError("attachment_planning.module_prompt_required", "当前模块尚未完成策划，不能只优化Prompt", 409)
    job, created = await start_module_planning(
        db, settings, project=project, session=session, version=version, plan=plan, module=module,
        action=action, aspect_ratio=payload.aspect_ratio,
        operator_requirement_cn=payload.operator_requirement_cn,
        idempotency_key=payload.idempotency_key, user_id=principal.user.id,
    )
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


@router.post("/projects/{project_id}/modules/{module_key}/replan", response_model=AttachmentPlanningResponse, status_code=status.HTTP_202_ACCEPTED)
async def replan_module(
    project_id: str, module_key: str, payload: AttachmentModulePlanRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    return await _start_one(
        project_id=project_id, module_key=module_key, payload=payload, action="module_replan",
        db=db, settings=settings, principal=principal,
    )


@router.post("/projects/{project_id}/modules/{module_key}/optimize-prompt", response_model=AttachmentPlanningResponse, status_code=status.HTTP_202_ACCEPTED)
async def optimize_module_prompt(
    project_id: str, module_key: str, payload: AttachmentModulePlanRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    return await _start_one(
        project_id=project_id, module_key=module_key, payload=payload, action="optimize_prompt",
        db=db, settings=settings, principal=principal,
    )


@router.patch("/projects/{project_id}/visual-direction", response_model=AttachmentPlanningResponse)
async def update_visual_direction(
    project_id: str, payload: AttachmentVisualDirectionUpdate,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    project, _, version, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    if payload.expected_state_version != plan.state_version:
        raise AppError(
            "attachment_planning.state_version_conflict", "整套视觉方向已被更新，请刷新后合并修改", 409,
            {"expected": payload.expected_state_version, "actual": plan.state_version},
        )
    value = payload.visual_direction_cn.strip()
    if value != plan.visual_direction_cn:
        await add_suite_version(
            db, plan=plan, action="manual_edit", selected=[], user_id=principal.user.id,
            visual_direction_cn=value,
        )
        plan.state_version += 1
        plan.updated_by = principal.user.id
        plan.last_saved_at = datetime.now(UTC)
        if plan.planning_status != "planning":
            plan.planning_status = "ready" if value else "idle"
        plan.error_message = None
    await db.commit()
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


@router.patch("/projects/{project_id}/modules/{module_key}", response_model=AttachmentPlanningResponse)
async def update_module(
    project_id: str, module_key: str, payload: AttachmentModulePlanUpdate,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    project, _, version, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    indexed = {item.module_key: item for item in modules}
    module = indexed.get(module_key)
    if module is None:
        raise AppError("attachment_planning.module_invalid", "选择了不支持的附图模块", 422)
    if payload.expected_state_version != module.state_version:
        raise AppError(
            "attachment_planning.state_version_conflict", "该模块已被更新，请刷新后合并修改", 409,
            {"expected": payload.expected_state_version, "actual": module.state_version, "module_key": module_key},
        )
    next_plan = module.plan_summary_cn if payload.plan_summary_cn is None else payload.plan_summary_cn.strip()
    next_prompt = module.prompt_cn if payload.prompt_cn is None else payload.prompt_cn.strip()
    next_requirement = module.operator_requirement_cn if payload.operator_requirement_cn is None else payload.operator_requirement_cn.strip()
    next_ratio = module.aspect_ratio if payload.aspect_ratio is None else payload.aspect_ratio
    if next_ratio not in {"1:1", "4:5", "3:4"}:
        raise AppError("attachment_planning.aspect_ratio_invalid", "图片比例无效", 422)
    changed = (next_plan, next_prompt, next_requirement, next_ratio) != (
        module.plan_summary_cn, module.prompt_cn, module.operator_requirement_cn, module.aspect_ratio,
    )
    if changed:
        module.operator_requirement_cn = next_requirement
        module.aspect_ratio = next_ratio
        await add_module_version(
            db, plan=plan, module=module, action="manual_edit", user_id=principal.user.id,
            rule_snapshot=attachment_module_rule(dict(version.category_skill_snapshot or {}), module_key),
            plan_summary_cn=next_plan, prompt_cn=next_prompt,
        )
        module.state_version += 1
        module.updated_by = principal.user.id
        module.last_saved_at = datetime.now(UTC)
        if module.status != "planning":
            module.status = "ready" if next_prompt else "draft"
        module.error_message = None
    await db.commit()
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


@router.get("/projects/{project_id}/versions", response_model=list[AttachmentPlanVersionResponse])
async def list_versions(
    project_id: str, module_key: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[AttachmentPlanVersionResponse]:
    _, _, _, plan, _ = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    if module_key is not None and module_key not in STANDARD_MODULE_CODES:
        raise AppError("attachment_planning.module_invalid", "选择了不支持的附图模块", 422)
    rows = await list_attachment_versions(
        db, organization_id=_organization_id(principal), plan_id=plan.id, module_key=module_key,
    )
    return [AttachmentPlanVersionResponse.model_validate(row, from_attributes=True) for row in rows]
