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
from app.services.attachment_planning_service import STANDARD_MODULE_CODES, attachment_module_rule
from app.services.attachment_reference_service import effective_reference_snapshot, latest_reference_understanding
from app.services.category_listing_service import resolve_bound_model_code
from app.services.listing_image_task_group_service import build_input_asset_snapshot, create_group_for_batch
from app.services.resource_pool_service import validate_operation_binding
from app.services.task_service import submit_batch


REFERENCE_ROLE_ORDER = ("PRODUCT", "PRINT", "MODEL", "TEMPLATE", "SCENE", "OTHER")
MAX_PROVIDER_REFERENCES = 10
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
class AttachmentGenerationDirection:
    slot_index: int
    plan_version: AttachmentWorkbenchPlanVersion
    execution_prompt: str
    creative_direction_index: int | None = None


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
    directions: list[AttachmentGenerationDirection]


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


def _flatten_references(
    grouped: dict[str, list[str]], reference_snapshot: dict[str, object] | None = None,
) -> list[str]:
    ordered = (reference_snapshot or {}).get("execution_order")
    if isinstance(ordered, list):
        return list(dict.fromkeys(
            str(item.get("asset_id")) for item in ordered
            if isinstance(item, dict) and item.get("asset_id")
        ))
    return list(dict.fromkeys(
        asset_id
        for role in REFERENCE_ROLE_ORDER
        for asset_id in grouped.get(role, [])
    ))


def _reference_index(
    grouped: dict[str, list[str]], reference_snapshot: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    ordered = (reference_snapshot or {}).get("execution_order")
    if isinstance(ordered, list) and ordered:
        return [dict(item) for item in ordered if isinstance(item, dict)]
    rows: list[dict[str, object]] = []
    for role in REFERENCE_ROLE_ORDER:
        for asset_id in grouped.get(role, []):
            rows.append({"image_index": len(rows) + 1, "role": role, "asset_id": asset_id})
    return rows


async def resolve_attachment_generation_references(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan, module: AttachmentWorkbenchModulePlan,
    plan_version: AttachmentWorkbenchPlanVersion, supports_model: bool,
) -> tuple[dict[str, list[str]], dict[str, object], list[str]]:
    """Resolve the exact provider input order on the server and freeze it in the snapshot."""
    grouped, snapshot = await effective_reference_snapshot(db, plan=plan, module=module)
    if not grouped.get("PRODUCT"):
        raise AppError("attachment_generation.product_required", f"{MODULE_NAMES[module.module_key]}缺少商品参考图", 409)
    grouped = {**grouped, "MODEL": []}
    models = list(plan_version.selected_model_snapshot or []) if supports_model else []
    product_count = int(snapshot.get("product_count") or 1)
    product_mode = str(snapshot.get("product_mode") or "SINGLE")
    if models and product_mode == "MULTI" and len(models) < product_count:
        raise AppError("attachment_generation.model_count_invalid", "多人场景的已发布AI模特数量不足，请重新选择模特", 409)
    preferred_roles = ("FULL_BODY_FRONT", "THREE_QUARTER_LEFT", "THREE_QUARTER_RIGHT", "PORTRAIT")
    model_rows: list[dict[str, object]] = []
    for model_index, model in enumerate(models[:product_count], 1):
        if not isinstance(model, dict):
            continue
        refs = model.get("reference_assets")
        refs = refs if isinstance(refs, list) else []
        indexed = {str(item.get("role")): item for item in refs if isinstance(item, dict) and item.get("asset_id")}
        max_per_model = 2 if product_count == 1 else 1
        selected = [indexed[role] for role in preferred_roles if role in indexed][:max_per_model]
        if not selected and model.get("identity_asset_id"):
            selected = [{"role": "IDENTITY", "asset_id": model["identity_asset_id"]}]
        for item in selected:
            asset_id = str(item["asset_id"])
            grouped["MODEL"].append(asset_id)
            model_rows.append({
                "asset_id": asset_id,
                "slot_type": "MODEL",
                "model_slot": model_index,
                "model_name": model.get("model_name"),
                "model_code": model.get("model_code"),
                "identity_version_id": model.get("identity_version_id"),
                "identity_reference_role": item.get("role"),
            })

    old_order = snapshot.get("execution_order")
    old_order = [dict(item) for item in old_order if isinstance(item, dict)] if isinstance(old_order, list) else []
    necessary_rows = [item for item in old_order if item.get("slot_type") in {"PRODUCT", "PRINT"}]
    necessary_rows.extend(model_rows)
    optional_rows = [item for item in old_order if item.get("slot_type") not in {"PRODUCT", "PRINT", "MODEL"}]
    execution_order: list[dict[str, object]] = []
    for item in necessary_rows:
        asset_id = str(item.get("asset_id") or "")
        if not asset_id or any(row.get("asset_id") == asset_id for row in execution_order):
            continue
        if len(execution_order) >= MAX_PROVIDER_REFERENCES:
            raise AppError(
                "attachment_generation.reference_limit",
                "商品、印花和AI模特的必要参考图已超过10张，请减少商品或模特数量",
                422,
            )
        execution_order.append({**item, "image_index": len(execution_order) + 1})
    for item in optional_rows:
        asset_id = str(item.get("asset_id") or "")
        if (
            not asset_id
            or len(execution_order) >= MAX_PROVIDER_REFERENCES
            or any(row.get("asset_id") == asset_id for row in execution_order)
        ):
            continue
        execution_order.append({**item, "image_index": len(execution_order) + 1})
    grouped = {
        role: [str(item["asset_id"]) for item in execution_order if item.get("slot_type") == role]
        for role in REFERENCE_ROLE_ORDER
    }
    snapshot = {
        **snapshot,
        "roles": grouped,
        "priority": list(REFERENCE_ROLE_ORDER),
        "selected_models": models,
        "selected_model_count": len(models),
        "execution_order": execution_order,
        "provider_reference_limit": MAX_PROVIDER_REFERENCES,
    }
    references = _flatten_references(grouped, snapshot)
    return grouped, snapshot, references


def build_attachment_execution_prompt(
    *, module: AttachmentWorkbenchModulePlan, plan: AttachmentWorkbenchPlan,
    version: AttachmentWorkbenchPlanVersion, understanding: AttachmentReferenceUnderstanding,
    grouped_references: dict[str, list[str]], aspect_ratio: str,
    generation_mode: str = "standard",
    reference_snapshot: dict[str, object] | None = None,
) -> str:
    role_rows = _reference_index(grouped_references, reference_snapshot)
    role_lines = "\n".join(
        f"- Image {item['image_index']} = {item.get('slot_type') or item.get('role')} reference"
        + (f" for {item.get('product_role')} product #{item.get('product_display_order')} ({item.get('product_name')}); view={item.get('view_role')}" if item.get("product_role") else "")
        for item in role_rows
    )
    product_mode = str((reference_snapshot or {}).get("product_mode") or "SINGLE")
    products = (reference_snapshot or {}).get("products")
    products = products if isinstance(products, list) else []
    product_mapping = ""
    selected_models = (reference_snapshot or {}).get("selected_models")
    selected_models = selected_models if isinstance(selected_models, list) else []
    if product_mode == "MULTI":
        mappings = []
        for index, product in enumerate(products):
            if not isinstance(product, dict):
                continue
            model = chr(ord("A") + index)
            identity = selected_models[index] if index < len(selected_models) and isinstance(selected_models[index], dict) else {}
            mappings.append(
                f"- Model {model} -> {product.get('product_role')} product "
                f"#{product.get('display_order')}: {product.get('display_name')}; "
                f"person identity source: {identity.get('model_name') or 'generated person'}"
            )
        product_mapping = f"""MULTI-PRODUCT IDENTITY MAP (hard constraint):
{chr(10).join(mappings)}
- Generate exactly {len(products)} models for exactly {len(products)} independent products.
- Never transfer or mix colors, silhouette, collar, cuffs, logos, prints, text, names, numbers or customization details between products.
- PRIMARY product / Model A must be the clearest and most visually prominent subject near the core visual area.
- SECONDARY products support the group scene and must remain individually recognizable.
- Arrange positions, interaction and camera composition naturally, but never change the identity mapping above.
"""
    elif selected_models:
        identity = selected_models[0] if isinstance(selected_models[0], dict) else {}
        product_mapping = f"""PERSON / PRODUCT MAP (hard constraint):
- The only person must preserve the identity of MODEL preset: {identity.get('model_name') or identity.get('model_code') or 'selected model'}.
- That person must wear the current PRODUCT garment, never the neutral clothing visible in MODEL references.
"""
    understanding_text = json.dumps(understanding.structured_json or {}, ensure_ascii=False, separators=(",", ":"))
    if generation_mode == "creative":
        direction_block = f"""CREATIVE DIRECTION (primary module-level direction):
{version.plan_summary_cn or module.plan_summary_cn}

CREATIVE FINAL PROMPT:
{version.prompt_cn or module.prompt_cn}

GLOBAL VISUAL DIRECTION (soft context only; never erase the creative direction above):
{plan.visual_direction_cn.strip()}"""
    elif version.derived_from_output_id or module.derived_from_output_id:
        direction_block = f"""CURRENT DERIVED MODULE DIRECTION (primary; overrides global style details):
{version.plan_summary_cn or module.plan_summary_cn}

CURRENT FINAL MODULE PROMPT:
{version.prompt_cn or module.prompt_cn}

GLOBAL VISUAL DIRECTION (soft context only; never erase the derived module direction above):
{plan.visual_direction_cn.strip()}"""
    else:
        direction_block = f"""GLOBAL VISUAL DIRECTION:
{plan.visual_direction_cn.strip()}

CURRENT MODULE PLAN:
{version.plan_summary_cn or module.plan_summary_cn}

CURRENT FINAL MODULE PROMPT:
{version.prompt_cn or module.prompt_cn}"""
    return f"""Create one production-ready Amazon listing image for module: {MODULE_NAMES.get(module.module_key, module.module_key)}.

REFERENCE ORDER (must follow exactly):
{role_lines}

ROLE RULES:
- PRODUCT is the sole source of truth for product identity, colors, structure, logos, text, numbers and construction details.
- PRINT is a high-fidelity reference for typography, numbers and artwork only; it must not replace the product structure.
- MODEL controls only person identity: face, hair, skin, apparent age and body traits. Ignore all clothing visible in MODEL references.
- Never inherit MODEL clothing, colors, logos, graphics, text or accessories. The garment must come exclusively from the matching PRODUCT reference.
- TEMPLATE controls composition and layout only; never inherit the template's old product design.
- SCENE controls environment, atmosphere and lighting only.
- OTHER is supplemental and never overrides PRODUCT.

{product_mapping}

{direction_block}

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
    creative_planning_job_id: str | None = None,
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
    from app.services.creative_preset_service import module_model_context_snapshot
    indexed = {item.module_key: item for item in modules}
    prepared: list[AttachmentGenerationModule] = []
    creative_versions = list((await db.scalars(select(AttachmentWorkbenchPlanVersion).where(
        AttachmentWorkbenchPlanVersion.organization_id == project.organization_id,
        AttachmentWorkbenchPlanVersion.workbench_plan_id == plan.id,
        AttachmentWorkbenchPlanVersion.ai_job_id == creative_planning_job_id,
        AttachmentWorkbenchPlanVersion.generation_mode == "creative",
    ).order_by(
        AttachmentWorkbenchPlanVersion.module_key,
        AttachmentWorkbenchPlanVersion.creative_direction_index,
    ))).all()) if creative_planning_job_id else []

    for module_key in selected:
        module = indexed[module_key]
        module_rule = attachment_module_rule(dict(version.category_skill_snapshot or {}), module_key)
        current_model_context = await module_model_context_snapshot(db, plan=plan, module_key=module_key)
        current_model_identity_ids = [
            str(item.get("identity_version_id")) for item in current_model_context.get("selected_models", [])
            if isinstance(item, dict) and item.get("identity_version_id")
        ]
        draft = _module_draft(project, module_key)
        mode = str(draft.get("generationMode") or "standard")
        if mode not in {"standard", "creative"}:
            raise AppError("attachment_generation.mode_invalid", "附图生成模式无效", 422)
        if mode == "creative" and not bool(module_rule.get("supports_creative")):
            raise AppError("attachment_generation.mode_unsupported", f"{MODULE_NAMES[module_key]}不支持创意生成", 422)
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
        if mode == "standard":
            if module.current_version_number < 1 or not module.plan_summary_cn.strip() or not module.prompt_cn.strip():
                raise AppError("attachment_generation.prompt_required", f"请先完成{MODULE_NAMES[module_key]}的方案和Prompt", 409)
            plan_version = await db.scalar(select(AttachmentWorkbenchPlanVersion).where(
                AttachmentWorkbenchPlanVersion.module_plan_id == module.id,
                AttachmentWorkbenchPlanVersion.version_scope == f"module:{module_key}",
                AttachmentWorkbenchPlanVersion.version_number == module.current_version_number,
            ))
            if plan_version is None:
                raise AppError("attachment_generation.version_missing", f"{MODULE_NAMES[module_key]}当前版本不存在，请重新保存", 409)
            if plan.visual_preset_version_id and (
                plan_version.visual_preset_version_id != plan.visual_preset_version_id
                or plan_version.theme_preset_version_id != plan.theme_preset_version_id
            ):
                raise AppError("attachment_generation.plan_stale", f"{MODULE_NAMES[module_key]}的视觉或主题已变化，请重新策划", 409)
            version_model_ids = [
                str(item.get("identity_version_id")) for item in list(plan_version.selected_model_snapshot or [])
                if isinstance(item, dict) and item.get("identity_version_id")
            ]
            if bool(module_rule.get("supports_model")) and plan.visual_preset_version_id and version_model_ids != current_model_identity_ids:
                raise AppError("attachment_generation.model_stale", f"{MODULE_NAMES[module_key]}的AI模特已变化，请重新策划", 409)
            if plan.current_product_identity_lock_version_id and plan_version.product_identity_lock_version_id != plan.current_product_identity_lock_version_id:
                raise AppError("attachment_generation.product_identity_stale", f"{MODULE_NAMES[module_key]}的商品事实已更新，请重新策划", 409)
            selected_versions = [plan_version] * image_count
        else:
            if not creative_planning_job_id:
                raise AppError("attachment_generation.creative_planning_required", "请先完成创意方向策划", 409)
            selected_versions = [item for item in creative_versions if item.module_plan_id == module.id]
            if len(selected_versions) != image_count:
                raise AppError("attachment_generation.creative_directions_missing", f"{MODULE_NAMES[module_key]}创意方向数量不完整，请重新策划", 409)
            plan_version = selected_versions[0]
        if module.reference_context_dirty:
            raise AppError("attachment_generation.reference_stale", f"{MODULE_NAMES[module_key]}参考素材已变化，请重新分析", 409)
        understanding = await latest_reference_understanding(db, module.id, ready_only=True)
        if understanding is None:
            raise AppError("attachment_generation.reference_analysis_required", f"请先完成{MODULE_NAMES[module_key]}参考素材分析", 409)
        grouped, reference_snapshot, _reference_ids = await resolve_attachment_generation_references(
            db, plan=plan, module=module, plan_version=plan_version,
            supports_model=bool(module_rule.get("supports_model")),
        )
        product_mode = str(reference_snapshot.get("product_mode") or "SINGLE")
        products = reference_snapshot.get("products")
        products = products if isinstance(products, list) else []
        if product_mode == "MULTI":
            if not bool(module_rule.get("supports_multi_product")):
                raise AppError("attachment_generation.multi_product_unsupported", f"{MODULE_NAMES[module_key]}不支持多件商品", 422)
            if not 2 <= len(products) <= 3:
                raise AppError("attachment_generation.product_count_invalid", "多件商品模式需要2到3件商品", 409)
            if sum(1 for item in products if isinstance(item, dict) and item.get("product_role") == "PRIMARY") != 1:
                raise AppError("attachment_generation.primary_product_invalid", "多件商品模式必须包含唯一主商品", 409)
        current_composition_version_id = reference_snapshot.get("product_composition_version_id")
        if product_mode == "MULTI" and any(
            item.product_composition_version_id != current_composition_version_id for item in selected_versions
        ):
            raise AppError("attachment_generation.composition_stale", "商品组合已更新，需要重新策划后生成", 409)
        if product_mode == "MULTI" and understanding.product_composition_version_id != current_composition_version_id:
            raise AppError("attachment_generation.composition_analysis_stale", "商品组合已更新，需要重新分析参考素材", 409)
        generation_roles = dict(reference_snapshot.get("roles") or {})
        generation_roles.pop("MODEL", None)
        if generation_roles != (understanding.source_snapshot_json or {}).get("roles"):
            raise AppError("attachment_generation.reference_stale", f"{MODULE_NAMES[module_key]}参考素材与分析版本不一致，请重新分析", 409)
        width, height = DELIVERY_SIZES[aspect_ratio]
        directions = [AttachmentGenerationDirection(
            slot_index=index,
            plan_version=direction_version,
            creative_direction_index=int(direction_version.creative_direction_index or index) if mode == "creative" else None,
            execution_prompt=build_attachment_execution_prompt(
                module=module, plan=plan, version=direction_version, understanding=understanding,
                grouped_references=grouped, aspect_ratio=aspect_ratio, generation_mode=mode,
                reference_snapshot=reference_snapshot,
            ),
        ) for index, direction_version in enumerate(selected_versions, 1)]
        prepared.append(AttachmentGenerationModule(
            module_key=module_key, module_name=MODULE_NAMES[module_key], aspect_ratio=aspect_ratio,
            image_count=image_count, generation_mode=mode, width=width, height=height,
            plan_version=plan_version, understanding=understanding,
            grouped_references=grouped, reference_snapshot=reference_snapshot,
            execution_prompt=directions[0].execution_prompt,
            directions=directions,
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
            "directions": [{
                "slot_index": direction.slot_index,
                "plan_version_id": direction.plan_version.id,
                "prompt_version_id": direction.plan_version.id,
                "creative_direction_index": direction.creative_direction_index,
            } for direction in item.directions],
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
    creative_planning_job_id: str | None = None,
) -> tuple[AttachmentGenerationPreview, JobBatch, list[Job], object, bool]:
    preview = await build_attachment_generation_preview(
        db, project=project, session=session, version=version, plan=plan,
        modules=modules, selected_module_keys=selected_module_keys,
        creative_planning_job_id=creative_planning_job_id,
    )
    if snapshot_signature != preview.snapshot_signature:
        raise AppError("attachment_generation.snapshot_changed", "确认期间方案、Prompt、比例或参考素材已变化，请重新确认", 409)

    items: list[BatchJobItemRequest] = []
    for module in preview.modules:
        module_rule = attachment_module_rule(dict(version.category_skill_snapshot or {}), module.module_key)
        reference_ids = _flatten_references(module.grouped_references, module.reference_snapshot)
        for direction in module.directions:
            slot_index = direction.slot_index
            items.append(BatchJobItemRequest(
                client_item_id=f"attachment:{module.module_key}:{slot_index}:{idempotency_key[-12:]}",
                prompt=direction.execution_prompt, reference_asset_ids=reference_ids,
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
                    "plan_version_id": direction.plan_version.id,
                    "plan_version_number": direction.plan_version.version_number,
                    "prompt_version_id": direction.plan_version.id,
                    "prompt_version_number": direction.plan_version.version_number,
                    "plan_summary_snapshot": direction.plan_version.plan_summary_cn,
                    "prompt_snapshot": direction.plan_version.prompt_cn,
                    "creative_direction_index": direction.creative_direction_index,
                    "creative_planning_job_id": creative_planning_job_id if module.generation_mode == "creative" else None,
                    "reference_understanding_id": module.understanding.id,
                    "reference_understanding_version": module.understanding.version_number,
                    "reference_snapshot": module.reference_snapshot,
                    "product_mode": module.reference_snapshot.get("product_mode", "SINGLE"),
                    "product_count": module.reference_snapshot.get("product_count", 1),
                    "model_count": module.reference_snapshot.get("model_count", 1),
                    "products": module.reference_snapshot.get("products", []),
                    "product_composition_version_id": module.reference_snapshot.get("product_composition_version_id"),
                    "reference_execution_order": module.reference_snapshot.get("execution_order", []),
                    "visual_preset_id": direction.plan_version.visual_preset_id,
                    "visual_preset_version_id": direction.plan_version.visual_preset_version_id,
                    "visual_preset_prompt_snapshot": direction.plan_version.visual_preset_prompt_snapshot,
                    "theme_preset_id": direction.plan_version.theme_preset_id,
                    "theme_preset_version_id": direction.plan_version.theme_preset_version_id,
                    "theme_prompt_snapshot": direction.plan_version.theme_prompt_snapshot,
                    "model_identity_snapshot": list(direction.plan_version.selected_model_snapshot or []),
                    "product_identity_lock_version_id": direction.plan_version.product_identity_lock_version_id,
                    "module_sales_objective_snapshot": {
                        "buyer_question": module_rule.get("buyer_question", ""),
                        "image_sales_objective": module_rule.get("image_sales_objective", ""),
                        "required_information": list(module_rule.get("required_information", [])),
                        "avoid_duplication": list(module_rule.get("avoid_duplication", [])),
                    },
                    "reference_library_snapshot": list(direction.plan_version.reference_library_snapshot or []),
                    "effective_prompt_snapshot": direction.execution_prompt,
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
        asset_id for item in preview.modules for role in ("PRINT", "MODEL", "SCENE", "OTHER")
        for asset_id in item.grouped_references.get(role, [])
    ))
    snapshot = await build_input_asset_snapshot(
        db, organization_id=project.organization_id, product_asset_ids=product_ids,
        reference_asset_ids=reference_ids, template_asset_ids=template_ids,
        primary_asset_id=session.primary_asset_id,
    )
    snapshot["workflow"] = "attachment_workbench_generation"
    snapshot["snapshot_signature"] = preview.snapshot_signature
    snapshot["product_mode"] = "MULTI" if any(
        item.reference_snapshot.get("product_mode") == "MULTI" for item in preview.modules
    ) else "SINGLE"
    snapshot["modules"] = [{
        "module_key": item.module_key,
        "module_name": item.module_name,
        "aspect_ratio": item.aspect_ratio,
        "image_count": item.image_count,
        "generation_mode": item.generation_mode,
        "directions": [{
            "slot_index": direction.slot_index,
            "plan_version_id": direction.plan_version.id,
            "prompt_version_id": direction.plan_version.id,
            "creative_direction_index": direction.creative_direction_index,
        } for direction in item.directions],
        "reference_understanding_id": item.understanding.id,
        "product_mode": item.reference_snapshot.get("product_mode", "SINGLE"),
        "product_count": item.reference_snapshot.get("product_count", 1),
        "model_count": item.reference_snapshot.get("model_count", 1),
        "products": item.reference_snapshot.get("products", []),
        "product_composition_version_id": item.reference_snapshot.get("product_composition_version_id"),
        "reference_execution_order": item.reference_snapshot.get("execution_order", []),
        "visual_preset_id": item.plan_version.visual_preset_id,
        "visual_preset_version_id": item.plan_version.visual_preset_version_id,
        "theme_preset_id": item.plan_version.theme_preset_id,
        "theme_preset_version_id": item.plan_version.theme_preset_version_id,
        "model_identity_snapshot": list(item.plan_version.selected_model_snapshot or []),
        "product_identity_lock_version_id": item.plan_version.product_identity_lock_version_id,
        "module_sales_objective_snapshot": {
            "buyer_question": attachment_module_rule(dict(version.category_skill_snapshot or {}), item.module_key).get("buyer_question", ""),
            "image_sales_objective": attachment_module_rule(dict(version.category_skill_snapshot or {}), item.module_key).get("image_sales_objective", ""),
            "required_information": list(attachment_module_rule(dict(version.category_skill_snapshot or {}), item.module_key).get("required_information", [])),
            "avoid_duplication": list(attachment_module_rule(dict(version.category_skill_snapshot or {}), item.module_key).get("avoid_duplication", [])),
        },
        "reference_library_snapshot": list(item.plan_version.reference_library_snapshot or []),
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
