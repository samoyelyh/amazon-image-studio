from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import warnings

from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import AppError
from app.models.content import Asset, GeneratedOutput, ProjectAsset
from app.schemas.content import AssetPage, AssetResponse, AssetUrlResponse
from app.services.storage_service import StorageService


UTC = timezone.utc
FORMAT_DETAILS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


def safe_filename(value: str | None) -> str:
    name = Path(value or "image").name.replace("\x00", "").strip()
    return (name or "image")[:255]


def validate_image(data: bytes, declared_mime: str | None, settings: Settings) -> tuple[str, str, int, int, str]:
    if not data:
        raise AppError("asset.empty_file", "Uploaded file is empty", 422)
    if len(data) > settings.asset_max_upload_bytes:
        raise AppError(
            "asset.file_too_large",
            "Uploaded image exceeds the configured size limit",
            413,
            {"max_bytes": settings.asset_max_upload_bytes},
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                detected_format = image.format
                width, height = image.size
                image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise AppError("asset.invalid_image", "File is not a valid supported image", 422) from error

    if detected_format not in FORMAT_DETAILS:
        raise AppError("asset.unsupported_format", "Only JPEG, PNG, and WebP images are supported", 415)
    mime_type, extension = FORMAT_DETAILS[detected_format]
    normalized_declared = (declared_mime or "").split(";", 1)[0].strip().lower()
    accepted_declared = {mime_type}
    if mime_type == "image/jpeg":
        accepted_declared.add("image/jpg")
    if normalized_declared and normalized_declared not in accepted_declared:
        raise AppError(
            "asset.mime_mismatch",
            "Declared MIME type does not match the image content",
            422,
            {"declared": normalized_declared, "detected": mime_type},
        )
    if width < 1 or height < 1:
        raise AppError("asset.invalid_dimensions", "Image dimensions are invalid", 422)
    if width > settings.asset_max_image_dimension or height > settings.asset_max_image_dimension:
        raise AppError(
            "asset.dimensions_too_large",
            "Image dimensions exceed the configured limit",
            422,
            {"max_dimension": settings.asset_max_image_dimension},
        )
    if width * height > settings.asset_max_image_pixels:
        raise AppError(
            "asset.too_many_pixels",
            "Image pixel count exceeds the configured limit",
            422,
            {"max_pixels": settings.asset_max_image_pixels},
        )
    return mime_type, extension, width, height, sha256(data).hexdigest()


async def create_asset(
    session: AsyncSession,
    storage: StorageService,
    settings: Settings,
    *,
    organization_id: str,
    user_id: str,
    category: str,
    filename: str | None,
    declared_mime: str | None,
    data: bytes,
) -> Asset:
    mime_type, extension, width, height, digest = validate_image(data, declared_mime, settings)
    asset_id = str(uuid4())
    storage_key = f"organizations/{organization_id}/assets/{asset_id}/{uuid4().hex}.{extension}"
    try:
        metadata = await run_in_threadpool(
            storage.upload,
            storage_key,
            data,
            content_type=mime_type,
            metadata={"organization-id": organization_id, "asset-id": asset_id, "sha256": digest},
        )
    except Exception as error:
        raise AppError("asset.storage_upload_failed", "Object storage upload failed", 502) from error

    asset = Asset(
        id=asset_id,
        organization_id=organization_id,
        category=category,
        storage_key=storage_key,
        filename=safe_filename(filename),
        mime_type=mime_type,
        size=metadata.size or len(data),
        width=width,
        height=height,
        sha256=digest,
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(asset)
    try:
        await session.flush()
    except SQLAlchemyError:
        await session.rollback()
        try:
            await run_in_threadpool(storage.delete, storage_key)
        except Exception:
            pass
        raise
    return asset


async def get_asset(session: AsyncSession, organization_id: str, asset_id: str, *, lock: bool = False) -> Asset:
    statement = select(Asset).where(
        Asset.id == asset_id,
        Asset.organization_id == organization_id,
        Asset.deleted_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    asset = await session.scalar(statement)
    if asset is None:
        raise AppError("asset.not_found", "Asset was not found", 404)
    return asset


async def signed_asset_response(asset: Asset, storage: StorageService, settings: Settings) -> AssetResponse:
    try:
        url = await run_in_threadpool(
            storage.create_presigned_url,
            asset.storage_key,
            expires_in=settings.s3_presigned_url_ttl_seconds,
        )
    except Exception as error:
        raise AppError("asset.url_signing_failed", "Could not create a private asset URL", 502) from error
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.s3_presigned_url_ttl_seconds)
    return AssetResponse.model_validate(asset).model_copy(update={"url": url, "url_expires_at": expires_at})


async def asset_url(asset: Asset, storage: StorageService, settings: Settings) -> AssetUrlResponse:
    response = await signed_asset_response(asset, storage, settings)
    return AssetUrlResponse(asset_id=asset.id, url=response.url or "", expires_at=response.url_expires_at or datetime.now(UTC))


async def list_assets(
    session: AsyncSession,
    storage: StorageService,
    settings: Settings,
    *,
    organization_id: str,
    category: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> AssetPage:
    filters = [Asset.organization_id == organization_id, Asset.deleted_at.is_(None)]
    if category:
        filters.append(Asset.category == category)
    if search:
        term = f"%{search.strip()}%"
        filters.append(or_(Asset.filename.like(term), Asset.sha256.like(term)))
    total = int(await session.scalar(select(func.count()).select_from(Asset).where(*filters)) or 0)
    assets = list((await session.scalars(
        select(Asset).where(*filters).order_by(Asset.created_at.desc()).limit(limit).offset(offset)
    )).all())
    items = [await signed_asset_response(item, storage, settings) for item in assets]
    return AssetPage(items=items, total=total, limit=limit, offset=offset)


async def delete_asset(
    session: AsyncSession,
    storage: StorageService,
    *,
    organization_id: str,
    asset_id: str,
    user_id: str,
) -> Asset:
    asset = await get_asset(session, organization_id, asset_id, lock=True)
    project_link = await session.scalar(select(ProjectAsset.id).where(ProjectAsset.asset_id == asset.id).limit(1))
    generated_link = await session.scalar(select(GeneratedOutput.id).where(GeneratedOutput.asset_id == asset.id).limit(1))
    if project_link or generated_link:
        raise AppError("asset.in_use", "Asset is still referenced by a project or generated output", 409)
    try:
        await run_in_threadpool(storage.delete, asset.storage_key)
    except Exception as error:
        raise AppError("asset.storage_delete_failed", "Object storage deletion failed", 502) from error
    asset.deleted_at = datetime.now(UTC)
    asset.updated_by = user_id
    await session.flush()
    return asset
