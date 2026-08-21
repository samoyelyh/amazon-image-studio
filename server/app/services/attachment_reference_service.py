from __future__ import annotations

import json
import re
from hashlib import sha256
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.attachment_planning import (
    AttachmentModuleReference,
    AttachmentProductComposition,
    AttachmentProductReferenceGroup,
    AttachmentProductReferenceItem,
    AttachmentReferenceUnderstanding,
    AttachmentReferenceLibraryItem,
    AttachmentReferenceLibraryItemModule,
    AttachmentWorkbenchModulePlan,
    AttachmentWorkbenchPlan,
)
from app.models.content import Asset
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject
from app.models.tasks import Job, JobStatus
from app.schemas.tasks import JobSubmitRequest
from app.services.ai_task_model_policy_service import next_analysis_retry, resolve_ai_task_route
from app.services.attachment_product_composition_service import (
    current_composition_version,
)
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

REFERENCE_ANALYSIS_SYSTEM_PROMPT = """你是亚马逊电商附图参考素材分析专家。你会收到按业务角色和商品身份标注的多张图片。
只返回一个有效JSON对象，不要Markdown，不要分析过程。结构必须是：
{
  "product":{"summary":"中文摘要","constraints":["约束"]},
  "products":[
    {"product_role":"PRIMARY","display_order":0,"summary":"中文摘要","colors":["颜色"],"structure":["结构"],"prints":["印花/Logo/号码"],"fidelity_constraints":["保真约束"]}
  ],
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
多商品时必须逐件分析并保留products数组；PRIMARY和每个SECONDARY的颜色、Logo、印花、号码、版型与结构必须彼此独立，禁止串用。
没有某类素材时，对应对象保留空摘要和空数组。"""
REFERENCE_ANALYSIS_PROMPT_VERSION = "attachment-reference-v3"
REFERENCE_ANALYSIS_POLICY_VERSION = "phase10-reference-routing-v1"


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
    keywords: list[str] | None = None, guidance: str = "", library_item_id: str | None = None,
) -> AttachmentModuleReference:
    slot_type = slot_type.upper()
    definition = _slot_definition(module.module_key, slot_type)
    asset = await db.scalar(select(Asset).where(
        Asset.id == asset_id, Asset.organization_id == module.organization_id, Asset.deleted_at.is_(None),
    ))
    if asset is None:
        raise AppError("asset.not_found", "参考图片不存在或无权访问", 404)
    if library_item_id:
        library_item = await db.scalar(select(AttachmentReferenceLibraryItem).where(
            AttachmentReferenceLibraryItem.id == library_item_id,
            AttachmentReferenceLibraryItem.organization_id == module.organization_id,
            AttachmentReferenceLibraryItem.asset_id == asset_id,
            AttachmentReferenceLibraryItem.is_active.is_(True),
        ))
        supported = await db.scalar(select(AttachmentReferenceLibraryItemModule.id).where(
            AttachmentReferenceLibraryItemModule.library_item_id == library_item_id,
            AttachmentReferenceLibraryItemModule.module_key == module.module_key,
        ))
        if library_item is None or supported is None or library_item.reference_role != slot_type:
            raise AppError("attachment_reference.library_item_invalid", "公共参考图与当前模块、素材角色或图片不匹配", 422)
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
        metadata_json=dict(metadata), keywords=list(keywords or []), guidance=guidance.strip(),
        library_item_id=library_item_id, created_by=user_id, updated_by=user_id,
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


async def update_module_reference_options(
    db: AsyncSession, *, module: AttachmentWorkbenchModulePlan, reference_id: str,
    keywords: list[str], guidance: str, expected_reference_state_version: int,
    user_id: str,
) -> AttachmentModuleReference:
    if expected_reference_state_version != module.reference_state_version:
        raise AppError(
            "attachment_reference.state_version_conflict",
            "参考素材已被更新，请刷新后再保存", 409,
            {"expected": expected_reference_state_version, "actual": module.reference_state_version},
        )
    row = await db.scalar(select(AttachmentModuleReference).where(
        AttachmentModuleReference.id == reference_id,
        AttachmentModuleReference.organization_id == module.organization_id,
        AttachmentModuleReference.module_plan_id == module.id,
    ).with_for_update())
    if row is None:
        raise AppError("attachment_reference.not_found", "参考素材引用不存在", 404)
    next_keywords = list(dict.fromkeys(value.strip() for value in keywords if value.strip()))
    next_guidance = guidance.strip()
    if next_keywords != list(row.keywords or []) or next_guidance != row.guidance:
        row.keywords = next_keywords
        row.guidance = next_guidance
        row.updated_by = user_id
        module.reference_context_dirty = True
        module.reference_state_version += 1
        module.reference_analysis_job_id = None
    await db.flush()
    return row


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
    reference_options = [{
        "reference_id": item.id, "asset_id": item.asset_id, "role": item.slot_type,
        "keywords": list(item.keywords or []), "guidance": item.guidance,
        "library_item_id": item.library_item_id,
    } for item in refs]
    grouped = {slot: [] for slot in SLOT_TYPES}
    composition = await db.scalar(select(AttachmentProductComposition).where(
        AttachmentProductComposition.module_plan_id == module.id,
        AttachmentProductComposition.organization_id == module.organization_id,
    ))
    composition_version = await current_composition_version(db, composition) if composition else None
    composition_snapshot = dict(composition_version.snapshot_json or {}) if composition_version else {}
    products = composition_snapshot.get("products")
    products = products if isinstance(products, list) else []
    execution_order: list[dict[str, object]] = []

    def add_execution_asset(
        *, asset_id: str, slot_type: str, product: dict[str, object] | None = None,
        view_role: str | None = None,
    ) -> None:
        if any(row.get("asset_id") == asset_id for row in execution_order):
            return
        execution_order.append({
            "image_index": len(execution_order) + 1,
            "asset_id": asset_id,
            "slot_type": slot_type,
            "product_entry_id": product.get("product_entry_id") if product else None,
            "product_role": product.get("product_role") if product else None,
            "product_display_order": product.get("display_order") if product else None,
            "product_name": product.get("display_name") if product else None,
            "view_role": view_role,
        })

    product_mode = composition.mode if composition else "SINGLE"
    if product_mode == "MULTI":
        active_products = sorted(
            (item for item in products if isinstance(item, dict)),
            key=lambda item: int(item.get("display_order") or 0),
        )
        for product in active_products:
            product_assets = product.get("assets")
            product_assets = product_assets if isinstance(product_assets, list) else []
            ordered = sorted(
                (item for item in product_assets if isinstance(item, dict) and item.get("asset_id")),
                key=lambda item: (
                    {"front": 0, "back": 1, "detail": 2}.get(str(item.get("view_role") or ""), 9),
                    int(item.get("sort_order") or 0),
                ),
            )
            limit = 2 if product.get("product_role") == "PRIMARY" else 1
            for asset in ordered[:limit]:
                asset_id = str(asset["asset_id"])
                grouped["PRODUCT"].append(asset_id)
                add_execution_asset(
                    asset_id=asset_id, slot_type="PRODUCT", product=product,
                    view_role=str(asset.get("view_role") or "front"),
                )
            if product.get("product_role") == "PRIMARY":
                for reference in [item for item in refs if item.slot_type == "PRINT"][:1]:
                    grouped["PRINT"].append(reference.asset_id)
                    add_execution_asset(
                        asset_id=reference.asset_id, slot_type="PRINT", product=product,
                        view_role="print",
                    )
    else:
        explicit_product = [item.asset_id for item in refs if item.slot_type == "PRODUCT"]
        grouped["PRODUCT"] = explicit_product or [item.asset_id for item in effective_products]
        primary = next((item for item in products if isinstance(item, dict) and item.get("product_role") == "PRIMARY"), None)
        for asset_id in grouped["PRODUCT"]:
            add_execution_asset(asset_id=asset_id, slot_type="PRODUCT", product=primary)
    for item in refs:
        if item.slot_type not in {"PRODUCT", "PRINT"}:
            grouped[item.slot_type].append(item.asset_id)
    if product_mode != "MULTI":
        for item in [row for row in refs if row.slot_type == "PRINT"]:
            grouped["PRINT"].append(item.asset_id)
            add_execution_asset(asset_id=item.asset_id, slot_type="PRINT", product=primary)
    for slot_type, limit in (("TEMPLATE", 1), ("SCENE", 1), ("OTHER", 1)):
        grouped[slot_type] = grouped[slot_type][:limit] if product_mode == "MULTI" else grouped[slot_type]
        for asset_id in grouped[slot_type]:
            add_execution_asset(asset_id=asset_id, slot_type=slot_type)
    grouped = {key: list(dict.fromkeys(value)) for key, value in grouped.items()}
    snapshot = {
        "module_key": module.module_key,
        "reference_state_version": module.reference_state_version,
        "roles": grouped,
        "priority": ["PRODUCT", "PRINT", "TEMPLATE", "SCENE", "OTHER"],
        "product_mode": product_mode,
        "product_count": 1 if product_mode == "SINGLE" else len(products),
        "model_count": 1 if product_mode == "SINGLE" else len(products),
        "product_composition_id": composition.id if composition else None,
        "product_composition_version_id": composition_version.id if composition_version else None,
        "product_composition_version_number": composition_version.version_number if composition_version else None,
        "products": products,
        "execution_order": execution_order,
        "reference_options": reference_options,
    }
    return grouped, snapshot


def build_reference_analysis_input(
    module_key: str, grouped: dict[str, list[str]], snapshot: dict[str, object] | None = None,
) -> tuple[str, str, list[str]]:
    execution_order = (snapshot or {}).get("execution_order")
    descriptors = execution_order if isinstance(execution_order, list) else []
    references = [str(item.get("asset_id")) for item in descriptors if isinstance(item, dict) and item.get("asset_id")]
    if not references:
        descriptors = []
        for slot in ("PRODUCT", "PRINT", "TEMPLATE", "SCENE", "OTHER"):
            for asset_id in grouped.get(slot, []):
                references.append(asset_id)
                descriptors.append({"image_index": len(references), "slot_type": slot, "asset_id": asset_id})
    user_prompt = json.dumps({
        "module_key": module_key,
        "product_mode": (snapshot or {}).get("product_mode", "SINGLE"),
        "product_composition": (snapshot or {}).get("products", []),
        "images_in_submission_order": descriptors,
        "role_semantics": {
            "PRODUCT": "决定商品外观，是最高优先级事实来源",
            "TEMPLATE": "只参考构图和摆放，不继承旧商品",
            "SCENE": "只参考氛围和环境",
            "PRINT": "保持字形、号码和图形的视觉结构",
            "OTHER": "补充局部细节",
        },
        "reference_keywords_and_guidance": (snapshot or {}).get("reference_options", []),
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
    if snapshot.get("product_mode") == "MULTI" and not 2 <= int(snapshot.get("product_count") or 0) <= 3:
        raise AppError("attachment_composition.product_count_invalid", "多件商品模式需要2到3件商品", 409)
    system_prompt, user_prompt, references = build_reference_analysis_input(module.module_key, grouped, snapshot)
    input_hash = sha256(json.dumps({
        "prompt_version": REFERENCE_ANALYSIS_PROMPT_VERSION,
        "model_policy_version": REFERENCE_ANALYSIS_POLICY_VERSION,
        "module_key": module.module_key,
        "roles": snapshot.get("roles"), "product_composition_version_id": snapshot.get("product_composition_version_id"),
        "reference_options": snapshot.get("reference_options"),
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    fresh = await db.scalar(select(AttachmentReferenceUnderstanding).where(
        AttachmentReferenceUnderstanding.module_plan_id == module.id,
        AttachmentReferenceUnderstanding.input_hash == input_hash,
        AttachmentReferenceUnderstanding.status.in_(["analyzing", "ready"]),
    ).order_by(AttachmentReferenceUnderstanding.version_number.desc()).limit(1))
    if fresh and fresh.ai_job_id:
        existing_job = await db.get(Job, fresh.ai_job_id)
        if existing_job:
            module.reference_analysis_job_id = existing_job.id if fresh.status == "analyzing" else None
            if fresh.status == "ready":
                module.reference_context_dirty = False
            return existing_job, fresh, False
    route = await resolve_ai_task_route(
        db, organization_id=project.organization_id, task_type="REFERENCE_ANALYSIS", capability="text_generation",
    )
    job, created = await submit_job(
        db, settings, organization_id=project.organization_id, user_id=user_id,
        payload=JobSubmitRequest(
            operation_code=route.operation_code, workspace_type="listing", queue_name="planning_queue",
            capability="text_generation", model_code=route.model_code, project_id=None,
            input={
                "system_prompt": system_prompt, "user_prompt": user_prompt,
                "response_format": "json_object", "reference_asset_ids": references,
                "metadata": {
                    "workflow": "attachment_reference_understanding", "action": "analyze_reference",
                    "module_plan_id": module.id, "module_key": module.module_key,
                    "analysis_task_type": route.task_type, "analysis_input_hash": input_hash,
                    "analysis_prompt_version": REFERENCE_ANALYSIS_PROMPT_VERSION,
                    "analysis_model_policy_version": REFERENCE_ANALYSIS_POLICY_VERSION,
                    "analysis_attempt": 1, "analysis_fallback": route.used_fallback_binding,
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
        source_snapshot_json=snapshot, ai_job_id=job.id,
        input_hash=input_hash, analysis_task_type=route.task_type,
        analysis_model_config={"operation_code": route.operation_code, "model_code": route.model_code, "fallback_binding": route.used_fallback_binding},
        analysis_prompt_version=REFERENCE_ANALYSIS_PROMPT_VERSION,
        role_snapshot=dict(snapshot.get("roles") or {}),
        keywords_snapshot={str(item.get("reference_id")): list(item.get("keywords") or []) for item in snapshot.get("reference_options", []) if isinstance(item, dict)},
        guidance_snapshot={str(item.get("reference_id")): str(item.get("guidance") or "") for item in snapshot.get("reference_options", []) if isinstance(item, dict)},
        product_composition_version_id=snapshot.get("product_composition_version_id"),
        created_by=user_id,
    )
    db.add(understanding)
    module.reference_analysis_job_id = job.id
    await db.flush()
    return job, understanding, created


async def reconcile_reference_understandings(
    db: AsyncSession, settings: Settings, *, plan: AttachmentWorkbenchPlan, modules: list[AttachmentWorkbenchModulePlan],
) -> int:
    retry_jobs_created = 0
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
        _, current_snapshot = await effective_reference_snapshot(db, plan=plan, module=module)
        if (
            current_snapshot.get("roles") != understanding.source_snapshot_json.get("roles")
            or current_snapshot.get("product_composition_version_id")
            != understanding.source_snapshot_json.get("product_composition_version_id")
            or current_snapshot.get("reference_options")
            != understanding.source_snapshot_json.get("reference_options")
        ):
            understanding.status = "stale"
            module.reference_context_dirty = True
            if module.reference_analysis_job_id == job.id:
                module.reference_analysis_job_id = None
            continue
        metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
        metadata = metadata if isinstance(metadata, dict) else {}
        attempt = int(metadata.get("analysis_attempt") or 1)
        fallback_used = bool(metadata.get("analysis_fallback"))
        retry_reason: str | None = None
        if job.status == JobStatus.SUCCEEDED.value:
            try:
                text = str((job.result_json or {}).get("metadata", {}).get("text") or "")
                parsed = parse_reference_understanding(text)
                if understanding.source_snapshot_json.get("product_mode") == "MULTI":
                    parsed_products = parsed.get("products")
                    expected_count = int(understanding.source_snapshot_json.get("product_count") or 0)
                    if not isinstance(parsed_products, list) or len(parsed_products) != expected_count:
                        raise AppError(
                            "attachment_reference.multi_product_result_invalid",
                            "AI未按商品组合逐件返回理解结果，请重新分析", 422,
                        )
                understanding.structured_json = parsed
                understanding.ai_model = job.model_code
                understanding.status = "ready"
                module.reference_context_dirty = False
            except AppError as error:
                retry_reason = error.message
        else:
            retry_reason = job.error_message or "参考素材分析失败，可重试"
        if retry_reason:
            decision = next_analysis_retry(attempt=attempt, fallback_used=fallback_used)
            if decision is not None:
                next_attempt = decision.attempt
                use_fallback = decision.use_fallback
                system_prompt, user_prompt, references = build_reference_analysis_input(
                    module.module_key, (await effective_reference_snapshot(db, plan=plan, module=module))[0], current_snapshot,
                )
                route = await resolve_ai_task_route(
                    db, organization_id=plan.organization_id,
                    task_type="MODULE_PLANNING" if use_fallback else "REFERENCE_ANALYSIS",
                    capability="text_generation",
                )
                retry_job, created = await submit_job(
                    db, settings, organization_id=plan.organization_id, user_id=understanding.created_by,
                    payload=JobSubmitRequest(
                        operation_code=route.operation_code, workspace_type="listing", queue_name="planning_queue",
                        capability="text_generation", model_code=route.model_code, project_id=None,
                        input={
                            "system_prompt": system_prompt, "user_prompt": user_prompt,
                            "response_format": "json_object", "reference_asset_ids": references,
                            "metadata": {
                                "workflow": "attachment_reference_understanding", "action": "analyze_reference",
                                "module_plan_id": module.id, "module_key": module.module_key,
                                "analysis_task_type": "REFERENCE_ANALYSIS", "analysis_input_hash": understanding.input_hash,
                                "analysis_attempt": next_attempt, "analysis_fallback": use_fallback,
                                "analysis_prompt_version": REFERENCE_ANALYSIS_PROMPT_VERSION,
                                "analysis_model_policy_version": REFERENCE_ANALYSIS_POLICY_VERSION,
                                "retry_reason": retry_reason[:300],
                            },
                        },
                        idempotency_key=f"attachment-reference:{understanding.id}:attempt:{next_attempt}",
                        billing_factors={"workspace": "attachment_reference_understanding", "module_key": module.module_key},
                    ),
                )
                understanding.ai_job_id = retry_job.id
                understanding.ai_model = route.model_code
                understanding.analysis_model_config = {
                    **dict(understanding.analysis_model_config or {}),
                    "last_operation_code": route.operation_code, "last_model_code": route.model_code,
                    "attempt": next_attempt, "fallback": use_fallback,
                }
                understanding.error_message = retry_reason
                module.reference_analysis_job_id = retry_job.id
                retry_jobs_created += int(created)
                continue
            understanding.status = "failed"
            understanding.error_message = retry_reason
            module.reference_context_dirty = True
        if module.reference_analysis_job_id == job.id:
            module.reference_analysis_job_id = None
    return retry_jobs_created


async def current_understanding_context(
    db: AsyncSession, module: AttachmentWorkbenchModulePlan,
) -> tuple[str | None, dict[str, object] | None]:
    if module.reference_context_dirty:
        return None, None
    row = await latest_reference_understanding(db, module.id, ready_only=True)
    return (row.id, dict(row.structured_json or {})) if row else (None, None)
