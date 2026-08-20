from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.attachment_planning import (
    AttachmentProductComposition,
    AttachmentProductCompositionAsset,
    AttachmentProductCompositionItem,
    AttachmentProductCompositionVersion,
    AttachmentProductReferenceItem,
    AttachmentWorkbenchModulePlan,
)
from app.models.content import Asset
from app.models.listing_workflow import ListingGenerationSession, ProductCategory


UTC = timezone.utc
PRODUCT_MODES = {"SINGLE", "MULTI"}
PRODUCT_ROLES = {"PRIMARY", "SECONDARY"}
MAX_PRODUCTS = 3


def _localized(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("zh") or value.get("en") or "").strip()
    return ""


def _session_name(session: ListingGenerationSession) -> str:
    listing = session.listing_content if isinstance(session.listing_content, dict) else {}
    title = _localized(listing.get("title"))
    return title or f"商品 {session.id[:8]}"


async def _category_name(db: AsyncSession, session: ListingGenerationSession) -> str:
    category = await db.get(ProductCategory, session.category_id)
    return category.category_name if category else ""


async def _items_and_assets(
    db: AsyncSession, composition_id: str,
) -> tuple[list[AttachmentProductCompositionItem], dict[str, list[AttachmentProductCompositionAsset]]]:
    items = list((await db.scalars(select(AttachmentProductCompositionItem).where(
        AttachmentProductCompositionItem.composition_id == composition_id,
    ).order_by(AttachmentProductCompositionItem.display_order, AttachmentProductCompositionItem.created_at))).all())
    item_ids = [item.id for item in items]
    assets = list((await db.scalars(select(AttachmentProductCompositionAsset).where(
        AttachmentProductCompositionAsset.composition_item_id.in_(item_ids),
    ).order_by(AttachmentProductCompositionAsset.sort_order, AttachmentProductCompositionAsset.created_at))).all()) if item_ids else []
    grouped: dict[str, list[AttachmentProductCompositionAsset]] = {item.id: [] for item in items}
    for asset in assets:
        grouped.setdefault(asset.composition_item_id, []).append(asset)
    return items, grouped


async def composition_snapshot(
    db: AsyncSession, composition: AttachmentProductComposition,
) -> dict[str, object]:
    items, assets_by_item = await _items_and_assets(db, composition.id)
    return {
        "composition_id": composition.id,
        "mode": composition.mode,
        "product_count": 1 if composition.mode == "SINGLE" else len(items),
        "model_count": 1 if composition.mode == "SINGLE" else len(items),
        "products": [{
            "product_entry_id": item.id,
            "product_role": item.product_role,
            "display_order": item.display_order,
            "display_name": item.display_name_snapshot,
            "category_name": item.category_name_snapshot,
            "source_session_id": item.source_session_id,
            "source_project_id": item.source_project_id,
            "assets": [{
                "composition_asset_id": asset.id,
                "asset_id": asset.asset_id,
                "source_asset_id": asset.source_asset_id,
                "view_role": asset.view_role,
                "sort_order": asset.sort_order,
            } for asset in assets_by_item.get(item.id, [])],
        } for item in items],
    }


async def _create_version(
    db: AsyncSession, *, composition: AttachmentProductComposition, user_id: str,
) -> AttachmentProductCompositionVersion:
    snapshot = await composition_snapshot(db, composition)
    number = composition.current_version_number + 1
    version = AttachmentProductCompositionVersion(
        organization_id=composition.organization_id,
        composition_id=composition.id,
        version_number=number,
        mode=composition.mode,
        snapshot_json=snapshot,
        created_by=user_id,
    )
    db.add(version)
    composition.current_version_number = number
    composition.updated_by = user_id
    await db.flush()
    return version


async def current_composition_version(
    db: AsyncSession, composition: AttachmentProductComposition,
) -> AttachmentProductCompositionVersion:
    version = await db.scalar(select(AttachmentProductCompositionVersion).where(
        AttachmentProductCompositionVersion.composition_id == composition.id,
        AttachmentProductCompositionVersion.version_number == composition.current_version_number,
    ))
    if version is None:
        raise AppError("attachment_composition.version_missing", "商品组合版本不存在，请刷新后重试", 409)
    return version


def _mark_module_stale(module: AttachmentWorkbenchModulePlan, user_id: str) -> None:
    module.reference_context_dirty = True
    module.reference_state_version += 1
    module.status = "stale" if module.current_version_number > 0 else "draft"
    module.error_message = "商品组合已更新，需要重新分析并策划后生成。"
    module.state_version += 1
    module.updated_by = user_id
    module.last_saved_at = datetime.now(UTC)


async def _replace_item_assets(
    db: AsyncSession, *, item: AttachmentProductCompositionItem,
    rows: list[dict[str, object]], user_id: str,
) -> None:
    await db.execute(delete(AttachmentProductCompositionAsset).where(
        AttachmentProductCompositionAsset.composition_item_id == item.id,
    ))
    for index, row in enumerate(rows):
        db.add(AttachmentProductCompositionAsset(
            organization_id=item.organization_id,
            composition_item_id=item.id,
            asset_id=str(row["asset_id"]),
            source_asset_id=str(row.get("source_asset_id") or "") or None,
            view_role=str(row.get("view_role") or "front"),
            sort_order=index,
            metadata_json=dict(row.get("metadata") or {}),
            created_by=user_id,
            updated_by=user_id,
        ))
    await db.flush()


async def ensure_product_composition(
    db: AsyncSession, *, module: AttachmentWorkbenchModulePlan,
    session: ListingGenerationSession, product_references: list[AttachmentProductReferenceItem], user_id: str,
) -> AttachmentProductComposition:
    composition = await db.scalar(select(AttachmentProductComposition).where(
        AttachmentProductComposition.module_plan_id == module.id,
        AttachmentProductComposition.organization_id == module.organization_id,
    ).with_for_update())
    created = composition is None
    if composition is None:
        composition = AttachmentProductComposition(
            organization_id=module.organization_id,
            module_plan_id=module.id,
            mode="SINGLE",
            current_version_number=0,
            state_version=0,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(composition)
        await db.flush()
    items, assets_by_item = await _items_and_assets(db, composition.id)
    primary = next((item for item in items if item.product_role == "PRIMARY"), None)
    if primary is None:
        primary = AttachmentProductCompositionItem(
            organization_id=module.organization_id,
            composition_id=composition.id,
            product_role="PRIMARY",
            source_session_id=session.id,
            source_project_id=session.project_id,
            display_name_snapshot=_session_name(session),
            category_name_snapshot=await _category_name(db, session),
            display_order=0,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(primary)
        await db.flush()
        assets_by_item[primary.id] = []
        created = True
    desired = [{
        "asset_id": ref.asset_id,
        "source_asset_id": ref.source_asset_id,
        "view_role": ref.view_role,
        "metadata": dict(ref.transform_metadata or {}),
    } for ref in product_references]
    current = [(row.asset_id, row.source_asset_id, row.view_role) for row in assets_by_item.get(primary.id, [])]
    target = [(str(row["asset_id"]), row.get("source_asset_id"), str(row["view_role"])) for row in desired]
    if current != target:
        await _replace_item_assets(db, item=primary, rows=desired, user_id=user_id)
        if not created:
            composition.state_version += 1
            _mark_module_stale(module, user_id)
        created = True
    if composition.current_version_number == 0 or created:
        await _create_version(db, composition=composition, user_id=user_id)
    return composition


async def get_product_composition(
    db: AsyncSession, *, module: AttachmentWorkbenchModulePlan, lock: bool = False,
) -> AttachmentProductComposition:
    statement = select(AttachmentProductComposition).where(
        AttachmentProductComposition.module_plan_id == module.id,
        AttachmentProductComposition.organization_id == module.organization_id,
    )
    if lock:
        statement = statement.with_for_update()
    composition = await db.scalar(statement)
    if composition is None:
        raise AppError("attachment_composition.missing", "商品组合尚未初始化，请刷新后重试", 409)
    return composition


async def set_product_mode(
    db: AsyncSession, *, module: AttachmentWorkbenchModulePlan, mode: str,
    expected_state_version: int, user_id: str, supports_multi_product: bool,
) -> AttachmentProductComposition:
    value = mode.upper()
    if value not in PRODUCT_MODES:
        raise AppError("attachment_composition.mode_invalid", "商品模式无效", 422)
    if value == "MULTI" and not supports_multi_product:
        raise AppError("attachment_composition.mode_unsupported", "当前模块不支持多件商品", 422)
    composition = await get_product_composition(db, module=module, lock=True)
    if composition.state_version != expected_state_version:
        raise AppError(
            "attachment_composition.state_version_conflict", "商品组合已被其他页面更新，请刷新后重试", 409,
            {"expected": expected_state_version, "actual": composition.state_version},
        )
    if composition.mode != value:
        composition.mode = value
        composition.state_version += 1
        _mark_module_stale(module, user_id)
        await _create_version(db, composition=composition, user_id=user_id)
    return composition


async def _validated_source_session(
    db: AsyncSession, *, organization_id: str, source_session_id: str,
) -> ListingGenerationSession:
    session = await db.scalar(select(ListingGenerationSession).where(
        ListingGenerationSession.id == source_session_id,
        ListingGenerationSession.organization_id == organization_id,
    ))
    if session is None:
        raise AppError("attachment_composition.source_not_found", "商品不存在或无权访问", 404)
    if not session.confirmed_at or not session.primary_asset_id:
        raise AppError("attachment_composition.source_not_ready", "只能选择已确认且具有商品主图的商品", 409)
    asset = await db.scalar(select(Asset).where(
        Asset.id == session.primary_asset_id,
        Asset.organization_id == organization_id,
        Asset.deleted_at.is_(None),
    ))
    if asset is None:
        raise AppError("attachment_composition.asset_not_found", "所选商品主图不存在或无权访问", 404)
    return session


async def add_secondary_product(
    db: AsyncSession, *, module: AttachmentWorkbenchModulePlan, source_session_id: str,
    expected_state_version: int, user_id: str,
) -> AttachmentProductComposition:
    composition = await get_product_composition(db, module=module, lock=True)
    if composition.state_version != expected_state_version:
        raise AppError("attachment_composition.state_version_conflict", "商品组合已被更新，请刷新后重试", 409)
    if composition.mode != "MULTI":
        raise AppError("attachment_composition.multi_required", "请先切换到多件商品模式", 409)
    items, _ = await _items_and_assets(db, composition.id)
    if any(item.source_session_id == source_session_id for item in items):
        raise AppError("attachment_composition.product_duplicate", "同一商品不能重复选择", 422)
    secondaries = [item for item in items if item.product_role == "SECONDARY"]
    if len(secondaries) >= 2:
        raise AppError("attachment_composition.product_limit", "最多添加2件附加商品", 422)
    session = await _validated_source_session(
        db, organization_id=composition.organization_id, source_session_id=source_session_id,
    )
    item = AttachmentProductCompositionItem(
        organization_id=composition.organization_id,
        composition_id=composition.id,
        product_role="SECONDARY",
        source_session_id=session.id,
        source_project_id=session.project_id,
        display_name_snapshot=_session_name(session),
        category_name_snapshot=await _category_name(db, session),
        display_order=len(secondaries) + 1,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(item)
    await db.flush()
    await _replace_item_assets(db, item=item, rows=[{
        "asset_id": session.primary_asset_id,
        "source_asset_id": session.primary_asset_id,
        "view_role": "front",
    }], user_id=user_id)
    composition.state_version += 1
    _mark_module_stale(module, user_id)
    await _create_version(db, composition=composition, user_id=user_id)
    return composition


async def replace_secondary_product(
    db: AsyncSession, *, module: AttachmentWorkbenchModulePlan, item_id: str,
    source_session_id: str, expected_state_version: int, user_id: str,
) -> AttachmentProductComposition:
    composition = await get_product_composition(db, module=module, lock=True)
    if composition.state_version != expected_state_version:
        raise AppError("attachment_composition.state_version_conflict", "商品组合已被更新，请刷新后重试", 409)
    items, _ = await _items_and_assets(db, composition.id)
    item = next((row for row in items if row.id == item_id and row.product_role == "SECONDARY"), None)
    if item is None:
        raise AppError("attachment_composition.item_not_found", "附加商品不存在", 404)
    if any(row.id != item.id and row.source_session_id == source_session_id for row in items):
        raise AppError("attachment_composition.product_duplicate", "同一商品不能重复选择", 422)
    session = await _validated_source_session(
        db, organization_id=composition.organization_id, source_session_id=source_session_id,
    )
    item.source_session_id = session.id
    item.source_project_id = session.project_id
    item.display_name_snapshot = _session_name(session)
    item.category_name_snapshot = await _category_name(db, session)
    item.updated_by = user_id
    await _replace_item_assets(db, item=item, rows=[{
        "asset_id": session.primary_asset_id,
        "source_asset_id": session.primary_asset_id,
        "view_role": "front",
    }], user_id=user_id)
    composition.state_version += 1
    _mark_module_stale(module, user_id)
    await _create_version(db, composition=composition, user_id=user_id)
    return composition


async def remove_secondary_product(
    db: AsyncSession, *, module: AttachmentWorkbenchModulePlan, item_id: str,
    expected_state_version: int, user_id: str,
) -> AttachmentProductComposition:
    composition = await get_product_composition(db, module=module, lock=True)
    if composition.state_version != expected_state_version:
        raise AppError("attachment_composition.state_version_conflict", "商品组合已被更新，请刷新后重试", 409)
    item = await db.scalar(select(AttachmentProductCompositionItem).where(
        AttachmentProductCompositionItem.id == item_id,
        AttachmentProductCompositionItem.composition_id == composition.id,
        AttachmentProductCompositionItem.product_role == "SECONDARY",
    ))
    if item is None:
        raise AppError("attachment_composition.item_not_found", "附加商品不存在", 404)
    await db.delete(item)
    await db.flush()
    remaining = list((await db.scalars(select(AttachmentProductCompositionItem).where(
        AttachmentProductCompositionItem.composition_id == composition.id,
        AttachmentProductCompositionItem.product_role == "SECONDARY",
    ).order_by(AttachmentProductCompositionItem.display_order))).all())
    for index, row in enumerate(remaining, 1):
        row.display_order = index
    composition.state_version += 1
    _mark_module_stale(module, user_id)
    await _create_version(db, composition=composition, user_id=user_id)
    return composition


async def validate_active_composition(
    db: AsyncSession, *, module: AttachmentWorkbenchModulePlan, supports_multi_product: bool,
) -> tuple[AttachmentProductComposition, AttachmentProductCompositionVersion, dict[str, object]]:
    composition = await get_product_composition(db, module=module)
    version = await current_composition_version(db, composition)
    snapshot = dict(version.snapshot_json or {})
    products = snapshot.get("products") if isinstance(snapshot.get("products"), list) else []
    if not products or sum(1 for item in products if item.get("product_role") == "PRIMARY") != 1:
        raise AppError("attachment_composition.primary_invalid", "商品组合必须包含唯一主商品", 409)
    if composition.mode == "MULTI":
        if not supports_multi_product:
            raise AppError("attachment_composition.mode_unsupported", "当前模块不支持多件商品", 422)
        if not 2 <= len(products) <= MAX_PRODUCTS:
            raise AppError("attachment_composition.product_count_invalid", "多件商品模式需要2到3件商品", 409)
        if sum(1 for item in products if item.get("product_role") == "SECONDARY") > 2:
            raise AppError("attachment_composition.secondary_limit", "附加商品最多2件", 409)
    return composition, version, snapshot
