from __future__ import annotations

from io import BytesIO
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.content import Asset
from app.models.tasks import BatchTryOnReviewItem, BatchTryOnVersion, Job, JobBatch
from app.services.asset_service import read_asset_content
from app.services.batch_tryon_filename_service import (
    deduplicate_download_filename,
    sanitize_batch_try_on_filename_stem,
)
from app.services.batch_tryon_review_service import ensure_batch_try_on_version_filenames
from app.services.storage_service import StorageService


TemplateExportScope = Literal["approved", "all_succeeded"]


async def _load_export_versions(
    session: AsyncSession,
    *,
    organization_id: str,
    items: list[BatchTryOnReviewItem],
) -> tuple[dict[str, list[BatchTryOnVersion]], dict[str, Asset]]:
    item_ids = [item.id for item in items]
    if not item_ids:
        return {}, {}
    candidate_versions = list((await session.scalars(
        select(BatchTryOnVersion)
        .where(
            BatchTryOnVersion.organization_id == organization_id,
            BatchTryOnVersion.item_id.in_(item_ids),
        )
        .order_by(BatchTryOnVersion.item_id, BatchTryOnVersion.version_number.desc())
    )).all())
    task_ids = {version.task_id for version in candidate_versions if version.task_id}
    batch_id_by_item_id = {item.id: item.batch_id for item in items}
    version_item_id_by_task_id = {
        version.task_id: version.item_id
        for version in candidate_versions
        if version.task_id
    }
    valid_task_ids = {
        job.id
        for job in (await session.scalars(
            select(Job).where(
                Job.id.in_(task_ids),
                Job.organization_id == organization_id,
            )
        )).all()
        if job.batch_id == batch_id_by_item_id.get(
            version_item_id_by_task_id.get(job.id, "")
        )
    } if task_ids else set()
    versions = [
        version for version in candidate_versions
        if version.task_id in valid_task_ids
    ]
    versions_by_item: dict[str, list[BatchTryOnVersion]] = {}
    for version in versions:
        versions_by_item.setdefault(version.item_id, []).append(version)
    asset_ids = {
        version.generated_asset_id
        for version in versions
        if version.generated_asset_id and version.generation_status == "succeeded"
    }
    assets = {
        asset.id: asset
        for asset in (await session.scalars(
            select(Asset).where(
                Asset.organization_id == organization_id,
                Asset.id.in_(asset_ids),
                Asset.deleted_at.is_(None),
            )
        )).all()
    } if asset_ids else {}
    return versions_by_item, assets


def _selected_version(
    item: BatchTryOnReviewItem,
    versions: list[BatchTryOnVersion],
    assets: dict[str, Asset],
    scope: TemplateExportScope,
) -> BatchTryOnVersion | None:
    succeeded = [
        version
        for version in versions
        if version.generation_status == "succeeded"
        and version.generated_asset_id in assets
    ]
    approved = next(
        (version for version in succeeded if version.id == item.approved_version_id),
        None,
    )
    if scope == "approved":
        return approved
    return approved or (succeeded[0] if succeeded else None)


async def build_batch_try_on_results_zip(
    session: AsyncSession,
    storage: StorageService,
    *,
    batch: JobBatch,
) -> tuple[bytes, int, int]:
    """Build the legacy whole-batch archive.

    This endpoint remains compatible with existing clients. New per-template
    exports use the bounded-memory streaming builder below.
    """
    if batch.workspace_type != "batch_tryon":
        raise AppError(
            "batch_tryon.export_invalid_batch",
            "当前批次不是批量套图任务",
            409,
        )
    items = list((await session.scalars(
        select(BatchTryOnReviewItem)
        .where(
            BatchTryOnReviewItem.organization_id == batch.organization_id,
            BatchTryOnReviewItem.batch_id == batch.id,
        )
        .order_by(BatchTryOnReviewItem.id)
    )).all())
    if not items:
        raise AppError(
            "batch_tryon.export_empty",
            "当前批次没有可导出的生成结果",
            409,
        )
    versions_by_item, assets = await _load_export_versions(
        session,
        organization_id=batch.organization_id,
        items=items,
    )
    archive = BytesIO()
    used_by_folder: dict[str, set[str]] = {"": set(), "待审核": set()}
    success_count = 0
    skipped_count = 0
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as zipped:
        for item in items:
            approved = bool(item.approved_version_id)
            version = _selected_version(
                item,
                versions_by_item.get(item.id, []),
                assets,
                "approved" if approved else "all_succeeded",
            )
            asset = assets.get(version.generated_asset_id or "") if version else None
            if version is None or asset is None:
                skipped_count += 1
                continue
            _, display_filename, _, _ = await ensure_batch_try_on_version_filenames(
                session,
                item,
                version,
                generated_asset=asset,
            )
            folder = "" if approved else "待审核"
            filename = deduplicate_download_filename(
                display_filename,
                used_by_folder[folder],
            )
            archive_name = filename if not folder else f"{folder}/{filename}"
            zipped.writestr(archive_name, await read_asset_content(asset, storage))
            success_count += 1
    if success_count == 0:
        raise AppError(
            "batch_tryon.export_no_success",
            "当前批次没有可下载的成功结果",
            409,
        )
    return archive.getvalue(), success_count, skipped_count


async def build_batch_try_on_template_zip(
    session: AsyncSession,
    storage: StorageService,
    *,
    batch: JobBatch,
    template_id: str,
    scope: TemplateExportScope,
) -> tuple[BinaryIO, str, int, int]:
    """Build one template archive without retaining the whole ZIP in memory."""
    if batch.workspace_type != "batch_tryon":
        raise AppError(
            "batch_tryon.export_invalid_batch",
            "当前批次不是批量套图任务",
            409,
        )
    items = list((await session.scalars(
        select(BatchTryOnReviewItem)
        .where(
            BatchTryOnReviewItem.organization_id == batch.organization_id,
            BatchTryOnReviewItem.batch_id == batch.id,
            BatchTryOnReviewItem.template_id == template_id,
        )
        .order_by(BatchTryOnReviewItem.id)
    )).all())
    if not items:
        raise AppError(
            "batch_tryon.template_export_empty",
            "当前模板没有可导出的任务",
            404,
        )
    versions_by_item, assets = await _load_export_versions(
        session,
        organization_id=batch.organization_id,
        items=items,
    )
    return await _build_template_archive(
        session,
        storage,
        items=items,
        versions_by_item=versions_by_item,
        assets=assets,
        template_id=template_id,
        scope=scope,
    )


async def build_selected_batch_try_on_template_zip(
    session: AsyncSession,
    storage: StorageService,
    *,
    organization_id: str,
    template_id: str,
    item_ids: list[str],
    scope: TemplateExportScope,
) -> tuple[BinaryIO, str, int, int]:
    """Build one archive from the current review items, even across retry batches."""
    unique_item_ids = list(dict.fromkeys(item_ids))
    items_by_id = {
        item.id: item
        for item in (await session.scalars(
            select(BatchTryOnReviewItem).where(
                BatchTryOnReviewItem.organization_id == organization_id,
                BatchTryOnReviewItem.id.in_(unique_item_ids),
                BatchTryOnReviewItem.template_id == template_id,
            )
        )).all()
    }
    if len(items_by_id) != len(unique_item_ids):
        raise AppError(
            "batch_tryon.template_export_items_invalid",
            "部分模板任务不存在、无权访问或不属于当前模板，请刷新页面后重试",
            404,
        )
    items = [items_by_id[item_id] for item_id in unique_item_ids]
    batches = {
        batch.id: batch
        for batch in (await session.scalars(
            select(JobBatch).where(
                JobBatch.organization_id == organization_id,
                JobBatch.id.in_({item.batch_id for item in items}),
            )
        )).all()
    }
    if len(batches) != len({item.batch_id for item in items}) or any(
        batch.workspace_type != "batch_tryon" for batch in batches.values()
    ):
        raise AppError(
            "batch_tryon.export_invalid_batch",
            "所选结果包含无效的批量套图批次",
            409,
        )
    versions_by_item, assets = await _load_export_versions(
        session,
        organization_id=organization_id,
        items=items,
    )
    return await _build_template_archive(
        session,
        storage,
        items=items,
        versions_by_item=versions_by_item,
        assets=assets,
        template_id=template_id,
        scope=scope,
    )


async def _build_template_archive(
    session: AsyncSession,
    storage: StorageService,
    *,
    items: list[BatchTryOnReviewItem],
    versions_by_item: dict[str, list[BatchTryOnVersion]],
    assets: dict[str, Asset],
    template_id: str,
    scope: TemplateExportScope,
) -> tuple[BinaryIO, str, int, int]:
    template_name = items[0].template_name or f"template-{template_id[:8]}"
    safe_template_name = (
        sanitize_batch_try_on_filename_stem(template_name)
        or f"template-{template_id[:8]}"
    )
    archive = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    used_names: set[str] = set()
    success_count = 0
    skipped_count = 0
    try:
        with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as zipped:
            for item in items:
                version = _selected_version(
                    item,
                    versions_by_item.get(item.id, []),
                    assets,
                    scope,
                )
                asset = assets.get(version.generated_asset_id or "") if version else None
                if version is None or asset is None:
                    skipped_count += 1
                    continue
                _, display_filename, _, _ = await ensure_batch_try_on_version_filenames(
                    session,
                    item,
                    version,
                    generated_asset=asset,
                )
                filename = deduplicate_download_filename(display_filename, used_names)
                zipped.writestr(filename, await read_asset_content(asset, storage))
                success_count += 1
        if success_count == 0:
            raise AppError(
                "batch_tryon.template_export_no_success",
                "当前模板在所选范围内没有可下载的成功结果",
                409,
            )
        archive.seek(0)
        return (
            archive,
            f"{safe_template_name}-批量套图结果.zip",
            success_count,
            skipped_count,
        )
    except Exception:
        archive.close()
        raise
