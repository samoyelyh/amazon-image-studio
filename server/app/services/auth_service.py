from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.identity import (
    MembershipStatus,
    OrganizationMember,
    OrganizationStatus,
    RefreshToken,
    User,
    UserStatus,
)
from app.security.identity import IdentityProvider, LocalIdentityProvider
from app.security.passwords import hash_password, verify_password
from app.security.principal import Principal, resolve_principal
from app.security.tokens import create_access_token, create_refresh_secret, hash_refresh_secret
from app.services.audit_service import add_audit_log, add_login_audit, client_ip, user_agent
from app.services.password_service import validate_password


UTC = timezone.utc


@dataclass(frozen=True)
class AuthSession:
    access_token: str
    expires_in: int
    refresh_secret: str
    principal: Principal


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class AuthService:
    def __init__(self, settings: Settings, identity_provider: IdentityProvider | None = None) -> None:
        self.settings = settings
        self.identity_provider = identity_provider or LocalIdentityProvider()

    async def login(
        self,
        session: AsyncSession,
        request: Request,
        account: str,
        password: str,
        organization_id: str | None,
    ) -> AuthSession:
        normalized_account = account.strip().lower()
        user = await self.identity_provider.authenticate(session, normalized_account, password)
        if user is None or user.status != UserStatus.ACTIVE.value:
            add_login_audit(
                session,
                request=request,
                event="login",
                outcome="failure",
                account=normalized_account,
                detail="invalid_credentials",
            )
            await session.commit()
            raise AppError("auth.invalid_credentials", "账号或密码错误", 401)

        selected_organization_id = await self._select_organization(session, user, organization_id)
        now = datetime.now(UTC)
        user.last_login_at = now
        principal = await resolve_principal(session, user.id, selected_organization_id)
        auth_session = self._create_session_record(session, request, principal, now=now)
        add_login_audit(
            session,
            request=request,
            event="login",
            outcome="success",
            account=user.account,
            user_id=user.id,
            organization_id=selected_organization_id,
        )
        await session.commit()
        return auth_session

    async def refresh(
        self,
        session: AsyncSession,
        request: Request,
        refresh_secret: str | None,
        organization_id: str | None = None,
    ) -> AuthSession:
        if not refresh_secret:
            raise AppError("auth.refresh_required", "Refresh token is required", 401)
        token = await session.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_secret(refresh_secret))
            .with_for_update()
        )
        if token is None:
            add_login_audit(session, request=request, event="refresh", outcome="failure", detail="unknown_token")
            await session.commit()
            raise AppError("auth.invalid_refresh_token", "Refresh token is invalid", 401)

        now = datetime.now(UTC)
        if token.revoked_at is not None:
            is_same_client_rotation_race = (
                token.replaced_by_token_id is not None
                and now - _as_utc(token.revoked_at) <= timedelta(seconds=5)
                and token.created_ip == client_ip(request)
                and token.user_agent == user_agent(request)
            )
            if is_same_client_rotation_race:
                add_login_audit(
                    session,
                    request=request,
                    event="refresh_race",
                    outcome="failure",
                    user_id=token.user_id,
                    organization_id=token.organization_id,
                    detail="concurrent_rotation_retry",
                )
                await session.commit()
                raise AppError(
                    "auth.refresh_race",
                    "登录状态已在另一个页面更新，正在重试。",
                    409,
                )
            # The first replay revokes the active descendants. Later requests from stale tabs
            # must not keep issuing an UPDATE against the same family: those writes can contend
            # with a legitimate login and cause MySQL deadlocks during refresh-token insertion.
            active_family_token_id = await session.scalar(
                select(RefreshToken.id)
                .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
                .limit(1)
            )
            if active_family_token_id is not None:
                await session.execute(
                    update(RefreshToken)
                    .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
                    .values(revoked_at=now)
                )
            add_login_audit(
                session,
                request=request,
                event="refresh_reuse",
                outcome="failure",
                user_id=token.user_id,
                organization_id=token.organization_id,
                detail="revoked_token_reused",
            )
            await session.commit()
            raise AppError("auth.refresh_token_reused", "Refresh token reuse detected; session revoked", 401)
        if _as_utc(token.expires_at) <= now:
            token.revoked_at = now
            add_login_audit(
                session,
                request=request,
                event="refresh",
                outcome="failure",
                user_id=token.user_id,
                organization_id=token.organization_id,
                detail="expired_token",
            )
            await session.commit()
            raise AppError("auth.refresh_expired", "Refresh token has expired", 401)

        selected_organization_id = token.organization_id
        if organization_id is not None:
            user = await session.get(User, token.user_id)
            if user is None:
                raise AppError("auth.invalid_user", "User no longer exists", 401)
            if user.must_change_password:
                raise AppError("auth.password_change_required", "首次登录或密码已重置，请先修改密码。", 403)
            selected_organization_id = await self._select_organization(session, user, organization_id)

        principal = await resolve_principal(session, token.user_id, selected_organization_id)
        rotated = self._create_session_record(
            session,
            request,
            principal,
            now=now,
            family_id=token.family_id,
        )
        await session.flush()
        token.revoked_at = now
        replacement = await session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_secret(rotated.refresh_secret))
        )
        token.replaced_by_token_id = replacement.id if replacement else None
        add_login_audit(
            session,
            request=request,
            event="organization_switch" if organization_id is not None else "refresh",
            outcome="success",
            user_id=token.user_id,
            organization_id=selected_organization_id,
        )
        await session.commit()
        return rotated

    async def logout(
        self,
        session: AsyncSession,
        request: Request,
        refresh_secret: str | None,
    ) -> None:
        if refresh_secret:
            token = await session.scalar(
                select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_secret(refresh_secret)).with_for_update()
            )
            if token and token.revoked_at is None:
                token.revoked_at = datetime.now(UTC)
                add_login_audit(
                    session,
                    request=request,
                    event="logout",
                    outcome="success",
                    user_id=token.user_id,
                    organization_id=token.organization_id,
                )
        await session.commit()

    async def change_password(
        self,
        session: AsyncSession,
        request: Request,
        principal: Principal,
        current_password: str,
        new_password: str,
    ) -> AuthSession:
        user = principal.user
        if not principal.is_platform_admin and "organization_admin" not in principal.role_codes:
            raise AppError("auth.password_change_forbidden", "普通成员不能自行修改密码，请联系管理员重置", 403)
        if not verify_password(current_password, user.password_hash):
            add_audit_log(
                session, request=request, actor_user_id=user.id,
                organization_id=principal.organization.id if principal.organization else None,
                action="password.change", resource_type="user", resource_id=user.id,
                metadata={"outcome": "failure", "reason": "auth.current_password_incorrect"},
            )
            await session.commit()
            raise AppError("auth.current_password_incorrect", "当前密码不正确", 422)
        if verify_password(new_password, user.password_hash):
            add_audit_log(
                session, request=request, actor_user_id=user.id,
                organization_id=principal.organization.id if principal.organization else None,
                action="password.change", resource_type="user", resource_id=user.id,
                metadata={"outcome": "failure", "reason": "auth.password_unchanged"},
            )
            await session.commit()
            raise AppError("auth.password_unchanged", "新密码不能与当前密码相同", 422)
        try:
            validate_password(new_password, account=user.account, display_name=user.display_name)
        except AppError as error:
            add_audit_log(
                session, request=request, actor_user_id=user.id,
                organization_id=principal.organization.id if principal.organization else None,
                action="password.change", resource_type="user", resource_id=user.id,
                metadata={"outcome": "failure", "reason": error.code},
            )
            await session.commit()
            raise

        now = datetime.now(UTC)
        was_forced = user.must_change_password
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        user.password_changed_at = now
        user.temporary_password_created_at = None
        user.token_version += 1
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.flush()
        refreshed_principal = await resolve_principal(
            session,
            user.id,
            principal.organization.id if principal.organization else None,
        )
        auth_session = self._create_session_record(session, request, refreshed_principal, now=now)
        add_audit_log(
            session,
            request=request,
            actor_user_id=user.id,
            organization_id=principal.organization.id if principal.organization else None,
            action="password.change",
            resource_type="user",
            resource_id=user.id,
            metadata={"forced_change_completed": was_forced, "outcome": "success"},
        )
        add_login_audit(
            session,
            request=request,
            event="password_change",
            outcome="success",
            account=user.account,
            user_id=user.id,
            organization_id=principal.organization.id if principal.organization else None,
        )
        await session.commit()
        return auth_session

    async def _select_organization(
        self,
        session: AsyncSession,
        user: User,
        requested_id: str | None,
    ) -> str | None:
        statement = (
            select(OrganizationMember)
            .join(OrganizationMember.organization)
            .where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.status == MembershipStatus.ACTIVE.value,
                OrganizationMember.organization.has(status=OrganizationStatus.ACTIVE.value),
            )
            .order_by(OrganizationMember.created_at)
        )
        memberships = list((await session.scalars(statement)).all())
        if requested_id is not None:
            if not any(item.organization_id == requested_id for item in memberships):
                raise AppError("auth.organization_access_denied", "You are not a member of this organization", 403)
            return requested_id
        if memberships:
            return memberships[0].organization_id
        if user.platform_role and user.platform_role.code == "platform_admin":
            return None
        raise AppError("auth.no_organization", "User has no active organization", 403)

    def _create_session_record(
        self,
        session: AsyncSession,
        request: Request,
        principal: Principal,
        *,
        now: datetime,
        family_id: str | None = None,
    ) -> AuthSession:
        organization_id = principal.organization.id if principal.organization else None
        access_token, expires_in = create_access_token(
            self.settings, principal.user.id, organization_id, principal.user.token_version,
        )
        refresh_secret = create_refresh_secret()
        session.add(RefreshToken(
            token_hash=hash_refresh_secret(refresh_secret),
            family_id=family_id or str(uuid4()),
            user_id=principal.user.id,
            organization_id=organization_id,
            expires_at=now + timedelta(days=self.settings.refresh_token_ttl_days),
            created_at=now,
            created_ip=client_ip(request),
            user_agent=user_agent(request),
        ))
        return AuthSession(access_token, expires_in, refresh_secret, principal)
