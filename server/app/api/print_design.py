from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.content import Asset
from app.models.print_design import PrintAssetGroup, PrintAssetLibraryItem, ProductPrintMapping
from app.schemas.print_design import (
    PrintAssetCreate, PrintAssetGroupCreate, PrintAssetGroupResponse, PrintAssetGroupUpdate,
    PrintAssetPage, PrintAssetResponse, PrintAssetUpdate, ProductPrintMappingCreate,
    ProductPrintMappingResponse,
)
from app.security.principal import Principal, require_permissions
from app.services.asset_service import get_asset, signed_asset_response
from app.services.audit_service import add_audit_log
from app.services.storage_service import StorageService, get_storage_service


router = APIRouter(prefix="/print-design", tags=["print-design"])


def organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队。", 409)
    return principal.organization.id


def _admins_only(principal: Principal) -> None:
    if not principal.role_codes.intersection({"platform_admin", "organization_admin"}):
        raise AppError("print_design.admin_required", "只有管理员可以维护印花素材组和 SKU 映射。", 403)


@router.get("/asset-groups", response_model=list[PrintAssetGroupResponse])
async def list_groups(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> list[PrintAssetGroupResponse]:
    rows = list((await session.scalars(select(PrintAssetGroup).where(
        PrintAssetGroup.organization_id == organization_id(principal)
    ).order_by(PrintAssetGroup.name))).all())
    return [PrintAssetGroupResponse.model_validate(row, from_attributes=True) for row in rows]


@router.post("/asset-groups", response_model=PrintAssetGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: PrintAssetGroupCreate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("assets.upload")),
) -> PrintAssetGroupResponse:
    _admins_only(principal)
    org_id = organization_id(principal)
    existing = await session.scalar(select(PrintAssetGroup.id).where(
        PrintAssetGroup.organization_id == org_id, PrintAssetGroup.code == payload.code,
    ))
    if existing:
        raise AppError("print_design.group_code_conflict", "印花素材组编码已存在。", 409)
    row = PrintAssetGroup(
        organization_id=org_id, code=payload.code, name=payload.name.strip(),
        product_type=payload.product_type, remark=payload.remark,
        created_by=principal.user.id, updated_by=principal.user.id,
    )
    session.add(row)
    await session.flush()
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                  action="print_design.asset_group.create", resource_type="print_asset_group", resource_id=row.id)
    await session.commit()
    await session.refresh(row)
    return PrintAssetGroupResponse.model_validate(row, from_attributes=True)


async def _get_group(session: AsyncSession, org_id: str, group_id: str) -> PrintAssetGroup:
    row = await session.scalar(select(PrintAssetGroup).where(
        PrintAssetGroup.id == group_id, PrintAssetGroup.organization_id == org_id,
    ))
    if row is None:
        raise AppError("print_design.group_not_found", "印花素材组不存在。", 404)
    return row


@router.get("/asset-groups/{group_id}", response_model=PrintAssetGroupResponse)
async def get_group(
    group_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> PrintAssetGroupResponse:
    row = await _get_group(session, organization_id(principal), group_id)
    return PrintAssetGroupResponse.model_validate(row, from_attributes=True)


@router.patch("/asset-groups/{group_id}", response_model=PrintAssetGroupResponse)
async def update_group(
    group_id: str,
    payload: PrintAssetGroupUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("assets.upload")),
) -> PrintAssetGroupResponse:
    _admins_only(principal)
    org_id = organization_id(principal)
    row = await _get_group(session, org_id, group_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value.strip() if isinstance(value, str) else value)
    row.updated_by = principal.user.id
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                  action="print_design.asset_group.update", resource_type="print_asset_group", resource_id=row.id)
    await session.commit()
    await session.refresh(row)
    return PrintAssetGroupResponse.model_validate(row, from_attributes=True)


async def _asset_response(
    row: PrintAssetLibraryItem, asset: Asset, storage: StorageService, settings: Settings,
) -> PrintAssetResponse:
    return PrintAssetResponse(
        id=row.id, asset_group_id=row.asset_group_id, asset_code=row.asset_code,
        asset_name=row.asset_name, asset_type=row.asset_type, category=row.category,
        tags=list(row.tags_json or []), default_position=row.default_position_json,
        allow_rotate=row.allow_rotate, allow_stretch=row.allow_stretch,
        keep_ratio_default=row.keep_ratio_default, version=row.version, status=row.status,
        created_at=row.created_at, updated_at=row.updated_at,
        asset=await signed_asset_response(asset, storage, settings),
    )


async def _get_library_item(session: AsyncSession, org_id: str, item_id: str) -> PrintAssetLibraryItem:
    row = await session.scalar(select(PrintAssetLibraryItem).where(
        PrintAssetLibraryItem.id == item_id, PrintAssetLibraryItem.organization_id == org_id,
    ))
    if row is None:
        raise AppError("print_design.asset_not_found", "印花素材不存在。", 404)
    return row


@router.get("/assets", response_model=PrintAssetPage)
async def list_print_assets(
    search: str | None = Query(default=None, max_length=160),
    group_id: str | None = None,
    limit: int = Query(default=80, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> PrintAssetPage:
    org_id = organization_id(principal)
    filters = [PrintAssetLibraryItem.organization_id == org_id, PrintAssetLibraryItem.status == "active"]
    if group_id:
        filters.append(PrintAssetLibraryItem.asset_group_id == group_id)
    if search:
        needle = f"%{search.strip()}%"
        filters.append(or_(
            PrintAssetLibraryItem.asset_code.like(needle),
            PrintAssetLibraryItem.asset_name.like(needle),
            cast(PrintAssetLibraryItem.tags_json, String).like(needle),
        ))
    total = int(await session.scalar(select(func.count()).select_from(PrintAssetLibraryItem).where(*filters)) or 0)
    rows = (await session.execute(
        select(PrintAssetLibraryItem, Asset).join(Asset, Asset.id == PrintAssetLibraryItem.asset_id)
        .where(*filters, Asset.deleted_at.is_(None))
        .order_by(PrintAssetLibraryItem.updated_at.desc()).limit(limit)
    )).all()
    return PrintAssetPage(items=[await _asset_response(row, asset, storage, settings) for row, asset in rows], total=total)


@router.post("/assets", response_model=PrintAssetResponse, status_code=status.HTTP_201_CREATED)
async def register_print_asset(
    payload: PrintAssetCreate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.upload")),
) -> PrintAssetResponse:
    org_id = organization_id(principal)
    asset = await get_asset(session, org_id, payload.asset_id)
    if asset.category != "print_asset":
        raise AppError("print_design.invalid_asset_category", "只有印花素材类型的图片可以加入印花库。", 422)
    if payload.asset_group_id:
        group = await session.scalar(select(PrintAssetGroup.id).where(
            PrintAssetGroup.id == payload.asset_group_id, PrintAssetGroup.organization_id == org_id,
        ))
        if not group:
            raise AppError("print_design.group_not_found", "印花素材组不存在。", 404)
    row = PrintAssetLibraryItem(
        organization_id=org_id, asset_id=asset.id, asset_group_id=payload.asset_group_id,
        asset_code=payload.asset_code, asset_name=payload.asset_name.strip(), asset_type=payload.asset_type,
        category=payload.category, tags_json=[tag.strip()[:60] for tag in payload.tags if tag.strip()],
        default_position_json=payload.default_position, allow_rotate=payload.allow_rotate,
        allow_stretch=payload.allow_stretch, keep_ratio_default=payload.keep_ratio_default,
        version=payload.version, status="active", created_by=principal.user.id, updated_by=principal.user.id,
    )
    session.add(row)
    try:
        await session.flush()
    except Exception as error:
        await session.rollback()
        raise AppError("print_design.asset_conflict", "印花素材编码版本或图片已存在。", 409) from error
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                  action="print_design.asset.register", resource_type="print_asset", resource_id=row.id,
                  metadata={"asset_id": asset.id, "asset_code": row.asset_code, "version": row.version})
    await session.commit()
    await session.refresh(row)
    return await _asset_response(row, asset, storage, settings)


@router.get("/assets/{item_id}", response_model=PrintAssetResponse)
async def get_print_asset(
    item_id: str,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> PrintAssetResponse:
    row = await _get_library_item(session, organization_id(principal), item_id)
    asset = await get_asset(session, organization_id(principal), row.asset_id)
    return await _asset_response(row, asset, storage, settings)


@router.patch("/assets/{item_id}", response_model=PrintAssetResponse)
async def update_print_asset(
    item_id: str,
    payload: PrintAssetUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.upload")),
) -> PrintAssetResponse:
    org_id = organization_id(principal)
    row = await _get_library_item(session, org_id, item_id)
    values = payload.model_dump(exclude_unset=True)
    if "asset_group_id" in values and values["asset_group_id"]:
        await _get_group(session, org_id, str(values["asset_group_id"]))
    if "tags" in values:
        values["tags_json"] = [tag.strip()[:60] for tag in values.pop("tags") if tag.strip()]
    if "default_position" in values:
        values["default_position_json"] = values.pop("default_position")
    for key, value in values.items():
        setattr(row, key, value.strip() if isinstance(value, str) else value)
    row.updated_by = principal.user.id
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                  action="print_design.asset.update", resource_type="print_asset", resource_id=row.id)
    await session.commit()
    await session.refresh(row)
    asset = await get_asset(session, org_id, row.asset_id)
    return await _asset_response(row, asset, storage, settings)


@router.delete("/assets/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_print_asset(
    item_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("assets.upload")),
) -> None:
    org_id = organization_id(principal)
    row = await _get_library_item(session, org_id, item_id)
    row.status = "archived"
    row.updated_by = principal.user.id
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                  action="print_design.asset.archive", resource_type="print_asset", resource_id=row.id)
    await session.commit()


@router.post("/product-mappings", response_model=ProductPrintMappingResponse, status_code=status.HTTP_201_CREATED)
async def create_mapping(
    payload: ProductPrintMappingCreate,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("assets.upload")),
) -> ProductPrintMappingResponse:
    _admins_only(principal)
    org_id = organization_id(principal)
    await _get_group(session, org_id, payload.asset_group_id)
    row = ProductPrintMapping(
        organization_id=org_id, sku=payload.sku.strip(), asset_group_id=payload.asset_group_id,
        product_code=payload.product_code, style_code=payload.style_code, template_code=payload.template_code,
        created_by=principal.user.id, updated_by=principal.user.id,
    )
    session.add(row)
    try:
        await session.commit()
    except Exception as error:
        await session.rollback()
        raise AppError("print_design.mapping_conflict", "该编号已绑定这个素材组。", 409) from error
    await session.refresh(row)
    return ProductPrintMappingResponse.model_validate(row, from_attributes=True)


@router.get("/product-mappings", response_model=list[ProductPrintMappingResponse])
async def list_mappings(
    sku: str | None = Query(default=None, max_length=160),
    code: str | None = Query(default=None, max_length=160),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> list[ProductPrintMappingResponse]:
    query = select(ProductPrintMapping).where(ProductPrintMapping.organization_id == organization_id(principal))
    if sku:
        query = query.where(ProductPrintMapping.sku == sku)
    if code:
        value = code.strip()
        query = query.where(or_(
            ProductPrintMapping.sku == value,
            ProductPrintMapping.product_code == value,
            ProductPrintMapping.style_code == value,
            ProductPrintMapping.template_code == value,
        ))
    rows = list((await session.scalars(query.order_by(ProductPrintMapping.updated_at.desc()))).all())
    return [ProductPrintMappingResponse.model_validate(row, from_attributes=True) for row in rows]


@router.delete("/product-mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping(
    mapping_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("assets.upload")),
) -> None:
    _admins_only(principal)
    row = await session.scalar(select(ProductPrintMapping).where(
        ProductPrintMapping.id == mapping_id,
        ProductPrintMapping.organization_id == organization_id(principal),
    ))
    if row is None:
        raise AppError("print_design.mapping_not_found", "产品印花映射不存在。", 404)
    await session.delete(row)
    await session.commit()
