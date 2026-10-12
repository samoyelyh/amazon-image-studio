from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.content import Asset, GeneratedOutput
from app.models.tasks import BatchTryOnReviewItem, BatchTryOnTemplatePrompt, BatchTryOnVersion, Job, JobBatch
from app.schemas.batch_tryon_review import (
    BatchTryOnBatchDetailedAnalysisError,
    BatchTryOnBatchDetailedAnalysisRequest,
    BatchTryOnBatchDetailedAnalysisTask,
    BatchTryOnBatchRegenerateError,
    BatchTryOnBatchRegenerateRequest,
    BatchTryOnBatchRegenerateTask,
    BatchTryOnDetailedReviewAnalysisRequest,
    BatchTryOnRegionReplaceRequest,
    BatchTryOnRegenerateRequest,
    BatchTryOnReviewDetailResponse,
    BatchTryOnVersionResponse,
    ReviewAssetResponse,
)
from app.schemas.tasks import JobSubmitRequest
from app.services.asset_service import asset_content_url
from app.services.batch_tryon_filename_service import (
    build_batch_try_on_output_filename,
    normalize_output_extension,
    sanitize_batch_try_on_filename_stem,
)
from app.services.batch_tryon_prompt_service import append_manual_retry_constraints
from app.services.batch_tryon_prompt_template_service import prompt_analysis_preset_only, resolve_prompt_preset
from app.services.resource_pool_service import resolve_operation_model_code


UTC = timezone.utc
REVIEW_CORRECTION_HEADER = "REVIEW CORRECTION REQUIREMENTS:"
REGION_REPLACE_TECHNICAL_CONTRACT = """Edit only the transparent masked region in the first provided base image.

The first image already contains a deterministic pixel-level placement of the exact artwork inside the target frame. Do not redraw, reinterpret, replace, translate, or change the identity of that placed artwork.

The second provided image is the exact source surface patch extracted from Image C. Treat it as one indivisible product-surface structure supplied only to preserve fidelity during local integration.

Keep the patch's internal visual structure, pattern layout, line relationships, colors, proportions, relative positions and surface details stable. Do not semantically reinterpret, redesign, reconstruct, approximate, invent details, or mix it with the old surface content being replaced.

Only perform the minimum local fusion needed to integrate the already placed surface with the garment: edge cleanup, perspective or surface warping, fabric texture, folds, seams, lighting, and shadows. These adaptations must not change the protected internal visual structure.

Preserve every unmasked area of the base image. Do not modify garment color, collar, cuffs, silhouette, background, props, composition, scene, or any other unmasked content."""


def _job_source_filename(job: Job | None) -> str | None:
    if job is None:
        return None
    metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
    value = metadata.get("source_filename") or metadata.get("garment_filename")
    return str(value).strip() if value else None


def _job_template_name(job: Job | None) -> str | None:
    if job is None:
        return None
    metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
    value = metadata.get("template_name")
    return str(value).strip() if value else None


async def _item_source_filename(
    session: AsyncSession,
    item: BatchTryOnReviewItem,
    *,
    job: Job | None = None,
) -> str:
    garment = await session.get(Asset, item.garment_asset_id)
    asset_filename = garment.filename if garment is not None else None
    job_filename = _job_source_filename(job)
    # Older clients uploaded the garment asset without its extension. Their
    # immutable job metadata still contains the full original filename.
    source = item.source_filename or asset_filename or job_filename or ""
    if job_filename and "." not in source.rsplit("/", 1)[-1]:
        source = job_filename
    item.source_filename = source or None
    return source


async def _item_template_name(
    session: AsyncSession,
    item: BatchTryOnReviewItem,
    *,
    job: Job | None = None,
) -> str:
    model = await session.get(Asset, item.model_asset_id)
    source = item.template_name or _job_template_name(job) or (model.filename if model is not None else "")
    source = str(source or "").strip()
    item.template_name = source or None
    return source


async def _item_duplicate_index(
    session: AsyncSession,
    item: BatchTryOnReviewItem,
    source_filename: str,
) -> int:
    rows = (await session.execute(
        select(BatchTryOnReviewItem, Asset.filename)
        .join(Asset, Asset.id == BatchTryOnReviewItem.garment_asset_id)
        .where(BatchTryOnReviewItem.batch_id == item.batch_id)
    )).all()
    target_stem = sanitize_batch_try_on_filename_stem(source_filename).casefold()
    target_template = sanitize_batch_try_on_filename_stem(item.template_name).casefold()
    matching_ids = sorted(
        candidate.id
        for candidate, asset_filename in rows
        if sanitize_batch_try_on_filename_stem(candidate.source_filename or asset_filename).casefold() == target_stem
        and sanitize_batch_try_on_filename_stem(candidate.template_name).casefold() == target_template
    )
    return matching_ids.index(item.id) + 1 if item.id in matching_ids else 1


async def _item_template_index(
    session: AsyncSession,
    item: BatchTryOnReviewItem,
    *,
    job: Job | None,
) -> int | None:
    metadata = job.input_json.get("metadata") if job is not None and isinstance(job.input_json.get("metadata"), dict) else {}
    explicit_index = metadata.get("template_index")
    explicit_count = metadata.get("template_count")
    if isinstance(explicit_index, int) and explicit_index > 0:
        return explicit_index if not isinstance(explicit_count, int) or explicit_count > 1 else None

    jobs = list((await session.scalars(
        select(Job).where(Job.batch_id == item.batch_id).order_by(Job.created_at, Job.id)
    )).all())
    ordered_templates: list[str] = []
    target_key = ""
    ordered_jobs = sorted(
        jobs,
        key=lambda candidate: (
            int(candidate.input_json.get("metadata", {}).get("index", 0))
            if isinstance(candidate.input_json.get("metadata"), dict)
            and isinstance(candidate.input_json.get("metadata", {}).get("index"), int)
            else 0,
            candidate.created_at,
            candidate.id,
        ),
    )
    for candidate in ordered_jobs:
        candidate_metadata = (
            candidate.input_json.get("metadata")
            if isinstance(candidate.input_json.get("metadata"), dict)
            else {}
        )
        references = candidate.input_json.get("reference_asset_ids", []) or []
        template_key = str(
            candidate_metadata.get("template_id")
            or (references[0] if references else "")
            or candidate_metadata.get("template_name")
            or ""
        )
        if template_key and template_key not in ordered_templates:
            ordered_templates.append(template_key)
        if job is not None and candidate.id == job.id:
            target_key = template_key
    if len(ordered_templates) <= 1:
        return None
    if not target_key:
        target_key = str(item.model_asset_id or item.template_name or "")
    return ordered_templates.index(target_key) + 1 if target_key in ordered_templates else None


async def ensure_batch_try_on_version_filenames(
    session: AsyncSession,
    item: BatchTryOnReviewItem,
    version: BatchTryOnVersion,
    *,
    job: Job | None = None,
    generated_asset: Asset | None = None,
    output_format: str | None = None,
) -> tuple[str, str, str, str]:
    if job is None and version.task_id:
        job = await session.get(Job, version.task_id)
    source_filename = version.source_filename or await _item_source_filename(session, item, job=job)
    template_name = await _item_template_name(session, item, job=job)
    resolved_format = normalize_output_extension(
        output_format
        or version.output_format
        or (generated_asset.mime_type if generated_asset is not None else None)
        or (job.input_json.get("output_format") if job is not None else None)
    )
    duplicate_index = await _item_duplicate_index(session, item, source_filename)
    template_index = await _item_template_index(session, item, job=job)
    display_filename = build_batch_try_on_output_filename(
        source_filename,
        resolved_format,
        version.version_number,
        True,
        duplicate_index,
        item_id=item.id,
        template_name=template_name,
        template_index=template_index,
    )
    historical_filename = build_batch_try_on_output_filename(
        source_filename,
        resolved_format,
        version.version_number,
        False,
        duplicate_index,
        item_id=item.id,
        template_name=template_name,
        template_index=template_index,
    )
    version.source_filename = source_filename
    version.display_filename = display_filename
    version.download_filename = historical_filename
    version.output_format = resolved_format
    if job is not None:
        metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
        job.input_json = {
            **job.input_json,
            "metadata": {
                **metadata,
                "source_filename": source_filename,
                "template_name": template_name,
            },
        }
    await session.flush()
    return source_filename, display_filename, historical_filename, resolved_format


async def prepare_batch_try_on_output_filename(
    session: AsyncSession,
    job: Job,
    output_format: str,
) -> str | None:
    if job.workspace_type != "batch_tryon":
        return None
    metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
    version_id = str(metadata.get("batch_tryon_version_id") or "")
    version = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.organization_id == job.organization_id,
        BatchTryOnVersion.id == version_id,
    )) if version_id else None
    if version is None:
        version = await session.scalar(select(BatchTryOnVersion).where(
            BatchTryOnVersion.organization_id == job.organization_id,
            BatchTryOnVersion.task_id == job.id,
        ))
    if version is None:
        return None
    item = await session.get(BatchTryOnReviewItem, version.item_id)
    if item is None:
        return None
    _, display_filename, _, _ = await ensure_batch_try_on_version_filenames(
        session, item, version, job=job, output_format=output_format,
    )
    return display_filename


async def resolve_batch_try_on_asset_download_filename(
    session: AsyncSession,
    organization_id: str,
    asset: Asset,
) -> str:
    row = (await session.execute(
        select(BatchTryOnVersion, BatchTryOnReviewItem)
        .join(BatchTryOnReviewItem, BatchTryOnReviewItem.id == BatchTryOnVersion.item_id)
        .where(
            BatchTryOnVersion.organization_id == organization_id,
            BatchTryOnVersion.generated_asset_id == asset.id,
        )
        .limit(1)
    )).first()
    if row is None:
        return asset.filename
    version, item = row
    _, display_filename, historical_filename, _ = await ensure_batch_try_on_version_filenames(
        session, item, version, generated_asset=asset,
    )
    return (
        display_filename
        if item.current_version_id == version.id or item.approved_version_id == version.id
        else historical_filename
    )


def append_batch_try_on_review_requirements(base_prompt: str, review_notes: str | None) -> str:
    notes = (review_notes or "").strip()
    if not notes:
        return base_prompt
    return f"""{base_prompt.rstrip()}

{REVIEW_CORRECTION_HEADER}

The previous generated result did not pass manual review.

Correct the following issues:
{notes}

These correction instructions are additional requirements only.
They must not replace or weaken the mandatory garment fidelity requirements.

Continue to preserve:
- the original model identity and face
- hairstyle
- pose
- body proportions
- camera angle
- background
- lighting
- garment color
- graphics
- text
- numbers, including leading zeros
- logos
- stripes
- stitching
- panel structure
- neckline
- sleeves
- hem
- garment silhouette
- fabric appearance
- print-versus-embroidery characteristics"""


async def ensure_batch_try_on_review_records(
    session: AsyncSession, batch: JobBatch,
) -> list[BatchTryOnReviewItem]:
    if batch.workspace_type != "batch_tryon":
        return []
    jobs = list((await session.scalars(
        select(Job).where(Job.batch_id == batch.id).order_by(Job.created_at, Job.id)
    )).all())
    existing = {
        item.client_item_id: item for item in (await session.scalars(
            select(BatchTryOnReviewItem).where(BatchTryOnReviewItem.batch_id == batch.id)
        )).all()
    }
    grouped: dict[str, list[Job]] = {}
    for job in jobs:
        if job.client_item_id:
            grouped.setdefault(job.client_item_id, []).append(job)

    for client_item_id, item_jobs in grouped.items():
        item = existing.get(client_item_id)
        references = [str(value) for value in item_jobs[0].input_json.get("reference_asset_ids", []) or []]
        if item is None:
            if len(references) < 2:
                continue
            metadata = item_jobs[0].input_json.get("metadata") if isinstance(item_jobs[0].input_json.get("metadata"), dict) else {}
            preset_codes = metadata.get("preset_codes") if isinstance(metadata.get("preset_codes"), dict) else None
            original_garment_asset_id = str(metadata.get("garment_asset_id") or references[1])
            item = BatchTryOnReviewItem(
                organization_id=batch.organization_id,
                batch_id=batch.id,
                client_item_id=client_item_id,
                model_asset_id=references[0],
                garment_asset_id=original_garment_asset_id,
                template_id=str(metadata.get("template_id") or "").strip() or None,
                template_name=str(metadata.get("template_name") or "").strip() or None,
                preset_summary=str(metadata.get("preset_summary") or "").strip() or None,
                preset_codes=preset_codes,
                review_status="pending",
                regeneration_count=0,
                created_by=item_jobs[0].created_by,
                updated_by=item_jobs[0].updated_by,
            )
            session.add(item)
            await session.flush()
            existing[client_item_id] = item

        source_filename = await _item_source_filename(session, item, job=item_jobs[0])
        item.source_filename = source_filename
        first_metadata = item_jobs[0].input_json.get("metadata") if isinstance(item_jobs[0].input_json.get("metadata"), dict) else {}
        item.template_id = item.template_id or str(first_metadata.get("template_id") or "").strip() or None
        item.template_name = item.template_name or str(first_metadata.get("template_name") or "").strip() or None
        item.preset_summary = item.preset_summary or str(first_metadata.get("preset_summary") or "").strip() or None
        if item.preset_codes is None and isinstance(first_metadata.get("preset_codes"), dict):
            item.preset_codes = first_metadata["preset_codes"]
        for item_job in item_jobs:
            metadata = item_job.input_json.get("metadata") if isinstance(item_job.input_json.get("metadata"), dict) else {}
            item_job.input_json = {
                **item_job.input_json,
                "metadata": {**metadata, "source_filename": source_filename},
            }

        versions = list((await session.scalars(
            select(BatchTryOnVersion).where(BatchTryOnVersion.item_id == item.id)
            .order_by(BatchTryOnVersion.version_number)
        )).all())
        versions_by_task = {version.task_id: version for version in versions if version.task_id}
        parent = versions[-1] if versions else None
        for job in item_jobs:
            if job.id in versions_by_task:
                parent = versions_by_task[job.id]
                continue
            generated_asset_id = await session.scalar(
                select(GeneratedOutput.asset_id).where(GeneratedOutput.job_id == job.id)
                .order_by(GeneratedOutput.sequence_number).limit(1)
            )
            metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
            version = BatchTryOnVersion(
                organization_id=batch.organization_id,
                item_id=item.id,
                version_number=(parent.version_number + 1) if parent else 1,
                parent_version_id=parent.id if parent else None,
                generated_asset_id=generated_asset_id,
                task_id=job.id,
                prompt_snapshot=str(job.input_json.get("prompt") or ""),
                review_notes=str(metadata.get("review_notes") or "").strip() or None,
                retry_mode=str(metadata.get("retry_mode") or ("initial" if parent is None else "direct")),
                generation_status=job.status,
                review_status="pending",
                created_by=job.created_by,
                created_at=job.created_at or datetime.now(UTC),
                completed_at=job.finished_at,
            )
            session.add(version)
            await session.flush()
            generated_asset = await session.get(Asset, generated_asset_id) if generated_asset_id else None
            await ensure_batch_try_on_version_filenames(
                session, item, version, job=job, generated_asset=generated_asset,
            )
            metadata = {
                **metadata,
                "batch_tryon_review_item_id": item.id,
                "batch_tryon_version_id": version.id,
            }
            job.input_json = {**job.input_json, "metadata": metadata}
            versions.append(version)
            versions_by_task[job.id] = version
            parent = version

        for version in versions:
            generated_asset = await session.get(Asset, version.generated_asset_id) if version.generated_asset_id else None
            await ensure_batch_try_on_version_filenames(
                session,
                item,
                version,
                generated_asset=generated_asset,
            )

        if versions and item.current_version_id is None:
            latest = versions[-1]
            item.current_version_id = latest.id
            item.regeneration_count = max(0, latest.version_number - 1)
            item.review_status = _item_status_for_version(latest)
    await session.flush()
    return list(existing.values())


def _item_status_for_version(version: BatchTryOnVersion) -> str:
    if version.review_status == "approved":
        return "approved"
    if version.generation_status == "succeeded":
        return "pending"
    if version.generation_status in {"failed", "cancelled"}:
        return "generation_failed"
    return "regenerating" if version.version_number > 1 else "pending"


async def get_review_item(
    session: AsyncSession, organization_id: str, item_id: str, *, lock: bool = False,
) -> BatchTryOnReviewItem:
    statement = select(BatchTryOnReviewItem).where(
        BatchTryOnReviewItem.id == item_id,
        BatchTryOnReviewItem.organization_id == organization_id,
    )
    if lock:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise AppError("batch_tryon.review_item_not_found", "批量套图审核任务不存在", 404)
    return item


def _asset_response(
    asset: Asset,
    *,
    display_filename: str | None = None,
    download_filename: str | None = None,
) -> ReviewAssetResponse:
    return ReviewAssetResponse(
        id=asset.id,
        filename=display_filename or asset.filename,
        display_filename=display_filename or asset.filename,
        download_filename=download_filename or asset.filename,
        download_url=f"/api/v1/assets/{asset.id}/download",
        preview_url=asset_content_url(asset.id),
        width=asset.width,
        height=asset.height,
        mime_type=asset.mime_type,
        size=asset.size,
    )


async def review_detail(
    session: AsyncSession, organization_id: str, item_id: str,
) -> BatchTryOnReviewDetailResponse:
    item = await get_review_item(session, organization_id, item_id)
    garment = await session.scalar(select(Asset).where(
        Asset.id == item.garment_asset_id, Asset.organization_id == organization_id, Asset.deleted_at.is_(None),
    ))
    model = await session.scalar(select(Asset).where(
        Asset.id == item.model_asset_id, Asset.organization_id == organization_id, Asset.deleted_at.is_(None),
    ))
    if garment is None or model is None:
        raise AppError("batch_tryon.review_asset_missing", "审核所需的原始图片不存在", 409)
    versions = list((await session.scalars(
        select(BatchTryOnVersion).where(
            BatchTryOnVersion.organization_id == organization_id,
            BatchTryOnVersion.item_id == item.id,
        ).order_by(BatchTryOnVersion.version_number.desc())
    )).all())
    asset_ids = {version.generated_asset_id for version in versions if version.generated_asset_id}
    task_ids = {version.task_id for version in versions if version.task_id}
    jobs = {
        job.id: job for job in (await session.scalars(
            select(Job).where(Job.organization_id == organization_id, Job.id.in_(task_ids))
        )).all()
    } if task_ids else {}
    assets = {
        asset.id: asset for asset in (await session.scalars(
            select(Asset).where(Asset.organization_id == organization_id, Asset.id.in_(asset_ids), Asset.deleted_at.is_(None))
        )).all()
    } if asset_ids else {}
    for version in versions:
        await ensure_batch_try_on_version_filenames(
            session,
            item,
            version,
            job=jobs.get(version.task_id or ""),
            generated_asset=assets.get(version.generated_asset_id or ""),
        )
    version_responses = [
        BatchTryOnVersionResponse(
            id=version.id,
            version_number=version.version_number,
            parent_version_id=version.parent_version_id,
            generated_asset_id=version.generated_asset_id,
            task_id=version.task_id,
            prompt_snapshot=version.prompt_snapshot,
            review_notes=version.review_notes,
            retry_mode=version.retry_mode,
            generation_status=version.generation_status,
            review_status=version.review_status,
            source_filename=version.source_filename,
            display_filename=version.display_filename,
            download_filename=(
                version.display_filename
                if item.current_version_id == version.id or item.approved_version_id == version.id
                else version.download_filename
            ),
            output_format=version.output_format,
            generated_asset=_asset_response(
                assets[version.generated_asset_id],
                display_filename=version.display_filename,
                download_filename=(
                    version.display_filename
                    if item.current_version_id == version.id or item.approved_version_id == version.id
                    else version.download_filename
                ),
            ) if version.generated_asset_id in assets else None,
            created_at=version.created_at,
            completed_at=version.completed_at,
            reviewed_by=version.reviewed_by,
            reviewed_at=version.reviewed_at,
            generation_duration_ms=jobs[version.task_id].generation_duration_ms
            if version.task_id in jobs else None,
        ) for version in versions
    ]
    current = next((version for version in version_responses if version.id == item.current_version_id), None)
    current_job = jobs.get(current.task_id or "") if current else None
    current_metadata = (
        current_job.input_json.get("metadata")
        if current_job and isinstance(current_job.input_json.get("metadata"), dict)
        else {}
    )
    template_prompt_id = str(current_metadata.get("template_prompt_id") or "").strip()
    template_prompt_record = await session.get(BatchTryOnTemplatePrompt, template_prompt_id) if template_prompt_id else None
    effective_prompt_snapshot = prompt_analysis_preset_only(str(
        current_metadata.get("analysis_prompt_snapshot")
        or (template_prompt_record.analysis_prompt_used if template_prompt_record else "")
    )) or None
    image_c_asset = None
    raw_image_c_asset_id = current_metadata.get("font_reference_asset_id")
    image_c_asset_id = (
        str(raw_image_c_asset_id).strip()
        if raw_image_c_asset_id not in {None, "", "null", "None"}
        else ""
    )
    if image_c_asset_id:
        image_c = await session.scalar(select(Asset).where(
            Asset.id == image_c_asset_id,
            Asset.organization_id == organization_id,
            Asset.deleted_at.is_(None),
        ))
        if image_c is not None:
            image_c_asset = _asset_response(image_c)
    return BatchTryOnReviewDetailResponse(
        item_id=item.id,
        batch_id=item.batch_id,
        client_item_id=item.client_item_id,
        template_id=item.template_id,
        review_status=item.review_status,
        current_version_id=item.current_version_id,
        approved_version_id=item.approved_version_id,
        regeneration_count=sum(
            1 for version in versions
            if version.retry_mode not in {"initial", "region_replace"}
        ),
        template_name=item.template_name or model.filename,
        preset_summary=item.preset_summary,
        preset_codes=item.preset_codes,
        template_type=str(current_metadata.get("template_type") or "").strip() or None,
        template_prompt_id=template_prompt_id or None,
        prompt_version=(
            int(current_metadata["prompt_version"])
            if str(current_metadata.get("prompt_version") or "").isdigit()
            else None
        ),
        effective_prompt_snapshot=effective_prompt_snapshot,
        garment_asset=_asset_response(garment),
        model_asset=_asset_response(model),
        image_c_asset=image_c_asset,
        current_version=current,
        versions=version_responses,
    )


async def select_review_version(
    session: AsyncSession,
    *,
    organization_id: str,
    item_id: str,
    version_id: str,
    user_id: str,
) -> BatchTryOnReviewItem:
    """Restore any successful historical version without deleting newer attempts."""
    from app.services.task_service import refresh_batch_status

    item = await get_review_item(session, organization_id, item_id, lock=True)
    version = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == version_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.organization_id == organization_id,
    ).with_for_update())
    if version is None:
        raise AppError("batch_tryon.version_not_found", "所选版本不存在。", 404)
    if version.generation_status != "succeeded" or not version.generated_asset_id:
        raise AppError("batch_tryon.version_not_selectable", "只能选择已经生成成功的图片版本。", 409)
    if version.retry_mode == "region_replace" and version.review_status != "approved":
        raise AppError(
            "batch_tryon.region_replace_requires_approval",
            "区域替换候选版本必须先审核通过，才能设为当前结果。",
            409,
        )
    item.current_version_id = version.id
    item.review_status = "approved" if version.review_status == "approved" else "pending"
    item.updated_by = user_id
    await refresh_batch_status(session, item.batch_id)
    await session.flush()
    return item


def compose_region_replace_prompt(edit_prompt: str, edit_region_type: str) -> str:
    region_labels = {
        "back_name": "back name print",
        "back_number": "back number print",
        "wearer_left_shoulder_number": "wearer's left shoulder number",
        "wearer_right_shoulder_number": "wearer's right shoulder number",
        "custom_region": "custom selected region",
    }
    region = region_labels.get(edit_region_type, "custom selected region")
    return (
        f"{REGION_REPLACE_TECHNICAL_CONTRACT}\n\n"
        f"TARGET REGION TYPE: {region}.\n"
        f"USER REPLACEMENT REQUIREMENT:\n{edit_prompt.strip()}"
    )


async def submit_region_replace(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: str,
    item_id: str,
    payload: BatchTryOnRegionReplaceRequest,
    user_id: str,
) -> tuple[BatchTryOnReviewItem, BatchTryOnVersion, Job, bool]:
    """Create one durable mask-edit Job and a non-current candidate version."""
    from app.services.task_service import refresh_batch_status, submit_job

    item = await get_review_item(session, organization_id, item_id, lock=True)
    source = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == payload.source_version_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.organization_id == organization_id,
    ).with_for_update())
    if source is None:
        raise AppError("batch_tryon.version_not_found", "来源版本不存在。", 404)
    if (
        item.approved_version_id != source.id
        or source.review_status != "approved"
        or item.review_status != "approved"
    ):
        raise AppError(
            "batch_tryon.region_replace_requires_approved_base",
            "请先审核通过当前生成结果，再进行区域涂抹替换。",
            409,
        )
    if item.current_version_id != source.id:
        existing_key = f"batch-region-replace:{sha256(f'{item.id}:{payload.idempotency_key}'.encode()).hexdigest()}"
        existing = await session.scalar(select(Job).where(
            Job.organization_id == organization_id,
            Job.idempotency_key == existing_key,
        ))
        if existing is None:
            raise AppError("batch_tryon.version_not_current", "当前图片已有更新版本，请刷新后重试。", 409)
    if source.generation_status != "succeeded" or not source.generated_asset_id or not source.task_id:
        raise AppError("batch_tryon.version_not_regenerable", "只有生成成功的结果才能执行区域涂抹替换。", 409)
    source_job = await session.scalar(select(Job).where(
        Job.id == source.task_id,
        Job.organization_id == organization_id,
    ))
    if source_job is None:
        raise AppError("batch_tryon.source_job_missing", "来源生成任务不存在。", 409)

    job_key = f"batch-region-replace:{sha256(f'{item.id}:{payload.idempotency_key}'.encode()).hexdigest()}"
    existing_job = await session.scalar(select(Job).where(
        Job.organization_id == organization_id,
        Job.idempotency_key == job_key,
    ))
    unresolved_candidate = await session.scalar(
        select(BatchTryOnVersion).where(
            BatchTryOnVersion.organization_id == organization_id,
            BatchTryOnVersion.item_id == item.id,
            BatchTryOnVersion.retry_mode == "region_replace",
            BatchTryOnVersion.review_status == "pending",
        ).order_by(BatchTryOnVersion.version_number.desc()).limit(1)
    )
    if unresolved_candidate is not None and (
        existing_job is None or unresolved_candidate.task_id != existing_job.id
    ):
        raise AppError(
            "batch_tryon.region_replace_confirmation_required",
            "当前图片已有待确认的区域替换结果，请先确认完成或放弃后再继续涂抹。",
            409,
        )

    asset_ids = {
        source.generated_asset_id,
        payload.target_mask_asset_id,
        payload.image_c_asset_id,
        payload.reference_patch_asset_id,
        *([payload.source_reference_mask_asset_id] if payload.source_reference_mask_asset_id else []),
    }
    assets = {
        asset.id: asset for asset in (await session.scalars(select(Asset).where(
            Asset.organization_id == organization_id,
            Asset.id.in_(asset_ids),
            Asset.deleted_at.is_(None),
        ))).all()
    }
    if set(assets) != asset_ids:
        raise AppError("batch_tryon.region_replace_asset_missing", "区域替换所需图片或蒙版不存在。", 409)
    target_mask = assets[payload.target_mask_asset_id]
    reference_patch = assets[payload.reference_patch_asset_id]
    source_mask = assets.get(payload.source_reference_mask_asset_id or "")
    if (
        target_mask.source_asset_id != source.generated_asset_id
        or (target_mask.metadata_json or {}).get("asset_role") != "target_edit_mask"
    ):
        raise AppError("batch_tryon.invalid_target_mask", "目标蒙版与当前基础结果不匹配。", 422)
    if (
        reference_patch.source_asset_id != payload.image_c_asset_id
        or (reference_patch.metadata_json or {}).get("asset_role") != "reference_patch"
    ):
        raise AppError("batch_tryon.invalid_reference_patch", "图C参考切片与当前字体参考图不匹配。", 422)
    if source_mask is not None and (
        source_mask.source_asset_id != payload.image_c_asset_id
        or (source_mask.metadata_json or {}).get("asset_role") != "source_reference_mask"
    ):
        raise AppError("batch_tryon.invalid_source_reference_mask", "图C来源蒙版与当前字体参考图不匹配。", 422)

    version_id = str(uuid5(NAMESPACE_URL, job_key))
    effective_prompt = compose_region_replace_prompt(payload.edit_prompt, payload.edit_region_type)
    source_metadata = (
        source_job.input_json.get("metadata")
        if isinstance(source_job.input_json.get("metadata"), dict)
        else {}
    )
    reference_source_role = str(
        (payload.source_reference_metadata or {}).get("source_role") or "image_c"
    ).strip()
    preserved_font_reference_asset_id = (
        payload.image_c_asset_id
        if reference_source_role == "image_c"
        else source_metadata.get("font_reference_asset_id")
    )
    input_json = {
        "prompt": effective_prompt,
        "business_prompt": payload.edit_prompt,
        "reference_asset_ids": [source.generated_asset_id, payload.reference_patch_asset_id],
        "mask_asset_id": payload.target_mask_asset_id,
        "size": source_job.input_json.get("size") or "auto",
        "aspect_ratio": source_job.input_json.get("aspect_ratio") or "auto",
        "output_format": source_job.input_json.get("output_format") or "png",
        "quality": source_job.input_json.get("quality"),
        "metadata": {
            **source_metadata,
            "workflow": "batch_region_replace",
            "workflow_role": "region_replace",
            "batch_tryon_review_item_id": item.id,
            "batch_tryon_version_id": version_id,
            "retry_mode": "region_replace",
            "base_output_asset_id": source.generated_asset_id,
            "image_c_asset_id": payload.image_c_asset_id,
            "region_replace_source_role": reference_source_role,
            "font_reference_asset_id": preserved_font_reference_asset_id,
            "target_edit_mask_asset_id": payload.target_mask_asset_id,
            "source_reference_mask_asset_id": payload.source_reference_mask_asset_id,
            "reference_patch_asset_id": payload.reference_patch_asset_id,
            "edit_region_type": payload.edit_region_type,
            "target_mask_metadata": payload.target_mask_metadata,
            "source_reference_metadata": payload.source_reference_metadata,
            "effective_prompt": effective_prompt,
        },
    }
    job, created = await submit_job(
        session,
        settings,
        organization_id=organization_id,
        user_id=user_id,
        payload=JobSubmitRequest(
            operation_code="batch_tryon.region_replace",
            workspace_type="batch_tryon",
            queue_name="batch_tryon_queue",
            capability="mask_edit",
            model_code=source_job.model_code,
            idempotency_key=job_key,
            project_id=source_job.project_id,
            client_item_id=item.client_item_id,
            input=input_json,
            billing_factors={
                key: value for key, value in {
                    "model": source_job.model_code,
                    "quality": str(source_job.input_json.get("quality") or "standard"),
                    "resolution": str(source_job.input_json.get("size") or "1024"),
                    "resource_pool": "platform",
                }.items()
            },
        ),
        batch_id=item.batch_id,
    )
    if not created:
        existing_version = await session.scalar(select(BatchTryOnVersion).where(
            BatchTryOnVersion.task_id == job.id,
            BatchTryOnVersion.organization_id == organization_id,
        ))
        if existing_version is None:
            raise AppError("batch_tryon.version_initializing", "区域替换版本正在初始化，请稍后重试。", 409)
        return item, existing_version, job, False

    next_number = int(await session.scalar(select(func.max(BatchTryOnVersion.version_number)).where(
        BatchTryOnVersion.item_id == item.id,
    )) or 0) + 1
    now = datetime.now(UTC)
    version = BatchTryOnVersion(
        id=version_id,
        organization_id=organization_id,
        item_id=item.id,
        version_number=next_number,
        parent_version_id=source.id,
        generated_asset_id=None,
        task_id=job.id,
        source_filename=item.source_filename,
        prompt_snapshot=effective_prompt,
        review_notes=payload.edit_prompt,
        retry_mode="region_replace",
        generation_status=job.status,
        review_status="pending",
        created_by=user_id,
        created_at=now,
    )
    session.add(version)
    await session.flush()
    await ensure_batch_try_on_version_filenames(session, item, version, job=job)
    # Region replacement is a review candidate. Keep the approved/current base
    # result visible until a reviewer explicitly accepts this child version.
    item.updated_by = user_id
    await refresh_batch_status(session, item.batch_id)
    await session.flush()
    return item, version, job, True


async def approve_region_replace_version(
    session: AsyncSession, *, organization_id: str, item_id: str, version_id: str, user_id: str,
) -> BatchTryOnReviewItem:
    """Atomically approve a successful region-replace candidate and make it current."""
    from app.services.task_service import refresh_batch_status

    item = await get_review_item(session, organization_id, item_id, lock=True)
    version = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == version_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.organization_id == organization_id,
    ).with_for_update())
    if version is None:
        raise AppError("batch_tryon.version_not_found", "区域替换候选版本不存在。", 404)
    if version.retry_mode != "region_replace":
        raise AppError("batch_tryon.version_not_region_replace", "只能通过区域替换生成的候选版本。", 409)
    if version.generation_status != "succeeded" or not version.generated_asset_id:
        raise AppError("batch_tryon.version_not_reviewable", "区域替换结果尚未生成成功，不能审核通过。", 409)
    if item.current_version_id == version.id and version.review_status == "approved":
        return item
    if item.current_version_id not in {version.parent_version_id, version.id}:
        raise AppError(
            "batch_tryon.region_replace_source_changed",
            "基础结果已经变化，不能再通过这个区域替换候选版本。",
            409,
        )
    now = datetime.now(UTC)
    version.review_status = "approved"
    version.reviewed_by = user_id
    version.reviewed_at = now
    sibling_candidates = list((await session.scalars(select(BatchTryOnVersion).where(
        BatchTryOnVersion.organization_id == organization_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.retry_mode == "region_replace",
        BatchTryOnVersion.review_status == "pending",
        BatchTryOnVersion.id != version.id,
    ))).all())
    for sibling in sibling_candidates:
        sibling.review_status = "rejected"
        sibling.reviewed_by = user_id
        sibling.reviewed_at = now
    item.current_version_id = version.id
    item.approved_version_id = version.id
    item.review_status = "approved"
    item.updated_by = user_id
    await refresh_batch_status(session, item.batch_id)
    await session.flush()
    return item


async def discard_region_replace_version(
    session: AsyncSession, *, organization_id: str, item_id: str, version_id: str, user_id: str,
) -> BatchTryOnReviewItem:
    """Discard one terminal region-replace candidate without changing the approved result."""
    from app.services.task_service import refresh_batch_status

    item = await get_review_item(session, organization_id, item_id, lock=True)
    version = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == version_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.organization_id == organization_id,
    ).with_for_update())
    if version is None:
        raise AppError("batch_tryon.version_not_found", "区域替换候选版本不存在。", 404)
    if version.retry_mode != "region_replace":
        raise AppError("batch_tryon.version_not_region_replace", "只能放弃区域涂抹替换候选版本。", 409)
    if version.review_status == "approved":
        raise AppError("batch_tryon.region_replace_already_confirmed", "该区域替换结果已经确认完成。", 409)
    if version.generation_status not in {"succeeded", "failed", "cancelled", "stopped"}:
        raise AppError("batch_tryon.region_replace_still_running", "区域替换仍在生成中，暂时不能放弃。", 409)
    now = datetime.now(UTC)
    pending_candidates = list((await session.scalars(select(BatchTryOnVersion).where(
        BatchTryOnVersion.organization_id == organization_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.retry_mode == "region_replace",
        BatchTryOnVersion.review_status == "pending",
    ))).all())
    for candidate in pending_candidates:
        candidate.review_status = "rejected"
        candidate.reviewed_by = user_id
        candidate.reviewed_at = now
    item.review_status = "approved" if item.approved_version_id == item.current_version_id else item.review_status
    item.updated_by = user_id
    await refresh_batch_status(session, item.batch_id)
    await session.flush()
    return item


async def approve_version(
    session: AsyncSession, *, organization_id: str, item_id: str, version_id: str, user_id: str,
) -> BatchTryOnReviewItem:
    from app.services.task_service import refresh_batch_status

    item = await get_review_item(session, organization_id, item_id, lock=True)
    version = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == version_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.organization_id == organization_id,
    ).with_for_update())
    if version is None:
        raise AppError("batch_tryon.version_not_found", "审核版本不存在", 404)
    if item.current_version_id != version.id:
        raise AppError("batch_tryon.version_not_current", "只能审核当前最新版本，请刷新后重试", 409)
    if version.review_status == "rejected":
        raise AppError("batch_tryon.version_discarded", "当前版本已经作废，不能再审核通过", 409)
    if version.generation_status != "succeeded" or not version.generated_asset_id:
        raise AppError("batch_tryon.version_not_reviewable", "当前版本尚未生成成功，不能审核通过", 409)
    now = datetime.now(UTC)
    version.review_status = "approved"
    version.reviewed_by = user_id
    version.reviewed_at = now
    item.review_status = "approved"
    item.approved_version_id = version.id
    item.updated_by = user_id
    await refresh_batch_status(session, item.batch_id)
    await session.flush()
    return item


async def discard_version(
    session: AsyncSession, *, organization_id: str, item_id: str, version_id: str, user_id: str,
) -> BatchTryOnReviewItem:
    """Discard the current generated candidate while keeping its image as history."""
    from app.services.task_service import refresh_batch_status

    item = await get_review_item(session, organization_id, item_id, lock=True)
    version = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == version_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.organization_id == organization_id,
    ).with_for_update())
    if version is None:
        raise AppError("batch_tryon.version_not_found", "审核版本不存在", 404)
    if item.current_version_id != version.id:
        raise AppError("batch_tryon.version_not_current", "只能作废当前最新版本，请刷新后重试", 409)
    if version.review_status == "approved" or item.approved_version_id == version.id:
        raise AppError("batch_tryon.version_already_approved", "已经审核通过的版本不能作废", 409)
    if version.generation_status != "succeeded" or not version.generated_asset_id:
        raise AppError("batch_tryon.version_not_reviewable", "当前版本尚未生成成功，不能作废", 409)
    if version.review_status == "rejected" and item.review_status == "rejected":
        return item

    now = datetime.now(UTC)
    version.review_status = "rejected"
    version.reviewed_by = user_id
    version.reviewed_at = now
    item.review_status = "rejected"
    item.updated_by = user_id
    await refresh_batch_status(session, item.batch_id)
    await session.flush()
    return item


async def submit_detailed_review_analysis(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: str,
    item_id: str,
    payload: BatchTryOnDetailedReviewAnalysisRequest,
    user_id: str,
    auto_regenerate: bool = False,
    batch_request_key: str | None = None,
) -> tuple[Job, bool]:
    """Queue one Luna visual review for the current generated image.

    The analysis is deliberately stored as an ordinary durable planning Job.
    Its result can be edited by the reviewer and then passed through the
    existing additive review-notes regeneration path.
    """
    from app.services.task_service import submit_job

    item = await get_review_item(session, organization_id, item_id)
    source = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == payload.source_version_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.organization_id == organization_id,
    ))
    if source is None:
        raise AppError("batch_tryon.version_not_found", "来源版本不存在", 404)
    if item.current_version_id != source.id:
        raise AppError("batch_tryon.version_not_current", "只能精细分析当前最新版本，请刷新后重试", 409)
    if source.generation_status != "succeeded" or not source.generated_asset_id:
        raise AppError("batch_tryon.version_not_reviewable", "当前版本尚未生成成功，不能进行精细分析", 409)

    source_job = await session.scalar(select(Job).where(
        Job.id == source.task_id,
        Job.organization_id == organization_id,
    )) if source.task_id else None
    source_metadata = (
        source_job.input_json.get("metadata")
        if source_job and isinstance(source_job.input_json.get("metadata"), dict)
        else {}
    )
    effective_ids = source_metadata.get("effective_garment_reference_asset_ids")
    if not isinstance(effective_ids, list) or not effective_ids:
        effective_ids = [item.garment_asset_id]
    font_reference_asset_id = str(source_metadata.get("font_reference_asset_id") or "").strip()
    source_references = list(source_job.input_json.get("reference_asset_ids", []) or []) if source_job else []
    reference_ids = [str(value) for value in source_references] or [item.model_asset_id] + [str(value) for value in effective_ids]
    if font_reference_asset_id and font_reference_asset_id not in reference_ids:
        reference_ids.insert(2, font_reference_asset_id)
    found_ids = set((await session.scalars(select(Asset.id).where(
        Asset.organization_id == organization_id,
        Asset.id.in_(reference_ids),
        Asset.deleted_at.is_(None),
    ))).all())
    if found_ids != set(reference_ids):
        raise AppError("batch_tryon.review_asset_missing", "模板图或服装原图已不存在", 409)

    project_id = source_job.project_id if source_job else None
    template_prompt_id = str(source_metadata.get("template_prompt_id") or "").strip()
    template_prompt_record = await session.get(BatchTryOnTemplatePrompt, template_prompt_id) if template_prompt_id else None
    template_type = str(
        payload.template_type
        or source_metadata.get("template_type")
        or (template_prompt_record.template_type if template_prompt_record else "")
        or "pure_white"
    ).strip()
    template_preset = prompt_analysis_preset_only(str(
        source_metadata.get("analysis_prompt_snapshot")
        or (template_prompt_record.analysis_prompt_used if template_prompt_record else "")
    ))
    selected_preset_id: str | None = None
    selected_preset_label: str | None = None
    if payload.prompt_preset_id:
        selected = await resolve_prompt_preset(
            session,
            organization_id=organization_id,
            user_id=user_id,
            preset_id=payload.prompt_preset_id,
            template_type=template_type,
        )
        selected_preset_id = selected.id
        selected_preset_label = selected.label
        template_type = selected.template_type
        template_preset = selected.analysis_prompt_template.strip()
    elif not template_preset:
        selected = await resolve_prompt_preset(
            session,
            organization_id=organization_id,
            user_id=user_id,
            preset_id=(template_prompt_record.preset_id if template_prompt_record else None),
            template_type=template_type,
        )
        selected_preset_id = selected.id
        selected_preset_label = selected.label
        template_preset = selected.analysis_prompt_template.strip()
    if payload.template_prompt_override:
        template_preset = payload.template_prompt_override
    template_preset = template_preset.strip()
    if len(template_preset) < 20:
        raise AppError("batch_tryon.analysis_prompt_too_short", "Luna 分析使用的模板预设至少需要 20 个字符。", 422)
    model_code = await resolve_operation_model_code(
        session,
        organization_id=organization_id,
        operation_code="batch_tryon.prompt_analyze_detailed",
        capability="text_generation",
    )
    job_key = f"batch-review-analysis:{sha256(f'{item.id}:{source.id}:{payload.idempotency_key}'.encode()).hexdigest()}"
    job, created = await submit_job(
        session,
        settings,
        organization_id=organization_id,
        user_id=user_id,
        payload=JobSubmitRequest(
            operation_code="batch_tryon.prompt_analyze_detailed",
            workspace_type="batch_tryon",
            queue_name="planning_queue",
            capability="text_generation",
            model_code=model_code,
            idempotency_key=job_key,
            project_id=project_id,
            client_item_id=f"review-analysis:{item.id}",
            input={
                # The selected/edited preset is the complete and only text instruction.
                # Reference images remain attached in their existing deterministic order.
                "system_prompt": template_preset,
                "user_prompt": "",
                "response_format": "text",
                "reference_asset_ids": reference_ids,
                "metadata": {
                    "workflow": "batch_tryon_review_analysis",
                    "workflow_role": "review_detailed_analysis",
                    "review_item_id": item.id,
                    "source_version_id": source.id,
                    "template_asset_id": item.model_asset_id,
                    "garment_asset_id": item.garment_asset_id,
                    "template_type": template_type,
                    "selected_prompt_preset_id": selected_preset_id,
                    "selected_prompt_preset_label": selected_preset_label,
                    "template_prompt_was_edited": bool(payload.template_prompt_override),
                    "template_prompt_id": source_metadata.get("template_prompt_id"),
                    "prompt_version": source_metadata.get("prompt_version"),
                    "effective_prompt_snapshot": template_preset,
                    "preset_summary": item.preset_summary,
                    "auto_regenerate": auto_regenerate,
                    "batch_request_key": batch_request_key,
                },
            },
            billing_factors={"quality": "detailed", "resolution": "text"},
        ),
    )
    return job, created


async def submit_detailed_review_analysis_batch(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: str,
    payload: BatchTryOnBatchDetailedAnalysisRequest,
    user_id: str,
) -> tuple[list[BatchTryOnBatchDetailedAnalysisTask], list[BatchTryOnBatchDetailedAnalysisError], list[Job]]:
    tasks: list[BatchTryOnBatchDetailedAnalysisTask] = []
    errors: list[BatchTryOnBatchDetailedAnalysisError] = []
    created_jobs: list[Job] = []
    for selected in payload.items:
        try:
            async with session.begin_nested():
                analysis_job, created = await submit_detailed_review_analysis(
                    session,
                    settings,
                    organization_id=organization_id,
                    item_id=selected.item_id,
                    payload=BatchTryOnDetailedReviewAnalysisRequest(
                        source_version_id=selected.version_id,
                        focus_notes=payload.focus_notes,
                        template_type=payload.template_type,
                        prompt_preset_id=payload.prompt_preset_id,
                        template_prompt_override=payload.template_prompt_override,
                        idempotency_key=(
                            "batch-luna-item:"
                            + sha256(f"{payload.idempotency_key}:{selected.item_id}".encode()).hexdigest()
                        ),
                    ),
                    user_id=user_id,
                    auto_regenerate=payload.auto_regenerate,
                    batch_request_key=payload.idempotency_key,
                )
                tasks.append(BatchTryOnBatchDetailedAnalysisTask(
                    item_id=selected.item_id,
                    source_version_id=selected.version_id,
                    analysis_job_id=analysis_job.id,
                    client_item_id=analysis_job.client_item_id or f"review-analysis:{selected.item_id}",
                    created=created,
                    auto_regenerate=payload.auto_regenerate,
                ))
                if created:
                    created_jobs.append(analysis_job)
        except AppError as error:
            errors.append(BatchTryOnBatchDetailedAnalysisError(
                item_id=selected.item_id,
                version_id=selected.version_id,
                code=error.code,
                message=error.message,
            ))
    await session.flush()
    return tasks, errors, created_jobs


async def continue_detailed_review_auto_regeneration(
    session: AsyncSession,
    settings: Settings,
    *,
    analysis_job: Job,
) -> tuple[Job | None, bool]:
    """Create the image regeneration job from one durable Luna result."""
    metadata = analysis_job.input_json.get("metadata") if isinstance(analysis_job.input_json, dict) else None
    if not isinstance(metadata, dict) or metadata.get("workflow_role") != "review_detailed_analysis":
        return None, False
    if not metadata.get("auto_regenerate"):
        return None, False
    result_metadata = analysis_job.result_json.get("metadata") if isinstance(analysis_job.result_json, dict) else None
    if not isinstance(result_metadata, dict):
        raise AppError("batch_tryon.analysis_result_missing", "Luna 分析结果不存在，无法自动重新生成", 409)
    generated_prompt = str(result_metadata.get("text") or "").strip()
    if not generated_prompt:
        raise AppError("batch_tryon.analysis_result_empty", "Luna 未返回可用提示词，无法自动重新生成", 409)
    item_id = str(metadata.get("review_item_id") or "").strip()
    source_version_id = str(metadata.get("source_version_id") or "").strip()
    if not item_id or not source_version_id:
        raise AppError("batch_tryon.analysis_context_missing", "Luna 分析任务缺少审核项上下文", 409)
    item, version, image_job, created = await regenerate_version(
        session,
        settings,
        organization_id=analysis_job.organization_id,
        item_id=item_id,
        payload=BatchTryOnRegenerateRequest(
            source_version_id=source_version_id,
            retry_mode="with_detailed_prompt",
            review_notes=generated_prompt,
            idempotency_key=f"luna-auto-regenerate:{analysis_job.id}",
        ),
        user_id=analysis_job.created_by,
        regeneration_type="luna_detailed_auto",
        require_succeeded_output=True,
    )
    analysis_job.result_json = {
        **(analysis_job.result_json or {}),
        "metadata": {
            **result_metadata,
            "auto_regeneration_status": "submitted",
            "auto_regeneration_job_id": image_job.id,
            "auto_regeneration_version_id": version.id,
            "auto_regeneration_created": created,
        },
    }
    await session.flush()
    return image_job, created


async def regenerate_version(
    session: AsyncSession, settings: Settings, *, organization_id: str, item_id: str,
    payload: BatchTryOnRegenerateRequest, user_id: str,
    regeneration_type: str | None = None,
    require_succeeded_output: bool = False,
) -> tuple[BatchTryOnReviewItem, BatchTryOnVersion, Job, bool]:
    from app.services.task_service import refresh_batch_status, submit_job

    item = await get_review_item(session, organization_id, item_id, lock=True)
    source = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == payload.source_version_id,
        BatchTryOnVersion.item_id == item.id,
        BatchTryOnVersion.organization_id == organization_id,
    ).with_for_update())
    if source is None:
        raise AppError("batch_tryon.version_not_found", "来源版本不存在", 404)
    if require_succeeded_output and (
        source.generation_status != "succeeded" or not source.generated_asset_id
    ):
        raise AppError(
            "batch_tryon.version_not_regenerable",
            "只有已经生成成功且存在结果图的版本才能批量重新生成",
            409,
        )
    if source.generation_status not in {"succeeded", "failed", "cancelled"} or not source.task_id:
        raise AppError("batch_tryon.version_not_regenerable", "当前版本仍在生成或等待调度，暂时不能重新生成", 409)
    if require_succeeded_output:
        available_inputs = int(await session.scalar(
            select(func.count()).select_from(Asset).where(
                Asset.organization_id == organization_id,
                Asset.id.in_([item.model_asset_id, item.garment_asset_id]),
                Asset.deleted_at.is_(None),
            )
        ) or 0)
        if available_inputs != 2:
            raise AppError(
                "batch_tryon.input_asset_missing",
                "模板图或服装原图已删除，不能重新生成",
                409,
            )

    source_job = await session.scalar(select(Job).where(
        Job.id == source.task_id, Job.organization_id == organization_id,
    ))
    if source_job is None:
        raise AppError("batch_tryon.source_job_missing", "来源生成任务不存在", 409)
    job_key = f"batch-review:{sha256(f'{item.id}:{payload.idempotency_key}'.encode()).hexdigest()}"
    version_id = str(uuid5(NAMESPACE_URL, job_key))
    input_json = deepcopy(source_job.input_json)
    source_metadata = input_json.get("metadata") if isinstance(input_json.get("metadata"), dict) else {}
    base_business_prompt = str(
        input_json.get("business_prompt")
        or source_metadata.get("business_prompt")
        or source.prompt_snapshot
    )
    if payload.retry_mode == "with_review_notes":
        retry_prompt = append_manual_retry_constraints(
            base_business_prompt,
            error_codes=list(payload.error_codes),
            manual_notes=payload.review_notes or "",
        )
        input_json["business_prompt"] = retry_prompt
        input_json["technical_delivery_contract"] = ""
        input_json["effective_prompt"] = retry_prompt
        input_json["prompt"] = retry_prompt
    elif payload.retry_mode == "with_detailed_prompt":
        detailed_prompt = str(payload.review_notes or "").strip()
        input_json["business_prompt"] = detailed_prompt
        input_json["technical_delivery_contract"] = ""
        input_json["effective_prompt"] = detailed_prompt
        input_json["prompt"] = detailed_prompt
    else:
        input_json["prompt"] = base_business_prompt
    metadata = input_json.get("metadata") if isinstance(input_json.get("metadata"), dict) else {}
    input_json["metadata"] = {
        **metadata,
        "batch_tryon_review_item_id": item.id,
        "batch_tryon_version_id": version_id,
        "retry_mode": regeneration_type or payload.retry_mode,
        "review_notes": payload.review_notes,
        "manual_error_codes": list(payload.error_codes),
        "business_prompt": input_json.get("business_prompt") or input_json.get("prompt"),
        "effective_prompt": input_json.get("effective_prompt") or input_json.get("prompt"),
    }
    job_payload = JobSubmitRequest(
        operation_code="batch_tryon.generate",
        workspace_type="batch_tryon",
        queue_name="batch_tryon_queue",
        capability=source_job.capability,
        model_code=source_job.model_code,
        idempotency_key=job_key,
        project_id=source_job.project_id,
        client_item_id=item.client_item_id,
        input=input_json,
    )
    existing_job = await session.scalar(select(Job).where(
        Job.organization_id == organization_id, Job.idempotency_key == job_key,
    ))
    if existing_job is None and item.current_version_id != source.id:
        raise AppError("batch_tryon.version_not_current", "当前任务已有更新版本，请刷新后重试", 409)
    job, created = await submit_job(
        session, settings, organization_id=organization_id, user_id=user_id,
        payload=job_payload, batch_id=item.batch_id,
    )
    if not created:
        existing_version = await session.scalar(select(BatchTryOnVersion).where(
            BatchTryOnVersion.task_id == job.id,
            BatchTryOnVersion.organization_id == organization_id,
        ))
        if existing_version is None:
            raise AppError("batch_tryon.version_initializing", "重新生成版本正在初始化，请稍后重试", 409)
        return item, existing_version, job, False

    next_number = int(await session.scalar(select(func.max(BatchTryOnVersion.version_number)).where(
        BatchTryOnVersion.item_id == item.id,
    )) or 0) + 1
    now = datetime.now(UTC)
    version = BatchTryOnVersion(
        id=version_id,
        organization_id=organization_id,
        item_id=item.id,
        version_number=next_number,
        parent_version_id=source.id,
        generated_asset_id=None,
        task_id=job.id,
        source_filename=item.source_filename,
        prompt_snapshot=str(input_json["prompt"]),
        review_notes=payload.review_notes,
        retry_mode=regeneration_type or payload.retry_mode,
        generation_status=job.status,
        review_status="pending",
        created_by=user_id,
        created_at=now,
    )
    session.add(version)
    await session.flush()
    await ensure_batch_try_on_version_filenames(session, item, version, job=job)
    if source.review_status != "approved":
        source.review_status = "rejected"
        source.review_notes = payload.review_notes
        source.reviewed_by = user_id
        source.reviewed_at = now
    item.current_version_id = version.id
    item.review_status = "regenerating"
    item.regeneration_count += 1
    item.updated_by = user_id
    await refresh_batch_status(session, item.batch_id)
    await session.flush()
    return item, version, job, True


async def regenerate_versions_batch(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: str,
    payload: BatchTryOnBatchRegenerateRequest,
    user_id: str,
) -> tuple[list[BatchTryOnBatchRegenerateTask], list[BatchTryOnBatchRegenerateError]]:
    """Create one independent version and queued Job for each valid selection.

    The Job rows are the durable transactional dispatch outbox. This function
    never publishes Celery messages; the scheduler only sees the queued rows
    after the API transaction commits.
    """
    tasks: list[BatchTryOnBatchRegenerateTask] = []
    errors: list[BatchTryOnBatchRegenerateError] = []
    for selected in payload.items:
        try:
            async with session.begin_nested():
                item, version, job, created = await regenerate_version(
                    session,
                    settings,
                    organization_id=organization_id,
                    item_id=selected.item_id,
                    payload=BatchTryOnRegenerateRequest(
                        source_version_id=selected.version_id,
                        retry_mode="with_review_notes",
                        review_notes=payload.review_notes,
                        idempotency_key=payload.idempotency_key,
                    ),
                    user_id=user_id,
                    regeneration_type="batch_review_notes",
                    require_succeeded_output=True,
                )
                tasks.append(BatchTryOnBatchRegenerateTask(
                    item_id=item.id,
                    source_version_id=selected.version_id,
                    version_id=version.id,
                    task_id=job.id,
                    client_item_id=item.client_item_id,
                    template_id=item.template_id,
                    garment_asset_id=item.garment_asset_id,
                    created=created,
                ))
        except AppError as error:
            errors.append(BatchTryOnBatchRegenerateError(
                item_id=selected.item_id,
                version_id=selected.version_id,
                code=error.code,
                message=error.message,
            ))
    await session.flush()
    return tasks, errors


async def sync_batch_try_on_version_for_job(
    session: AsyncSession, job: Job, *, generated_asset_id: str | None = None,
) -> None:
    if job.workspace_type != "batch_tryon":
        return
    metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
    version_id = str(metadata.get("batch_tryon_version_id") or "")
    version = await session.scalar(select(BatchTryOnVersion).where(
        BatchTryOnVersion.id == version_id,
        BatchTryOnVersion.organization_id == job.organization_id,
    )) if version_id else None
    if version is None:
        version = await session.scalar(select(BatchTryOnVersion).where(
            BatchTryOnVersion.task_id == job.id,
            BatchTryOnVersion.organization_id == job.organization_id,
        ))
    if version is None:
        return
    item = await session.get(BatchTryOnReviewItem, version.item_id, with_for_update=True)
    prompt_metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
    effective_prompt = str(
        job.input_json.get("effective_prompt")
        or prompt_metadata.get("effective_prompt")
        or job.input_json.get("prompt")
        or ""
    ).strip()
    if effective_prompt:
        version.prompt_snapshot = effective_prompt
    version.generation_status = job.status
    if generated_asset_id:
        version.generated_asset_id = generated_asset_id
        generated_asset = await session.get(Asset, generated_asset_id)
        await ensure_batch_try_on_version_filenames(
            session, item, version, job=job, generated_asset=generated_asset,
        )
    if job.status == "succeeded":
        version.review_status = "pending"
        version.completed_at = job.finished_at or datetime.now(UTC)
    elif job.status in {"failed", "cancelled"}:
        version.completed_at = job.finished_at or datetime.now(UTC)
    if item is not None and item.current_version_id == version.id:
        item.review_status = _item_status_for_version(version)
        item.updated_by = job.updated_by
    await session.flush()
