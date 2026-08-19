from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.attachment_planning import (
    AttachmentReferenceUnderstanding,
    AttachmentWorkbenchModulePlan,
    AttachmentWorkbenchPlan,
    AttachmentWorkbenchPlanVersion,
)
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject, ListingVersion
from app.models.tasks import Job, JobBatch
from app.schemas.tasks import BatchJobItemRequest, JobBatchSubmitRequest
from app.services.attachment_planning_service import STANDARD_MODULE_CODES
from app.services.attachment_reference_service import effective_reference_snapshot, latest_reference_understanding
from app.services.category_listing_service import resolve_bound_model_code
from app.services.listing_image_task_group_service import build_input_asset_snapshot, create_group_for_batch
from app.services.resource_pool_service import validate_operation_binding
from app.services.task_service import submit_batch


REFERENCE_ROLE_ORDER = ("PRODUCT", "PRINT", "TEMPLATE", "SCENE", "OTHER")
MODULE_NAMES = {
    "pure_white": "纯白底图",
    "custom_process": "定制流程图",
    "stadium_scene": "观赛场景图",
    "gift_scene": "礼品场景图",
    "detail_display": "细节展示图",
    "casual_scene": "休闲场景图",
}
DELIVERY_SIZES = {
    "1:1": (2048, 2048),
    "4:5": (1536, 1920),
    "3:4": (1536, 2048),
}


@dataclass(frozen=True)
class AttachmentGenerationModule:
    module_key: str
    module_name: str
    aspect_ratio: str
    image_count: int
    generation_mode: str
    width: int
    height: int
    plan_version: AttachmentWorkbenchPlanVersion
    understanding: AttachmentReferenceUnderstanding
    grouped_references: dict[str, list[str]]
    reference_snapshot: dict[str, object]
    execution_prompt: str


@dataclass(frozen=True)
class AttachmentGenerationPreview:
    model_code: str
    modules: list[AttachmentGenerationModule]
    snapshot_signature: str

    @property
    def total_images(self) -> int:
        return sum(item.image_count for item in self.modules)


def _attachment_config(project: ListingImageProject) -> dict[str, object]:
    value = (project.prompt_config or {}).get("attachment_workbench")
    return value if isinstance(value, dict) else {}


def _module_draft(project: ListingImageProject, module_key: str) -> dict[str, object]:
    modules = _attachment_config(project).get("modules")
    modules = modules if isinstance(modules, dict) else {}
    value = modules.get(module_key)
    return value if isinstance(value, dict) else {}


def _flatten_references(grouped: dict[str, list[str]]) -> list[str]:
    return list(dict.fromkeys(
        asset_id
        for role in REFERENCE_ROLE_ORDER
        for asset_id in grouped.get(role, [])
    ))


def _reference_index(grouped: dict[str, list[str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for role in REFERENCE_ROLE_ORDER:
        for asset_id in grouped.get(role, []):
            rows.append({"image_index": len(rows) + 1, "role": role, "asset_id": asset_id})
    return rows


def build_attachment_execution_prompt(
    *, module: AttachmentWorkbenchModulePlan, plan: AttachmentWorkbenchPlan,
    version: AttachmentWorkbenchPlanVersion, understanding: AttachmentReferenceUnderstanding,
    grouped_references: dict[str, list[str]], aspect_ratio: str,
) -> str:
    role_rows = _reference_index(grouped_references)
    role_lines = "\n".join(
        f"- Image {item['image_index']} = {item['role']} reference"
        for item in role_rows
    )
    understanding_text = json.dumps(understanding.structured_json or {}, ensure_ascii=False, separators=(",", ":"))
    return f"""Create one production-ready Amazon listing image for module: {MODULE_NAMES.get(module.module_key, module.module_key)}.

REFERENCE ORDER (must follow exactly):
{role_lines}

ROLE RULES:
- PRODUCT is the sole source of truth for product identity, colors, structure, logos, text, numbers and construction details.
- PRINT is a high-fidelity reference for typography, numbers and artwork only; it must not replace the product structure.
- TEMPLATE controls composition and layout only; never inherit the template's old product design.
- SCENE controls environment, atmosphere and lighting only.
- OTHER is supplemental and never overrides PRODUCT.

GLOBAL VISUAL DIRECTION:
{plan.visual_direction_cn.strip()}

CURRENT MODULE PLAN:
{version.plan_summary_cn or module.plan_summary_cn}

CURRENT FINAL MODULE PROMPT:
{version.prompt_cn or module.prompt_cn}

VALIDATED REFERENCE UNDERSTANDING:
{understanding_text}

OUTPUT CONTRACT:
- Generate exactly one standalone image, not a collage of alternatives.
- Required aspect ratio: {aspect_ratio}.
- Preserve product truth over all stylistic references.
- Do not include analysis, explanations, borders, watermarks or unrelated content.
""".strip()


def _supported_ratios(model_config: dict[str, object]) -> set[str]:
    values = model_config.get("supported_edit_aspect_ratios")
    supported = {str(item) for item in values} if isinstance(values, list) else set()
    verified = model_config.get("verified_edit_output_sizes")
    if isinstance(verified, dict):
        supported.update(str(item) for item in verified)
    return supported


async def build_attachment_generation_preview(
    db: AsyncSession, *, project: ListingImageProject, session: ListingGenerationSession,
    version: ListingVersion, plan: AttachmentWorkbenchPlan,
    modules: list[AttachmentWorkbenchModulePlan], selected_module_keys: list[str],
) -> AttachmentGenerationPreview:
    selected = list(dict.fromkeys(selected_module_keys))
    if not selected:
        raise AppError("attachment_generation.modules_required", "请至少选择一个附图模块", 422)
    invalid = sorted(set(selected) - set(STANDARD_MODULE_CODES))
    if invalid:
        raise AppError("attachment_generation.module_invalid", "选择了不支持的附图模块", 422, {"invalid": invalid})

    model_code = await resolve_bound_model_code(
        db, organization_id=project.organization_id,
        operation_code="listing.generate", capability="image_edit",
    )
    model = await validate_operation_binding(
        db, organization_id=project.organization_id,
        operation_code="listing.generate", model_code=model_code, capability="image_edit",
    )
    supported_ratios = _supported_ratios(dict(model.config_json or {}))
    indexed = {item.module_key: item for item in modules}
    prepared: list[AttachmentGenerationModule] = []

    for module_key in selected:
        module = indexed[module_key]
        draft = _module_draft(project, module_key)
        mode = str(draft.get("generationMode") or "standard")
        if mode != "standard":
            raise AppError("attachment_generation.mode_unsupported", "Phase 4 仅支持标准生成模式", 422)
        try:
            image_count = int(draft.get("imageCount") or 1)
        except (TypeError, ValueError) as error:
            raise AppError("attachment_generation.count_invalid", "生成数量必须为1到4张", 422) from error
        if image_count < 1 or image_count > 4:
            raise AppError("attachment_generation.count_invalid", "生成数量必须为1到4张", 422)
        aspect_ratio = str(draft.get("aspectRatio") or module.aspect_ratio)
        if aspect_ratio not in DELIVERY_SIZES:
            raise AppError("attachment_generation.aspect_ratio_invalid", "当前附图比例无效", 422)
        if aspect_ratio not in supported_ratios:
            raise AppError(
                "attachment_generation.aspect_ratio_not_verified",
                f"当前图片模型尚未验证 {aspect_ratio} 比例，请在模型能力测试通过后再生成",
                422,
                {"aspect_ratio": aspect_ratio, "model_code": model_code},
            )
        if module.current_version_number < 1 or not module.plan_summary_cn.strip() or not module.prompt_cn.strip():
            raise AppError("attachment_generation.prompt_required", f"请先完成{MODULE_NAMES[module_key]}的方案和Prompt", 409)
        plan_version = await db.scalar(select(AttachmentWorkbenchPlanVersion).where(
            AttachmentWorkbenchPlanVersion.module_plan_id == module.id,
            AttachmentWorkbenchPlanVersion.version_number == module.current_version_number,
        ))
        if plan_version is None:
            raise AppError("attachment_generation.version_missing", f"{MODULE_NAMES[module_key]}当前版本不存在，请重新保存", 409)
        if module.reference_context_dirty:
            raise AppError("attachment_generation.reference_stale", f"{MODULE_NAMES[module_key]}参考素材已变化，请重新分析", 409)
        understanding = await latest_reference_understanding(db, module.id, ready_only=True)
        if understanding is None:
            raise AppError("attachment_generation.reference_analysis_required", f"请先完成{MODULE_NAMES[module_key]}参考素材分析", 409)
        grouped, reference_snapshot = await effective_reference_snapshot(db, plan=plan, module=module)
        if not grouped.get("PRODUCT"):
            raise AppError("attachment_generation.product_required", f"{MODULE_NAMES[module_key]}缺少商品参考图", 409)
        if reference_snapshot.get("roles") != (understanding.source_snapshot_json or {}).get("roles"):
            raise AppError("attachment_generation.reference_stale", f"{MODULE_NAMES[module_key]}参考素材与分析版本不一致，请重新分析", 409)
        width, height = DELIVERY_SIZES[aspect_ratio]
        prepared.append(AttachmentGenerationModule(
            module_key=module_key, module_name=MODULE_NAMES[module_key], aspect_ratio=aspect_ratio,
            image_count=image_count, generation_mode=mode, width=width, height=height,
            plan_version=plan_version, understanding=understanding,
            grouped_references=grouped, reference_snapshot=reference_snapshot,
            execution_prompt=build_attachment_execution_prompt(
                module=module, plan=plan, version=plan_version, understanding=understanding,
                grouped_references=grouped, aspect_ratio=aspect_ratio,
            ),
        ))

    signature_payload = {
        "project_id": project.id,
        "listing_version_id": version.id,
        "skill_version_id": plan.skill_version_id,
        "visual_direction_version": plan.visual_direction_version,
        "modules": [{
            "module_key": item.module_key,
            "aspect_ratio": item.aspect_ratio,
            "image_count": item.image_count,
            "generation_mode": item.generation_mode,
            "plan_version_id": item.plan_version.id,
            "prompt_version_id": item.plan_version.id,
            "reference_understanding_id": item.understanding.id,
            "reference_snapshot": item.reference_snapshot,
        } for item in prepared],
    }
    signature = hashlib.sha256(json.dumps(
        signature_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return AttachmentGenerationPreview(model_code=model_code, modules=prepared, snapshot_signature=signature)


async def create_attachment_generation(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject,
    session: ListingGenerationSession, version: ListingVersion, plan: AttachmentWorkbenchPlan,
    modules: list[AttachmentWorkbenchModulePlan], selected_module_keys: list[str],
    snapshot_signature: str, idempotency_key: str, user_id: str,
) -> tuple[AttachmentGenerationPreview, JobBatch, list[Job], object, bool]:
    preview = await build_attachment_generation_preview(
        db, project=project, session=session, version=version, plan=plan,
        modules=modules, selected_module_keys=selected_module_keys,
    )
    if snapshot_signature != preview.snapshot_signature:
        raise AppError("attachment_generation.snapshot_changed", "确认期间方案、Prompt、比例或参考素材已变化，请重新确认", 409)

    items: list[BatchJobItemRequest] = []
    for module in preview.modules:
        reference_ids = _flatten_references(module.grouped_references)
        for slot_index in range(1, module.image_count + 1):
            items.append(BatchJobItemRequest(
                client_item_id=f"attachment:{module.module_key}:{slot_index}:{idempotency_key[-12:]}",
                prompt=module.execution_prompt, reference_asset_ids=reference_ids,
                size=f"{module.width}x{module.height}", aspect_ratio=module.aspect_ratio,
                requested_width=module.width, requested_height=module.height,
                quality="high", output_format="png",
                metadata={
                    "workflow": "attachment_workbench_generation",
                    "output_project_id": project.id,
                    "listing_session_id": session.id,
                    "listing_version_id": version.id,
                    "listing_version_number": version.version_number,
                    "skill_version_id": plan.skill_version_id,
                    "item_code": module.module_key,
                    "module_name": module.module_name,
                    "slot_index": slot_index,
                    "generation_mode": module.generation_mode,
                    "plan_version_id": module.plan_version.id,
                    "plan_version_number": module.plan_version.version_number,
                    "prompt_version_id": module.plan_version.id,
                    "prompt_version_number": module.plan_version.version_number,
                    "reference_understanding_id": module.understanding.id,
                    "reference_understanding_version": module.understanding.version_number,
                    "reference_snapshot": module.reference_snapshot,
                    "effective_prompt_snapshot": module.execution_prompt,
                    "requested_aspect_ratio": module.aspect_ratio,
                    "requested_width": module.width,
                    "requested_height": module.height,
                },
            ))
    batch, jobs, created = await submit_batch(
        db, settings, organization_id=project.organization_id, user_id=user_id,
        payload=JobBatchSubmitRequest(
            name=f"附图正式生成 · {len(preview.modules)}个模块 · {preview.total_images}张",
            workspace_type="listing", operation_code="listing.generate", capability="image_edit",
            model_code=preview.model_code, idempotency_key=idempotency_key,
            project_id=session.project_id, concurrency=min(12, preview.total_images), items=items,
        ),
    )

    product_ids = list(dict.fromkeys(
        asset_id for item in preview.modules for asset_id in item.grouped_references.get("PRODUCT", [])
    ))
    template_ids = list(dict.fromkeys(
        asset_id for item in preview.modules for asset_id in item.grouped_references.get("TEMPLATE", [])
    ))
    reference_ids = list(dict.fromkeys(
        asset_id for item in preview.modules for role in ("PRINT", "SCENE", "OTHER")
        for asset_id in item.grouped_references.get(role, [])
    ))
    snapshot = await build_input_asset_snapshot(
        db, organization_id=project.organization_id, product_asset_ids=product_ids,
        reference_asset_ids=reference_ids, template_asset_ids=template_ids,
        primary_asset_id=session.primary_asset_id,
    )
    snapshot["workflow"] = "attachment_workbench_generation"
    snapshot["snapshot_signature"] = preview.snapshot_signature
    snapshot["modules"] = [{
        "module_key": item.module_key,
        "module_name": item.module_name,
        "aspect_ratio": item.aspect_ratio,
        "image_count": item.image_count,
        "generation_mode": item.generation_mode,
        "plan_version_id": item.plan_version.id,
        "prompt_version_id": item.plan_version.id,
        "reference_understanding_id": item.understanding.id,
        "reference_snapshot": item.reference_snapshot,
    } for item in preview.modules]
    group = await create_group_for_batch(
        db, project=project, batch=batch, version=version,
        selected_image_types=[item.module_key for item in preview.modules],
        product_asset_ids=product_ids, reference_asset_ids=reference_ids,
        template_asset_ids=template_ids, input_asset_snapshot=snapshot, user_id=user_id,
    )
    group.group_name = f"附图正式生成任务组 #{group.group_number}"
    for job in jobs:
        metadata = job.input_json.get("metadata")
        job.input_json = {
            **job.input_json,
            "metadata": {
                **(metadata if isinstance(metadata, dict) else {}),
                "listing_image_task_group_id": group.id,
            },
        }
    project.last_batch_id = batch.id
    project.status = "generating"
    project.task_count = int(project.task_count or 0) + (len(jobs) if created else 0)
    project.updated_by = user_id
    await db.flush()
    return preview, batch, jobs, group, created
