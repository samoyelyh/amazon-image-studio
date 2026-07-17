from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.identity import CurrentIdentityResponse, ProfileUpdateRequest
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.identity_views import current_identity_response


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=CurrentIdentityResponse)
async def get_profile(
    principal: Principal = Depends(require_permissions("profile.read")),
) -> CurrentIdentityResponse:
    return current_identity_response(principal)


@router.patch("/me", response_model=CurrentIdentityResponse)
async def update_profile(
    payload: ProfileUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("profile.update")),
) -> CurrentIdentityResponse:
    principal.user.display_name = payload.display_name.strip()
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=principal.organization.id if principal.organization else None,
        action="profile.update",
        resource_type="user",
        resource_id=principal.user.id,
    )
    await session.commit()
    await session.refresh(principal.user)
    return current_identity_response(principal)
