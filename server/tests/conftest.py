from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.models.identity import Organization, OrganizationMember, User
from app.models.quota import QuotaPackage, QuotaRule
from app.security.passwords import hash_password
from app.security.rbac import sync_rbac
from app.services.storage_service import StorageObjectMetadata, StorageService, get_storage_service
from app.services.billing_service import ensure_account


class FakeStorageService(StorageService):
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, dict[str, str]]] = {}

    def upload(self, key, data, *, content_type, metadata=None):
        value = data if isinstance(data, bytes) else data.read()
        self.objects[key] = (value, content_type, metadata or {})
        return StorageObjectMetadata(key, len(value), content_type, "test-etag", metadata or {})

    def download(self, key):
        return self.objects[key][0]

    def delete(self, key):
        self.objects.pop(key, None)

    def exists(self, key):
        return key in self.objects

    def create_presigned_url(self, key, *, expires_in=None):
        return f"https://storage.test/private/{key}?expires={expires_in}"

    def get_metadata(self, key):
        data, content_type, metadata = self.objects[key]
        return StorageObjectMetadata(key, len(data), content_type, "test-etag", metadata)

    def check_health(self):
        return None


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
        platform_admin = User(
            email="platform-admin@example.com",
            display_name="Platform Admin",
            password_hash=hash_password("platform-password"),
            platform_role_id=roles["platform_admin"].id,
        )
        session.add_all([first_org, second_org, admin, viewer, second_user, platform_admin])
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
        platform_membership = OrganizationMember(
            organization_id=first_org.id, user_id=platform_admin.id, role_id=roles["manager"].id
        )
        session.add_all([first_admin_membership, first_viewer_membership, second_admin_membership, platform_membership])
        session.add(QuotaRule(
            organization_id=None,
            operation_code="listing.generate",
            name="Listing image generation",
            base_cost=10,
            model_multipliers={"premium": "2"},
            quality_multipliers={"high": "1.5"},
            resolution_multipliers={"2048": "2"},
            resource_pool_multipliers={"personal": "0", "platform": "1"},
            effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            created_by=platform_admin.id,
            updated_by=platform_admin.id,
        ))
        session.add(QuotaPackage(
            code="test-1000", name="Test package", quota_amount=1000,
            price=Decimal("99.00"), created_by=platform_admin.id, updated_by=platform_admin.id,
        ))
        await session.flush()
        await ensure_account(session, first_org.id, platform_admin.id, initial_balance=1000)
        await ensure_account(session, second_org.id, second_user.id, initial_balance=50)
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
    storage = FakeStorageService()
    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_storage_service] = lambda: storage
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {"client": client, "app": app, "session_factory": session_factory, "storage": storage, **ids}
    await engine.dispose()
