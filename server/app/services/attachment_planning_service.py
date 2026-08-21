from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.attachment_planning import (
    AttachmentWorkbenchModulePlan,
    AttachmentWorkbenchPlan,
    AttachmentWorkbenchPlanVersion,
)
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject, ListingVersion
from app.models.tasks import Job
from app.schemas.attachment_planning import AttachmentPlanningModuleInput
from app.schemas.tasks import JobSubmitRequest
from app.services.category_listing_service import resolve_bound_model_code
from app.services.listing_image_module_service import (
    STANDARD_LISTING_IMAGE_MODULES,
    STANDARD_MODULE_CODES,
    normalize_listing_product_profile,
)
from app.services.task_service import submit_job


UTC = timezone.utc
ALLOWED_ASPECT_RATIOS = {"1:1", "4:5", "3:4"}
MODULE_INDEX = {str(item["code"]): item for item in STANDARD_LISTING_IMAGE_MODULES}
TERMINAL_FAILURES = {"failed", "cancelled"}

SUITE_SYSTEM_PROMPT = """你是亚马逊电商附图策划专家。根据已确认的商品事实、Listing、Skill规则、整套方向和模块上下文，为运营生成统一且可执行的中文附图方案。

只返回一个有效 JSON 对象，不要使用 Markdown，不要解释。结构必须是：
{
  "visual_direction_cn": "2到4行中文整套视觉方向",
  "modules": [
    {"module_key": "模块编码", "plan_summary_cn": "简短中文画面方案", "prompt_cn": "可直接交给图片模型执行的完整中文提示词"}
  ]
}

要求：
- 只返回请求中列出的模块，module_key不得改名、遗漏或新增。
- 六类模块的画面行为必须不同，但标准模式都继承整套视觉方向。
- prompt_cn必须包含当前目标比例与相应构图，并保护商品颜色、结构、Logo、文字、号码、图案、印花和定制内容。
- 不得虚构图片或商品分析中不存在的材质、功能、授权、认证或性能。
- 运营补充要求不能覆盖商品真实性硬约束。
- Visual Preset是整套视觉策略的基础约束；Theme只能叠加环境与氛围，绝不能修改商品真实颜色。
- MODEL参考只决定人物身份、脸部、发型和身体特征。必须忽略MODEL图中原有衣服，服装只能来自PRODUCT。
- plan_summary_cn回答“这张图准备做成什么样”，不要写成技术说明。
- prompt_cn不要机械复制整套视觉方向，要把方向转化为当前模块可执行的画面要求。
- 每个模块必须直接回答其buyer_question并完成image_sales_objective；required_information必须可见，avoid_duplication中的任务不得与其他模块重复。
- 整套可以共享商品真实性、视觉模板、主题和商业气质，但不能把同一个卖点仅换背景后重复六次。
- 如果product_composition.mode为MULTI，必须明确人物数量等于商品数量、Model A/B/C与PRIMARY/SECONDARY逐一对应、主商品视觉优先，并逐件写明不可串用的商品身份特征。"""

MODULE_REPLAN_SYSTEM_PROMPT = """你是亚马逊电商附图策划专家。只重新策划指定模块，必须继承当前整套视觉方向与商品真实性约束。
只返回有效 JSON：{"module_key":"指定模块编码","plan_summary_cn":"中文方案","prompt_cn":"完整中文执行提示词"}。
不得返回其他模块，不得解释，不得使用Markdown。提示词必须写明目标比例并针对该比例组织构图。
必须直接回答module.buyer_question、完成module.image_sales_objective、包含required_information，并避开avoid_duplication列出的重复任务。
如果product_composition.mode为MULTI，必须明确人物数量等于商品数量、Model A/B/C与PRIMARY/SECONDARY逐一对应、主商品视觉优先，并逐件写明不可串用的商品身份特征。"""

PROMPT_OPTIMIZE_SYSTEM_PROMPT = """你是亚马逊电商图片提示词编辑专家。保持当前模块方案方向不变，只重构并优化中文执行提示词。
只返回有效 JSON：{"module_key":"指定模块编码","prompt_cn":"优化后的完整中文执行提示词"}。
不要修改方案，不要解释，不要使用Markdown。必须保留商品真实性约束、整套视觉方向和目标比例，消除重复与冲突。"""


def _module_definition(skill_snapshot: dict[str, object], module_key: str) -> dict[str, object]:
    base = deepcopy(MODULE_INDEX[module_key])
    image_config = skill_snapshot.get("image_prompt_config")
    custom_modules = image_config.get("listing_image_modules") if isinstance(image_config, dict) else None
    for item in custom_modules or []:
        if isinstance(item, dict) and item.get("code") == module_key:
            base.update(deepcopy(item))
            break
    return base


def attachment_module_rule(skill_snapshot: dict[str, object], module_key: str) -> dict[str, object]:
    return _module_definition(skill_snapshot, module_key)


def _compact_listing(listing: dict[str, object]) -> dict[str, object]:
    return {key: listing.get(key) for key in (
        "title", "bullet_points", "selling_points", "usage_scenarios", "customization_notes", "cautions",
    ) if listing.get(key) not in (None, "", [], {})}


def build_attachment_module_context(
    *, module_key: str, analysis_snapshot: dict[str, object], listing_snapshot: dict[str, object],
    skill_snapshot: dict[str, object], aspect_ratio: str, operator_requirement_cn: str,
    reference_understanding: dict[str, object] | None = None,
    product_composition: dict[str, object] | None = None,
    module_model_context: dict[str, object] | None = None,
) -> dict[str, object]:
    if module_key not in MODULE_INDEX:
        raise AppError("attachment_planning.module_invalid", "选择了不支持的附图模块", 422, {"module_key": module_key})
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        raise AppError("attachment_planning.aspect_ratio_invalid", "图片比例无效", 422, {"aspect_ratio": aspect_ratio})
    definition = _module_definition(skill_snapshot, module_key)
    profile = normalize_listing_product_profile(analysis_snapshot, listing_snapshot, skill_snapshot)
    field_keys = list(dict.fromkeys([
        *[str(value) for value in definition.get("high_weight_fields", [])],
        *[str(value) for value in definition.get("low_weight_fields", [])],
    ]))
    product_context = {key: profile.get(key) for key in field_keys if profile.get(key) not in (None, "", [], {})}
    return {
        "module_key": module_key,
        "module_name": str(definition.get("name") or module_key),
        "module_objective": str(definition.get("objective") or ""),
        "buyer_question": str(definition.get("buyer_question") or ""),
        "image_sales_objective": str(definition.get("image_sales_objective") or ""),
        "required_information": [str(value) for value in definition.get("required_information", [])],
        "avoid_duplication": [str(value) for value in definition.get("avoid_duplication", [])],
        "module_default_rule": str(definition.get("prompt_template") or ""),
        "product_context": product_context,
        "listing_context": _compact_listing(listing_snapshot),
        "aspect_ratio": aspect_ratio,
        "operator_requirement_cn": operator_requirement_cn.strip(),
        "reference_understanding": reference_understanding,
        "product_composition": product_composition or {"mode": "SINGLE", "products": []},
        "model_context": module_model_context or {"selection_mode": "inherit", "selected_models": []},
        "reference_priority": ["PRODUCT", "PRINT", "module_rule", "TEMPLATE", "SCENE", "OTHER"],
        "truth_constraints": [
            "商品参考图是商品外观的最高优先级事实来源",
            "不得改变颜色、结构、版型、领口、袖口、Logo、文字、号码、图案、印花和定制内容",
            "不得新增未经确认的功能、材质、授权、认证或性能宣称",
            "多商品时，Model A对应主商品，Model B/C依次对应附加商品；每个模特只能穿对应商品",
            "不同商品的颜色、结构、版型、Logo、文字、号码、图案、印花和定制信息不得串用",
            "主商品必须处于核心视觉区域且最突出、最清晰；附加商品只用于增强系列感和多人场景",
        ],
    }


def build_suite_planning_input(
    *, version: ListingVersion, modules: list[AttachmentPlanningModuleInput], visual_direction_cn: str,
    current_modules: dict[str, AttachmentWorkbenchModulePlan] | None = None,
    reference_understandings: dict[str, dict[str, object]] | None = None,
    product_compositions: dict[str, dict[str, object]] | None = None,
    creative_context: dict[str, object] | None = None,
    module_model_contexts: dict[str, dict[str, object]] | None = None,
    product_identity_lock: dict[str, object] | None = None,
) -> tuple[str, str, dict[str, dict[str, object]]]:
    skill_snapshot = dict(version.category_skill_snapshot or {})
    contexts: dict[str, dict[str, object]] = {}
    for item in modules:
        context = build_attachment_module_context(
            module_key=item.module_key,
            analysis_snapshot=dict(version.analysis_snapshot or {}),
            listing_snapshot=dict(version.listing_snapshot or {}),
            skill_snapshot=skill_snapshot,
            aspect_ratio=item.aspect_ratio,
            operator_requirement_cn=item.operator_requirement_cn,
            reference_understanding=(reference_understandings or {}).get(item.module_key),
            product_composition=(product_compositions or {}).get(item.module_key),
            module_model_context=(module_model_contexts or {}).get(item.module_key),
        )
        current = (current_modules or {}).get(item.module_key)
        if current is not None:
            context["current_plan_summary_cn"] = current.plan_summary_cn
            context["current_prompt_cn"] = current.prompt_cn
        contexts[item.module_key] = context
    payload = {
        "category": {
            "code": skill_snapshot.get("category_code"), "name": skill_snapshot.get("category_name"),
        },
        "product_name": normalize_listing_product_profile(
            dict(version.analysis_snapshot or {}), dict(version.listing_snapshot or {}), skill_snapshot,
        ).get("product_name"),
        "skill": {
            "name": skill_snapshot.get("skill_name"), "version": skill_snapshot.get("skill_version"),
        },
        "existing_visual_direction_cn": visual_direction_cn.strip(),
        "creative_context": creative_context or {},
        "product_identity_lock": product_identity_lock or {},
        "selected_modules": list(contexts.values()),
    }
    return SUITE_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False), contexts


def build_module_planning_input(
    *, version: ListingVersion, module: AttachmentWorkbenchModulePlan, visual_direction_cn: str,
    action: str,
    reference_understanding: dict[str, object] | None = None,
    product_composition: dict[str, object] | None = None,
    creative_context: dict[str, object] | None = None,
    module_model_context: dict[str, object] | None = None,
    product_identity_lock: dict[str, object] | None = None,
) -> tuple[str, str, dict[str, object]]:
    context = build_attachment_module_context(
        module_key=module.module_key,
        analysis_snapshot=dict(version.analysis_snapshot or {}),
        listing_snapshot=dict(version.listing_snapshot or {}),
        skill_snapshot=dict(version.category_skill_snapshot or {}),
        aspect_ratio=module.aspect_ratio,
        operator_requirement_cn=module.operator_requirement_cn,
        reference_understanding=reference_understanding,
        product_composition=product_composition,
        module_model_context=module_model_context,
    )
    payload = {
        "visual_direction_cn": visual_direction_cn,
        "creative_context": creative_context or {},
        "product_identity_lock": product_identity_lock or {},
        "module": context,
        "current_plan_summary_cn": module.plan_summary_cn,
        "current_prompt_cn": module.prompt_cn,
    }
    system = PROMPT_OPTIMIZE_SYSTEM_PROMPT if action == "optimize_prompt" else MODULE_REPLAN_SYSTEM_PROMPT
    return system, json.dumps(payload, ensure_ascii=False), context


def _json_object(text: str) -> dict[str, object]:
    value = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        value = fenced.group(1)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise AppError("attachment_planning.ai_result_invalid", "AI策划结果不是有效JSON，请重新策划", 422)
        try:
            parsed = json.loads(value[start:end + 1])
        except json.JSONDecodeError as error:
            raise AppError("attachment_planning.ai_result_invalid", "AI策划结果不是有效JSON，请重新策划", 422) from error
    if not isinstance(parsed, dict):
        raise AppError("attachment_planning.ai_result_invalid", "AI策划结果必须是JSON对象", 422)
    return parsed


def parse_suite_planning_result(text: str, expected_module_keys: list[str]) -> tuple[str, dict[str, dict[str, str]]]:
    payload = _json_object(text)
    visual = str(payload.get("visual_direction_cn") or "").strip()
    rows = payload.get("modules")
    if not visual or not isinstance(rows, list):
        raise AppError("attachment_planning.ai_result_invalid", "AI策划缺少整套视觉方向或模块结果", 422)
    modules: dict[str, dict[str, str]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("module_key") or "")
        plan = str(raw.get("plan_summary_cn") or "").strip()
        prompt = str(raw.get("prompt_cn") or "").strip()
        if key in modules or not plan or not prompt:
            raise AppError("attachment_planning.ai_result_invalid", "AI策划模块内容不完整或重复", 422)
        modules[key] = {"plan_summary_cn": plan, "prompt_cn": prompt}
    if set(modules) != set(expected_module_keys):
        raise AppError(
            "attachment_planning.module_result_mismatch", "AI返回的模块与当前选择不一致，请重新策划", 422,
            {"expected": expected_module_keys, "actual": sorted(modules)},
        )
    return visual, modules


def parse_module_planning_result(text: str, module_key: str, *, optimize_only: bool) -> dict[str, str]:
    payload = _json_object(text)
    if str(payload.get("module_key") or "") != module_key:
        raise AppError("attachment_planning.module_result_mismatch", "AI返回了错误的模块", 422)
    prompt = str(payload.get("prompt_cn") or "").strip()
    plan = str(payload.get("plan_summary_cn") or "").strip()
    if not prompt or (not optimize_only and not plan):
        raise AppError("attachment_planning.ai_result_invalid", "AI返回的模块方案或Prompt为空", 422)
    return {"prompt_cn": prompt, "plan_summary_cn": plan}


async def get_or_create_attachment_plan(
    db: AsyncSession, *, project: ListingImageProject, session: ListingGenerationSession,
    version: ListingVersion, user_id: str,
) -> tuple[AttachmentWorkbenchPlan, list[AttachmentWorkbenchModulePlan]]:
    # The workbench loads several endpoints in parallel. Serialize first-time
    # initialization on the already-existing project row before creating the
    # one-to-one plan and its module rows.
    await db.scalar(select(ListingImageProject.id).where(
        ListingImageProject.id == project.id,
        ListingImageProject.organization_id == project.organization_id,
    ).with_for_update())
    plan = await db.scalar(select(AttachmentWorkbenchPlan).where(
        AttachmentWorkbenchPlan.organization_id == project.organization_id,
        AttachmentWorkbenchPlan.listing_image_project_id == project.id,
    ).with_for_update())
    now = datetime.now(UTC)
    if plan is None:
        phase1 = (project.prompt_config or {}).get("attachment_workbench")
        phase1 = phase1 if isinstance(phase1, dict) else {}
        visual = str(phase1.get("visualDirection") or "").strip()
        plan = AttachmentWorkbenchPlan(
            organization_id=project.organization_id, listing_image_project_id=project.id,
            session_id=session.id, listing_version_id=version.id, skill_version_id=session.skill_version_id,
            visual_direction_cn=visual, visual_direction_source="phase1_import" if visual else "none",
            visual_direction_version=1 if visual else 0, planning_status="ready" if visual else "idle",
            state_version=0, last_saved_at=now, created_by=user_id, updated_by=user_id,
        )
        db.add(plan)
        await db.flush()
        if visual:
            db.add(AttachmentWorkbenchPlanVersion(
                organization_id=project.organization_id, workbench_plan_id=plan.id,
                version_scope="suite", version_number=1, action="phase1_import",
                visual_direction_cn=visual, selected_module_keys=[], skill_version_id=session.skill_version_id,
                skill_rule_snapshot={}, created_by=user_id,
            ))
    from app.services.creative_preset_service import ensure_plan_creative_context
    await ensure_plan_creative_context(db, plan=plan)
    existing = list((await db.scalars(select(AttachmentWorkbenchModulePlan).where(
        AttachmentWorkbenchModulePlan.workbench_plan_id == plan.id,
    ).with_for_update())).all())
    indexed = {item.module_key: item for item in existing}
    phase1 = (project.prompt_config or {}).get("attachment_workbench")
    phase1 = phase1 if isinstance(phase1, dict) else {}
    phase1_modules = phase1.get("modules") if isinstance(phase1.get("modules"), dict) else {}
    for definition in STANDARD_LISTING_IMAGE_MODULES:
        key = str(definition["code"])
        if key in indexed:
            continue
        saved = phase1_modules.get(key) if isinstance(phase1_modules, dict) else None
        saved = saved if isinstance(saved, dict) else {}
        ratio = str(saved.get("aspectRatio") or definition.get("recommended_aspect_ratio") or "1:1")
        item = AttachmentWorkbenchModulePlan(
            organization_id=project.organization_id, workbench_plan_id=plan.id, module_key=key,
            aspect_ratio=ratio if ratio in ALLOWED_ASPECT_RATIOS else "1:1", updated_by=user_id,
            last_saved_at=now,
        )
        db.add(item)
        indexed[key] = item
    await db.flush()
    return plan, [indexed[key] for key in STANDARD_MODULE_CODES]


async def _previous_version(db: AsyncSession, plan_id: str, scope: str, number: int) -> AttachmentWorkbenchPlanVersion | None:
    if number <= 0:
        return None
    return await db.scalar(select(AttachmentWorkbenchPlanVersion).where(
        AttachmentWorkbenchPlanVersion.workbench_plan_id == plan_id,
        AttachmentWorkbenchPlanVersion.version_scope == scope,
        AttachmentWorkbenchPlanVersion.version_number == number,
    ))


async def add_suite_version(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan, action: str, selected: list[str], user_id: str,
    visual_direction_cn: str, job: Job | None = None,
    creative_context: dict[str, object] | None = None,
) -> AttachmentWorkbenchPlanVersion:
    previous = await _previous_version(db, plan.id, "suite", plan.visual_direction_version)
    number = plan.visual_direction_version + 1
    if creative_context is None:
        from app.services.creative_preset_service import creative_context_snapshot
        creative_context = await creative_context_snapshot(db, plan=plan)
    creative = creative_context
    row = AttachmentWorkbenchPlanVersion(
        organization_id=plan.organization_id, workbench_plan_id=plan.id, version_scope="suite",
        version_number=number, action=action, visual_direction_cn=visual_direction_cn,
        selected_module_keys=selected, skill_version_id=plan.skill_version_id,
        skill_rule_snapshot={}, source_version_id=previous.id if previous else None,
        visual_preset_id=creative.get("visual_preset_id"),
        visual_preset_version_id=creative.get("visual_preset_version_id"),
        visual_preset_prompt_snapshot=str(creative.get("visual_preset_prompt") or ""),
        theme_preset_id=creative.get("theme_preset_id"),
        theme_preset_version_id=creative.get("theme_preset_version_id"),
        theme_prompt_snapshot=str(creative.get("theme_prompt") or ""),
        selected_model_snapshot=list(creative.get("selected_models") or []),
        product_identity_lock_version_id=plan.current_product_identity_lock_version_id,
        ai_job_id=job.id if job else None, ai_model=job.model_code if job else None, created_by=user_id,
    )
    db.add(row)
    plan.visual_direction_cn = visual_direction_cn
    plan.visual_direction_version = number
    plan.visual_direction_source = action
    return row


async def add_module_version(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan, module: AttachmentWorkbenchModulePlan,
    action: str, user_id: str, rule_snapshot: dict[str, object], job: Job | None = None,
    plan_summary_cn: str, prompt_cn: str,
    reference_understanding_id: str | None = None,
    product_composition_version_id: str | None = None,
    source_version_id: str | None = None,
    derived_from_output_id: str | None = None,
    creative_context: dict[str, object] | None = None,
) -> AttachmentWorkbenchPlanVersion:
    scope = f"module:{module.module_key}"
    previous = await _previous_version(db, plan.id, scope, module.current_version_number)
    number = module.current_version_number + 1
    if creative_context is None:
        from app.services.creative_preset_service import creative_context_snapshot
        creative_context = await creative_context_snapshot(db, plan=plan)
    creative = creative_context
    reference_library_snapshot: list[dict[str, object]] = []
    if reference_understanding_id:
        from app.models.attachment_planning import AttachmentReferenceUnderstanding
        understanding = await db.get(AttachmentReferenceUnderstanding, reference_understanding_id)
        options = (understanding.source_snapshot_json or {}).get("reference_options", []) if understanding else []
        reference_library_snapshot = [dict(item) for item in options if isinstance(item, dict) and item.get("library_item_id")]
    row = AttachmentWorkbenchPlanVersion(
        organization_id=plan.organization_id, workbench_plan_id=plan.id, module_plan_id=module.id,
        version_scope=scope, module_key=module.module_key, version_number=number, action=action,
        plan_summary_cn=plan_summary_cn, prompt_cn=prompt_cn,
        operator_requirement_cn=module.operator_requirement_cn, aspect_ratio=module.aspect_ratio,
        selected_module_keys=[module.module_key], skill_version_id=plan.skill_version_id,
        skill_rule_snapshot=rule_snapshot,
        visual_preset_id=creative.get("visual_preset_id"),
        visual_preset_version_id=creative.get("visual_preset_version_id"),
        visual_preset_prompt_snapshot=str(creative.get("visual_preset_prompt") or ""),
        theme_preset_id=creative.get("theme_preset_id"),
        theme_preset_version_id=creative.get("theme_preset_version_id"),
        theme_prompt_snapshot=str(creative.get("theme_prompt") or ""),
        selected_model_snapshot=list(creative.get("selected_models") or []),
        reference_library_snapshot=reference_library_snapshot,
        product_identity_lock_version_id=plan.current_product_identity_lock_version_id,
        source_version_id=source_version_id if source_version_id is not None else (previous.id if previous else None),
        generation_mode="standard", derived_from_output_id=derived_from_output_id,
        ai_job_id=job.id if job else None, ai_model=job.model_code if job else None, created_by=user_id,
        reference_understanding_id=reference_understanding_id,
        product_composition_version_id=product_composition_version_id,
    )
    db.add(row)
    module.plan_summary_cn = plan_summary_cn
    module.prompt_cn = prompt_cn
    module.current_version_number = number
    module.source = action
    return row


async def start_suite_planning(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject, session: ListingGenerationSession,
    version: ListingVersion, plan: AttachmentWorkbenchPlan, module_rows: list[AttachmentWorkbenchModulePlan],
    modules: list[AttachmentPlanningModuleInput], visual_direction_cn: str, idempotency_key: str, user_id: str,
) -> tuple[Job, bool]:
    from app.services.creative_preset_service import creative_context_snapshot
    creative_context = await creative_context_snapshot(db, plan=plan)
    if not creative_context.get("visual_preset_version_id"):
        raise AppError("creative_preset.visual_required", "请先选择整套视觉模板", 409)
    selected_keys = [item.module_key for item in modules]
    invalid = sorted(set(selected_keys) - set(STANDARD_MODULE_CODES))
    if invalid:
        raise AppError("attachment_planning.module_invalid", "选择了不支持的附图模块", 422, {"invalid": invalid})
    indexed = {item.module_key: item for item in module_rows}
    from app.services.attachment_reference_service import current_understanding_context, effective_reference_snapshot

    understanding_ids: dict[str, str] = {}
    understanding_contexts: dict[str, dict[str, object]] = {}
    from app.services.creative_preset_service import module_model_context_snapshot
    module_model_contexts = {
        key: await module_model_context_snapshot(db, plan=plan, module_key=key) for key in selected_keys
    }
    from app.services.attachment_product_identity_service import current_product_identity_lock
    identity_lock_row = await current_product_identity_lock(db, plan=plan)
    if identity_lock_row is None or identity_lock_row.status != "ready":
        raise AppError("product_identity.not_ready", "商品事实正在自动提取，请稍候再策划", 409)
    identity_lock = dict(identity_lock_row.structured_json or {})
    product_composition_version_ids: dict[str, str] = {}
    product_compositions: dict[str, dict[str, object]] = {}
    references: list[str] = []
    for key in selected_keys:
        understanding_id, understanding = await current_understanding_context(db, indexed[key])
        if understanding_id and understanding:
            understanding_ids[key] = understanding_id
            understanding_contexts[key] = understanding
        grouped, reference_snapshot = await effective_reference_snapshot(db, plan=plan, module=indexed[key])
        product_composition_version_ids[key] = str(reference_snapshot["product_composition_version_id"])
        product_compositions[key] = {
            "mode": reference_snapshot.get("product_mode"),
            "product_count": reference_snapshot.get("product_count"),
            "model_count": reference_snapshot.get("model_count"),
            "products": reference_snapshot.get("products", []),
        }
        ordered = reference_snapshot.get("execution_order")
        if isinstance(ordered, list):
            references.extend(
                str(row.get("asset_id")) for row in ordered
                if isinstance(row, dict) and row.get("asset_id")
            )
        else:
            for slot in ("PRODUCT", "PRINT", "TEMPLATE", "SCENE", "OTHER"):
                references.extend(grouped.get(slot, []))
    references = list(dict.fromkeys(references))
    system_prompt, user_prompt, _ = build_suite_planning_input(
        version=version, modules=modules, visual_direction_cn=visual_direction_cn,
        current_modules=indexed, reference_understandings=understanding_contexts,
        product_compositions=product_compositions,
        creative_context=creative_context,
        module_model_contexts=module_model_contexts,
        product_identity_lock=identity_lock,
    )
    target_plan_version = plan.state_version + 1
    target_module_versions = {key: indexed[key].state_version + 1 for key in selected_keys}
    model_code = await resolve_bound_model_code(
        db, organization_id=project.organization_id, operation_code="listing.plan", capability="text_generation",
    )
    if not references:
        references = [session.primary_asset_id] if session.primary_asset_id else list(session.source_asset_ids or [])[:1]
    job, created = await submit_job(db, settings, organization_id=project.organization_id, user_id=user_id, payload=JobSubmitRequest(
        operation_code="listing.plan", workspace_type="listing", queue_name="planning_queue",
        capability="text_generation", model_code=model_code, idempotency_key=idempotency_key,
        project_id=session.project_id,
        input={"system_prompt": system_prompt, "user_prompt": user_prompt, "temperature": 0.2,
               "response_format": "json_object", "reference_asset_ids": references,
               "metadata": {"workflow": "attachment_workbench_planning", "action": "suite_plan",
                            "planning_id": plan.id, "selected_modules": selected_keys,
                            "reference_understanding_ids": understanding_ids,
                            "product_composition_version_ids": product_composition_version_ids,
                            "product_identity_lock_version_id": identity_lock_row.id,
                            "creative_context_snapshot": creative_context,
                            "module_model_context_snapshots": module_model_contexts,
                            "creative_context_version": plan.creative_context_version,
                            "expected_plan_state_version": target_plan_version,
                            "expected_module_state_versions": target_module_versions}},
        billing_factors={"quality": "standard", "resolution": "text"}, client_item_id="attachment-suite",
    ))
    if not created:
        # A transport retry with the same idempotency key must return the original
        # orchestration state instead of advancing state_version a second time.
        return job, False
    now = datetime.now(UTC)
    plan.planning_job_id = job.id
    plan.planning_status = "planning"
    plan.error_message = None
    plan.state_version = target_plan_version
    plan.updated_by = user_id
    plan.last_saved_at = now
    for request in modules:
        row = indexed[request.module_key]
        row.aspect_ratio = request.aspect_ratio
        row.operator_requirement_cn = request.operator_requirement_cn
        row.planning_job_id = job.id
        row.status = "planning"
        row.error_message = None
        row.state_version = target_module_versions[row.module_key]
        row.updated_by = user_id
        row.last_saved_at = now
    return job, created


async def start_module_planning(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject, session: ListingGenerationSession,
    version: ListingVersion, plan: AttachmentWorkbenchPlan, module: AttachmentWorkbenchModulePlan,
    action: str, aspect_ratio: str, operator_requirement_cn: str, idempotency_key: str, user_id: str,
) -> tuple[Job, bool]:
    from app.services.creative_preset_service import creative_context_snapshot
    creative_context = await creative_context_snapshot(db, plan=plan)
    from app.services.creative_preset_service import module_model_context_snapshot
    module_model_context = await module_model_context_snapshot(db, plan=plan, module_key=module.module_key)
    from app.services.attachment_product_identity_service import current_product_identity_lock
    identity_lock_row = await current_product_identity_lock(db, plan=plan)
    if identity_lock_row is None or identity_lock_row.status != "ready":
        raise AppError("product_identity.not_ready", "商品事实正在自动提取，请稍候再策划", 409)
    identity_lock = dict(identity_lock_row.structured_json or {})
    module.aspect_ratio = aspect_ratio
    module.operator_requirement_cn = operator_requirement_cn
    from app.services.attachment_reference_service import current_understanding_context, effective_reference_snapshot

    understanding_id, understanding = await current_understanding_context(db, module)
    grouped, reference_snapshot = await effective_reference_snapshot(db, plan=plan, module=module)
    product_composition_version_id = str(reference_snapshot["product_composition_version_id"])
    system_prompt, user_prompt, _ = build_module_planning_input(
        version=version, module=module, visual_direction_cn=plan.visual_direction_cn, action=action,
        reference_understanding=understanding,
        product_composition={
            "mode": reference_snapshot.get("product_mode"),
            "product_count": reference_snapshot.get("product_count"),
            "model_count": reference_snapshot.get("model_count"),
            "products": reference_snapshot.get("products", []),
        },
        creative_context=creative_context,
        module_model_context=module_model_context,
        product_identity_lock=identity_lock,
    )
    target_module_version = module.state_version + 1
    model_code = await resolve_bound_model_code(
        db, organization_id=project.organization_id, operation_code="listing.plan", capability="text_generation",
    )
    ordered = reference_snapshot.get("execution_order")
    references = list(dict.fromkeys(
        str(row.get("asset_id")) for row in ordered
        if isinstance(row, dict) and row.get("asset_id")
    )) if isinstance(ordered, list) else list(dict.fromkeys(
        asset_id for slot in ("PRODUCT", "PRINT", "TEMPLATE", "SCENE", "OTHER")
        for asset_id in grouped.get(slot, [])
    ))
    if not references:
        references = [session.primary_asset_id] if session.primary_asset_id else list(session.source_asset_ids or [])[:1]
    job, created = await submit_job(db, settings, organization_id=project.organization_id, user_id=user_id, payload=JobSubmitRequest(
        operation_code="listing.plan", workspace_type="listing", queue_name="planning_queue",
        capability="text_generation", model_code=model_code, idempotency_key=idempotency_key,
        project_id=session.project_id,
        input={"system_prompt": system_prompt, "user_prompt": user_prompt, "temperature": 0.2,
               "response_format": "json_object", "reference_asset_ids": references,
               "metadata": {"workflow": "attachment_workbench_planning", "action": action,
                            "planning_id": plan.id, "module_key": module.module_key,
                            "reference_understanding_ids": {module.module_key: understanding_id} if understanding_id else {},
                            "product_composition_version_ids": {module.module_key: product_composition_version_id},
                            "product_identity_lock_version_id": identity_lock_row.id,
                            "creative_context_snapshot": creative_context,
                            "module_model_context_snapshots": {module.module_key: module_model_context},
                            "creative_context_version": plan.creative_context_version,
                            "expected_plan_state_version": plan.state_version,
                            "expected_module_state_versions": {module.module_key: target_module_version}}},
        billing_factors={"quality": "standard", "resolution": "text"},
        client_item_id=f"attachment:{module.module_key}",
    ))
    if not created:
        return job, False
    module.planning_job_id = job.id
    module.status = "planning"
    module.error_message = None
    module.state_version = target_module_version
    module.updated_by = user_id
    module.last_saved_at = datetime.now(UTC)
    return job, created


def _pending_module_payload(item: AttachmentPlanningModuleInput) -> dict[str, object]:
    return {
        "module_key": item.module_key,
        "aspect_ratio": item.aspect_ratio,
        "operator_requirement_cn": item.operator_requirement_cn,
    }


async def _start_planning_dependencies(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject,
    session: ListingGenerationSession, version: ListingVersion, plan: AttachmentWorkbenchPlan,
    selected: list[AttachmentWorkbenchModulePlan], user_id: str,
) -> tuple[dict[str, str], str, int]:
    """Start or reuse the exact analysis versions required by one planning intent."""
    from app.services.attachment_product_identity_service import start_product_identity_lock
    from app.services.attachment_reference_service import start_reference_analysis

    created_count = 0
    identity, _, identity_created = await start_product_identity_lock(
        db, settings, project=project, session=session, version=version, plan=plan,
        user_id=user_id, force=False,
    )
    created_count += int(identity_created)
    understanding_ids: dict[str, str] = {}
    for module in selected:
        _, understanding, created = await start_reference_analysis(
            db, settings, project=project, plan=plan, module=module,
            idempotency_key=(
                f"attachment-reference:auto-planning:{plan.id}:{module.id}:"
                f"{module.reference_state_version}"
            ),
            user_id=user_id,
        )
        understanding_ids[module.module_key] = understanding.id
        created_count += int(created)
    return understanding_ids, identity.id, created_count


def _set_preparing_state(
    *, plan: AttachmentWorkbenchPlan, selected: list[AttachmentWorkbenchModulePlan],
    pending: dict[str, object], user_id: str, suite: bool,
) -> None:
    now = datetime.now(UTC)
    plan.pending_planning_json = pending
    if suite:
        plan.planning_status = "preparing"
        plan.planning_job_id = None
        plan.error_message = None
    plan.updated_by = user_id
    plan.last_saved_at = now
    for module in selected:
        module.status = "preparing"
        module.planning_job_id = None
        module.error_message = None
        module.updated_by = user_id
        module.last_saved_at = now


async def request_suite_planning(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject,
    session: ListingGenerationSession, version: ListingVersion, plan: AttachmentWorkbenchPlan,
    module_rows: list[AttachmentWorkbenchModulePlan], modules: list[AttachmentPlanningModuleInput],
    visual_direction_cn: str, idempotency_key: str, user_id: str,
) -> tuple[Job | None, int]:
    """Persist a suite planning intent and let the backend resolve its AI dependencies."""
    existing = dict(plan.pending_planning_json or {})
    if existing:
        if existing.get("idempotency_key") == idempotency_key:
            return None, 0
        raise AppError("attachment_planning.already_preparing", "已有AI策划正在准备，请等待完成", 409)
    indexed = {item.module_key: item for item in module_rows}
    selected = [indexed[item.module_key] for item in modules if item.module_key in indexed]
    if len(selected) != len(modules):
        raise AppError("attachment_planning.module_invalid", "选择了不支持的附图模块", 422)
    # Validate ratios and the required visual preset before any dependency job is submitted.
    for item in modules:
        if item.aspect_ratio not in ALLOWED_ASPECT_RATIOS:
            raise AppError("attachment_planning.aspect_ratio_invalid", "图片比例无效", 422)
    from app.services.creative_preset_service import creative_context_snapshot
    if not (await creative_context_snapshot(db, plan=plan)).get("visual_preset_version_id"):
        raise AppError("creative_preset.visual_required", "请先选择整套视觉模板", 409)
    understanding_ids, identity_id, created_count = await _start_planning_dependencies(
        db, settings, project=project, session=session, version=version, plan=plan,
        selected=selected, user_id=user_id,
    )
    pending = {
        "scope": "suite", "action": "suite_plan", "idempotency_key": idempotency_key,
        "user_id": user_id, "visual_direction_cn": visual_direction_cn,
        "modules": [_pending_module_payload(item) for item in modules],
        "reference_understanding_ids": understanding_ids,
        "reference_state_versions": {item.module_key: item.reference_state_version for item in selected},
        "product_identity_lock_version_id": identity_id,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    _set_preparing_state(plan=plan, selected=selected, pending=pending, user_id=user_id, suite=True)
    planning_job, planning_created = await _continue_pending_for_loaded_context(
        db, settings, project=project, session=session, version=version,
        plan=plan, modules=module_rows,
    )
    return planning_job, created_count + int(planning_created)


async def request_module_planning(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject,
    session: ListingGenerationSession, version: ListingVersion, plan: AttachmentWorkbenchPlan,
    module_rows: list[AttachmentWorkbenchModulePlan], module: AttachmentWorkbenchModulePlan,
    action: str, aspect_ratio: str, operator_requirement_cn: str,
    idempotency_key: str, user_id: str,
) -> tuple[Job | None, int]:
    existing = dict(plan.pending_planning_json or {})
    if existing:
        if existing.get("idempotency_key") == idempotency_key:
            return None, 0
        raise AppError("attachment_planning.already_preparing", "已有AI策划正在准备，请等待完成", 409)
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        raise AppError("attachment_planning.aspect_ratio_invalid", "图片比例无效", 422)
    request = AttachmentPlanningModuleInput(
        module_key=module.module_key, aspect_ratio=aspect_ratio,
        operator_requirement_cn=operator_requirement_cn,
    )
    understanding_ids, identity_id, created_count = await _start_planning_dependencies(
        db, settings, project=project, session=session, version=version, plan=plan,
        selected=[module], user_id=user_id,
    )
    pending = {
        "scope": "module", "action": action, "module_key": module.module_key,
        "idempotency_key": idempotency_key, "user_id": user_id,
        "modules": [_pending_module_payload(request)],
        "reference_understanding_ids": understanding_ids,
        "reference_state_versions": {module.module_key: module.reference_state_version},
        "product_identity_lock_version_id": identity_id,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    _set_preparing_state(plan=plan, selected=[module], pending=pending, user_id=user_id, suite=False)
    planning_job, planning_created = await _continue_pending_for_loaded_context(
        db, settings, project=project, session=session, version=version,
        plan=plan, modules=module_rows,
    )
    return planning_job, created_count + int(planning_created)


async def _continue_pending_for_loaded_context(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject,
    session: ListingGenerationSession, version: ListingVersion, plan: AttachmentWorkbenchPlan,
    modules: list[AttachmentWorkbenchModulePlan],
) -> tuple[Job | None, bool]:
    pending = dict(plan.pending_planning_json or {})
    if not pending:
        return None, False
    indexed = {item.module_key: item for item in modules}
    requests = [
        AttachmentPlanningModuleInput.model_validate(item)
        for item in pending.get("modules", []) if isinstance(item, dict)
    ]
    selected = [indexed[item.module_key] for item in requests if item.module_key in indexed]
    if not requests or len(selected) != len(requests):
        plan.pending_planning_json = {}
        plan.planning_status = "failed"
        plan.error_message = "待执行的AI策划模块已失效，请重新提交"
        return None, False

    # A reference edit while analysis is running invalidates the captured version.
    # Start/reuse analysis for the new version and atomically retarget the intent.
    expected_versions = dict(pending.get("reference_state_versions") or {})
    understanding_ids = dict(pending.get("reference_understanding_ids") or {})
    from app.services.attachment_reference_service import start_reference_analysis
    for module in selected:
        if int(expected_versions.get(module.module_key, -1)) != module.reference_state_version:
            _, understanding, _ = await start_reference_analysis(
                db, settings, project=project, plan=plan, module=module,
                idempotency_key=(
                    f"attachment-reference:pending-refresh:{plan.id}:{module.id}:"
                    f"{module.reference_state_version}"
                ), user_id=str(pending["user_id"]),
            )
            understanding_ids[module.module_key] = understanding.id
            expected_versions[module.module_key] = module.reference_state_version
    pending["reference_understanding_ids"] = understanding_ids
    pending["reference_state_versions"] = expected_versions
    plan.pending_planning_json = pending

    from app.models.attachment_planning import (
        AttachmentProductIdentityLockVersion, AttachmentReferenceUnderstanding,
    )
    identity = await db.get(
        AttachmentProductIdentityLockVersion,
        str(pending.get("product_identity_lock_version_id") or ""),
    )
    understandings = {
        key: await db.get(AttachmentReferenceUnderstanding, str(row_id))
        for key, row_id in understanding_ids.items()
    }
    failed_message = None
    if identity is None or identity.status == "failed":
        failed_message = identity.error_message if identity else "商品事实理解记录不存在"
    for key, understanding in understandings.items():
        if understanding is None or understanding.status == "failed":
            failed_message = (
                understanding.error_message if understanding else f"{key}参考素材理解记录不存在"
            )
            break
    if failed_message:
        plan.pending_planning_json = {}
        message = str(failed_message or "参考素材理解失败，请调整后重试")[:1000]
        if pending.get("scope") == "suite":
            plan.planning_status = "failed"
            plan.error_message = message
        for module in selected:
            module.status = "failed"
            module.error_message = message
        return None, False
    if identity is None or identity.status != "ready" or any(
        row is None or row.status != "ready" for row in understandings.values()
    ):
        return None, False

    user_id = str(pending["user_id"])
    if pending.get("scope") == "suite":
        job, created = await start_suite_planning(
            db, settings, project=project, session=session, version=version, plan=plan,
            module_rows=modules, modules=requests,
            visual_direction_cn=str(pending.get("visual_direction_cn") or ""),
            idempotency_key=str(pending["idempotency_key"]), user_id=user_id,
        )
    else:
        module = selected[0]
        request = requests[0]
        job, created = await start_module_planning(
            db, settings, project=project, session=session, version=version, plan=plan,
            module=module, action=str(pending.get("action") or "module_replan"),
            aspect_ratio=request.aspect_ratio,
            operator_requirement_cn=request.operator_requirement_cn,
            idempotency_key=str(pending["idempotency_key"]), user_id=user_id,
        )
    plan.pending_planning_json = {}
    return job, created


async def continue_pending_attachment_planning(
    db: AsyncSession, settings: Settings, *, plan_id: str,
) -> int:
    """Reconcile analysis results and continue a durable planning intent.

    Called both by the worker completion callback and GET recovery. The
    idempotency key stored on the plan makes repeated calls safe.
    """
    plan = await db.scalar(select(AttachmentWorkbenchPlan).where(
        AttachmentWorkbenchPlan.id == plan_id,
    ).with_for_update())
    if plan is None:
        return 0
    project = await db.get(ListingImageProject, plan.listing_image_project_id)
    session = await db.get(ListingGenerationSession, plan.session_id)
    version = await db.get(ListingVersion, plan.listing_version_id)
    if project is None or session is None or version is None:
        return 0
    modules = list((await db.scalars(select(AttachmentWorkbenchModulePlan).where(
        AttachmentWorkbenchModulePlan.workbench_plan_id == plan.id,
    ))).all())
    from app.services.attachment_product_identity_service import reconcile_product_identity_lock
    from app.services.attachment_reference_service import reconcile_reference_understandings
    created_count = await reconcile_reference_understandings(
        db, settings, plan=plan, modules=modules,
    )
    created_count += await reconcile_product_identity_lock(db, settings, plan=plan)
    _, planning_created = await _continue_pending_for_loaded_context(
        db, settings, project=project, session=session, version=version,
        plan=plan, modules=modules,
    )
    return created_count + int(planning_created)


async def reconcile_attachment_planning(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan, modules: list[AttachmentWorkbenchModulePlan],
    version: ListingVersion,
) -> None:
    job_ids = []
    if plan.planning_status == "planning" and plan.planning_job_id:
        job_ids.append(plan.planning_job_id)
    job_ids.extend(item.planning_job_id for item in modules if item.status == "planning" and item.planning_job_id)
    indexed = {item.module_key: item for item in modules}
    processed: set[str] = set()
    for job_id in job_ids:
        if not job_id or job_id in processed:
            continue
        processed.add(job_id)
        job = await db.get(Job, job_id)
        if job is None or job.status not in {"succeeded", "failed", "cancelled"}:
            continue
        metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
        metadata = metadata if isinstance(metadata, dict) else {}
        if metadata.get("workflow") != "attachment_workbench_planning" or metadata.get("planning_id") != plan.id:
            continue
        action = str(metadata.get("action") or "")
        selected = [str(value) for value in metadata.get("selected_modules", [])]
        if action != "suite_plan":
            selected = [str(metadata.get("module_key") or "")]
        affected = [indexed[key] for key in selected if key in indexed]
        now = datetime.now(UTC)
        if job.status in TERMINAL_FAILURES:
            message = job.error_message or "AI策划任务失败，请重试"
            if action == "suite_plan":
                plan.planning_status = "failed"; plan.error_message = message; plan.state_version += 1
            for item in affected:
                if item.planning_job_id == job.id:
                    item.status = "failed"; item.error_message = message; item.state_version += 1
            continue
        expected_plan = int(metadata.get("expected_plan_state_version") or -1)
        expected_modules = metadata.get("expected_module_state_versions")
        expected_modules = expected_modules if isinstance(expected_modules, dict) else {}
        understanding_ids = metadata.get("reference_understanding_ids")
        understanding_ids = understanding_ids if isinstance(understanding_ids, dict) else {}
        product_composition_version_ids = metadata.get("product_composition_version_ids")
        product_composition_version_ids = (
            product_composition_version_ids if isinstance(product_composition_version_ids, dict) else {}
        )
        creative_context = metadata.get("creative_context_snapshot")
        creative_context = creative_context if isinstance(creative_context, dict) else {}
        module_model_contexts = metadata.get("module_model_context_snapshots")
        module_model_contexts = module_model_contexts if isinstance(module_model_contexts, dict) else {}
        expected_creative_context_version = int(metadata.get("creative_context_version") or -1)
        stale = plan.state_version != expected_plan or plan.creative_context_version != expected_creative_context_version or any(
            item.planning_job_id != job.id or item.state_version != int(expected_modules.get(item.module_key, -1))
            for item in affected
        )
        if stale:
            if action == "suite_plan" and plan.planning_job_id == job.id:
                plan.planning_status = "stale"
                plan.error_message = "AI策划已完成，但工作台在执行期间被修改，结果未覆盖当前版本。"
                plan.state_version += 1
            for item in affected:
                if item.planning_job_id == job.id and item.status == "planning":
                    item.status = "stale"; item.error_message = "策划期间内容已修改，请重新运行。"; item.state_version += 1
            continue
        result_metadata = job.result_json.get("metadata") if isinstance(job.result_json, dict) else None
        text = str(result_metadata.get("text") or "") if isinstance(result_metadata, dict) else ""
        try:
            if action == "suite_plan":
                visual, result_modules = parse_suite_planning_result(text, selected)
                await add_suite_version(
                    db, plan=plan, action="ai_suite_plan", selected=selected, user_id=job.created_by,
                    visual_direction_cn=visual, job=job,
                    creative_context=creative_context,
                )
                for item in affected:
                    definition = _module_definition(dict(version.category_skill_snapshot or {}), item.module_key)
                    result = result_modules[item.module_key]
                    await add_module_version(
                        db, plan=plan, module=item, action="ai_suite_plan", user_id=job.created_by,
                        rule_snapshot=definition, job=job, plan_summary_cn=result["plan_summary_cn"],
                        prompt_cn=result["prompt_cn"],
                        reference_understanding_id=str(understanding_ids.get(item.module_key) or "") or None,
                        product_composition_version_id=(
                            str(product_composition_version_ids.get(item.module_key) or "") or None
                        ),
                        creative_context={
                            **creative_context,
                            "selected_models": list((module_model_contexts.get(item.module_key) or {}).get("selected_models") or []),
                            "module_model_context": module_model_contexts.get(item.module_key) or {},
                        },
                    )
                    item.derived_from_output_id = None
                plan.planning_status = "ready"; plan.error_message = None
            else:
                item = affected[0]
                optimize_only = action == "optimize_prompt"
                result = parse_module_planning_result(text, item.module_key, optimize_only=optimize_only)
                definition = _module_definition(dict(version.category_skill_snapshot or {}), item.module_key)
                await add_module_version(
                    db, plan=plan, module=item,
                    action="ai_prompt_optimize" if optimize_only else "ai_module_replan",
                    user_id=job.created_by, rule_snapshot=definition, job=job,
                    plan_summary_cn=item.plan_summary_cn if optimize_only else result["plan_summary_cn"],
                    prompt_cn=result["prompt_cn"],
                    reference_understanding_id=str(understanding_ids.get(item.module_key) or "") or None,
                    product_composition_version_id=(
                        str(product_composition_version_ids.get(item.module_key) or "") or None
                    ),
                    creative_context={
                        **creative_context,
                        "selected_models": list((module_model_contexts.get(item.module_key) or {}).get("selected_models") or []),
                        "module_model_context": module_model_contexts.get(item.module_key) or {},
                    },
                )
                if not optimize_only:
                    item.derived_from_output_id = None
            for item in affected:
                item.status = "ready"; item.error_message = None; item.state_version += 1; item.last_saved_at = now
            plan.last_saved_at = now
        except AppError as error:
            if action == "suite_plan":
                plan.planning_status = "failed"; plan.error_message = error.message; plan.state_version += 1
            for item in affected:
                item.status = "failed"; item.error_message = error.message; item.state_version += 1


async def list_attachment_versions(
    db: AsyncSession, *, organization_id: str, plan_id: str, module_key: str | None,
) -> list[AttachmentWorkbenchPlanVersion]:
    statement = select(AttachmentWorkbenchPlanVersion).where(
        AttachmentWorkbenchPlanVersion.organization_id == organization_id,
        AttachmentWorkbenchPlanVersion.workbench_plan_id == plan_id,
    )
    if module_key:
        statement = statement.where(AttachmentWorkbenchPlanVersion.module_key == module_key)
    else:
        statement = statement.where(AttachmentWorkbenchPlanVersion.version_scope == "suite")
    return list((await db.scalars(statement.order_by(
        AttachmentWorkbenchPlanVersion.created_at.desc(),
        AttachmentWorkbenchPlanVersion.version_number.desc(),
    ))).all())
