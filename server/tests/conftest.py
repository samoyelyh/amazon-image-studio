from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.models.identity import Organization, OrganizationMember, User
from app.security.passwords import hash_password
from app.security.rbac import sync_rbac


@pytest_asyncio.fixture
async def identity_test_context() -> AsyncIterator[dict[str, object]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        roles = await sync_rbac(session)
        first_org = Organization(name="First Team", slug="first-team")
        second_org = Organization(name="Second Team", slug="second-team")
        admin = User(
            email="first-admin@example.com",
            display_name="First Admin",
            password_hash=hash_password("correct-password"),
        )
        viewer = User(
            email="first-viewer@example.com",
            display_name="First Viewer",
            password_hash=hash_password("viewer-password"),
        )
        second_user = User(
            email="second-admin@example.com",
            display_name="Second Admin",
            password_hash=hash_password("second-password"),
        )
        session.add_all([first_org, second_org, admin, viewer, second_user])
        await session.flush()
        first_admin_membership = OrganizationMember(
            organization_id=first_org.id, user_id=admin.id, role_id=roles["organization_admin"].id
        )
        first_viewer_membership = OrganizationMember(
            organization_id=first_org.id, user_id=viewer.id, role_id=roles["viewer"].id
        )
        second_admin_membership = OrganizationMember(
            organization_id=second_org.id, user_id=second_user.id, role_id=roles["organization_admin"].id
        )
        session.add_all([first_admin_membership, first_viewer_membership, second_admin_membership])
        await session.commit()
        ids = {
            "first_org": first_org.id,
            "second_org": second_org.id,
            "first_admin_membership": first_admin_membership.id,
            "first_viewer_membership": first_viewer_membership.id,
            "second_admin_membership": second_admin_membership.id,
        }

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {"client": client, "app": app, "session_factory": session_factory, **ids}
    await engine.dispose()
