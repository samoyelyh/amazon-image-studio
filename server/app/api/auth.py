import asyncio

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.schemas.identity import (
    AccessTokenResponse,
    ChangePasswordRequest,
    CurrentIdentityResponse,
    LoginRequest,
    SwitchOrganizationRequest,
)
from app.security.principal import Principal, get_current_principal
from app.services.auth_service import AuthService, AuthSession
from app.services.identity_views import current_identity_response


router = APIRouter(prefix="/auth", tags=["authentication"])


def _is_mysql_deadlock(error: OperationalError) -> bool:
    original = getattr(error, "orig", None)
    args = getattr(original, "args", ())
    return bool(args and args[0] == 1213)


async def _login_with_deadlock_retry(
    service: AuthService,
    session: AsyncSession,
    request: Request,
    account: str,
    password: str,
    organization_id: str | None,
) -> AuthSession:
    for attempt in range(3):
        try:
            return await service.login(session, request, account, password, organization_id)
        except OperationalError as error:
            await session.rollback()
            if not _is_mysql_deadlock(error) or attempt == 2:
                raise
            await asyncio.sleep(0.05 * (attempt + 1))
    raise RuntimeError("unreachable")


def _set_refresh_cookie(response: Response, settings: Settings, secret: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=secret,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=f"{settings.api_v1_prefix}/auth",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=f"{settings.api_v1_prefix}/auth",
    )


def _token_response(auth_session: AuthSession) -> AccessTokenResponse:
    return AccessTokenResponse(
        access_token=auth_session.access_token,
        expires_in=auth_session.expires_in,
        identity=current_identity_response(auth_session.principal),
    )


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AccessTokenResponse:
    auth_session = await _login_with_deadlock_retry(
        AuthService(settings), session, request,
        payload.account, payload.password, payload.organization_id,
    )
    _set_refresh_cookie(response, settings, auth_session.refresh_secret)
    return _token_response(auth_session)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AccessTokenResponse:
    refresh_secret = request.cookies.get(settings.refresh_cookie_name)
    auth_session = await AuthService(settings).refresh(session, request, refresh_secret)
    _set_refresh_cookie(response, settings, auth_session.refresh_secret)
    return _token_response(auth_session)


@router.post("/switch-organization", response_model=AccessTokenResponse)
async def switch_organization(
    payload: SwitchOrganizationRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AccessTokenResponse:
    refresh_secret = request.cookies.get(settings.refresh_cookie_name)
    auth_session = await AuthService(settings).refresh(
        session, request, refresh_secret, organization_id=payload.organization_id
    )
    _set_refresh_cookie(response, settings, auth_session.refresh_secret)
    return _token_response(auth_session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> None:
    refresh_secret = request.cookies.get(settings.refresh_cookie_name)
    await AuthService(settings).logout(session, request, refresh_secret)
    _clear_refresh_cookie(response, settings)


@router.post("/change-password", response_model=AccessTokenResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(get_current_principal),
) -> AccessTokenResponse:
    auth_session = await AuthService(settings).change_password(
        session,
        request,
        principal,
        payload.current_password,
        payload.new_password,
    )
    _set_refresh_cookie(response, settings, auth_session.refresh_secret)
    return _token_response(auth_session)


@router.get("/me", response_model=CurrentIdentityResponse)
async def me(principal: Principal = Depends(get_current_principal)) -> CurrentIdentityResponse:
    return current_identity_response(principal)
