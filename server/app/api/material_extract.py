from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.prompts.material_extract import build_material_extract_prompt
from app.schemas.material_extract import MaterialExtractRequest, MaterialExtractResponse
from app.schemas.tasks import JobSubmitRequest
from app.security.principal import Principal, require_permissions
from app.services.asset_service import create_asset, get_asset, read_asset_content
from app.services.audit_service import add_audit_log
from app.services.category_listing_service import resolve_bound_model_code
from app.services.material_extract_service import choose_background_color, crop_material_roi, high_resolution_size
from app.services.storage_service import StorageService, get_storage_service
from app.services.task_service import dispatch_jobs, due_jobs, get_job, job_response, submit_job


router = APIRouter(prefix="/material-extract", tags=["material-extract"])


def organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队", 409)
    return principal.organization.id


@router.post("/jobs", response_model=MaterialExtractResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_material_extract_job(
    payload: MaterialExtractRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit", "assets.upload")),
) -> MaterialExtractResponse:
    org_id = organization_id(principal)
    source_asset = await get_asset(session, org_id, payload.source_asset_id)
    source_content = await read_asset_content(source_asset, storage)
    bounds = payload.selection_bounds
    crop = crop_material_roi(source_content, (bounds.x, bounds.y, bounds.width, bounds.height))
    background_color = choose_background_color(crop.content)
    roi_asset = await create_asset(
        session,
        storage,
        settings,
        organization_id=org_id,
        user_id=principal.user.id,
        category="temporary",
        filename="material-extract-roi.png",
        declared_mime="image/png",
        data=crop.content,
    )
    target_width, target_height = high_resolution_size(crop.width, crop.height)
    prompt = build_material_extract_prompt(
        target_description=payload.target_description,
        background_color=background_color,
    )
    model_code = await resolve_bound_model_code(
        session,
        organization_id=org_id,
        operation_code="asset.extract",
        capability="image_edit",
    )
    job_payload = JobSubmitRequest(
        operation_code="asset.extract",
        workspace_type="material_extract",
        queue_name="listing_queue",
        capability="image_edit",
        model_code=model_code,
        idempotency_key=payload.idempotency_key,
        input={
            "prompt": prompt,
            "n": 1,
            "size": f"{target_width}x{target_height}",
            "aspect_ratio": f"{target_width}:{target_height}",
            "requested_width": target_width,
            "requested_height": target_height,
            "quality": "high",
            "output_format": "png",
            "output_compression": 100,
            "reference_asset_ids": [roi_asset.id],
            "metadata": {
                "source_asset_id": source_asset.id,
                "roi_asset_id": roi_asset.id,
                "background_color": background_color,
                "selection_bounds": payload.selection_bounds.model_dump(),
                "crop_box": list(crop.box),
                "target_description": payload.target_description.strip(),
                "brush_stroke_count": len(payload.brush_strokes),
            },
        },
        billing_factors={"quality": "high", "resolution": "2048"},
    )
    job, created = await submit_job(
        session,
        settings,
        organization_id=org_id,
        user_id=principal.user.id,
        payload=job_payload,
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="material_extract.submit",
        resource_type="job",
        resource_id=job.id,
        metadata={"source_asset_id": source_asset.id, "roi_asset_id": roi_asset.id, "created": created},
    )
    await session.commit()
    if created:
        await dispatch_jobs(session, await due_jobs(session, settings, limit=1))
    else:
        response.status_code = status.HTTP_200_OK
    resolved_job = await job_response(session, storage, settings, await get_job(session, org_id, job.id))
    return MaterialExtractResponse(
        job=resolved_job,
        source_asset_id=source_asset.id,
        roi_asset_id=roi_asset.id,
        background_color=background_color,
    )

