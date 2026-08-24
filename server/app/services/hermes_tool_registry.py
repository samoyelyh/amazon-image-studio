from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.attachment_planning import (
    AttachmentReferenceLibraryItem,
    AttachmentWorkbenchModulePlan,
    AttachmentWorkbenchPlan,
)
from app.models.creative_presets import AIModelPreset, ThemePreset, VisualPreset
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject, ListingVersion
from app.schemas.attachment_output_edit import AttachmentOutputEditItemRequest
from app.schemas.attachment_planning import AttachmentPlanningModuleInput
from app.services.attachment_generation_service import build_attachment_generation_preview, create_attachment_generation
from app.services.attachment_output_edit_service import create_output_edits
from app.services.attachment_planning_service import get_or_create_attachment_plan, request_suite_planning
from app.services.attachment_reference_service import add_module_reference
from app.services.creative_preset_service import selected_models, set_module_model_context, set_plan_creative_context


@dataclass(frozen=True)
class HermesWorkbenchContext:
    project: ListingImageProject
    session: ListingGenerationSession
    version: ListingVersion
    plan: AttachmentWorkbenchPlan
    modules: list[AttachmentWorkbenchModulePlan]
    user_id: str


@dataclass(frozen=True)
class HermesToolExecution:
    result: dict[str, object]
    dispatch_count: int = 0
    batch_id: str | None = None


@dataclass(frozen=True)
class HermesToolSpec:
    name: str
    kind: str
    description: str
    risk_level: str
    required_permission: str
    arguments: tuple[str, ...] = ()


TOOL_SPECS = (
    HermesToolSpec("get_workbench_context", "read", "读取当前附图项目、视觉、模块和状态摘要", "READ_ONLY", "jobs.read"),
    HermesToolSpec("get_product_context", "read", "读取已确认商品、Product Identity和Listing摘要", "READ_ONLY", "jobs.read"),
    HermesToolSpec("get_module_context", "read", "读取指定模块的方案、Prompt和就绪状态", "READ_ONLY", "jobs.read", ("module_key",)),
    HermesToolSpec("search_reference_library", "read", "按模块、关键词搜索公共参考图库", "READ_ONLY", "jobs.read", ("module_key", "keywords")),
    HermesToolSpec("search_model_library", "read", "搜索当前团队可用的AI模特", "READ_ONLY", "jobs.read", ("keywords",)),
    HermesToolSpec("set_visual_preset", "action", "切换整套视觉预设", "LOW_RISK_WRITE", "jobs.submit", ("preset_id_or_code",)),
    HermesToolSpec("set_theme", "action", "切换或清除主题预设", "LOW_RISK_WRITE", "jobs.submit", ("theme_id_or_code",)),
    HermesToolSpec(
        "set_module_model", "action",
        "设置模块AI模特；selection_mode只允许inherit/recommended/selected/none，选择具体模特必须用selected并传identity_version_ids，无人物用none",
        "LOW_RISK_WRITE", "jobs.submit", ("module_key", "selection_mode", "identity_version_ids"),
    ),
    HermesToolSpec("attach_reference_library_item", "action", "把公共图库素材挂到指定模块", "LOW_RISK_WRITE", "jobs.submit", ("module_key", "library_item_id")),
    HermesToolSpec(
        "plan_modules", "action",
        "按当前Lazy AI规则策划指定模块；requirements必须是以module_key为键、中文要求为值的对象，不能是字符串",
        "AI_ACTION", "jobs.submit", ("module_keys", "visual_direction_cn", "requirements"),
    ),
    HermesToolSpec("get_plan_result", "read", "读取当前策划结果和失败原因", "READ_ONLY", "jobs.read", ("module_keys",)),
    HermesToolSpec("generate_modules", "action", "使用现有生成预检和任务组生成指定模块", "EXPENSIVE_ACTION", "jobs.submit", ("module_keys",)),
    HermesToolSpec("edit_generated_output", "action", "使用现有图片编辑链路修改一张结果", "EXPENSIVE_ACTION", "jobs.submit", ("output_id", "instruction", "edit_scope")),
    HermesToolSpec("record_feedback", "action", "记录运营反馈，不直接改图", "LOW_RISK_WRITE", "jobs.read", ("feedback",)),
)
TOOL_INDEX = {item.name: item for item in TOOL_SPECS}


def tool_catalog() -> list[dict[str, object]]:
    """High-level application tools visible to Hermes; never infrastructure primitives."""
    return [{
        "name": item.name, "kind": item.kind, "description": item.description,
        "risk_level": item.risk_level, "required_permission": item.required_permission,
        "arguments": list(item.arguments),
    } for item in TOOL_SPECS]


ACTION_TOOLS = frozenset(item.name for item in TOOL_SPECS if item.kind == "action")


async def load_hermes_workbench_context(
    db: AsyncSession, *, organization_id: str, project_id: str, user_id: str,
) -> HermesWorkbenchContext:
    project = await db.scalar(select(ListingImageProject).where(
        ListingImageProject.id == project_id,
        ListingImageProject.organization_id == organization_id,
    ))
    if project is None:
        raise AppError("hermes.project_not_found", "附图项目不存在或无权访问", 404)
    session = await db.scalar(select(ListingGenerationSession).where(
        ListingGenerationSession.id == project.session_id,
        ListingGenerationSession.organization_id == organization_id,
    ))
    version = await db.scalar(select(ListingVersion).where(
        ListingVersion.id == project.listing_version_id,
        ListingVersion.organization_id == organization_id,
    ))
    if session is None or version is None or not session.confirmed_at:
        raise AppError("hermes.context_missing", "当前项目缺少已确认的商品与Listing上下文", 409)
    plan, modules = await get_or_create_attachment_plan(
        db, project=project, session=session, version=version, user_id=user_id,
    )
    return HermesWorkbenchContext(project, session, version, plan, modules, user_id)


def _module(context: HermesWorkbenchContext, module_key: str) -> AttachmentWorkbenchModulePlan:
    module = next((item for item in context.modules if item.module_key == module_key), None)
    if module is None:
        raise AppError("hermes.module_invalid", "选择了不支持的附图模块", 422, {"module_key": module_key})
    return module


async def _resolve_visual(db: AsyncSession, context: HermesWorkbenchContext, value: str) -> VisualPreset:
    row = await db.scalar(select(VisualPreset).where(
        or_(VisualPreset.organization_id == context.project.organization_id, VisualPreset.organization_id.is_(None)),
        VisualPreset.is_active.is_(True),
        or_(VisualPreset.id == value, VisualPreset.code == value, VisualPreset.name == value),
    ).order_by(VisualPreset.organization_id.desc()).limit(1))
    if row is None:
        raise AppError("hermes.visual_not_found", "没有找到可用的视觉预设", 422)
    return row


async def _resolve_theme(db: AsyncSession, context: HermesWorkbenchContext, value: str) -> ThemePreset:
    row = await db.scalar(select(ThemePreset).where(
        or_(ThemePreset.organization_id == context.project.organization_id, ThemePreset.organization_id.is_(None)),
        ThemePreset.is_active.is_(True),
        or_(ThemePreset.id == value, ThemePreset.code == value, ThemePreset.name == value),
    ).order_by(ThemePreset.organization_id.desc()).limit(1))
    if row is None:
        raise AppError("hermes.theme_not_found", "没有找到可用的主题预设", 422)
    return row


async def execute_hermes_tool(
    db: AsyncSession, settings: Settings, *, context: HermesWorkbenchContext,
    tool_name: str, arguments: dict[str, object], user_id: str, permissions: frozenset[str],
) -> HermesToolExecution:
    spec = TOOL_INDEX.get(tool_name)
    if spec is None or spec.kind != "action":
        raise AppError("hermes.tool_not_allowed", "Hermes 请求了未授权的业务动作", 422, {"tool": tool_name})
    if spec.required_permission not in permissions:
        raise AppError(
            "auth.permission_denied", "当前账号没有执行该 Hermes 动作的权限", 403,
            {"tool": tool_name, "required": [spec.required_permission]},
        )
    if tool_name == "record_feedback":
        feedback = str(arguments.get("feedback") or "").strip()
        if not feedback:
            raise AppError("hermes.feedback_required", "反馈内容不能为空", 422)
        return HermesToolExecution({"recorded": True, "feedback": feedback[:1000]})

    if tool_name in {"set_visual_preset", "set_theme"}:
        current_models = await selected_models(db, plan=context.plan)
        identity_ids = [identity.id for _, identity, _ in current_models]
        visual_id = context.plan.visual_preset_id
        theme_id = context.plan.theme_preset_id
        if tool_name == "set_visual_preset":
            visual = await _resolve_visual(db, context, str(arguments.get("preset_id_or_code") or ""))
            visual_id = visual.id
        else:
            raw = str(arguments.get("theme_id_or_code") or "").strip()
            theme_id = (await _resolve_theme(db, context, raw)).id if raw else None
        if not visual_id:
            raise AppError("hermes.visual_required", "请先选择整套视觉预设", 409)
        await set_plan_creative_context(
            db, plan=context.plan, modules=context.modules,
            visual_preset_id=visual_id, theme_preset_id=theme_id,
            model_selection_mode=context.plan.model_selection_mode,
            selected_model_identity_version_ids=identity_ids if context.plan.model_selection_mode == "selected" else [],
            expected_version=context.plan.creative_context_version, user_id=user_id,
        )
        return HermesToolExecution({"creative_context_version": context.plan.creative_context_version, "visual_preset_id": visual_id, "theme_preset_id": theme_id})

    if tool_name == "set_module_model":
        module = _module(context, str(arguments.get("module_key") or ""))
        raw_mode = str(arguments.get("selection_mode") or "inherit").strip().lower()
        mode = {
            "manual": "selected",
            "custom": "selected",
            "no_model": "none",
            "no-model": "none",
            "off": "none",
            "auto": "recommended",
            "default": "inherit",
        }.get(raw_mode, raw_mode)
        ids = [str(item) for item in (arguments.get("identity_version_ids") or []) if item]
        await set_module_model_context(
            db, plan=context.plan, module=module, selection_mode=mode,
            selected_model_identity_version_ids=ids, user_id=user_id,
        )
        return HermesToolExecution({"module_key": module.module_key, "selection_mode": mode, "model_count": len(ids)})

    if tool_name == "attach_reference_library_item":
        module = _module(context, str(arguments.get("module_key") or ""))
        item_id = str(arguments.get("library_item_id") or "")
        item = await db.scalar(select(AttachmentReferenceLibraryItem).where(
            AttachmentReferenceLibraryItem.id == item_id,
            AttachmentReferenceLibraryItem.organization_id == context.project.organization_id,
            AttachmentReferenceLibraryItem.is_active.is_(True),
        ))
        if item is None:
            raise AppError("hermes.library_item_not_found", "公共参考图不存在、已停用或无权访问", 404)
        row = await add_module_reference(
            db, module=module, slot_type=item.reference_role, asset_id=item.asset_id,
            metadata={"source": "hermes"}, keywords=list(item.tags or []), guidance=item.guidance,
            library_item_id=item.id, user_id=user_id,
        )
        return HermesToolExecution({"module_key": module.module_key, "reference_id": row.id, "library_item_id": item.id})

    if tool_name == "plan_modules":
        keys = list(dict.fromkeys(str(item) for item in (arguments.get("module_keys") or []) if item))
        if not keys:
            raise AppError("hermes.modules_required", "请至少选择一个要策划的模块", 422)
        requirements = arguments.get("requirements") if isinstance(arguments.get("requirements"), dict) else {}
        requests = [AttachmentPlanningModuleInput(
            module_key=key, aspect_ratio=_module(context, key).aspect_ratio,
            operator_requirement_cn=str(requirements.get(key) or _module(context, key).operator_requirement_cn),
        ) for key in keys]
        _, created_count = await request_suite_planning(
            db, settings, project=context.project, session=context.session, version=context.version,
            plan=context.plan, module_rows=context.modules, modules=requests,
            visual_direction_cn=str(arguments.get("visual_direction_cn") or context.plan.visual_direction_cn),
            idempotency_key=f"hermes-plan:{uuid4()}", user_id=user_id,
        )
        return HermesToolExecution({"module_keys": keys, "planning_status": context.plan.planning_status}, dispatch_count=created_count)

    if tool_name == "generate_modules":
        keys = list(dict.fromkeys(str(item) for item in (arguments.get("module_keys") or []) if item))
        if not keys:
            raise AppError("hermes.modules_required", "请至少选择一个要生成的模块", 422)
        preview = await build_attachment_generation_preview(
            db, project=context.project, session=context.session, version=context.version,
            plan=context.plan, modules=context.modules, selected_module_keys=keys,
        )
        _, batch, jobs, _group, created = await create_attachment_generation(
            db, settings, project=context.project, session=context.session, version=context.version,
            plan=context.plan, modules=context.modules, selected_module_keys=keys,
            snapshot_signature=preview.snapshot_signature,
            idempotency_key=f"hermes-generate:{uuid4()}", user_id=user_id,
        )
        return HermesToolExecution(
            {"module_keys": keys, "batch_id": batch.id, "job_ids": [item.id for item in jobs], "total_images": preview.total_images},
            dispatch_count=len(jobs) if created else 0, batch_id=batch.id,
        )

    if tool_name == "edit_generated_output":
        output_id = str(arguments.get("output_id") or "")
        instruction = str(arguments.get("instruction") or "").strip()
        if not output_id or not instruction:
            raise AppError("hermes.edit_input_required", "修改图片需要结果ID和修改要求", 422)
        item = AttachmentOutputEditItemRequest(
            source_output_id=output_id, instruction=instruction,
            edit_scope=str(arguments.get("edit_scope") or "whole_image"),
            reference_asset_ids=[str(value) for value in (arguments.get("reference_asset_ids") or []) if value],
            library_item_ids=[str(value) for value in (arguments.get("library_item_ids") or []) if value],
            override_confirmed=bool(arguments.get("override_confirmed")),
        )
        batch, _group, revisions, created = await create_output_edits(
            db, settings, project=context.project, version=context.version, requests=[item],
            idempotency_key=f"hermes-edit:{uuid4()}", concurrency=1, user_id=user_id,
        )
        return HermesToolExecution(
            {"output_id": output_id, "batch_id": batch.id, "revision_ids": [row.id for row in revisions]},
            dispatch_count=1 if created else 0, batch_id=batch.id,
        )

    raise AppError("hermes.tool_not_implemented", "该业务动作暂不可执行", 422, {"tool": tool_name})
