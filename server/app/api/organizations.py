from datetime import datetime, timezone
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.identity import (
    MembershipStatus,
    Organization,
    OrganizationMember,
    RefreshToken,
    Role,
    RoleScope,
    User,
    UserStatus,
)
from app.schemas.identity import (
    MemberCreateRequest,
    MemberRoleUpdateRequest,
    MemberStatusUpdateRequest,
    MembershipResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
    PasswordResetRequest,
    PasswordResetResponse,
)
from app.security.passwords import hash_password
from app.security.principal import Principal, require_organization, require_permissions
from app.services.audit_service import add_audit_log
from app.services.identity_views import membership_response
from app.services.billing_service import ensure_account
from app.services.password_service import validate_password


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


async def _raise_operation_error(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    organization_id: str,
    action: str,
    resource_id: str | None,
    error: AppError,
) -> NoReturn:
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=organization_id,
        action=action,
        resource_type="organization_member",
        resource_id=resource_id,
        metadata={"outcome": "failure", "reason": error.code},
    )
    await session.commit()
    raise error


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
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=8, max_length=160),
    ] = None,
) -> MembershipResponse:
    organization = _current_organization(principal)
    require_organization(principal, organization.id)
    email = str(payload.email).strip().lower()
    if idempotency_key:
        replay = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization.id,
                OrganizationMember.creation_idempotency_key == idempotency_key,
            )
        )
        if replay is not None:
            loaded = await _loaded_membership(session, replay.id)
            if loaded.user.email != email or loaded.role.code != payload.role_code:
                await _raise_operation_error(session, request, principal, organization.id, "organization.member.add", replay.id, AppError(
                    "organization.idempotency_conflict",
                    "同一个幂等键不能用于不同的创建请求",
                    409,
                ))
            return membership_response(loaded)

    if not payload.display_name or not payload.temporary_password:
        await _raise_operation_error(session, request, principal, organization.id, "organization.member.add", None, AppError(
            "organization.new_user_details_required",
            "创建用户时必须填写姓名和初始密码",
            422,
        ))
    if await session.scalar(select(User.id).where(User.email == email)):
        await _raise_operation_error(session, request, principal, organization.id, "organization.member.add", None, AppError(
            "organization.user_email_exists",
            "该邮箱已存在，请更换邮箱或重置该用户密码",
            409,
        ))
    display_name = payload.display_name.strip()
    try:
        validate_password(payload.temporary_password, email=email, display_name=display_name)
    except AppError as error:
        await _raise_operation_error(session, request, principal, organization.id, "organization.member.add", None, error)
    now = datetime.now(timezone.utc)
    user = User(
        email=email,
        display_name=display_name,
        password_hash=hash_password(payload.temporary_password),
        status=UserStatus.ACTIVE.value,
        must_change_password=True,
        temporary_password_created_at=now,
        created_by=principal.user.id,
    )
    session.add(user)
    await session.flush()
    role = await _organization_role(session, payload.role_code)
    membership = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role_id=role.id,
        invited_by=principal.user.id,
        creation_idempotency_key=idempotency_key,
    )
    session.add(membership)
    await session.flush()
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=organization.id,
        action="organization.member.add", resource_type="organization_member", resource_id=membership.id,
        metadata={"user_id": user.id, "role_code": role.code, "must_change_password": True, "outcome": "success"},
    )
    await session.commit()
    return membership_response(await _loaded_membership(session, membership.id))


@router.post(
    "/current/members/{member_id}/reset-password",
    response_model=PasswordResetResponse,
)
async def reset_member_password(
    member_id: str,
    payload: PasswordResetRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("organization.members.write")),
) -> PasswordResetResponse:
    organization = _current_organization(principal)
    membership = await _loaded_membership(session, member_id)
    require_organization(principal, membership.organization_id)
    if membership.organization_id != organization.id:
        raise AppError("auth.organization_access_denied", "Organization access denied", 403)
    if membership.user_id == principal.user.id:
        raise AppError("organization.cannot_reset_self", "请在个人中心修改自己的密码", 409)
    if membership.user.platform_role and membership.user.platform_role.code == "platform_admin" and not principal.is_platform_admin:
        raise AppError("auth.permission_denied", "组织管理员不能重置平台管理员密码", 403)

    try:
        validate_password(
            payload.temporary_password,
            email=membership.user.email,
            display_name=membership.user.display_name,
        )
    except AppError as error:
        await _raise_operation_error(
            session, request, principal, organization.id,
            "organization.member.password_reset", membership.id, error,
        )
    now = datetime.now(timezone.utc)
    membership.user.password_hash = hash_password(payload.temporary_password)
    membership.user.must_change_password = True
    membership.user.temporary_password_created_at = now
    membership.user.password_changed_at = None
    membership.user.token_version += 1
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == membership.user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=organization.id,
        action="organization.member.password_reset",
        resource_type="user",
        resource_id=membership.user_id,
        metadata={"force_change_password": True, "outcome": "success"},
    )
    await session.commit()
    return PasswordResetResponse(
        user_id=membership.user_id,
        must_change_password=membership.user.must_change_password,
    )


@router.patch("/current/members/{member_id}/status", response_model=MembershipResponse)
async def update_member_status(
    member_id: str,
    payload: MemberStatusUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("organization.members.write")),
) -> MembershipResponse:
    organization = _current_organization(principal)
    membership = await _loaded_membership(session, member_id)
    require_organization(principal, membership.organization_id)
    if membership.organization_id != organization.id:
        raise AppError("auth.organization_access_denied", "Organization access denied", 403)
    if membership.user_id == principal.user.id and payload.status == MembershipStatus.DISABLED.value:
        raise AppError("organization.cannot_disable_self", "不能停用自己的当前团队成员身份", 409)
    if membership.role.code == "organization_admin" and payload.status == MembershipStatus.DISABLED.value:
        admin_count = await session.scalar(
            select(func.count()).select_from(OrganizationMember).join(Role).where(
                OrganizationMember.organization_id == organization.id,
                OrganizationMember.status == MembershipStatus.ACTIVE.value,
                Role.code == "organization_admin",
            )
        )
        if (admin_count or 0) <= 1:
            raise AppError("organization.last_admin", "The last organization administrator cannot be disabled", 409)
    membership.status = payload.status
    if payload.status == MembershipStatus.DISABLED.value:
        await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == membership.user_id,
                RefreshToken.organization_id == organization.id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=organization.id,
        action="organization.member.status_update",
        resource_type="organization_member",
        resource_id=membership.id,
        metadata={"status": payload.status, "user_id": membership.user_id, "outcome": "success"},
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
        metadata={"role_code": role.code, "user_id": membership.user_id, "outcome": "success"},
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
        metadata={"user_id": membership.user_id, "outcome": "success"},
    )
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == membership.user_id,
            RefreshToken.organization_id == organization.id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await session.delete(membership)
    await session.commit()
