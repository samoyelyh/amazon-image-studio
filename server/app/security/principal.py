from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.identity import (
    MembershipStatus,
    Organization,
    OrganizationMember,
    OrganizationStatus,
    Role,
    User,
    UserStatus,
)
from app.security.rbac import has_all_permissions, permissions_for_role
from app.security.tokens import TokenError, decode_access_token


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user: User
    organization: Organization | None
    membership: OrganizationMember | None
    role_codes: frozenset[str]
    permissions: frozenset[str]

    @property
    def is_platform_admin(self) -> bool:
        return "platform.admin" in self.permissions


async def resolve_principal(session: AsyncSession, user_id: str, organization_id: str | None) -> Principal:
    user = await session.scalar(
        select(User)
        .options(
            selectinload(User.platform_role).selectinload(Role.permission_links),
            selectinload(User.memberships).selectinload(OrganizationMember.role).selectinload(Role.permission_links),
            selectinload(User.memberships).selectinload(OrganizationMember.organization),
        )
        .where(User.id == user_id)
    )
    if user is None or user.status != UserStatus.ACTIVE.value:
        raise AppError("auth.invalid_user", "User is disabled or no longer exists", 401)

    membership = next(
        (item for item in user.memberships if item.organization_id == organization_id), None
    ) if organization_id else None
    organization = membership.organization if membership else None
    if organization_id and (
        membership is None
        or membership.status != MembershipStatus.ACTIVE.value
        or organization is None
        or organization.status != OrganizationStatus.ACTIVE.value
    ):
        raise AppError("auth.organization_access_denied", "Organization access is no longer available", 403)

    permissions = permissions_for_role(user.platform_role)
    role_codes: set[str] = set()
    if user.platform_role:
        role_codes.add(user.platform_role.code)
    if membership:
        permissions |= permissions_for_role(membership.role)
        role_codes.add(membership.role.code)
    return Principal(user, organization, membership, frozenset(role_codes), frozenset(permissions))


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("auth.required", "Authentication is required", 401)
    try:
        claims = decode_access_token(get_settings(), credentials.credentials)
    except TokenError as error:
        raise AppError("auth.invalid_token", str(error), 401) from error
    return await resolve_principal(session, claims.user_id, claims.organization_id)


def require_permissions(*required: str):
    async def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not has_all_permissions(principal.permissions, required):
            raise AppError(
                "auth.permission_denied",
                "You do not have permission to perform this action",
                403,
                {"required": list(required)},
            )
        return principal

    return dependency


def require_organization(principal: Principal, organization_id: str) -> None:
    if not principal.is_platform_admin and (
        principal.organization is None or principal.organization.id != organization_id
    ):
        raise AppError("auth.organization_access_denied", "Organization access denied", 403)
