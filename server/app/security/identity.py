from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import User
from app.security.passwords import verify_password


class IdentityProvider(Protocol):
    """Replaceable authentication boundary for a future OIDC provider."""

    async def authenticate(self, session: AsyncSession, account: str, password: str) -> User | None: ...


class LocalIdentityProvider:
    async def authenticate(self, session: AsyncSession, account: str, password: str) -> User | None:
        user = await session.scalar(
            select(User).options(selectinload(User.platform_role)).where(User.account == account.strip().lower())
        )
        if not verify_password(password, user.password_hash if user else None):
            return None
        return user
