from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.content import Asset
from app.models.tasks import BatchTryOnReviewItem, BatchTryOnVersion, JobBatch
from app.services.asset_service import read_asset_content
from app.services.batch_tryon_filename_service import deduplicate_download_filename
from app.services.batch_tryon_review_service import ensure_batch_try_on_version_filenames
from app.services.storage_service import StorageService


async def build_batch_try_on_results_zip(
    session: AsyncSession,
    storage: StorageService,
    *,
    batch: JobBatch,
) -> tuple[bytes, int, int]:
    if batch.workspace_type != "batch_tryon":
        raise AppError("batch_tryon.export_invalid_batch", "当前批次不是批量套图任务", 409)
    items = list((await session.scalars(
        select(BatchTryOnReviewItem)
        .where(
            BatchTryOnReviewItem.organization_id == batch.organization_id,
            BatchTryOnReviewItem.batch_id == batch.id,
        )
        .order_by(BatchTryOnReviewItem.id)
    )).all())
    if not items:
        raise AppError("batch_tryon.export_empty", "当前批次没有可导出的生成结果", 409)

    version_ids = {
        version_id
        for item in items
        for version_id in (item.approved_version_id, item.current_version_id)
        if version_id
    }
    versions = {
        version.id: version
        for version in (await session.scalars(
            select(BatchTryOnVersion).where(
                BatchTryOnVersion.organization_id == batch.organization_id,
                BatchTryOnVersion.id.in_(version_ids),
            )
        )).all()
    } if version_ids else {}
    asset_ids = {
        version.generated_asset_id
        for version in versions.values()
        if version.generated_asset_id and version.generation_status == "succeeded"
    }
    assets = {
        asset.id: asset
        for asset in (await session.scalars(
            select(Asset).where(
                Asset.organization_id == batch.organization_id,
                Asset.id.in_(asset_ids),
                Asset.deleted_at.is_(None),
            )
        )).all()
    } if asset_ids else {}

    archive = BytesIO()
    used_by_folder: dict[str, set[str]] = {"": set(), "待审核": set()}
    success_count = 0
    skipped_count = 0
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as zipped:
        for item in items:
            approved = bool(item.approved_version_id)
            version_id = item.approved_version_id or item.current_version_id
            version = versions.get(version_id or "")
            asset = assets.get(version.generated_asset_id or "") if version else None
            if version is None or asset is None or version.generation_status != "succeeded":
                skipped_count += 1
                continue
            _, display_filename, _, _ = await ensure_batch_try_on_version_filenames(
                session, item, version, generated_asset=asset,
            )
            folder = "" if approved else "待审核"
            filename = deduplicate_download_filename(display_filename, used_by_folder[folder])
            archive_name = filename if not folder else f"{folder}/{filename}"
            zipped.writestr(archive_name, await read_asset_content(asset, storage))
            success_count += 1
    if success_count == 0:
        raise AppError("batch_tryon.export_no_success", "当前批次没有可下载的成功结果", 409)
    return archive.getvalue(), success_count, skipped_count

