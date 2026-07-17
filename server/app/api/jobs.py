from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.schemas.tasks import JobPage, JobResponse, JobSubmitRequest
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.task_service import cancel_job, dispatch_job, get_job, list_jobs, submit_job


router = APIRouter(prefix="/jobs", tags=["jobs"])


def organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "Select an organization first", 409)
    return principal.organization.id


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def add_job(
    payload: JobSubmitRequest, request: Request, response: Response,
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
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
    return JobResponse.model_validate(await get_job(session, org_id, job.id))


@router.get("", response_model=JobPage)
async def get_jobs(
    job_status: str | None = Query(default=None, alias="status", max_length=30),
    limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> JobPage:
    return await list_jobs(session, organization_id(principal), status=job_status, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_detail(
    job_id: str, session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> JobResponse:
    return JobResponse.model_validate(await get_job(session, organization_id(principal), job_id))


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def request_job_cancel(
    job_id: str, request: Request, session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.cancel")),
) -> JobResponse:
    org_id = organization_id(principal)
    job = await cancel_job(session, organization_id=org_id, job_id=job_id, user_id=principal.user.id)
    add_audit_log(session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
                  action="job.cancel", resource_type="job", resource_id=job.id)
    await session.commit()
    return JobResponse.model_validate(await get_job(session, org_id, job.id))
