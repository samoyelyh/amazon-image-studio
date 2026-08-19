from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.attachment_planning import (
    AttachmentModuleReference,
    AttachmentProductReferenceGroup,
    AttachmentProductReferenceItem,
    AttachmentReferenceUnderstanding,
    AttachmentWorkbenchModulePlan,
    AttachmentWorkbenchPlan,
)
from app.models.content import Asset
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject
from app.models.tasks import Job, JobStatus
from app.schemas.tasks import JobSubmitRequest
from app.services.category_listing_service import resolve_bound_model_code
from app.services.task_service import submit_job


UTC = timezone.utc
SLOT_TYPES = {"PRODUCT", "TEMPLATE", "SCENE", "PRINT", "OTHER"}
SLOT_DEFINITIONS: dict[str, list[dict[str, object]]] = {
    "pure_white": [
        {"slot_type": "PRODUCT", "required": True, "recommended": True, "max_items": 4},
        {"slot_type": "OTHER", "required": False, "recommended": False, "max_items": 3},
    ],
    "custom_process": [
        {"slot_type": "PRODUCT", "required": True, "recommended": True, "max_items": 4},
        {"slot_type": "TEMPLATE", "required": False, "recommended": True, "max_items": 2},
        {"slot_type": "PRINT", "required": False, "recommended": True, "max_items": 4},
        {"slot_type": "OTHER", "required": False, "recommended": False, "max_items": 3},
    ],
    "stadium_scene": [
        {"slot_type": "PRODUCT", "required": True, "recommended": True, "max_items": 4},
        {"slot_type": "SCENE", "required": False, "recommended": False, "max_items": 3},
        {"slot_type": "OTHER", "required": False, "recommended": False, "max_items": 3},
    ],
    "gift_scene": [
        {"slot_type": "PRODUCT", "required": True, "recommended": True, "max_items": 4},
        {"slot_type": "TEMPLATE", "required": False, "recommended": False, "max_items": 2},
        {"slot_type": "SCENE", "required": False, "recommended": False, "max_items": 3},
        {"slot_type": "PRINT", "required": False, "recommended": False, "max_items": 4},
        {"slot_type": "OTHER", "required": False, "recommended": False, "max_items": 3},
    ],
    "detail_display": [
        {"slot_type": "PRODUCT", "required": True, "recommended": True, "max_items": 4},
        {"slot_type": "OTHER", "required": False, "recommended": False, "max_items": 3},
    ],
    "casual_scene": [
        {"slot_type": "PRODUCT", "required": True, "recommended": True, "max_items": 4},
        {"slot_type": "SCENE", "required": False, "recommended": False, "max_items": 3},
        {"slot_type": "OTHER", "required": False, "recommended": False, "max_items": 3},
    ],
}

REFERENCE_ANALYSIS_SYSTEM_PROMPT = """你是亚马逊电商附图参考素材分析专家。你会收到按业务角色标注的多张图片。
只返回一个有效JSON对象，不要Markdown，不要分析过程。结构必须是：
{
  "product":{"summary":"中文摘要","constraints":["约束"]},
  "template":{"summary":"中文摘要","layout_constraints":["构图约束"]},
  "scene":{"summary":"中文摘要","style_cues":["氛围线索"]},
  "print":{"summary":"中文摘要","fidelity_constraints":["高保真约束"]},
  "other":{"summary":"中文摘要"},
  "combined_summary_cn":"中文综合摘要"
}
必须遵守优先级：当前PRODUCT商品真实性 > PRINT印花和定制素材 > 模块业务规则 > TEMPLATE结构 > SCENE氛围 > OTHER。
TEMPLATE只参考构图、摆放和结构，禁止继承模板中旧商品的颜色、款式、号码、Logo或印花。
SCENE只参考环境与氛围，不得改变商品身份。
PRINT是高保真视觉事实，必须保护轮廓、比例、描边、结构和朝向，不得重新设计成相似普通字体。
没有某类素材时，对应对象保留空摘要和空数组。"""


def slot_definitions(module_key: str) -> list[dict[str, object]]:
    definitions = SLOT_DEFINITIONS.get(module_key)
    if definitions is None:
        raise AppError("attachment_reference.module_invalid", "选择了不支持的附图模块", 422)
    return [dict(item) for item in definitions]


def _slot_definition(module_key: str, slot_type: str) -> dict[str, object]:
    value = slot_type.upper()
    if value not in SLOT_TYPES:
        raise AppError("attachment_reference.slot_invalid", "参考素材类型无效", 422)
    definition = next((item for item in slot_definitions(module_key) if item["slot_type"] == value), None)
    if definition is None:
        raise AppError("attachment_reference.slot_not_supported", "当前模块不支持该参考素材类型", 422)
    return definition


async def ensure_product_reference_group(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan, session: ListingGenerationSession, user_id: str,
) -> tuple[AttachmentProductReferenceGroup, list[AttachmentProductReferenceItem]]:
    group = await db.scalar(select(AttachmentProductReferenceGroup).where(
        AttachmentProductReferenceGroup.workbench_plan_id == plan.id,
        AttachmentProductReferenceGroup.organization_id == plan.organization_id,
    ).with_for_update())
    if group is None:
        group = AttachmentProductReferenceGroup(
            organization_id=plan.organization_id, workbench_plan_id=plan.id,
            state_version=0, created_by=user_id, updated_by=user_id,
        )
        db.add(group)
        await db.flush()
    items = list((await db.scalars(select(AttachmentProductReferenceItem).where(
        AttachmentProductReferenceItem.product_group_id == group.id,
    ).order_by(AttachmentProductReferenceItem.sort_order))).all())
    existing_reference_keys = {(item.asset_id, item.view_role) for item in items}
    ordered_source_ids = list(dict.fromkeys([
        *([session.primary_asset_id] if session.primary_asset_id else []),
        *(session.source_asset_ids or []),
    ]))[:4]
    if ordered_source_ids:
        valid_ids = set((await db.scalars(select(Asset.id).where(
            Asset.organization_id == plan.organization_id,
            Asset.id.in_(ordered_source_ids), Asset.deleted_at.is_(None),
        ))).all())
        added = False
        for index, asset_id in enumerate(ordered_source_ids):
            view_role = "front" if index == 0 else "detail"
            if asset_id not in valid_ids or (asset_id, view_role) in existing_reference_keys:
                continue
            db.add(AttachmentProductReferenceItem(
                organization_id=plan.organization_id, product_group_id=group.id,
                asset_id=asset_id, source_asset_id=None,
                view_role=view_role, sort_order=index,
                source="session", transform_metadata={}, created_by=user_id, updated_by=user_id,
            ))
            existing_reference_keys.add((asset_id, view_role))
            added = True
        if added:
            group.state_version += 1
            group.updated_by = user_id
            modules = list((await db.scalars(select(AttachmentWorkbenchModulePlan).where(
                AttachmentWorkbenchModulePlan.workbench_plan_id == plan.id,
            ))).all())
            for module in modules:
                module.reference_context_dirty = True
                module.reference_state_version += 1
            await db.flush()
            items = list((await db.scalars(select(AttachmentProductReferenceItem).where(
                AttachmentProductReferenceItem.product_group_id == group.id,
            ).order_by(AttachmentProductReferenceItem.sort_order))).all())
    return group, items


async def list_module_references(db: AsyncSession, module_plan_id: str) -> list[AttachmentModuleReference]:
    return list((await db.scalars(select(AttachmentModuleReference).where(
        AttachmentModuleReference.module_plan_id == module_plan_id,
    ).order_by(AttachmentModuleReference.slot_type, AttachmentModuleReference.sort_order))).all())


async def add_module_reference(
    db: AsyncSession, *, module: AttachmentWorkbenchModulePlan, slot_type: str,
    asset_id: str, metadata: dict[str, object], user_id: str,
) -> AttachmentModuleReference:
    slot_type = slot_type.upper()
    definition = _slot_definition(module.module_key, slot_type)
    asset = await db.scalar(select(Asset).where(
        Asset.id == asset_id, Asset.organization_id == module.organization_id, Asset.deleted_at.is_(None),
    ))
    if asset is None:
        raise AppError("asset.not_found", "参考图片不存在或无权访问", 404)
    existing = await db.scalar(select(AttachmentModuleReference).where(
        AttachmentModuleReference.module_plan_id == module.id,
        AttachmentModuleReference.slot_type == slot_type,
        AttachmentModuleReference.asset_id == asset_id,
    ))
    if existing:
        return existing
    count = int(await db.scalar(select(func.count()).select_from(AttachmentModuleReference).where(
        AttachmentModuleReference.module_plan_id == module.id,
        AttachmentModuleReference.slot_type == slot_type,
    )) or 0)
    if count >= int(definition["max_items"]):
        raise AppError(
            "attachment_reference.slot_limit", "该参考素材槽位已达到数量上限", 422,
            {"slot_type": slot_type, "max_items": definition["max_items"]},
        )
    row = AttachmentModuleReference(
        organization_id=module.organization_id, module_plan_id=module.id,
        slot_type=slot_type, asset_id=asset.id, sort_order=count,
        metadata_json=dict(metadata), created_by=user_id, updated_by=user_id,
    )
    db.add(row)
    module.reference_context_dirty = True
    module.reference_state_version += 1
    module.reference_analysis_job_id = None
    await db.flush()
    return row


async def remove_module_reference(
    db: AsyncSession, *, module: AttachmentWorkbenchModulePlan, reference_id: str,
) -> None:
    row = await db.scalar(select(AttachmentModuleReference).where(
        AttachmentModuleReference.id == reference_id,
        AttachmentModuleReference.organization_id == module.organization_id,
        AttachmentModuleReference.module_plan_id == module.id,
    ).with_for_update())
    if row is None:
        raise AppError("attachment_reference.not_found", "参考素材引用不存在", 404)
    await db.delete(row)
    module.reference_context_dirty = True
    module.reference_state_version += 1
    module.reference_analysis_job_id = None
    await db.flush()


async def replace_product_reference(
    db: AsyncSession, *, group: AttachmentProductReferenceGroup, asset_id: str,
    source_asset_id: str | None, view_role: str, transform_metadata: dict[str, object], user_id: str,
) -> AttachmentProductReferenceItem:
    if view_role not in {"front", "back", "detail"}:
        raise AppError("attachment_reference.product_role_invalid", "商品参考角色无效", 422)
    asset = await db.scalar(select(Asset).where(
        Asset.id == asset_id, Asset.organization_id == group.organization_id, Asset.deleted_at.is_(None),
    ))
    if asset is None:
        raise AppError("asset.not_found", "商品参考图片不存在或无权访问", 404)
    current = await db.scalar(select(AttachmentProductReferenceItem).where(
        AttachmentProductReferenceItem.product_group_id == group.id,
        AttachmentProductReferenceItem.view_role == view_role,
        AttachmentProductReferenceItem.source == "override",
    ).with_for_update())
    matching_asset = await db.scalar(select(AttachmentProductReferenceItem).where(
        AttachmentProductReferenceItem.product_group_id == group.id,
        AttachmentProductReferenceItem.view_role == view_role,
        AttachmentProductReferenceItem.asset_id == asset.id,
    ).with_for_update())
    if matching_asset is not None and (current is None or matching_asset.id != current.id):
        if current is not None:
            await db.delete(current)
            await db.flush()
        current = matching_asset
    if current is None:
        current = AttachmentProductReferenceItem(
            organization_id=group.organization_id, product_group_id=group.id,
            asset_id=asset.id, source_asset_id=source_asset_id, view_role=view_role,
            sort_order={"front": 0, "back": 1, "detail": 2}[view_role], source="override",
            transform_metadata=dict(transform_metadata), created_by=user_id, updated_by=user_id,
        )
        db.add(current)
    else:
        current.asset_id = asset.id
        current.source_asset_id = source_asset_id
        current.source = "override"
        current.transform_metadata = dict(transform_metadata)
        current.updated_by = user_id
    group.state_version += 1
    group.updated_by = user_id
    modules = list((await db.scalars(select(AttachmentWorkbenchModulePlan).where(
        AttachmentWorkbenchModulePlan.workbench_plan_id == group.workbench_plan_id,
    ))).all())
    for module in modules:
        module.reference_context_dirty = True
        module.reference_state_version += 1
        module.reference_analysis_job_id = None
    await db.flush()
    return current


async def effective_reference_snapshot(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan, module: AttachmentWorkbenchModulePlan,
) -> tuple[dict[str, list[str]], dict[str, object]]:
    group = await db.scalar(select(AttachmentProductReferenceGroup).where(
        AttachmentProductReferenceGroup.workbench_plan_id == plan.id,
    ))
    product_items = [] if group is None else list((await db.scalars(select(AttachmentProductReferenceItem).where(
        AttachmentProductReferenceItem.product_group_id == group.id,
    ).order_by(AttachmentProductReferenceItem.source.desc(), AttachmentProductReferenceItem.sort_order))).all())
    # One explicit override per view wins; inherited session assets remain as fallback.
    effective_products: list[AttachmentProductReferenceItem] = []
    for role in ("front", "back", "detail"):
        matching = [item for item in product_items if item.view_role == role]
        selected = next((item for item in matching if item.source == "override"), None)
        if selected:
            effective_products.append(selected)
        else:
            effective_products.extend(item for item in matching if item.source == "session")
    refs = await list_module_references(db, module.id)
    grouped = {slot: [] for slot in SLOT_TYPES}
    explicit_product = [item.asset_id for item in refs if item.slot_type == "PRODUCT"]
    grouped["PRODUCT"] = explicit_product or [item.asset_id for item in effective_products]
    for item in refs:
        if item.slot_type != "PRODUCT":
            grouped[item.slot_type].append(item.asset_id)
    grouped = {key: list(dict.fromkeys(value)) for key, value in grouped.items()}
    snapshot = {
        "module_key": module.module_key,
        "reference_state_version": module.reference_state_version,
        "roles": grouped,
        "priority": ["PRODUCT", "PRINT", "TEMPLATE", "SCENE", "OTHER"],
    }
    return grouped, snapshot


def build_reference_analysis_input(module_key: str, grouped: dict[str, list[str]]) -> tuple[str, str, list[str]]:
    descriptors = []
    references: list[str] = []
    for slot in ("PRODUCT", "PRINT", "TEMPLATE", "SCENE", "OTHER"):
        for asset_id in grouped.get(slot, []):
            references.append(asset_id)
            descriptors.append({"image_index": len(references), "slot_type": slot, "asset_id": asset_id})
    user_prompt = json.dumps({
        "module_key": module_key,
        "images_in_submission_order": descriptors,
        "role_semantics": {
            "PRODUCT": "决定商品外观，是最高优先级事实来源",
            "TEMPLATE": "只参考构图和摆放，不继承旧商品",
            "SCENE": "只参考氛围和环境",
            "PRINT": "保持字形、号码和图形的视觉结构",
            "OTHER": "补充局部细节",
        },
    }, ensure_ascii=False)
    return REFERENCE_ANALYSIS_SYSTEM_PROMPT, user_prompt, references


def parse_reference_understanding(text: str) -> dict[str, object]:
    value = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        value = fenced.group(1)
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise AppError("attachment_reference.ai_result_invalid", "参考素材理解结果不是有效JSON，可重新分析", 422) from error
    if not isinstance(payload, dict) or not str(payload.get("combined_summary_cn") or "").strip():
        raise AppError("attachment_reference.ai_result_invalid", "参考素材理解缺少综合摘要，可重新分析", 422)
    for key in ("product", "template", "scene", "print", "other"):
        if not isinstance(payload.get(key), dict):
            raise AppError("attachment_reference.ai_result_invalid", "参考素材理解结构不完整，可重新分析", 422)
    return payload


async def latest_reference_understanding(
    db: AsyncSession, module_plan_id: str, *, ready_only: bool = False,
) -> AttachmentReferenceUnderstanding | None:
    query = select(AttachmentReferenceUnderstanding).where(
        AttachmentReferenceUnderstanding.module_plan_id == module_plan_id,
    )
    if ready_only:
        query = query.where(AttachmentReferenceUnderstanding.status == "ready")
    return await db.scalar(query.order_by(AttachmentReferenceUnderstanding.version_number.desc()).limit(1))


async def start_reference_analysis(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject,
    plan: AttachmentWorkbenchPlan, module: AttachmentWorkbenchModulePlan,
    idempotency_key: str, user_id: str,
) -> tuple[Job, AttachmentReferenceUnderstanding, bool]:
    grouped, snapshot = await effective_reference_snapshot(db, plan=plan, module=module)
    if not grouped["PRODUCT"]:
        raise AppError("attachment_reference.product_required", "当前模块缺少商品参考图", 409)
    system_prompt, user_prompt, references = build_reference_analysis_input(module.module_key, grouped)
    model_code = await resolve_bound_model_code(
        db, organization_id=project.organization_id, operation_code="listing.plan", capability="text_generation",
    )
    job, created = await submit_job(
        db, settings, organization_id=project.organization_id, user_id=user_id,
        payload=JobSubmitRequest(
            operation_code="listing.plan", workspace_type="listing", queue_name="planning_queue",
            capability="text_generation", model_code=model_code, project_id=None,
            input={
                "system_prompt": system_prompt, "user_prompt": user_prompt,
                "response_format": "json_object", "reference_asset_ids": references,
                "metadata": {
                    "workflow": "attachment_reference_understanding", "action": "analyze_reference",
                    "module_plan_id": module.id, "module_key": module.module_key,
                },
            },
            idempotency_key=idempotency_key,
            billing_factors={"workspace": "attachment_reference_understanding", "module_key": module.module_key},
        ),
    )
    existing = await db.scalar(select(AttachmentReferenceUnderstanding).where(
        AttachmentReferenceUnderstanding.ai_job_id == job.id,
    ))
    if existing:
        module.reference_analysis_job_id = job.id
        return job, existing, created
    version_number = int(await db.scalar(select(func.max(AttachmentReferenceUnderstanding.version_number)).where(
        AttachmentReferenceUnderstanding.module_plan_id == module.id,
    )) or 0) + 1
    understanding = AttachmentReferenceUnderstanding(
        organization_id=project.organization_id, module_plan_id=module.id,
        version_number=version_number, status="analyzing", structured_json={},
        source_snapshot_json=snapshot, ai_job_id=job.id, created_by=user_id,
    )
    db.add(understanding)
    module.reference_analysis_job_id = job.id
    await db.flush()
    return job, understanding, created


async def reconcile_reference_understandings(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan, modules: list[AttachmentWorkbenchModulePlan],
) -> None:
    indexed = {item.id: item for item in modules}
    pending = list((await db.scalars(select(AttachmentReferenceUnderstanding).where(
        AttachmentReferenceUnderstanding.module_plan_id.in_(indexed),
        AttachmentReferenceUnderstanding.status == "analyzing",
    ))).all())
    for understanding in pending:
        if not understanding.ai_job_id:
            continue
        job = await db.scalar(select(Job).where(Job.id == understanding.ai_job_id))
        if job is None or job.status not in {
            JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value,
        }:
            continue
        module = indexed[understanding.module_plan_id]
        if job.status == JobStatus.SUCCEEDED.value:
            try:
                text = str((job.result_json or {}).get("metadata", {}).get("text") or "")
                understanding.structured_json = parse_reference_understanding(text)
                understanding.ai_model = job.model_code
                _, current_snapshot = await effective_reference_snapshot(db, plan=plan, module=module)
                if current_snapshot["roles"] == understanding.source_snapshot_json.get("roles"):
                    understanding.status = "ready"
                    module.reference_context_dirty = False
                else:
                    understanding.status = "stale"
                    module.reference_context_dirty = True
            except AppError as error:
                understanding.status = "failed"
                understanding.error_message = error.message
                module.reference_context_dirty = True
        else:
            understanding.status = "failed"
            understanding.error_message = job.error_message or "参考素材分析失败，可重试"
            module.reference_context_dirty = True
        if module.reference_analysis_job_id == job.id:
            module.reference_analysis_job_id = None


async def current_understanding_context(
    db: AsyncSession, module: AttachmentWorkbenchModulePlan,
) -> tuple[str | None, dict[str, object] | None]:
    if module.reference_context_dirty:
        return None, None
    row = await latest_reference_understanding(db, module.id, ready_only=True)
    return (row.id, dict(row.structured_json or {})) if row else (None, None)
