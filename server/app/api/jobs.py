from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.schemas.tasks import JobBatchPage, JobBatchResponse, JobBatchSubmitRequest, JobPage, JobResponse, JobSubmitRequest
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.storage_service import StorageService, get_storage_service
from app.services.task_service import (
    cancel_job, dispatch_job, get_batch, get_job, job_response, list_jobs,
    refresh_batch_status, submit_batch, submit_job,
)
from app.models.tasks import Job, JobBatch
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
        try:
            dispatch_job(job)
            await session.commit()
        except Exception:
            await session.rollback()
    else:
        response.status_code = status.HTTP_200_OK
    return await job_response(session, storage, settings, await get_job(session, org_id, job.id))


@router.get("", response_model=JobPage)
async def get_jobs(
    job_status: str | None = Query(default=None, alias="status", max_length=30),
    limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> JobPage:
    org_id = organization_id(principal)
    page = await list_jobs(session, org_id, status=job_status, limit=limit, offset=offset)
    jobs = [await get_job(session, org_id, item.id) for item in page.items]
    return page.model_copy(update={"items": [await job_response(session, storage, settings, item) for item in jobs]})


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_detail(
    job_id: str, session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> JobResponse:
    job = await get_job(session, organization_id(principal), job_id)
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
    return await job_response(session, storage, settings, await get_job(session, org_id, job.id))


async def _batch_response(
    session: AsyncSession, storage: StorageService, settings: Settings, batch: JobBatch,
) -> JobBatchResponse:
    jobs = list((await session.scalars(select(Job).where(Job.batch_id == batch.id).order_by(Job.created_at))).all())
    return JobBatchResponse(
        id=batch.id, organization_id=batch.organization_id, project_id=batch.project_id,
        workspace_type=batch.workspace_type, operation_code=batch.operation_code, name=batch.name,
        model_code=batch.model_code, capability=batch.capability, status=batch.status,
        concurrency=batch.concurrency, total_jobs=batch.total_jobs, succeeded_jobs=batch.succeeded_jobs,
        failed_jobs=batch.failed_jobs, cancelled_jobs=batch.cancelled_jobs, error_message=batch.error_message,
        started_at=batch.started_at, finished_at=batch.finished_at, created_at=batch.created_at,
        updated_at=batch.updated_at,
        jobs=[await job_response(session, storage, settings, item) for item in jobs],
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
                  metadata={"jobs": len(jobs), "created": created})
    await session.commit()
    if created:
        for job in jobs:
            try:
                dispatch_job(job)
            except Exception:
                continue
        await session.commit()
    else:
        response.status_code = status.HTTP_200_OK
    return await _batch_response(session, storage, settings, await get_batch(session, org_id, batch.id))


@batch_router.get("", response_model=JobBatchPage)
async def get_job_batches(
    batch_status: str | None = Query(default=None, alias="status", max_length=30),
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> JobBatchPage:
    org_id = organization_id(principal)
    filters = [JobBatch.organization_id == org_id]
    if batch_status:
        filters.append(JobBatch.status == batch_status)
    total = int(await session.scalar(select(func.count()).select_from(JobBatch).where(*filters)) or 0)
    batches = list((await session.scalars(select(JobBatch).where(*filters).order_by(JobBatch.created_at.desc()).limit(limit).offset(offset))).all())
    return JobBatchPage(items=[await _batch_response(session, storage, settings, item) for item in batches], total=total, limit=limit, offset=offset)


@batch_router.get("/{batch_id}", response_model=JobBatchResponse)
async def get_job_batch_detail(
    batch_id: str, session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> JobBatchResponse:
    batch = await get_batch(session, organization_id(principal), batch_id)
    return await _batch_response(session, storage, settings, batch)


@batch_router.post("/{batch_id}/cancel", response_model=JobBatchResponse)
async def cancel_job_batch(
    batch_id: str, request: Request, session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.cancel")),
) -> JobBatchResponse:
    org_id = organization_id(principal)
    batch = await get_batch(session, org_id, batch_id, lock=True)
    jobs = list((await session.scalars(select(Job).where(Job.batch_id == batch.id))).all())
    for job in jobs:
        await cancel_job(session, organization_id=org_id, job_id=job.id, user_id=principal.user.id)
    await refresh_batch_status(session, batch.id)
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                  action="job_batch.cancel", resource_type="job_batch", resource_id=batch.id)
    await session.commit()
    return await _batch_response(session, storage, settings, await get_batch(session, org_id, batch.id))


@batch_router.post("/{batch_id}/pause", response_model=JobBatchResponse)
async def pause_job_batch(
    batch_id: str, request: Request, session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.cancel")),
) -> JobBatchResponse:
    org_id = organization_id(principal)
    batch = await get_batch(session, org_id, batch_id, lock=True)
    if batch.status not in {"succeeded", "failed", "cancelled", "partially_succeeded"}:
        batch.status = "paused"
        add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                      action="job_batch.pause", resource_type="job_batch", resource_id=batch.id)
        await session.commit()
    return await _batch_response(session, storage, settings, await get_batch(session, org_id, batch.id))


@batch_router.post("/{batch_id}/resume", response_model=JobBatchResponse)
async def resume_job_batch(
    batch_id: str, request: Request, session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> JobBatchResponse:
    org_id = organization_id(principal)
    batch = await get_batch(session, org_id, batch_id, lock=True)
    if batch.status == "paused":
        batch.status = "running" if batch.started_at else "queued"
        jobs = list((await session.scalars(select(Job).where(
            Job.batch_id == batch.id,
            Job.status.in_(["queued", "dispatching", "retry_waiting"]),
        ))).all())
        for job in jobs:
            job.dispatched_at = None
            job.celery_task_id = None
            if job.status == "dispatching":
                job.status = "queued"
        add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                      action="job_batch.resume", resource_type="job_batch", resource_id=batch.id)
        await session.commit()
        for job in jobs:
            try:
                dispatch_job(job)
            except Exception:
                continue
        await session.commit()
    return await _batch_response(session, storage, settings, await get_batch(session, org_id, batch.id))
