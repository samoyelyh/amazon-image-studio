from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.schemas.batch_tryon_workflow import (
    BatchTryOnTemplatePromptAnalyzeRequest,
    BatchTryOnTemplatePromptResponse,
    BatchTryOnTemplatePromptSaveRequest,
    BatchTryOnWorkflowCreateRequest,
    BatchTryOnWorkflowResponse,
    BatchTryOnWorkflowSubmitRequest,
)
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.batch_tryon_workflow_service import (
    create_batch_tryon_workflow,
    get_batch_tryon_workflow,
    get_latest_batch_tryon_workflow,
    reanalyze_template_prompt,
    save_template_prompt,
    submit_confirmed_batch_tryon_workflow,
    workflow_response,
)
from app.services.batch_tryon_prompt_template_service import template_prompt_response
from app.services.task_service import dispatch_jobs


router = APIRouter(prefix="/batch-tryon/workflows", tags=["batch-tryon-workflows"])


def _organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队。", 409)
    return principal.organization.id


@router.post("", response_model=BatchTryOnWorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_workflow(
    payload: BatchTryOnWorkflowCreateRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> BatchTryOnWorkflowResponse:
    organization_id = _organization_id(principal)
    root, created_jobs, created = await create_batch_tryon_workflow(
        session,
        settings,
        organization_id=organization_id,
        user_id=principal.user.id,
        payload=payload,
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=organization_id,
        action="batch_tryon.workflow_submit",
        resource_type="job",
        resource_id=root.id,
        metadata={"created": created, "generation_mode": payload.generation_mode, "matrix_size": len(payload.templates) * len(payload.garments)},
    )
    await session.commit()
    if created_jobs:
        await dispatch_jobs(session, created_jobs)
    else:
        response.status_code = status.HTTP_200_OK
    root, template_jobs, batch, prompt_records = await get_batch_tryon_workflow(
        session, settings, organization_id=organization_id, workflow_job_id=root.id,
        user_id=principal.user.id,
    )
    return workflow_response(root, template_jobs, batch, prompt_records)


@router.get("", response_model=BatchTryOnWorkflowResponse)
async def read_latest_workflow(
    project_id: str = Query(min_length=1, max_length=36),
    workspace_batch_id: str | None = Query(default=None, min_length=1, max_length=36),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> BatchTryOnWorkflowResponse:
    root, template_jobs, batch, prompt_records = await get_latest_batch_tryon_workflow(
        session,
        settings,
        organization_id=_organization_id(principal),
        project_id=project_id,
        workspace_batch_id=workspace_batch_id,
        user_id=principal.user.id,
    )
    return workflow_response(root, template_jobs, batch, prompt_records)


@router.patch("/{workflow_job_id}/template-prompts/{template_id}", response_model=BatchTryOnTemplatePromptResponse)
async def confirm_template_prompt(
    workflow_job_id: str,
    template_id: str,
    payload: BatchTryOnTemplatePromptSaveRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> BatchTryOnTemplatePromptResponse:
    organization_id = _organization_id(principal)
    record = await save_template_prompt(
        session,
        organization_id=organization_id,
        user_id=principal.user.id,
        workflow_job_id=workflow_job_id,
        template_id=template_id,
        edited_final_prompt=payload.edited_final_prompt,
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=organization_id,
        action="batch_tryon.template_prompt.confirm", resource_type="batch_tryon_template_prompt",
        resource_id=record.id, metadata={"template_id": template_id, "prompt_version": record.prompt_version},
    )
    await session.commit()
    return template_prompt_response(record)


@router.post("/{workflow_job_id}/template-prompts/{template_id}/analyze", response_model=BatchTryOnTemplatePromptResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_template_prompt(
    workflow_job_id: str,
    template_id: str,
    payload: BatchTryOnTemplatePromptAnalyzeRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> BatchTryOnTemplatePromptResponse:
    organization_id = _organization_id(principal)
    record, job, created = await reanalyze_template_prompt(
        session, settings,
        organization_id=organization_id,
        user_id=principal.user.id,
        workflow_job_id=workflow_job_id,
        template_id=template_id,
        analysis_prompt=payload.analysis_prompt,
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=organization_id,
        action="batch_tryon.template_prompt.analyze", resource_type="batch_tryon_template_prompt",
        resource_id=record.id, metadata={"job_id": job.id, "prompt_version": record.prompt_version},
    )
    await session.commit()
    if created:
        await dispatch_jobs(session, [job])
    return template_prompt_response(record)


@router.post("/{workflow_job_id}/submit", response_model=BatchTryOnWorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_confirmed_workflow(
    workflow_job_id: str,
    payload: BatchTryOnWorkflowSubmitRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> BatchTryOnWorkflowResponse:
    organization_id = _organization_id(principal)
    batch, jobs, created = await submit_confirmed_batch_tryon_workflow(
        session, settings,
        organization_id=organization_id,
        user_id=principal.user.id,
        workflow_job_id=workflow_job_id,
        idempotency_key=payload.idempotency_key,
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=organization_id,
        action="batch_tryon.workflow_image_submit", resource_type="job_batch", resource_id=batch.id,
        metadata={"workflow_job_id": workflow_job_id, "created": created, "job_count": len(jobs)},
    )
    await session.commit()
    if created:
        await dispatch_jobs(session, jobs[:batch.concurrency])
    else:
        response.status_code = status.HTTP_200_OK
    root, analysis_jobs, current_batch, prompt_records = await get_batch_tryon_workflow(
        session, settings, organization_id=organization_id, workflow_job_id=workflow_job_id,
        user_id=principal.user.id,
    )
    return workflow_response(root, analysis_jobs, current_batch, prompt_records)


@router.get("/{workflow_job_id}", response_model=BatchTryOnWorkflowResponse)
async def read_workflow(
    workflow_job_id: str,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> BatchTryOnWorkflowResponse:
    root, template_jobs, batch, prompt_records = await get_batch_tryon_workflow(
        session,
        settings,
        organization_id=_organization_id(principal),
        workflow_job_id=workflow_job_id,
        user_id=principal.user.id,
    )
    return workflow_response(root, template_jobs, batch, prompt_records)
