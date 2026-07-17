import asyncio
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import get_engine
from app.models.identity import Organization, OrganizationMember, User
from app.security.passwords import hash_password
from app.security.rbac import sync_rbac


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "default-organization"


async def bootstrap(session: AsyncSession) -> None:
    settings = get_settings()
    roles = await sync_rbac(session)
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        await session.commit()
        print("RBAC definitions synchronized; bootstrap admin is disabled.")
        return

    email = str(settings.bootstrap_admin_email).strip().lower()
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            display_name=settings.bootstrap_admin_name,
            password_hash=hash_password(settings.bootstrap_admin_password.get_secret_value()),
            platform_role_id=roles["platform_admin"].id,
        )
        session.add(user)
        await session.flush()
    else:
        user.platform_role_id = roles["platform_admin"].id

    slug = slugify(settings.bootstrap_organization_name)
    organization = await session.scalar(select(Organization).where(Organization.slug == slug))
    if organization is None:
        organization = Organization(
            name=settings.bootstrap_organization_name,
            slug=slug,
            created_by=user.id,
            updated_by=user.id,
        )
        session.add(organization)
        await session.flush()

    membership = await session.scalar(select(OrganizationMember).where(
        OrganizationMember.organization_id == organization.id,
        OrganizationMember.user_id == user.id,
    ))
    if membership is None:
        session.add(OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role_id=roles["organization_admin"].id,
            invited_by=user.id,
        ))
    await session.commit()
    print(f"Identity bootstrap ready for {email} in {organization.slug}.")


async def main() -> None:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        await bootstrap(session)


if __name__ == "__main__":
    asyncio.run(main())
