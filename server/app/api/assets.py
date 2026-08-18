import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.schemas.content import (
    AssetCategoryValue,
    AssetPage,
    AssetResponse,
    AssetUrlResponse,
    GeneratedAssetCategoryValue,
)
from app.security.principal import Principal, require_permissions
from app.services.asset_service import (
    asset_url,
    content_disposition_header,
    create_asset,
    delete_asset,
    get_asset,
    list_assets,
    read_asset_content,
    signed_asset_response,
    validate_image,
)
from app.services.audit_service import add_audit_log
from app.services.storage_service import StorageService, get_storage_service


router = APIRouter(prefix="/assets", tags=["assets"])


def organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "Select an organization first", 409)
    return principal.organization.id


async def read_upload(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise AppError("asset.file_too_large", "Uploaded image exceeds the configured size limit", 413, {"max_bytes": max_bytes})
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    request: Request,
    file: Annotated[UploadFile, File()],
    category: Annotated[AssetCategoryValue, Form()],
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.upload")),
) -> AssetResponse:
    org_id = organization_id(principal)
    data = await read_upload(file, settings.asset_max_upload_bytes)
    asset = await create_asset(
        session, storage, settings,
        organization_id=org_id, user_id=principal.user.id, category=category,
        filename=file.filename, declared_mime=file.content_type, data=data,
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="asset.upload", resource_type="asset", resource_id=asset.id,
        metadata={"category": category, "size": asset.size, "sha256": asset.sha256},
    )
    await session.commit()
    await session.refresh(asset)
    return await signed_asset_response(asset, storage, settings)


@router.post("/garment-references", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_garment_reference(
    request: Request,
    file: Annotated[UploadFile, File()],
    source_asset_id: Annotated[str, Form(min_length=1, max_length=36)],
    garment_view: Annotated[str, Form(pattern=r"^(front|back|detail)$")],
    transform_type: Annotated[str, Form(pattern=r"^(crop|keep|mask|crop_mask)$")],
    transform_metadata: Annotated[str, Form(max_length=1000000)],
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.upload")),
) -> AssetResponse:
    """Save a non-destructive garment reference derived in the browser.

    This endpoint intentionally accepts a rendered image, not a Provider edit
    mask. The normalized transform is retained only for audit/reproduction.
    """
    org_id = organization_id(principal)
    source = await get_asset(session, org_id, source_asset_id)
    if source.category != "garment":
        raise AppError("asset.invalid_reference_source", "服装参考图必须来源于服装原图。", 422)
    try:
        parsed = json.loads(transform_metadata)
    except (TypeError, ValueError) as error:
        raise AppError("asset.invalid_transform_metadata", "参考图处理参数不是有效 JSON。", 422) from error
    if not isinstance(parsed, dict):
        raise AppError("asset.invalid_transform_metadata", "参考图处理参数必须是对象。", 422)
    crop = parsed.get("crop")
    if crop is not None:
        if not isinstance(crop, dict) or any(
            not isinstance(crop.get(key), (int, float)) or not 0 <= float(crop[key]) <= 1
            for key in ("x", "y", "width", "height")
        ) or float(crop["width"]) <= 0 or float(crop["height"]) <= 0:
            raise AppError("asset.invalid_crop", "裁剪区域必须使用 0 到 1 的归一化坐标。", 422)
        if float(crop["x"]) + float(crop["width"]) > 1.000001 or float(crop["y"]) + float(crop["height"]) > 1.000001:
            raise AppError("asset.invalid_crop", "裁剪区域超出原图边界。", 422)
    data = await read_upload(file, settings.asset_max_upload_bytes)
    metadata = {
        **parsed,
        "asset_role": "garment_reference",
        "garment_view": garment_view,
        "transform_type": transform_type,
    }
    asset = await create_asset(
        session, storage, settings,
        organization_id=org_id, user_id=principal.user.id, category="garment_reference",
        filename=file.filename, declared_mime=file.content_type, data=data,
        source_asset_id=source.id, metadata_json=metadata,
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="asset.garment_reference.create", resource_type="asset", resource_id=asset.id,
        metadata={"source_asset_id": source.id, "garment_view": garment_view, "transform_type": transform_type},
    )
    await session.commit()
    await session.refresh(asset)
    return await signed_asset_response(asset, storage, settings)


@router.post("/region-replace-references", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_region_replace_reference(
    request: Request,
    file: Annotated[UploadFile, File()],
    source_asset_id: Annotated[str, Form(min_length=1, max_length=36)],
    asset_role: Annotated[
        str,
        Form(pattern=r"^(target_edit_mask|source_reference_mask|reference_patch)$"),
    ],
    transform_metadata: Annotated[str, Form(max_length=30000)],
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.upload")),
) -> AssetResponse:
    """Persist a review-time mask or extracted Image C patch as a derived asset."""
    org_id = organization_id(principal)
    source = await get_asset(session, org_id, source_asset_id)
    try:
        parsed = json.loads(transform_metadata)
    except (TypeError, ValueError) as error:
        raise AppError("asset.invalid_transform_metadata", "区域处理参数不是有效 JSON。", 422) from error
    if not isinstance(parsed, dict):
        raise AppError("asset.invalid_transform_metadata", "区域处理参数必须是对象。", 422)
    normalized_bounds = parsed.get("normalized_bounds")
    if normalized_bounds is not None:
        if not isinstance(normalized_bounds, dict) or any(
            not isinstance(normalized_bounds.get(key), (int, float))
            or not 0 <= float(normalized_bounds[key]) <= 1
            for key in ("x", "y", "width", "height")
        ):
            raise AppError("asset.invalid_region_bounds", "区域坐标必须使用 0 到 1 的归一化坐标。", 422)
        if (
            float(normalized_bounds["width"]) <= 0
            or float(normalized_bounds["height"]) <= 0
            or float(normalized_bounds["x"]) + float(normalized_bounds["width"]) > 1.000001
            or float(normalized_bounds["y"]) + float(normalized_bounds["height"]) > 1.000001
        ):
            raise AppError("asset.invalid_region_bounds", "区域坐标超出图片边界。", 422)
    data = await read_upload(file, settings.asset_max_upload_bytes)
    mime_type, _, width, height, _ = validate_image(data, file.content_type, settings)
    if mime_type != "image/png":
        raise AppError("asset.region_reference_must_be_png", "区域蒙版和参考切片必须使用 PNG 格式。", 422)
    if asset_role in {"target_edit_mask", "source_reference_mask"} and (
        width != source.width or height != source.height
    ):
        raise AppError(
            "asset.region_mask_size_mismatch",
            "蒙版尺寸必须与对应源图片完全一致。",
            422,
            {"expected_width": source.width, "expected_height": source.height, "actual_width": width, "actual_height": height},
        )
    asset = await create_asset(
        session,
        storage,
        settings,
        organization_id=org_id,
        user_id=principal.user.id,
        category="temporary",
        filename=file.filename,
        declared_mime=file.content_type,
        data=data,
        source_asset_id=source.id,
        metadata_json={
            **parsed,
            "asset_role": asset_role,
            "workflow": "batch_region_replace",
        },
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="asset.batch_region_reference.create",
        resource_type="asset",
        resource_id=asset.id,
        metadata={"source_asset_id": source.id, "asset_role": asset_role},
    )
    await session.commit()
    await session.refresh(asset)
    return await signed_asset_response(asset, storage, settings)


@router.post("/print-design-references", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_print_design_reference(
    request: Request,
    file: Annotated[UploadFile, File()],
    source_asset_id: Annotated[str, Form(min_length=1, max_length=36)],
    asset_role: Annotated[str, Form(pattern=r"^(composite_input|asset_alpha_mask|replacement_mask|protect_mask|blend_mask)$")],
    metadata: Annotated[str, Form(max_length=30000)] = "{}",
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.upload")),
) -> AssetResponse:
    """Store lossless full-resolution print-design composites and masks."""
    org_id = organization_id(principal)
    source = await get_asset(session, org_id, source_asset_id)
    try:
        parsed = json.loads(metadata)
    except (TypeError, ValueError) as error:
        raise AppError("print_design.invalid_metadata", "印花编辑参数不是有效 JSON。", 422) from error
    if not isinstance(parsed, dict):
        raise AppError("print_design.invalid_metadata", "印花编辑参数必须是对象。", 422)
    data = await read_upload(file, settings.asset_max_upload_bytes)
    mime_type, _, width, height, _ = validate_image(data, file.content_type, settings)
    if mime_type != "image/png":
        raise AppError("print_design.reference_must_be_png", "印花编辑中间文件必须使用 PNG。", 422)
    if width != source.width or height != source.height:
        raise AppError(
            "print_design.reference_size_mismatch", "印花编辑中间文件必须与底图保持原始尺寸。", 422,
            {"expected_width": source.width, "expected_height": source.height, "actual_width": width, "actual_height": height},
        )
    asset = await create_asset(
        session, storage, settings, organization_id=org_id, user_id=principal.user.id,
        category="temporary", filename=file.filename, declared_mime=file.content_type, data=data,
        source_asset_id=source.id,
        metadata_json={**parsed, "asset_role": asset_role, "workflow": "print_design"},
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="asset.print_design_reference.create", resource_type="asset", resource_id=asset.id,
        metadata={"source_asset_id": source.id, "asset_role": asset_role},
    )
    await session.commit()
    await session.refresh(asset)
    return await signed_asset_response(asset, storage, settings)


@router.get("", response_model=AssetPage)
async def get_assets(
    category: GeneratedAssetCategoryValue | None = None,
    search: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> AssetPage:
    return await list_assets(
        session, storage, settings, organization_id=organization_id(principal),
        category=category, search=search, limit=limit, offset=offset,
        owner_user_id=principal.user.id,
    )


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset_detail(
    asset_id: str,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> AssetResponse:
    asset = await get_asset(
        session, organization_id(principal), asset_id,
        owner_user_id=principal.user.id,
    )
    return await signed_asset_response(asset, storage, settings)


@router.get("/{asset_id}/url", response_model=AssetUrlResponse)
async def get_asset_url(
    asset_id: str,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> AssetUrlResponse:
    asset = await get_asset(
        session, organization_id(principal), asset_id,
        owner_user_id=principal.user.id,
    )
    return await asset_url(asset, storage, settings)


@router.get("/{asset_id}/content")
async def get_asset_content(
    asset_id: str,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> Response:
    asset = await get_asset(
        session, organization_id(principal), asset_id,
        owner_user_id=principal.user.id,
    )
    content = await read_asset_content(asset, storage)
    return Response(
        content=content,
        media_type=asset.mime_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": content_disposition_header(asset.filename, "inline"),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{asset_id}/download")
async def download_asset(
    asset_id: str,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> Response:
    org_id = organization_id(principal)
    asset = await get_asset(
        session, org_id, asset_id, owner_user_id=principal.user.id,
    )
    from app.services.batch_tryon_review_service import resolve_batch_try_on_asset_download_filename

    filename = await resolve_batch_try_on_asset_download_filename(session, org_id, asset)
    content = await read_asset_content(asset, storage)
    await session.commit()
    return Response(
        content=content,
        media_type=asset.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": content_disposition_header(filename),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_asset(
    asset_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("assets.delete")),
) -> None:
    org_id = organization_id(principal)
    asset = await delete_asset(
        session, storage, organization_id=org_id, asset_id=asset_id, user_id=principal.user.id
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="asset.delete", resource_type="asset", resource_id=asset.id,
    )
    await session.commit()
