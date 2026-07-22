from typing import Annotated

from urllib.parse import quote

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
from app.services.asset_service import asset_url, create_asset, delete_asset, get_asset, list_assets, read_asset_content, signed_asset_response
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
    )


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset_detail(
    asset_id: str,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> AssetResponse:
    asset = await get_asset(session, organization_id(principal), asset_id)
    return await signed_asset_response(asset, storage, settings)


@router.get("/{asset_id}/url", response_model=AssetUrlResponse)
async def get_asset_url(
    asset_id: str,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> AssetUrlResponse:
    asset = await get_asset(session, organization_id(principal), asset_id)
    return await asset_url(asset, storage, settings)


@router.get("/{asset_id}/content")
async def get_asset_content(
    asset_id: str,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> Response:
    asset = await get_asset(session, organization_id(principal), asset_id)
    content = await read_asset_content(asset, storage)
    return Response(
        content=content,
        media_type=asset.mime_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(asset.filename)}",
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
