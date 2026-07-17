from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.identity import (
    MembershipStatus,
    Organization,
    OrganizationMember,
    Role,
    RoleScope,
    User,
    UserStatus,
)
from app.schemas.identity import (
    MemberCreateRequest,
    MemberRoleUpdateRequest,
    MembershipResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
)
from app.security.passwords import hash_password
from app.security.principal import Principal, require_organization, require_permissions
from app.services.audit_service import add_audit_log
from app.services.identity_views import membership_response
from app.services.billing_service import ensure_account


router = APIRouter(prefix="/organizations", tags=["organizations"])


def _current_organization(principal: Principal) -> Organization:
    if principal.organization is None:
        raise AppError("organization.required", "Select an organization first", 409)
    return principal.organization


async def _loaded_membership(session: AsyncSession, member_id: str) -> OrganizationMember:
    membership = await session.scalar(
        select(OrganizationMember)
        .options(
            selectinload(OrganizationMember.user),
            selectinload(OrganizationMember.organization),
            selectinload(OrganizationMember.role).selectinload(Role.permission_links),
        )
        .where(OrganizationMember.id == member_id)
    )
    if membership is None:
        raise AppError("organization.member_not_found", "Organization member was not found", 404)
    return membership


async def _organization_role(session: AsyncSession, role_code: str) -> Role:
    role = await session.scalar(
        select(Role).options(selectinload(Role.permission_links)).where(
            Role.code == role_code, Role.scope == RoleScope.ORGANIZATION.value
        )
    )
    if role is None:
        raise AppError("organization.invalid_role", "Organization role is invalid", 422)
    return role


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("organizations.read")),
) -> list[OrganizationResponse]:
    if principal.is_platform_admin:
        organizations = list((await session.scalars(select(Organization).order_by(Organization.name))).all())
    else:
        organizations = [item.organization for item in principal.user.memberships if item.status == MembershipStatus.ACTIVE.value]
    return [OrganizationResponse.model_validate(item) for item in organizations]


@router.get("/current", response_model=OrganizationResponse)
async def get_current_organization(
    principal: Principal = Depends(require_permissions("organizations.read")),
) -> OrganizationResponse:
    return OrganizationResponse.model_validate(_current_organization(principal))


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("organizations.write")),
) -> OrganizationResponse:
    if await session.scalar(select(Organization.id).where(Organization.slug == payload.slug)):
        raise AppError("organization.slug_exists", "Organization slug already exists", 409)
    organization = Organization(
        name=payload.name.strip(), slug=payload.slug, created_by=principal.user.id, updated_by=principal.user.id
    )
    session.add(organization)
    await session.flush()
    await ensure_account(session, organization.id, principal.user.id)
    admin_role = await _organization_role(session, "organization_admin")
    session.add(OrganizationMember(
        organization_id=organization.id,
        user_id=principal.user.id,
        role_id=admin_role.id,
        invited_by=principal.user.id,
    ))
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=organization.id,
        action="organization.create", resource_type="organization", resource_id=organization.id,
    )
    await session.commit()
    await session.refresh(organization)
    return OrganizationResponse.model_validate(organization)


@router.get("/current/members", response_model=list[MembershipResponse])
async def list_members(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("organization.members.read")),
) -> list[MembershipResponse]:
    organization = _current_organization(principal)
    memberships = list((await session.scalars(
        select(OrganizationMember)
        .options(
            selectinload(OrganizationMember.user),
            selectinload(OrganizationMember.organization),
            selectinload(OrganizationMember.role).selectinload(Role.permission_links),
        )
        .where(OrganizationMember.organization_id == organization.id)
        .order_by(OrganizationMember.created_at)
    )).all())
    return [membership_response(item) for item in memberships]


@router.post("/current/members", response_model=MembershipResponse, status_code=status.HTTP_201_CREATED)
async def add_member(
    payload: MemberCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("organization.members.write", "roles.assign")),
) -> MembershipResponse:
    organization = _current_organization(principal)
    require_organization(principal, organization.id)
    email = str(payload.email).strip().lower()
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        if not payload.display_name or not payload.temporary_password:
            raise AppError(
                "organization.new_user_details_required",
                "Display name and temporary password are required for a new user",
                422,
            )
        user = User(
            email=email,
            display_name=payload.display_name.strip(),
            password_hash=hash_password(payload.temporary_password),
            status=UserStatus.ACTIVE.value,
        )
        session.add(user)
        await session.flush()
    existing = await session.scalar(select(OrganizationMember).where(
        OrganizationMember.organization_id == organization.id,
        OrganizationMember.user_id == user.id,
    ))
    if existing:
        raise AppError("organization.member_exists", "User is already an organization member", 409)
    role = await _organization_role(session, payload.role_code)
    membership = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role_id=role.id,
        invited_by=principal.user.id,
    )
    session.add(membership)
    await session.flush()
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=organization.id,
        action="organization.member.add", resource_type="organization_member", resource_id=membership.id,
        metadata={"user_id": user.id, "role_code": role.code},
    )
    await session.commit()
    return membership_response(await _loaded_membership(session, membership.id))


@router.patch("/current/members/{member_id}/role", response_model=MembershipResponse)
async def update_member_role(
    member_id: str,
    payload: MemberRoleUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("organization.members.write", "roles.assign")),
) -> MembershipResponse:
    organization = _current_organization(principal)
    membership = await _loaded_membership(session, member_id)
    require_organization(principal, membership.organization_id)
    if membership.organization_id != organization.id:
        raise AppError("auth.organization_access_denied", "Organization access denied", 403)
    role = await _organization_role(session, payload.role_code)
    if membership.role.code == "organization_admin" and role.code != "organization_admin":
        admin_count = await session.scalar(
            select(func.count()).select_from(OrganizationMember).join(Role).where(
                OrganizationMember.organization_id == organization.id,
                OrganizationMember.status == MembershipStatus.ACTIVE.value,
                Role.code == "organization_admin",
            )
        )
        if (admin_count or 0) <= 1:
            raise AppError("organization.last_admin", "The last organization administrator cannot be demoted", 409)
    membership.role_id = role.id
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=organization.id,
        action="organization.member.role_update", resource_type="organization_member", resource_id=membership.id,
        metadata={"role_code": role.code},
    )
    await session.commit()
    return membership_response(await _loaded_membership(session, membership.id))


@router.delete("/current/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    member_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("organization.members.write")),
) -> None:
    organization = _current_organization(principal)
    membership = await _loaded_membership(session, member_id)
    require_organization(principal, membership.organization_id)
    if membership.organization_id != organization.id:
        raise AppError("auth.organization_access_denied", "Organization access denied", 403)
    if membership.role.code == "organization_admin":
        admin_count = await session.scalar(
            select(func.count()).select_from(OrganizationMember).join(Role).where(
                OrganizationMember.organization_id == organization.id,
                OrganizationMember.status == MembershipStatus.ACTIVE.value,
                Role.code == "organization_admin",
            )
        )
        if (admin_count or 0) <= 1:
            raise AppError("organization.last_admin", "The last organization administrator cannot be removed", 409)
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=organization.id,
        action="organization.member.remove", resource_type="organization_member", resource_id=membership.id,
        metadata={"user_id": membership.user_id},
    )
    await session.delete(membership)
    await session.commit()
