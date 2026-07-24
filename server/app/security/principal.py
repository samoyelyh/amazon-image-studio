from dataclasses import dataclass

from fastapi import Depends, Request
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


async def resolve_principal(
    session: AsyncSession, user_id: str, organization_id: str | None,
    *, expected_token_version: int | None = None,
) -> Principal:
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
        raise AppError("auth.invalid_user", "账号已停用或不存在，请联系管理员", 401)
    if expected_token_version is not None and user.token_version != expected_token_version:
        raise AppError("auth.session_revoked", "登录会话已失效，请重新登录。", 401)

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
        raise AppError("auth.organization_access_denied", "当前团队不可用或你已不再是团队成员", 403)

    permissions = permissions_for_role(user.platform_role)
    role_codes: set[str] = set()
    if user.platform_role:
        role_codes.add(user.platform_role.code)
    if membership:
        permissions |= permissions_for_role(membership.role)
        role_codes.add(membership.role.code)
    return Principal(user, organization, membership, frozenset(role_codes), frozenset(permissions))


async def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("auth.required", "请先登录后再执行此操作", 401)
    try:
        claims = decode_access_token(get_settings(), credentials.credentials)
    except TokenError as error:
        raise AppError("auth.invalid_token", str(error), 401) from error
    principal = await resolve_principal(
        session, claims.user_id, claims.organization_id,
        expected_token_version=claims.token_version,
    )
    api_prefix = get_settings().api_v1_prefix
    allowed_while_changing_password = request.url.path in {
        f"{api_prefix}/auth/me",
        f"{api_prefix}/auth/change-password",
    } or (request.method == "GET" and request.url.path == f"{api_prefix}/users/me")
    if principal.user.must_change_password and not allowed_while_changing_password:
        raise AppError("auth.password_change_required", "首次登录或密码已重置，请先修改密码。", 403)
    return principal


def require_permissions(*required: str):
    async def dependency(
        request: Request,
        session: AsyncSession = Depends(get_db_session),
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if not has_all_permissions(principal.permissions, required):
            from app.services.audit_service import add_audit_log

            add_audit_log(
                session,
                request=request,
                actor_user_id=principal.user.id,
                organization_id=principal.organization.id if principal.organization else None,
                action="authorization.denied",
                resource_type="request",
                resource_id=request.url.path[:100],
                metadata={"required": list(required), "outcome": "failure", "reason": "auth.permission_denied"},
            )
            await session.commit()
            raise AppError(
                "auth.permission_denied",
                "当前账号没有执行此操作的权限，请联系团队管理员",
                403,
                {"required": list(required)},
            )
        return principal

    return dependency


def require_organization(principal: Principal, organization_id: str) -> None:
    if not principal.is_platform_admin and (
        principal.organization is None or principal.organization.id != organization_id
    ):
        raise AppError("auth.organization_access_denied", "无权访问该团队的数据", 403)
