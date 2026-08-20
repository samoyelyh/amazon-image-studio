from __future__ import annotations

import json
import re

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
from app.schemas.attachment_planning import AttachmentCreativeDirectionResponse, AttachmentCreativePlanningResponse
from app.schemas.tasks import JobSubmitRequest
from app.services.attachment_planning_service import attachment_module_rule, build_attachment_module_context
from app.services.attachment_reference_service import effective_reference_snapshot, latest_reference_understanding
from app.services.category_listing_service import resolve_bound_model_code
from app.services.task_service import submit_job


CREATIVE_SYSTEM_PROMPT = """你是亚马逊电商附图创意策划专家。一次为请求中的每个模块生成指定数量、彼此明显不同的创意方向。

只返回一个有效JSON对象，不要Markdown，不要解释：
{"modules":[{"module_key":"模块编码","directions":[{"direction_index":1,"plan_summary_cn":"中文画面方案","prompt_cn":"完整中文生图提示词"}]}]}

硬性要求：
- 模块和方向数量必须与输入完全一致，direction_index从1连续编号。
- 同一模块的方向必须在构图、镜头、人物关系、环境设计、展示方式或氛围上有可观察差异，禁止只替换近义词。
- PRODUCT永远是商品身份、颜色、结构、Logo、文字、号码、图案和印花的最高优先级事实来源。
- PRINT仅约束字形、号码和印花，不得改变商品结构。
- TEMPLATE仅约束版式；SCENE仅约束环境；都不得覆盖PRODUCT。
- 模块业务目标、当前比例、定制信息和真实性规则是硬约束。
- 整套视觉方向只作弱参考，可以探索不同风格，不得让它抹掉创意差异。
- 多商品时可以探索人物站位和互动，但Model A/B/C必须与PRIMARY/SECONDARY逐一对应，商品颜色、结构、Logo、印花、文字和号码禁止串位，PRIMARY必须视觉优先。
- prompt_cn必须是一张独立成图的完整执行提示词，不得包含分析过程。"""


def _config(project: ListingImageProject) -> dict[str, object]:
    value = (project.prompt_config or {}).get("attachment_workbench")
    return value if isinstance(value, dict) else {}


def _draft(project: ListingImageProject, module_key: str) -> dict[str, object]:
    modules = _config(project).get("modules")
    modules = modules if isinstance(modules, dict) else {}
    value = modules.get(module_key)
    return value if isinstance(value, dict) else {}


def _result_text(job: Job) -> str:
    metadata = job.result_json.get("metadata") if isinstance(job.result_json, dict) else None
    return str(metadata.get("text") or "") if isinstance(metadata, dict) else ""


def _json_object(text: str) -> dict[str, object]:
    value = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        value = fenced.group(1)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise AppError("attachment_creative.ai_result_invalid", "创意方向策划结果不是有效JSON", 422) from error
        try:
            parsed = json.loads(value[start:end + 1])
        except json.JSONDecodeError as nested:
            raise AppError("attachment_creative.ai_result_invalid", "创意方向策划结果不是有效JSON", 422) from nested
    if not isinstance(parsed, dict):
        raise AppError("attachment_creative.ai_result_invalid", "创意方向策划结果必须是JSON对象", 422)
    return parsed


def parse_creative_directions(
    text: str, expected: dict[str, int],
) -> dict[str, list[dict[str, object]]]:
    payload = _json_object(text)
    raw_modules = payload.get("modules")
    if not isinstance(raw_modules, list):
        raise AppError("attachment_creative.ai_result_invalid", "创意方向策划缺少模块结果", 422)
    parsed: dict[str, list[dict[str, object]]] = {}
    for raw_module in raw_modules:
        if not isinstance(raw_module, dict):
            continue
        module_key = str(raw_module.get("module_key") or "")
        raw_directions = raw_module.get("directions")
        if module_key in parsed or module_key not in expected or not isinstance(raw_directions, list):
            raise AppError("attachment_creative.ai_result_invalid", "创意方向模块重复或无效", 422)
        directions: list[dict[str, object]] = []
        for raw in raw_directions:
            if not isinstance(raw, dict):
                continue
            index = int(raw.get("direction_index") or 0)
            plan = str(raw.get("plan_summary_cn") or "").strip()
            prompt = str(raw.get("prompt_cn") or "").strip()
            if index != len(directions) + 1 or not plan or not prompt:
                raise AppError("attachment_creative.ai_result_invalid", "创意方向编号或内容不完整", 422)
            directions.append({"direction_index": index, "plan_summary_cn": plan, "prompt_cn": prompt})
        if len(directions) != expected[module_key]:
            raise AppError("attachment_creative.direction_count_mismatch", "AI返回的创意方向数量与请求不一致", 422)
        normalized_plans = {" ".join(str(item["plan_summary_cn"]).lower().split()) for item in directions}
        normalized_prompts = {" ".join(str(item["prompt_cn"]).lower().split()) for item in directions}
        if len(normalized_plans) != len(directions) or len(normalized_prompts) != len(directions):
            raise AppError("attachment_creative.directions_not_distinct", "AI返回了重复创意方向，请重新策划", 422)
        parsed[module_key] = directions
    if set(parsed) != set(expected):
        raise AppError("attachment_creative.module_result_mismatch", "AI返回的创意模块与请求不一致", 422)
    return parsed


async def start_creative_planning(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject,
    session: ListingGenerationSession, version: ListingVersion, plan: AttachmentWorkbenchPlan,
    modules: list[AttachmentWorkbenchModulePlan], selected_module_keys: list[str],
    idempotency_key: str, user_id: str,
) -> tuple[Job, bool]:
    selected = list(dict.fromkeys(selected_module_keys))
    indexed = {item.module_key: item for item in modules}
    if not selected or any(key not in indexed for key in selected):
        raise AppError("attachment_creative.modules_required", "请至少选择一个支持创意生成的模块", 422)

    contexts: list[dict[str, object]] = []
    reference_ids: list[str] = []
    metadata_modules: list[dict[str, object]] = []
    for module_key in selected:
        module = indexed[module_key]
        rule = attachment_module_rule(dict(version.category_skill_snapshot or {}), module_key)
        if not bool(rule.get("supports_creative")):
            raise AppError("attachment_creative.not_supported", f"{rule.get('name') or module_key}不支持创意生成", 422)
        draft = _draft(project, module_key)
        if str(draft.get("generationMode") or "standard") != "creative":
            raise AppError("attachment_creative.mode_mismatch", "模块当前不是创意生成模式，请刷新后重试", 409)
        try:
            count = int(draft.get("imageCount") or 1)
        except (TypeError, ValueError) as error:
            raise AppError("attachment_creative.count_invalid", "创意方向数量必须为1到4个", 422) from error
        if count < 1 or count > 4:
            raise AppError("attachment_creative.count_invalid", "创意方向数量必须为1到4个", 422)
        if module.reference_context_dirty:
            raise AppError("attachment_creative.reference_stale", f"{rule.get('name') or module_key}参考素材已变化，请重新分析", 409)
        understanding = await latest_reference_understanding(db, module.id, ready_only=True)
        if understanding is None:
            raise AppError("attachment_creative.reference_analysis_required", f"请先完成{rule.get('name') or module_key}参考素材分析", 409)
        grouped, reference_snapshot = await effective_reference_snapshot(db, plan=plan, module=module)
        if not grouped.get("PRODUCT"):
            raise AppError("attachment_creative.product_required", f"{rule.get('name') or module_key}缺少商品参考图", 409)
        if reference_snapshot.get("roles") != (understanding.source_snapshot_json or {}).get("roles"):
            raise AppError("attachment_creative.reference_stale", f"{rule.get('name') or module_key}参考素材与分析版本不一致", 409)
        if reference_snapshot.get("product_composition_version_id") != understanding.product_composition_version_id:
            raise AppError("attachment_creative.composition_stale", f"{rule.get('name') or module_key}商品组合已更新，请重新分析", 409)
        ratio = str(draft.get("aspectRatio") or module.aspect_ratio)
        context = build_attachment_module_context(
            module_key=module_key,
            analysis_snapshot=dict(version.analysis_snapshot or {}),
            listing_snapshot=dict(version.listing_snapshot or {}),
            skill_snapshot=dict(version.category_skill_snapshot or {}),
            aspect_ratio=ratio,
            operator_requirement_cn=module.operator_requirement_cn,
            reference_understanding=dict(understanding.structured_json or {}),
            product_composition={
                "mode": reference_snapshot.get("product_mode"),
                "product_count": reference_snapshot.get("product_count"),
                "model_count": reference_snapshot.get("model_count"),
                "products": reference_snapshot.get("products", []),
            },
        )
        context["direction_count"] = count
        context["visual_direction_soft_context"] = plan.visual_direction_cn
        contexts.append(context)
        ordered = reference_snapshot.get("execution_order")
        if isinstance(ordered, list):
            reference_ids.extend(
                str(row.get("asset_id")) for row in ordered
                if isinstance(row, dict) and row.get("asset_id")
            )
        else:
            for role in ("PRODUCT", "PRINT", "TEMPLATE", "SCENE", "OTHER"):
                reference_ids.extend(grouped.get(role, []))
        source_version = await db.scalar(select(AttachmentWorkbenchPlanVersion).where(
            AttachmentWorkbenchPlanVersion.module_plan_id == module.id,
            AttachmentWorkbenchPlanVersion.version_number == module.current_version_number,
            AttachmentWorkbenchPlanVersion.version_scope == f"module:{module_key}",
        )) if module.current_version_number else None
        metadata_modules.append({
            "module_key": module_key,
            "direction_count": count,
            "aspect_ratio": ratio,
            "module_state_version": module.state_version,
            "reference_state_version": module.reference_state_version,
            "reference_understanding_id": understanding.id,
            "product_composition_version_id": reference_snapshot.get("product_composition_version_id"),
            "source_version_id": source_version.id if source_version else None,
            "operator_requirement_cn": module.operator_requirement_cn,
            "rule_snapshot": rule,
        })

    model_code = await resolve_bound_model_code(
        db, organization_id=project.organization_id,
        operation_code="listing.plan", capability="text_generation",
    )
    user_prompt = json.dumps({
        "project_id": project.id,
        "skill": {
            "name": (version.category_skill_snapshot or {}).get("skill_name"),
            "version": (version.category_skill_snapshot or {}).get("skill_version"),
        },
        "modules": contexts,
    }, ensure_ascii=False)
    job, created = await submit_job(
        db, settings, organization_id=project.organization_id, user_id=user_id,
        payload=JobSubmitRequest(
            operation_code="listing.plan", workspace_type="listing", queue_name="planning_queue",
            capability="text_generation", model_code=model_code, idempotency_key=idempotency_key,
            project_id=session.project_id,
            input={
                "system_prompt": CREATIVE_SYSTEM_PROMPT,
                "user_prompt": user_prompt,
                "temperature": 0.65,
                "response_format": "json_object",
                "reference_asset_ids": list(dict.fromkeys(reference_ids)),
                "metadata": {
                    "workflow": "attachment_workbench_creative_planning",
                    "project_id": project.id,
                    "planning_id": plan.id,
                    "modules": metadata_modules,
                },
            },
            billing_factors={"quality": "standard", "resolution": "text"},
            client_item_id="attachment-creative-directions",
        ),
    )
    return job, created


async def creative_planning_response(
    db: AsyncSession, *, project: ListingImageProject, plan: AttachmentWorkbenchPlan,
    modules: list[AttachmentWorkbenchModulePlan], planning_job_id: str,
) -> AttachmentCreativePlanningResponse:
    job = await db.scalar(select(Job).where(
        Job.id == planning_job_id,
        Job.organization_id == project.organization_id,
    ).with_for_update())
    if job is None:
        raise AppError("attachment_creative.planning_not_found", "创意方向策划任务不存在或无权访问", 404)
    metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    if (
        metadata.get("workflow") != "attachment_workbench_creative_planning"
        or metadata.get("project_id") != project.id
        or metadata.get("planning_id") != plan.id
    ):
        raise AppError("attachment_creative.planning_invalid", "该任务不属于当前附图项目", 422)

    existing = list((await db.scalars(select(AttachmentWorkbenchPlanVersion).where(
        AttachmentWorkbenchPlanVersion.organization_id == project.organization_id,
        AttachmentWorkbenchPlanVersion.ai_job_id == job.id,
        AttachmentWorkbenchPlanVersion.generation_mode == "creative",
    ).order_by(AttachmentWorkbenchPlanVersion.module_key, AttachmentWorkbenchPlanVersion.creative_direction_index))).all())
    if existing:
        return AttachmentCreativePlanningResponse(
            project_id=project.id, planning_job_id=job.id, status="ready",
            directions=[AttachmentCreativeDirectionResponse(
                plan_version_id=row.id, module_key=str(row.module_key or ""),
                direction_index=int(row.creative_direction_index or 0),
                plan_summary_cn=str(row.plan_summary_cn or ""), prompt_cn=str(row.prompt_cn or ""),
                aspect_ratio=str(row.aspect_ratio or "1:1"),
            ) for row in existing],
        )
    if job.status in {"failed", "cancelled"}:
        return AttachmentCreativePlanningResponse(
            project_id=project.id, planning_job_id=job.id, status=job.status,
            error_message=job.error_message or "创意方向策划失败",
        )
    if job.status != "succeeded":
        return AttachmentCreativePlanningResponse(
            project_id=project.id, planning_job_id=job.id,
            status="running" if job.status in {"running", "dispatching"} else "queued",
        )

    requested = metadata.get("modules")
    requested = requested if isinstance(requested, list) else []
    indexed = {item.module_key: item for item in modules}
    for item in requested:
        if not isinstance(item, dict):
            continue
        module = indexed.get(str(item.get("module_key") or ""))
        if module is None or module.state_version != int(item.get("module_state_version") or -1) \
                or module.reference_state_version != int(item.get("reference_state_version") or -1):
            return AttachmentCreativePlanningResponse(
                project_id=project.id, planning_job_id=job.id, status="stale",
                error_message="创意策划期间模块方案或参考素材已变化，请重新生成创意方向。",
            )
    parse_error = None
    result_metadata = job.result_json.get("metadata") if isinstance(job.result_json, dict) else None
    if isinstance(result_metadata, dict):
        parse_error = str(result_metadata.get("creative_parse_error") or "") or None
    if parse_error:
        return AttachmentCreativePlanningResponse(
            project_id=project.id, planning_job_id=job.id, status="failed", error_message=parse_error,
        )
    expected = {
        str(item.get("module_key")): int(item.get("direction_count") or 0)
        for item in requested if isinstance(item, dict)
    }
    try:
        parsed = parse_creative_directions(_result_text(job), expected)
    except AppError as error:
        result_json = dict(job.result_json or {})
        result_meta = dict(result_json.get("metadata") or {})
        result_meta["creative_parse_error"] = error.message
        job.result_json = {**result_json, "metadata": result_meta}
        await db.flush()
        return AttachmentCreativePlanningResponse(
            project_id=project.id, planning_job_id=job.id, status="failed", error_message=error.message,
        )

    rows: list[AttachmentWorkbenchPlanVersion] = []
    requested_index = {str(item.get("module_key")): item for item in requested if isinstance(item, dict)}
    for module_key, directions in parsed.items():
        module = indexed[module_key]
        item = requested_index[module_key]
        for direction in directions:
            row = AttachmentWorkbenchPlanVersion(
                organization_id=project.organization_id,
                workbench_plan_id=plan.id,
                module_plan_id=module.id,
                version_scope=f"creative:{module_key}:{job.id}",
                module_key=module_key,
                version_number=int(direction["direction_index"]),
                action="ai_creative_plan",
                generation_mode="creative",
                creative_direction_index=int(direction["direction_index"]),
                plan_summary_cn=str(direction["plan_summary_cn"]),
                prompt_cn=str(direction["prompt_cn"]),
                operator_requirement_cn=str(item.get("operator_requirement_cn") or ""),
                aspect_ratio=str(item.get("aspect_ratio") or module.aspect_ratio),
                selected_module_keys=[module_key],
                skill_version_id=plan.skill_version_id,
                skill_rule_snapshot=dict(item.get("rule_snapshot") or {}),
                source_version_id=str(item.get("source_version_id") or "") or None,
                ai_job_id=job.id,
                ai_model=job.model_code,
                reference_understanding_id=str(item.get("reference_understanding_id") or "") or None,
                product_composition_version_id=(
                    str(item.get("product_composition_version_id") or "") or None
                ),
                created_by=job.created_by,
            )
            db.add(row)
            rows.append(row)
    await db.flush()
    return AttachmentCreativePlanningResponse(
        project_id=project.id, planning_job_id=job.id, status="ready",
        directions=[AttachmentCreativeDirectionResponse(
            plan_version_id=row.id, module_key=str(row.module_key or ""),
            direction_index=int(row.creative_direction_index or 0),
            plan_summary_cn=str(row.plan_summary_cn or ""), prompt_cn=str(row.prompt_cn or ""),
            aspect_ratio=str(row.aspect_ratio or "1:1"),
        ) for row in rows],
    )
