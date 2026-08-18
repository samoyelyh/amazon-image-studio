
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.schemas.batch_tryon_review import (
    BatchTryOnApproveRequest,
    BatchTryOnBatchDetailedAnalysisRequest,
    BatchTryOnBatchDetailedAnalysisResponse,
    BatchTryOnBatchRegenerateRequest,
    BatchTryOnBatchRegenerateResponse,
    BatchTryOnDetailedReviewAnalysisRequest,
    BatchTryOnRegenerateRequest,
    BatchTryOnRegenerateResponse,
    BatchTryOnRegionReplaceRequest,
    BatchTryOnRegionReplaceResponse,
    BatchTryOnReviewDetailResponse,
    BatchTryOnSelectVersionRequest,
    BatchTryOnTemplateExportRequest,
)
from app.schemas.tasks import JobResponse
from app.models.tasks import BatchTryOnReviewItem, JobBatch
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.asset_service import content_disposition_header
from app.services.batch_tryon_export_service import (
    build_batch_try_on_template_zip,
    build_selected_batch_try_on_template_zip,
)
from app.services.batch_tryon_review_service import (
    approve_region_replace_version,
    approve_version,
    discard_region_replace_version,
    ensure_batch_try_on_review_records,
    regenerate_version,
    regenerate_versions_batch,
    review_detail,
    select_review_version,
    submit_detailed_review_analysis,
    submit_detailed_review_analysis_batch,
    submit_region_replace,
)
from app.services.storage_service import StorageService, get_storage_service
from app.services.task_service import dispatch_jobs, get_batch, get_job, job_response


router = APIRouter(prefix="/batch-tryon/items", tags=["batch-tryon-review"])
batch_router = APIRouter(prefix="/batch-tryon/batches", tags=["batch-tryon-review"])
template_router = APIRouter(prefix="/batch-tryon/templates", tags=["batch-tryon-review"])


def organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "Select an organization first", 409)
    return principal.organization.id


async def _require_owned_review_items(
    session: AsyncSession,
    principal: Principal,
    item_ids: list[str],
) -> None:
    requested = set(item_ids)
    if not requested:
        return
    existing = set((await session.scalars(
        select(BatchTryOnReviewItem.id).where(
            BatchTryOnReviewItem.organization_id == organization_id(principal),
            BatchTryOnReviewItem.id.in_(requested),
        )
    )).all())
    owned = set((await session.scalars(
        select(BatchTryOnReviewItem.id)
        .join(JobBatch, JobBatch.id == BatchTryOnReviewItem.batch_id)
        .where(
            BatchTryOnReviewItem.organization_id == organization_id(principal),
            BatchTryOnReviewItem.id.in_(requested),
            JobBatch.created_by == principal.user.id,
        )
    )).all())
    if existing - owned:
        raise AppError(
            "batch_tryon.review_item_not_found",
            "审核记录不存在或不属于当前账号。",
            404,
        )


async def _require_owned_review_item(
    session: AsyncSession, principal: Principal, item_id: str,
) -> None:
    await _require_owned_review_items(session, principal, [item_id])


@router.post(
    "/batch-detailed-analysis-auto-regenerate",
    response_model=BatchTryOnBatchDetailedAnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def batch_detailed_analysis_auto_regenerate(
    payload: BatchTryOnBatchDetailedAnalysisRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("batch_tryon.review", "jobs.submit")),
) -> BatchTryOnBatchDetailedAnalysisResponse:
    org_id = organization_id(principal)
    await _require_owned_review_items(
        session, principal, [item.item_id for item in payload.items],
    )
    analysis_tasks, errors, created_jobs = await submit_detailed_review_analysis_batch(
        session,
        settings,
        organization_id=org_id,
        payload=payload,
        user_id=principal.user.id,
    )
    created_count = sum(1 for task in analysis_tasks if task.created)
    replayed_count = len(analysis_tasks) - created_count
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="batch_tryon.review.batch_detailed_analysis_auto_regenerate",
        resource_type="batch_tryon_review_item",
        resource_id=None,
        metadata={
            "requested_count": len(payload.items),
            "created_count": created_count,
            "replayed_count": replayed_count,
            "failed_count": len(errors),
            "auto_regenerate": payload.auto_regenerate,
            "item_ids": [item.item_id for item in payload.items],
        },
    )
    await session.commit()
    if created_jobs:
        await dispatch_jobs(session, created_jobs)
    if errors:
        response.status_code = status.HTTP_207_MULTI_STATUS
    elif not created_count:
        response.status_code = status.HTTP_200_OK
    return BatchTryOnBatchDetailedAnalysisResponse(
        requested_count=len(payload.items),
        created_count=created_count,
        replayed_count=replayed_count,
        failed_count=len(errors),
        auto_regenerate=payload.auto_regenerate,
        analysis_tasks=analysis_tasks,
        errors=errors,
    )


def template_archive_response(
    archive,
    *,
    filename: str,
    success_count: int,
    skipped_count: int,
    template_id: str,
    scope: str,
) -> StreamingResponse:
    def stream_archive():
        try:
            while chunk := archive.read(1024 * 1024):
                yield chunk
        finally:
            archive.close()

    return StreamingResponse(
        stream_archive(),
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition_header(filename),
            "Cache-Control": "private, no-store",
            "X-Batch-Try-On-Exported": str(success_count),
            "X-Batch-Try-On-Skipped": str(skipped_count),
            "X-Batch-Try-On-Template": template_id,
            "X-Batch-Try-On-Scope": scope,
        },
    )


@batch_router.get("/{batch_id}/review-items", response_model=list[BatchTryOnReviewDetailResponse])
async def list_batch_try_on_review_items(
    batch_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[BatchTryOnReviewDetailResponse]:
    org_id = organization_id(principal)
    batch = await get_batch(
        session, org_id, batch_id, owner_user_id=principal.user.id,
    )
    await ensure_batch_try_on_review_records(session, batch)
    item_ids = list((await session.scalars(
        select(BatchTryOnReviewItem.id).where(
            BatchTryOnReviewItem.organization_id == org_id,
            BatchTryOnReviewItem.batch_id == batch.id,
        ).order_by(BatchTryOnReviewItem.created_at, BatchTryOnReviewItem.id)
    )).all())
    details = [await review_detail(session, org_id, item_id) for item_id in item_ids]
    await session.commit()
    return details


@router.post(
    "/batch-regenerate-with-notes",
    response_model=BatchTryOnBatchRegenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def batch_regenerate_review_items(
    payload: BatchTryOnBatchRegenerateRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(
        require_permissions("batch_tryon.review", "jobs.submit")
    ),
) -> BatchTryOnBatchRegenerateResponse:
    org_id = organization_id(principal)
    await _require_owned_review_items(
        session, principal, [item.item_id for item in payload.items],
    )
    created_tasks, errors = await regenerate_versions_batch(
        session,
        settings,
        organization_id=org_id,
        payload=payload,
        user_id=principal.user.id,
    )
    created_count = sum(1 for task in created_tasks if task.created)
    replayed_count = len(created_tasks) - created_count
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="batch_tryon.review.batch_regenerate",
        resource_type="batch_tryon_review_item",
        resource_id=None,
        metadata={
            "requested_count": len(payload.items),
            "created_count": created_count,
            "replayed_count": replayed_count,
            "failed_count": len(errors),
            "item_ids": [item.item_id for item in payload.items],
        },
    )
    # Commit queued Job rows before the scheduler publishes Celery messages.
    # These rows are the existing durable dispatch outbox.
    await session.commit()
    if errors:
        response.status_code = status.HTTP_207_MULTI_STATUS
    elif not created_count:
        response.status_code = status.HTTP_200_OK
    return BatchTryOnBatchRegenerateResponse(
        requested_count=len(payload.items),
        created_count=created_count,
        replayed_count=replayed_count,
        failed_count=len(errors),
        created_tasks=created_tasks,
        errors=errors,
    )


@batch_router.get("/{batch_id}/templates/{template_id}/download")
async def download_batch_try_on_template_results(
    batch_id: str,
    template_id: str,
    scope: Literal["approved", "all_succeeded"] = Query(default="approved"),
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(
        require_permissions("jobs.read", "assets.read")
    ),
) -> StreamingResponse:
    org_id = organization_id(principal)
    batch = await get_batch(
        session, org_id, batch_id, owner_user_id=principal.user.id,
    )
    await ensure_batch_try_on_review_records(session, batch)
    archive, filename, success_count, skipped_count = (
        await build_batch_try_on_template_zip(
            session,
            storage,
            batch=batch,
            template_id=template_id,
            scope=scope,
        )
    )
    await session.commit()

    return template_archive_response(
        archive,
        filename=filename,
        success_count=success_count,
        skipped_count=skipped_count,
        template_id=template_id,
        scope=scope,
    )


@template_router.post("/{template_id}/download")
async def download_selected_batch_try_on_template_results(
    template_id: str,
    payload: BatchTryOnTemplateExportRequest,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(
        require_permissions("jobs.read", "assets.read")
    ),
) -> StreamingResponse:
    await _require_owned_review_items(session, principal, payload.item_ids)
    archive, filename, success_count, skipped_count = (
        await build_selected_batch_try_on_template_zip(
            session,
            storage,
            organization_id=organization_id(principal),
            template_id=template_id,
            item_ids=payload.item_ids,
            scope=payload.scope,
        )
    )
    await session.commit()
    return template_archive_response(
        archive,
        filename=filename,
        success_count=success_count,
        skipped_count=skipped_count,
        template_id=template_id,
        scope=payload.scope,
    )


@router.get("/{item_id}/review-detail", response_model=BatchTryOnReviewDetailResponse)
async def get_review_detail(
    item_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> BatchTryOnReviewDetailResponse:
    await _require_owned_review_item(session, principal, item_id)
    detail = await review_detail(session, organization_id(principal), item_id)
    await session.commit()
    return detail


@router.post("/{item_id}/approve", response_model=BatchTryOnReviewDetailResponse)
async def approve_review_item(
    item_id: str,
    payload: BatchTryOnApproveRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("batch_tryon.review")),
) -> BatchTryOnReviewDetailResponse:
    org_id = organization_id(principal)
    await _require_owned_review_item(session, principal, item_id)
    item = await approve_version(
        session, organization_id=org_id, item_id=item_id,
        version_id=payload.source_version_id, user_id=principal.user.id,
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="batch_tryon.review.approve", resource_type="batch_tryon_review_item", resource_id=item.id,
        metadata={"version_id": payload.source_version_id},
    )
    await session.commit()
    return await review_detail(session, org_id, item.id)


@router.post("/{item_id}/regenerate", response_model=BatchTryOnRegenerateResponse, status_code=status.HTTP_202_ACCEPTED)
async def regenerate_review_item(
    item_id: str,
    payload: BatchTryOnRegenerateRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("batch_tryon.review", "jobs.submit")),
) -> BatchTryOnRegenerateResponse:
    org_id = organization_id(principal)
    await _require_owned_review_item(session, principal, item_id)
    item, version, job, created = await regenerate_version(
        session, settings, organization_id=org_id, item_id=item_id,
        payload=payload, user_id=principal.user.id,
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="batch_tryon.review.regenerate", resource_type="batch_tryon_review_item", resource_id=item.id,
        metadata={"source_version_id": payload.source_version_id, "version_id": version.id, "retry_mode": payload.retry_mode, "created": created},
    )
    await session.commit()
    if created:
        await dispatch_jobs(session, [job])
    else:
        response.status_code = status.HTTP_200_OK
    current_job = await get_job(session, org_id, job.id)
    return BatchTryOnRegenerateResponse(
        review=await review_detail(session, org_id, item.id),
        job=await job_response(session, storage, settings, current_job),
    )


@router.post(
    "/{item_id}/region-replace",
    response_model=BatchTryOnRegionReplaceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def region_replace_review_item(
    item_id: str,
    payload: BatchTryOnRegionReplaceRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("batch_tryon.review", "jobs.submit")),
) -> BatchTryOnRegionReplaceResponse:
    org_id = organization_id(principal)
    await _require_owned_review_item(session, principal, item_id)
    item, version, job, created = await submit_region_replace(
        session,
        settings,
        organization_id=org_id,
        item_id=item_id,
        payload=payload,
        user_id=principal.user.id,
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="batch_tryon.review.region_replace",
        resource_type="batch_tryon_review_item",
        resource_id=item.id,
        metadata={
            "source_version_id": payload.source_version_id,
            "version_id": version.id,
            "edit_region_type": payload.edit_region_type,
            "created": created,
        },
    )
    await session.commit()
    if created:
        await dispatch_jobs(session, [job])
    else:
        response.status_code = status.HTTP_200_OK
    current_job = await get_job(session, org_id, job.id)
    return BatchTryOnRegionReplaceResponse(
        review=await review_detail(session, org_id, item.id),
        job=await job_response(session, storage, settings, current_job),
    )


@router.post("/{item_id}/region-replace/approve", response_model=BatchTryOnReviewDetailResponse)
async def approve_region_replace_candidate(
    item_id: str,
    payload: BatchTryOnApproveRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("batch_tryon.review")),
) -> BatchTryOnReviewDetailResponse:
    org_id = organization_id(principal)
    await _require_owned_review_item(session, principal, item_id)
    item = await approve_region_replace_version(
        session,
        organization_id=org_id,
        item_id=item_id,
        version_id=payload.source_version_id,
        user_id=principal.user.id,
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="batch_tryon.review.region_replace.approve",
        resource_type="batch_try_on_version",
        resource_id=payload.source_version_id,
        metadata={"item_id": item.id, "version_id": payload.source_version_id},
    )
    await session.commit()
    return await review_detail(session, org_id, item.id)


@router.post("/{item_id}/region-replace/discard", response_model=BatchTryOnReviewDetailResponse)
async def discard_region_replace_candidate(
    item_id: str,
    payload: BatchTryOnApproveRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("batch_tryon.review")),
) -> BatchTryOnReviewDetailResponse:
    org_id = organization_id(principal)
    await _require_owned_review_item(session, principal, item_id)
    item = await discard_region_replace_version(
        session,
        organization_id=org_id,
        item_id=item_id,
        version_id=payload.source_version_id,
        user_id=principal.user.id,
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="batch_tryon.review.region_replace.discard",
        resource_type="batch_try_on_version",
        resource_id=payload.source_version_id,
        metadata={"item_id": item.id, "version_id": payload.source_version_id},
    )
    await session.commit()
    return await review_detail(session, org_id, item.id)


@router.post("/{item_id}/select-version", response_model=BatchTryOnReviewDetailResponse)
async def select_review_item_version(
    item_id: str,
    payload: BatchTryOnSelectVersionRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("batch_tryon.review")),
) -> BatchTryOnReviewDetailResponse:
    org_id = organization_id(principal)
    await _require_owned_review_item(session, principal, item_id)
    item = await select_review_version(
        session,
        organization_id=org_id,
        item_id=item_id,
        version_id=payload.version_id,
        user_id=principal.user.id,
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="batch_tryon.review.select_version",
        resource_type="batch_tryon_review_item",
        resource_id=item.id,
        metadata={"version_id": payload.version_id},
    )
    await session.commit()
    return await review_detail(session, org_id, item.id)


@router.post(
    "/{item_id}/detailed-analysis",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_review_item_in_detail(
    item_id: str,
    payload: BatchTryOnDetailedReviewAnalysisRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("batch_tryon.review", "jobs.submit")),
) -> JobResponse:
    org_id = organization_id(principal)
    await _require_owned_review_item(session, principal, item_id)
    job, created = await submit_detailed_review_analysis(
        session,
        settings,
        organization_id=org_id,
        item_id=item_id,
        payload=payload,
        user_id=principal.user.id,
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="batch_tryon.review.detailed_analysis",
        resource_type="batch_tryon_review_item",
        resource_id=item_id,
        metadata={"source_version_id": payload.source_version_id, "job_id": job.id, "created": created},
    )
    await session.commit()
    if created:
        await dispatch_jobs(session, [job])
    else:
        response.status_code = status.HTTP_200_OK
    return await job_response(session, storage, settings, await get_job(session, org_id, job.id))
