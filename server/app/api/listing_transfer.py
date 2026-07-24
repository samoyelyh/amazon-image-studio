from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.schemas.listing_transfer import SendListingOutputRequest, SendListingOutputResponse
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.listing_transfer_service import send_listing_output_to_batch_tryon
from app.services.storage_service import StorageService, get_storage_service


router = APIRouter(prefix="/listing/generated-outputs", tags=["listing-transfer"])


def organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队", 409)
    return principal.organization.id


@router.post("/{output_id}/send-to-batch-tryon", response_model=SendListingOutputResponse, status_code=status.HTTP_201_CREATED)
async def send_to_batch_tryon(
    output_id: str,
    payload: SendListingOutputRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("generated_outputs.read", "projects.write")),
) -> SendListingOutputResponse:
    org_id = organization_id(principal)
    result, old_template_asset_id = await send_listing_output_to_batch_tryon(
        session,
        settings,
        storage,
        organization_id=org_id,
        user_id=principal.user.id,
        output_id=output_id,
        payload=payload,
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="listing_output_sent_to_batch_tryon",
        resource_type="project",
        resource_id=result.batch_project_id,
        metadata={
            "listing_project_id": result.listing_project_id,
            "listing_output_id": result.listing_output_id,
            "source_asset_id": result.model_asset_id,
            "batch_project_id": result.batch_project_id,
            "old_template_asset_id": old_template_asset_id,
            "new_template_asset_id": result.model_asset_id,
            "operation_result": "replayed" if result.replayed else "succeeded",
        },
    )
    if result.template_replaced and not result.replayed:
        add_audit_log(
            session,
            request=request,
            actor_user_id=principal.user.id,
            organization_id=org_id,
            action="batch_tryon_template_replaced_from_listing",
            resource_type="project",
            resource_id=result.batch_project_id,
            metadata={
                "listing_output_id": result.listing_output_id,
                "old_template_asset_id": old_template_asset_id,
                "new_template_asset_id": result.model_asset_id,
            },
        )
    await session.commit()
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    return result
