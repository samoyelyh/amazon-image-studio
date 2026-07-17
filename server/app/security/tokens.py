from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

import jwt

from app.core.config import Settings


UTC = timezone.utc


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: str
    organization_id: str | None
    token_id: str


class TokenError(ValueError):
    pass


def create_access_token(settings: Settings, user_id: str, organization_id: str | None) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires_in = settings.access_token_ttl_minutes * 60
    payload = {
        "sub": user_id,
        "org": organization_id,
        "type": "access",
        "jti": str(uuid4()),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=expires_in),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    encoded = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm)
    return encoded, expires_in


def decode_access_token(settings: Settings, encoded: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            encoded,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "type", "jti", "iat", "exp", "iss", "aud"]},
        )
    except jwt.PyJWTError as error:
        raise TokenError("Invalid or expired access token") from error
    if payload.get("type") != "access":
        raise TokenError("Invalid token type")
    return AccessTokenClaims(
        user_id=str(payload["sub"]),
        organization_id=str(payload["org"]) if payload.get("org") else None,
        token_id=str(payload["jti"]),
    )


def create_refresh_secret() -> str:
    return token_urlsafe(64)


def hash_refresh_secret(secret: str) -> str:
    return sha256(secret.encode("utf-8")).hexdigest()
