from __future__ import annotations

import json
import logging
from time import monotonic
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Literal
from zipfile import ZIP_STORED, ZipFile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

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
logger = logging.getLogger(__name__)
MAX_SYNCHRONOUS_EXPORT_BYTES = 512 * 1024 * 1024
EXPORT_MEMORY_BYTES = 8 * 1024 * 1024


class _SeekableArchiveReader:
    """SpooledTemporaryFile lacked seekable() on Python 3.10."""
    def __init__(self, file):
        self.file = file

    def seekable(self):
        return True

    def __getattr__(self, name):
        return getattr(self.file, name)


def _export_error(code: str, message: str, status: int, *, stage: str, items=(), template_id=None, request_id=None, **details):
    batch_ids = sorted({item.batch_id for item in items})
    context = {"stage": stage, "batch_id": batch_ids[0] if len(batch_ids) == 1 else None,
               "batch_ids": batch_ids, "template_id": template_id, **details}
    # Do not log storage URLs, exception strings, filenames, prompts or credentials.
    logger.warning("batch_export_failed request_id=%s batch_id=%s template_id=%s stage=%s code=%s",
                   request_id, context["batch_id"], template_id, stage, code)
    return AppError(code, message, status, context)


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
    owner_by_item_id = {item.id: item.created_by for item in items}
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
        ) and job.created_by == owner_by_item_id.get(version_item_id_by_task_id.get(job.id, ""))
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
        if version.generation_status == "succeeded" and version.review_status != "rejected"
    ]
    approved = next(
        (version for version in succeeded if version.id == item.approved_version_id and version.review_status == "approved"),
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
    allow_partial: bool = False,
    request_id: str | None = None,
) -> tuple[bytes, int, int]:
    """Build the legacy whole-batch archive.

    This endpoint remains compatible with existing clients. New per-template
    exports use the bounded-memory streaming builder below.
    """
    archive, _, exported, skipped = await build_batch_try_on_results_archive(
        session, storage, batch=batch, allow_partial=allow_partial, request_id=request_id,
    )
    try:
        return archive.read(), exported, skipped
    finally:
        archive.close()


async def build_batch_try_on_results_archive(
    session: AsyncSession, storage: StorageService, *, batch: JobBatch,
    allow_partial: bool = False, request_id: str | None = None,
) -> tuple[BinaryIO, str, int, int]:
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
    return await _build_template_archive(
        session, storage, items=items, versions_by_item=versions_by_item, assets=assets,
        template_id=None, scope="all_succeeded", whole_batch=True,
        allow_partial=allow_partial, request_id=request_id,
    )


async def build_batch_try_on_template_zip(
    session: AsyncSession,
    storage: StorageService,
    *,
    batch: JobBatch,
    template_id: str,
    scope: TemplateExportScope,
    allow_partial: bool = False,
    request_id: str | None = None,
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
        allow_partial=allow_partial, request_id=request_id,
    )


async def build_selected_batch_try_on_template_zip(
    session: AsyncSession,
    storage: StorageService,
    *,
    organization_id: str,
    template_id: str,
    item_ids: list[str],
    scope: TemplateExportScope,
    allow_partial: bool = False,
    request_id: str | None = None,
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
        allow_partial=allow_partial, request_id=request_id,
    )


async def build_selected_batch_try_on_results_archive(
    session: AsyncSession, storage: StorageService, *, organization_id: str, owner_user_id: str,
    batch_ids: list[str], allow_partial: bool = False, request_id: str | None = None,
) -> tuple[BinaryIO, str, int, int]:
    ids = list(dict.fromkeys(batch_ids))
    batches = list((await session.scalars(select(JobBatch).where(
        JobBatch.id.in_(ids), JobBatch.organization_id == organization_id,
        JobBatch.created_by == owner_user_id, JobBatch.workspace_type == "batch_tryon",
        JobBatch.batch_kind != "workspace",
    ))).all())
    if len(batches) != len(ids):
        raise AppError("job.batch_not_found", "部分批次不存在或不属于当前账号。", 404)
    items = list((await session.scalars(select(BatchTryOnReviewItem).where(
        BatchTryOnReviewItem.batch_id.in_(ids), BatchTryOnReviewItem.organization_id == organization_id,
        BatchTryOnReviewItem.created_by == owner_user_id,
    ).order_by(BatchTryOnReviewItem.created_at, BatchTryOnReviewItem.id))).all())
    versions, assets = await _load_export_versions(session, organization_id=organization_id, items=items)
    return await _build_template_archive(session, storage, items=items, versions_by_item=versions, assets=assets,
        template_id=None, scope="all_succeeded", whole_batch=True,
        allow_partial=allow_partial, request_id=request_id)


async def _build_template_archive(
    session: AsyncSession,
    storage: StorageService,
    *,
    items: list[BatchTryOnReviewItem],
    versions_by_item: dict[str, list[BatchTryOnVersion]],
    assets: dict[str, Asset],
    template_id: str | None,
    scope: TemplateExportScope,
    whole_batch: bool = False,
    allow_partial: bool = False,
    request_id: str | None = None,
) -> tuple[BinaryIO, str, int, int]:
    started = monotonic()
    if not items:
        raise _export_error("batch_tryon.export_empty", "当前范围没有可导出的任务。", 409,
                            stage="selection", request_id=request_id, template_id=template_id)
    template_name = items[0].template_name or f"template-{(template_id or 'results')[:8]}"
    safe_template_name = (
        sanitize_batch_try_on_filename_stem(template_name)
        or f"template-{(template_id or 'results')[:8]}"
    )
    selected = []
    omitted = []
    for item in items:
        version = _selected_version(item, versions_by_item.get(item.id, []), assets,
            "approved" if whole_batch and item.approved_version_id else scope)
        if version is None:
            # 'approved' intentionally excludes non-approved items; this is not a missing file.
            omitted.append({"item_id": item.id, "reason": "not_approved" if scope == "approved" else item.review_status})
            continue
        asset = assets.get(version.generated_asset_id or "")
        if asset is None or asset.created_by != item.created_by:
            raise _export_error("batch_tryon.export_asset_missing", "生成结果的素材记录缺失，请联系管理员检查；未下载不完整压缩包。", 502,
                stage="asset_lookup", items=items, template_id=template_id, request_id=request_id,
                item_id=item.id, asset_id=version.generated_asset_id)
        selected.append((item, version, asset))
    if not selected:
        raise _export_error("batch_tryon.template_export_no_success", "当前范围没有可下载的有效成功结果（已打回的版本不会导出）。", 409,
            stage="selection", items=items, template_id=template_id, request_id=request_id,
            requested_count=len(items), available_count=0, omitted_count=len(omitted))
    if omitted and scope != "approved" and not allow_partial:
        raise _export_error("batch_tryon.export_partial_confirmation_required",
            f"当前 {len(items)} 项中有 {len(selected)} 项可下载、{len(omitted)} 项尚未完成或已作废。是否仅导出有效结果？", 409,
            stage="preflight", items=items, template_id=template_id, request_id=request_id,
            requested_count=len(items), available_count=len(selected), omitted_count=len(omitted))
    if sum(asset.size for _, _, asset in selected) > MAX_SYNCHRONOUS_EXPORT_BYTES:
        raise _export_error("batch_tryon.export_too_large", "本次结果超过同步打包的512MB上限，请按模板或更小范围分批下载。", 413,
            stage="preflight", items=items, template_id=template_id, request_id=request_id)
    archive = SpooledTemporaryFile(max_size=EXPORT_MEMORY_BYTES, mode="w+b")
    used_by_folder: dict[str, set[str]] = {"": set(), "待审核/": set()}
    success_count = 0
    stage = "zip_write"
    try:
        # PNG/JPEG/WebP are already compressed. STORE avoids expensive recompression.
        with ZipFile(archive, "w", compression=ZIP_STORED) as zipped:
            for item, version, asset in selected:
                stage = "filename"
                _, display_filename, _, _ = await ensure_batch_try_on_version_filenames(
                    session,
                    item,
                    version,
                    generated_asset=asset,
                )
                folder = "待审核/" if whole_batch and version.id != item.approved_version_id else ""
                filename = folder + deduplicate_download_filename(display_filename, used_by_folder[folder])
                stage = "read_asset"
                try:
                    data = await read_asset_content(asset, storage)
                except AppError as error:
                    raise _export_error("batch_tryon.export_asset_missing" if error.code == "asset.content_missing" else "batch_tryon.export_storage_unavailable",
                        "读取生成图片失败，未返回不完整压缩包。请凭请求编号联系管理员检查。", 502,
                        stage=stage, items=items, template_id=template_id, request_id=request_id,
                        asset_id=asset.id, item_id=item.id, source_code=error.code) from error
                stage = "zip_write"
                await run_in_threadpool(zipped.writestr, filename, data)
                del data
                success_count += 1
            if omitted and scope != "approved":
                await run_in_threadpool(zipped.writestr, "_export-report.json", json.dumps({
                    "request_id": request_id, "exported": success_count, "omitted": omitted,
                    "note": "用户已确认仅导出有效成功结果。", "scope": scope,
                }, ensure_ascii=False).encode("utf-8"))
        stage = "zip_verify"
        archive.seek(0)
        def verify_archive():
            with ZipFile(_SeekableArchiveReader(archive)) as check:
                expected = success_count + int(bool(omitted and scope != "approved"))
                if len(check.namelist()) != expected or len(set(check.namelist())) != expected or check.testzip() is not None:
                    raise ValueError("archive_integrity_check_failed")
        await run_in_threadpool(verify_archive)
        archive.seek(0)
        logger.info("batch_export_complete request_id=%s template_id=%s exported=%s omitted=%s duration_ms=%s",
                    request_id, template_id, success_count, len(omitted), int((monotonic()-started)*1000))
        return (
            archive,
            "batch-tryon-results.zip" if whole_batch else f"{safe_template_name}-批量套图结果.zip",
            success_count,
            len(omitted),
        )
    except Exception as error:
        archive.close()
        if isinstance(error, AppError):
            raise
        raise _export_error("batch_tryon.export_pack_failed", "压缩包生成或完整性校验失败，请凭请求编号联系管理员。", 502,
            stage=stage, items=items, template_id=template_id, request_id=request_id,
            exception_type=type(error).__name__) from error
