from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.tasks import Job, JobBatch
from app.schemas.batch_tryon_workspace import (
    BatchTryOnWorkspaceCreateRequest, BatchTryOnWorkspacePage,
    BatchTryOnWorkspaceResponse, BatchTryOnWorkspaceUpdateRequest,
)
from app.schemas.tasks import JobBatchHardDeleteResponse
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.job_batch_deletion_service import delete_storage_objects, hard_delete_job_batch
from app.services.storage_service import StorageService, get_storage_service
from app.services.batch_tryon_workspace_service import (
    child_batches, create_workspace, get_workspace, list_workspaces, update_workspace,
)


router = APIRouter(prefix="/batch-tryon/workspaces", tags=["batch-tryon-workspaces"])


def _org(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队。", 409)
    return principal.organization.id


async def _response(session: AsyncSession, batch: JobBatch) -> BatchTryOnWorkspaceResponse:
    children = await child_batches(session, batch)
    production = [item for item in children if item.batch_kind == "production"]
    validation = [item for item in children if item.batch_kind == "validation"]
    counted = production or validation
    return BatchTryOnWorkspaceResponse(
        id=batch.id, project_id=batch.project_id, name=batch.name or "未命名批次", status=batch.status,
        hidden=batch.workspace_hidden, config=batch.workspace_config_json or {},
        production_batch_ids=[item.id for item in production],
        validation_batch_ids=[item.id for item in validation],
        total_jobs=sum(item.total_jobs for item in counted),
        completed_jobs=sum(item.succeeded_jobs + item.failed_jobs + item.cancelled_jobs for item in counted),
        created_at=batch.created_at, updated_at=batch.updated_at,
    )


@router.post("", response_model=BatchTryOnWorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create(
    payload: BatchTryOnWorkspaceCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> BatchTryOnWorkspaceResponse:
    batch = await create_workspace(
        session, organization_id=_org(principal), user_id=principal.user.id,
        project_id=payload.project_id, name=payload.name, config=payload.config,
    )
    await session.commit()
    await session.refresh(batch)
    return await _response(session, batch)


@router.get("", response_model=BatchTryOnWorkspacePage)
async def read_many(
    project_id: str = Query(min_length=1, max_length=36), include_hidden: bool = False,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> BatchTryOnWorkspacePage:
    rows = await list_workspaces(
        session, organization_id=_org(principal), user_id=principal.user.id,
        project_id=project_id, include_hidden=include_hidden,
    )
    return BatchTryOnWorkspacePage(items=[await _response(session, item) for item in rows], total=len(rows))


@router.patch("/{workspace_id}", response_model=BatchTryOnWorkspaceResponse)
async def update(
    workspace_id: str, payload: BatchTryOnWorkspaceUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> BatchTryOnWorkspaceResponse:
    batch = await update_workspace(
        session, organization_id=_org(principal), user_id=principal.user.id, workspace_id=workspace_id,
        name=payload.name, status=payload.status, config=payload.config,
    )
    await session.commit()
    await session.refresh(batch)
    return await _response(session, batch)


@router.post("/{workspace_id}/hide", response_model=BatchTryOnWorkspaceResponse)
async def hide(
    workspace_id: str, session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> BatchTryOnWorkspaceResponse:
    batch = await get_workspace(
        session, organization_id=_org(principal), user_id=principal.user.id,
        workspace_id=workspace_id, lock=True,
    )
    batch.workspace_hidden = True
    batch.updated_by = principal.user.id
    await session.commit()
    await session.refresh(batch)
    return await _response(session, batch)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_draft(
    workspace_id: str, session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> Response:
    batch = await get_workspace(
        session, organization_id=_org(principal), user_id=principal.user.id,
        workspace_id=workspace_id, lock=True,
    )
    children = await child_batches(session, batch)
    if batch.status != "draft" or children:
        raise AppError("batch_tryon.workspace_delete_forbidden", "只有尚未创建验证或生产任务的草稿批次可以删除。", 409)
    await session.delete(batch)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{workspace_id}/hard", response_model=JobBatchHardDeleteResponse)
async def hard_delete_workspace(
    workspace_id: str,
    request: Request,
    confirmation: str = Query(max_length=32),
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.cancel", "assets.delete")),
) -> JobBatchHardDeleteResponse:
    if confirmation != "PERMANENT_DELETE":
        raise AppError("job.batch_delete_confirmation_required", "永久删除确认信息无效。", 422)
    org_id = _org(principal)
    result = await hard_delete_job_batch(
        session,
        organization_id=org_id,
        batch_id=workspace_id,
        include_workspace_children=True,
        owner_user_id=principal.user.id,
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="batch_tryon.workspace_hard_delete",
        resource_type="job_batch",
        resource_id=workspace_id,
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
