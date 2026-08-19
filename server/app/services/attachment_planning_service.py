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
- plan_summary_cn回答“这张图准备做成什么样”，不要写成技术说明。
- prompt_cn不要机械复制整套视觉方向，要把方向转化为当前模块可执行的画面要求。"""

MODULE_REPLAN_SYSTEM_PROMPT = """你是亚马逊电商附图策划专家。只重新策划指定模块，必须继承当前整套视觉方向与商品真实性约束。
只返回有效 JSON：{"module_key":"指定模块编码","plan_summary_cn":"中文方案","prompt_cn":"完整中文执行提示词"}。
不得返回其他模块，不得解释，不得使用Markdown。提示词必须写明目标比例并针对该比例组织构图。"""

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
        "module_default_rule": str(definition.get("prompt_template") or ""),
        "product_context": product_context,
        "listing_context": _compact_listing(listing_snapshot),
        "aspect_ratio": aspect_ratio,
        "operator_requirement_cn": operator_requirement_cn.strip(),
        "truth_constraints": [
            "商品参考图是商品外观的最高优先级事实来源",
            "不得改变颜色、结构、版型、领口、袖口、Logo、文字、号码、图案、印花和定制内容",
            "不得新增未经确认的功能、材质、授权、认证或性能宣称",
        ],
    }


def build_suite_planning_input(
    *, version: ListingVersion, modules: list[AttachmentPlanningModuleInput], visual_direction_cn: str,
    current_modules: dict[str, AttachmentWorkbenchModulePlan] | None = None,
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
        "selected_modules": list(contexts.values()),
    }
    return SUITE_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False), contexts


def build_module_planning_input(
    *, version: ListingVersion, module: AttachmentWorkbenchModulePlan, visual_direction_cn: str,
    action: str,
) -> tuple[str, str, dict[str, object]]:
    context = build_attachment_module_context(
        module_key=module.module_key,
        analysis_snapshot=dict(version.analysis_snapshot or {}),
        listing_snapshot=dict(version.listing_snapshot or {}),
        skill_snapshot=dict(version.category_skill_snapshot or {}),
        aspect_ratio=module.aspect_ratio,
        operator_requirement_cn=module.operator_requirement_cn,
    )
    payload = {
        "visual_direction_cn": visual_direction_cn,
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
) -> AttachmentWorkbenchPlanVersion:
    previous = await _previous_version(db, plan.id, "suite", plan.visual_direction_version)
    number = plan.visual_direction_version + 1
    row = AttachmentWorkbenchPlanVersion(
        organization_id=plan.organization_id, workbench_plan_id=plan.id, version_scope="suite",
        version_number=number, action=action, visual_direction_cn=visual_direction_cn,
        selected_module_keys=selected, skill_version_id=plan.skill_version_id,
        skill_rule_snapshot={}, source_version_id=previous.id if previous else None,
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
) -> AttachmentWorkbenchPlanVersion:
    scope = f"module:{module.module_key}"
    previous = await _previous_version(db, plan.id, scope, module.current_version_number)
    number = module.current_version_number + 1
    row = AttachmentWorkbenchPlanVersion(
        organization_id=plan.organization_id, workbench_plan_id=plan.id, module_plan_id=module.id,
        version_scope=scope, module_key=module.module_key, version_number=number, action=action,
        plan_summary_cn=plan_summary_cn, prompt_cn=prompt_cn,
        operator_requirement_cn=module.operator_requirement_cn, aspect_ratio=module.aspect_ratio,
        selected_module_keys=[module.module_key], skill_version_id=plan.skill_version_id,
        skill_rule_snapshot=rule_snapshot, source_version_id=previous.id if previous else None,
        ai_job_id=job.id if job else None, ai_model=job.model_code if job else None, created_by=user_id,
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
    selected_keys = [item.module_key for item in modules]
    invalid = sorted(set(selected_keys) - set(STANDARD_MODULE_CODES))
    if invalid:
        raise AppError("attachment_planning.module_invalid", "选择了不支持的附图模块", 422, {"invalid": invalid})
    indexed = {item.module_key: item for item in module_rows}
    system_prompt, user_prompt, _ = build_suite_planning_input(
        version=version, modules=modules, visual_direction_cn=visual_direction_cn,
        current_modules=indexed,
    )
    target_plan_version = plan.state_version + 1
    target_module_versions = {key: indexed[key].state_version + 1 for key in selected_keys}
    model_code = await resolve_bound_model_code(
        db, organization_id=project.organization_id, operation_code="listing.plan", capability="text_generation",
    )
    references = [session.primary_asset_id] if session.primary_asset_id else list(session.source_asset_ids or [])[:1]
    job, created = await submit_job(db, settings, organization_id=project.organization_id, user_id=user_id, payload=JobSubmitRequest(
        operation_code="listing.plan", workspace_type="listing", queue_name="planning_queue",
        capability="text_generation", model_code=model_code, idempotency_key=idempotency_key,
        project_id=session.project_id,
        input={"system_prompt": system_prompt, "user_prompt": user_prompt, "temperature": 0.2,
               "response_format": "json_object", "reference_asset_ids": references,
               "metadata": {"workflow": "attachment_workbench_planning", "action": "suite_plan",
                            "planning_id": plan.id, "selected_modules": selected_keys,
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
    module.aspect_ratio = aspect_ratio
    module.operator_requirement_cn = operator_requirement_cn
    system_prompt, user_prompt, _ = build_module_planning_input(
        version=version, module=module, visual_direction_cn=plan.visual_direction_cn, action=action,
    )
    target_module_version = module.state_version + 1
    model_code = await resolve_bound_model_code(
        db, organization_id=project.organization_id, operation_code="listing.plan", capability="text_generation",
    )
    references = [session.primary_asset_id] if session.primary_asset_id else list(session.source_asset_ids or [])[:1]
    job, created = await submit_job(db, settings, organization_id=project.organization_id, user_id=user_id, payload=JobSubmitRequest(
        operation_code="listing.plan", workspace_type="listing", queue_name="planning_queue",
        capability="text_generation", model_code=model_code, idempotency_key=idempotency_key,
        project_id=session.project_id,
        input={"system_prompt": system_prompt, "user_prompt": user_prompt, "temperature": 0.2,
               "response_format": "json_object", "reference_asset_ids": references,
               "metadata": {"workflow": "attachment_workbench_planning", "action": action,
                            "planning_id": plan.id, "module_key": module.module_key,
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
        stale = plan.state_version != expected_plan or any(
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
                )
                for item in affected:
                    definition = _module_definition(dict(version.category_skill_snapshot or {}), item.module_key)
                    result = result_modules[item.module_key]
                    await add_module_version(
                        db, plan=plan, module=item, action="ai_suite_plan", user_id=job.created_by,
                        rule_snapshot=definition, job=job, plan_summary_cn=result["plan_summary_cn"],
                        prompt_cn=result["prompt_cn"],
                    )
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
                )
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
    scope = f"module:{module_key}" if module_key else "suite"
    return list((await db.scalars(statement.where(
        AttachmentWorkbenchPlanVersion.version_scope == scope,
    ).order_by(AttachmentWorkbenchPlanVersion.version_number.desc()))).all())
