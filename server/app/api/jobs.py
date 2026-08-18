from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.schemas.tasks import (
    JobBatchDiagnosticsResponse, JobBatchHardDeleteResponse, JobBatchPage, JobBatchResponse, JobBatchSubmitRequest,
    JobBatchStatusRequest, JobPage, JobResponse, JobSubmitRequest,
)
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.asset_service import content_disposition_header
from app.services.storage_service import StorageService, get_storage_service
from app.services.job_diagnostics_service import batch_diagnostics
from app.services.job_batch_deletion_service import delete_storage_objects, hard_delete_job_batch
from app.services.task_service import (
    cancel_job, dispatch_jobs, due_jobs, effective_batch_jobs, get_batch, get_job, job_response, list_jobs,
    refresh_batch_status, submit_batch, submit_job,
)
from app.models.tasks import BatchGarmentStyleProfile, Job, JobBatch
from sqlalchemy import func, select


router = APIRouter(prefix="/jobs", tags=["jobs"])
batch_router = APIRouter(prefix="/job-batches", tags=["job-batches"])


def organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "Select an organization first", 409)
    return principal.organization.id


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def add_job(
    payload: JobSubmitRequest, request: Request, response: Response,
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> JobResponse:
    org_id = organization_id(principal)
    job, created = await submit_job(session, settings, organization_id=org_id, user_id=principal.user.id, payload=payload)
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                  action="job.submit", resource_type="job", resource_id=job.id,
                  metadata={"operation_code": job.operation_code, "created": created})
    await session.commit()
    if created:
        await dispatch_jobs(session, await due_jobs(session, settings, limit=1))
    else:
        response.status_code = status.HTTP_200_OK
    return await job_response(session, storage, settings, await get_job(
        session, org_id, job.id, owner_user_id=principal.user.id,
    ))


@router.get("", response_model=JobPage)
async def get_jobs(
    job_status: str | None = Query(default=None, alias="status", max_length=30),
    limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> JobPage:
    org_id = organization_id(principal)
    page = await list_jobs(
        session, org_id, status=job_status, limit=limit, offset=offset,
        owner_user_id=principal.user.id,
    )
    jobs = [await get_job(session, org_id, item.id, owner_user_id=principal.user.id) for item in page.items]
    return page.model_copy(update={"items": [await job_response(session, storage, settings, item) for item in jobs]})


@router.post("/batch-status", response_model=list[JobResponse])
async def get_job_batch_status(
    payload: JobBatchStatusRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[JobResponse]:
    org_id = organization_id(principal)
    jobs_by_id = {
        job.id: job
        for job in (await session.scalars(
            select(Job).where(
                Job.organization_id == org_id,
                Job.created_by == principal.user.id,
                Job.id.in_(payload.job_ids),
            )
        )).all()
    }
    if len(jobs_by_id) != len(payload.job_ids):
        raise AppError(
            "job.batch_status_incomplete",
            "部分任务不存在或无权访问，请刷新页面后重试",
            404,
        )
    return [
        await job_response(session, storage, settings, jobs_by_id[job_id])
        for job_id in payload.job_ids
    ]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_detail(
    job_id: str, session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> JobResponse:
    job = await get_job(
        session, organization_id(principal), job_id, owner_user_id=principal.user.id,
    )
    return await job_response(session, storage, settings, job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def request_job_cancel(
    job_id: str, request: Request, session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.cancel")),
) -> JobResponse:
    org_id = organization_id(principal)
    job = await cancel_job(session, organization_id=org_id, job_id=job_id, user_id=principal.user.id)
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                  action="job.cancel", resource_type="job", resource_id=job.id)
    await session.commit()
    return await job_response(session, storage, settings, await get_job(
        session, org_id, job.id, owner_user_id=principal.user.id,
    ))


async def _batch_response(
    session: AsyncSession, storage: StorageService, settings: Settings, batch: JobBatch,
    *, include_jobs: bool = True,
) -> JobBatchResponse:
    if include_jobs and batch.workspace_type == "batch_tryon":
        from app.services.batch_tryon_review_service import ensure_batch_try_on_review_records

        batch_id = batch.id
        organization_id = batch.organization_id
        await ensure_batch_try_on_review_records(session, batch)
        await refresh_batch_status(session, batch.id)
        await session.commit()
        batch = await get_batch(session, organization_id, batch_id)
    jobs: list[Job] = []
    style_profiles: list[BatchGarmentStyleProfile] = []
    if include_jobs:
        jobs, _ = await effective_batch_jobs(session, batch)
        if batch.workspace_type == "batch_tryon":
            style_profiles = list((await session.scalars(
                select(BatchGarmentStyleProfile)
                .where(BatchGarmentStyleProfile.batch_id == batch.id)
                .order_by(BatchGarmentStyleProfile.created_at, BatchGarmentStyleProfile.id)
            )).all())
    cancel_requested_jobs = int(await session.scalar(
        select(func.count()).select_from(Job).where(
            Job.batch_id == batch.id,
            Job.cancel_requested_at.is_not(None),
            Job.status.not_in({"succeeded", "failed", "cancelled"}),
        )
    ) or 0)
    return JobBatchResponse(
        id=batch.id, organization_id=batch.organization_id, project_id=batch.project_id,
        workspace_type=batch.workspace_type, operation_code=batch.operation_code, name=batch.name,
        parent_batch_id=batch.parent_batch_id, batch_kind=batch.batch_kind,
        model_code=batch.model_code, capability=batch.capability, status=batch.status,
        concurrency=batch.concurrency, admin_test_mode=batch.admin_test_mode,
        total_jobs=batch.total_jobs, succeeded_jobs=batch.succeeded_jobs,
        failed_jobs=batch.failed_jobs, cancelled_jobs=batch.cancelled_jobs,
        cancel_requested_jobs=cancel_requested_jobs, error_message=batch.error_message,
        started_at=batch.started_at, finished_at=batch.finished_at, created_at=batch.created_at,
        updated_at=batch.updated_at,
        jobs=[await job_response(session, storage, settings, item) for item in jobs],
        style_profiles=style_profiles,
    )


@batch_router.post("", response_model=JobBatchResponse, status_code=status.HTTP_202_ACCEPTED)
async def add_job_batch(
    payload: JobBatchSubmitRequest, request: Request, response: Response,
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> JobBatchResponse:
    org_id = organization_id(principal)
    batch, jobs, created = await submit_batch(
        session, settings, organization_id=org_id, user_id=principal.user.id, payload=payload,
    )
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                  action="job_batch.submit", resource_type="job_batch", resource_id=batch.id,
                  metadata={
                      "jobs": len(jobs), "created": created,
                      "concurrency": payload.concurrency,
                      "admin_test_mode": payload.admin_test_mode,
                  })
    await session.commit()
    if created:
        due = await due_jobs(session, settings, limit=len(jobs), batch_id=batch.id)
        await dispatch_jobs(session, due)
    else:
        response.status_code = status.HTTP_200_OK
    return await _batch_response(session, storage, settings, await get_batch(
        session, org_id, batch.id, owner_user_id=principal.user.id,
    ))


@batch_router.get("", response_model=JobBatchPage)
async def get_job_batches(
    batch_status: str | None = Query(default=None, alias="status", max_length=30),
    workspace_type: str | None = Query(default=None, max_length=30),
    operation_code: str | None = Query(default=None, max_length=100),
    project_id: str | None = Query(default=None, max_length=64),
    include_jobs: bool = Query(default=True),
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> JobBatchPage:
    org_id = organization_id(principal)
    filters = [
        JobBatch.organization_id == org_id,
        JobBatch.created_by == principal.user.id,
    ]
    if batch_status:
        filters.append(JobBatch.status == batch_status)
    if workspace_type:
        filters.append(JobBatch.workspace_type == workspace_type)
    if operation_code:
        filters.append(JobBatch.operation_code == operation_code)
    if project_id:
        filters.append(JobBatch.project_id == project_id)
    total = int(await session.scalar(select(func.count()).select_from(JobBatch).where(*filters)) or 0)
    # Select the narrow ID set first. JobBatch contains a potentially large workspace_config JSON value;
    # asking MySQL to sort the full rows can exhaust sort_buffer_size even for a modest page.
    batch_ids = list((await session.scalars(
        select(JobBatch.id)
        .where(*filters)
        .order_by(JobBatch.created_at.desc(), JobBatch.id.desc())
        .limit(limit)
        .offset(offset)
    )).all())
    batches_by_id = {
        item.id: item
        for item in (await session.scalars(select(JobBatch).where(JobBatch.id.in_(batch_ids)))).all()
    } if batch_ids else {}
    batches = [batches_by_id[batch_id] for batch_id in batch_ids if batch_id in batches_by_id]
    return JobBatchPage(
        items=[
            await _batch_response(session, storage, settings, item, include_jobs=include_jobs)
            for item in batches
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@batch_router.get("/{batch_id}", response_model=JobBatchResponse)
async def get_job_batch_detail(
    batch_id: str, session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> JobBatchResponse:
    batch = await get_batch(
        session, organization_id(principal), batch_id, owner_user_id=principal.user.id,
    )
    return await _batch_response(session, storage, settings, batch)


@batch_router.get("/{batch_id}/diagnostics", response_model=JobBatchDiagnosticsResponse)
async def get_job_batch_diagnostics(
    batch_id: str,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.read", "audit.read")),
) -> JobBatchDiagnosticsResponse:
    batch = await get_batch(
        session, organization_id(principal), batch_id, owner_user_id=principal.user.id,
    )
    return await batch_diagnostics(session, settings, batch=batch)


@batch_router.get("/{batch_id}/batch-tryon-results.zip")
async def download_batch_try_on_results(
    batch_id: str,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read", "assets.read")),
) -> Response:
    from app.services.batch_tryon_export_service import build_batch_try_on_results_zip

    batch = await get_batch(
        session, organization_id(principal), batch_id, owner_user_id=principal.user.id,
    )
    content, success_count, skipped_count = await build_batch_try_on_results_zip(
        session, storage, batch=batch,
    )
    await session.commit()
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition_header("batch-tryon-results.zip"),
            "Cache-Control": "private, no-store",
            "X-Batch-Try-On-Exported": str(success_count),
            "X-Batch-Try-On-Skipped": str(skipped_count),
        },
    )


@batch_router.post("/{batch_id}/cancel", response_model=JobBatchResponse)
async def cancel_job_batch(
    batch_id: str, request: Request, session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.cancel")),
) -> JobBatchResponse:
    org_id = organization_id(principal)
    batch = await get_batch(
        session, org_id, batch_id, lock=True, owner_user_id=principal.user.id,
    )
    if batch.batch_kind == "workspace":
        raise AppError(
            "job.workspace_batch_action_invalid",
            "This record is a batch workspace, not an executable task batch",
            409,
        )
    jobs = list((await session.scalars(select(Job).where(Job.batch_id == batch.id))).all())
    for job in jobs:
        await cancel_job(session, organization_id=org_id, job_id=job.id, user_id=principal.user.id)
    await refresh_batch_status(session, batch.id)
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                  action="job_batch.cancel", resource_type="job_batch", resource_id=batch.id)
    await session.commit()
    return await _batch_response(session, storage, settings, await get_batch(
        session, org_id, batch.id, owner_user_id=principal.user.id,
    ))


@batch_router.delete("/{batch_id}/hard", response_model=JobBatchHardDeleteResponse)
async def hard_delete_task_batch(
    batch_id: str,
    request: Request,
    confirmation: str = Query(max_length=32),
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.cancel", "assets.delete")),
) -> JobBatchHardDeleteResponse:
    if confirmation != "PERMANENT_DELETE":
        raise AppError("job.batch_delete_confirmation_required", "永久删除确认信息无效。", 422)
    org_id = organization_id(principal)
    result = await hard_delete_job_batch(
        session,
        organization_id=org_id,
        batch_id=batch_id,
        include_workspace_children=False,
        owner_user_id=principal.user.id,
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="job_batch.hard_delete",
        resource_type="job_batch",
        resource_id=batch_id,
        metadata={
            "deleted_batches": result.deleted_batches,
            "deleted_jobs": result.deleted_jobs,
            "deleted_outputs": result.deleted_outputs,
            "deleted_assets": result.deleted_assets,
        },
    )
    await session.commit()
    await delete_storage_objects(storage, result)
    return JobBatchHardDeleteResponse(
        deleted_batches=result.deleted_batches,
        deleted_jobs=result.deleted_jobs,
        deleted_outputs=result.deleted_outputs,
        deleted_assets=result.deleted_assets,
        retained_shared_assets=result.retained_shared_assets,
        storage_delete_failures=result.storage_delete_failures,
    )


@batch_router.post("/{batch_id}/pause", response_model=JobBatchResponse)
async def pause_job_batch(
    batch_id: str, request: Request, session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.cancel")),
) -> JobBatchResponse:
    org_id = organization_id(principal)
    batch = await get_batch(
        session, org_id, batch_id, lock=True, owner_user_id=principal.user.id,
    )
    if batch.batch_kind == "workspace":
        raise AppError(
            "job.workspace_batch_action_invalid",
            "This record is a batch workspace, not an executable task batch",
            409,
        )
    if batch.status not in {"succeeded", "failed", "cancelled", "partially_succeeded"}:
        batch.status = "paused"
        add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                      action="job_batch.pause", resource_type="job_batch", resource_id=batch.id)
        await session.commit()
    return await _batch_response(session, storage, settings, await get_batch(
        session, org_id, batch.id, owner_user_id=principal.user.id,
    ))


@batch_router.post("/{batch_id}/resume", response_model=JobBatchResponse)
async def resume_job_batch(
    batch_id: str, request: Request, session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> JobBatchResponse:
    org_id = organization_id(principal)
    batch = await get_batch(
        session, org_id, batch_id, lock=True, owner_user_id=principal.user.id,
    )
    if batch.batch_kind == "workspace":
        raise AppError(
            "job.workspace_batch_action_invalid",
            "This record is a batch workspace, not an executable task batch",
            409,
        )
    if batch.status == "paused":
        batch.status = "running" if batch.started_at else "queued"
        stale_dispatching = list((await session.scalars(select(Job).where(
            Job.batch_id == batch.id,
            Job.status == "dispatching",
        ))).all())
        for job in stale_dispatching:
            job.dispatched_at = None
            job.celery_task_id = None
            job.status = "queued"
        jobs = await due_jobs(session, settings, limit=batch.concurrency, batch_id=batch.id)
        add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                      action="job_batch.resume", resource_type="job_batch", resource_id=batch.id)
        await session.commit()
        await dispatch_jobs(session, jobs)
    return await _batch_response(session, storage, settings, await get_batch(
        session, org_id, batch.id, owner_user_id=principal.user.id,
    ))
