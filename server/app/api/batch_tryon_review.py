import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.schemas.batch_tryon_review import (
    BatchTryOnApproveRequest,
    BatchTryOnRegenerateRequest,
    BatchTryOnRegenerateResponse,
    BatchTryOnReviewDetailResponse,
)
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.batch_tryon_review_service import (
    approve_version,
    regenerate_version,
    review_detail,
)
from app.services.storage_service import StorageService, get_storage_service
from app.services.task_service import dispatch_job, get_job, job_response


router = APIRouter(prefix="/batch-tryon/items", tags=["batch-tryon-review"])
logger = logging.getLogger(__name__)


def organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "Select an organization first", 409)
    return principal.organization.id


@router.get("/{item_id}/review-detail", response_model=BatchTryOnReviewDetailResponse)
async def get_review_detail(
    item_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> BatchTryOnReviewDetailResponse:
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
        try:
            dispatch_job(job)
            await session.commit()
        except Exception as error:
            await session.rollback()
            job = await get_job(session, org_id, job.id, lock=True)
            job.status = "queued"
            job.error_code = "job.dispatch_failed"
            job.error_message = "任务队列暂时不可用，系统将自动重试"
            job.dispatched_at = None
            job.celery_task_id = None
            await session.commit()
            logger.error("batch_tryon_regenerate_dispatch_failed job_id=%s error_type=%s", job.id, type(error).__name__)
    else:
        response.status_code = status.HTTP_200_OK
    current_job = await get_job(session, org_id, job.id)
    return BatchTryOnRegenerateResponse(
        review=await review_detail(session, org_id, item.id),
        job=await job_response(session, storage, settings, current_job),
    )
