"""Real DDL rehearsal, restricted to the disposable agent_phase1_ database."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.db.base import Base
import app.models
from app.models.identity import User, Organization
from app.models.listing_workflow import ListingImageProject
from tests.test_hermes_agent import _project

pytestmark = pytest.mark.skipif(not os.environ.get("AGENT_TEST_CHECKPOINT_URL"), reason="Explicit isolated MySQL required")


async def test_migration_upgrade_downgrade_preserves_old_controller(monkeypatch):
    url = os.environ["AGENT_TEST_CHECKPOINT_URL"]
    parsed = urlsplit(url)
    assert parsed.hostname in {"127.0.0.1", "localhost"} and parsed.path.lstrip("/").startswith("agent_phase1_")
    engine = create_async_engine(url)
    spec = importlib.util.spec_from_file_location("agent_migration", Path(__file__).parents[1] / "alembic/versions/0063_agent_control_phase1.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        org = await db.scalar(select(Organization).where(Organization.slug == "agent-migration-test"))
        if org is None:
            org = Organization(name="Agent migration test", slug="agent-migration-test")
            db.add(org)
        user = await db.scalar(select(User).where(User.account == "first-admin"))
        if user is None:
            user = User(account="first-admin", display_name="Test only", password_hash="not-a-login-password")
            db.add(user)
        await db.commit()
        org_id, user_id = org.id, user.id
        project = await db.scalar(select(ListingImageProject).where(ListingImageProject.organization_id == org_id))
        project_id = project.id if project else None
    if project_id is None:
        project_id, user_id = await _project({"session_factory": sessions, "first_org": org_id})
    legacy_id = str(uuid4())
    async with engine.begin() as conn:
        def rehearsal(sync):
            ops = Operations(MigrationContext.configure(sync))
            monkeypatch.setattr(migration, "op", ops)
            # Reconstruct the 0062-era Hermes shape without touching any real app DB.
            for table in ("agent_job_links", "agent_events", "agent_runs"):
                ops.drop_table(table)
            fk = next(f for f in inspect(sync).get_foreign_keys("hermes_conversations") if f["constrained_columns"] == ["context_project_id"])
            ops.drop_constraint(fk["name"], "hermes_conversations", type_="foreignkey")
            ops.drop_column("hermes_conversations", "context_project_id")
            ops.drop_column("hermes_conversations", "controller_type")
            for table in ("hermes_conversations", "hermes_proposals", "hermes_tool_audits"):
                import sqlalchemy as sa
                ops.alter_column(table, "listing_image_project_id", existing_type=sa.String(36), nullable=False)
            sync.execute(text("INSERT INTO hermes_conversations (id,organization_id,user_id,listing_image_project_id,title,mode,status,created_at,updated_at) VALUES (:id,:org,:user,:project,'Legacy saved conversation','suggest','active',NOW(),NOW())"),
                {"id": legacy_id, "org": org_id, "user": user_id, "project": project_id})
            migration.upgrade()
            cols = {c["name"]: c for c in inspect(sync).get_columns("hermes_conversations")}
            assert cols["controller_type"]["default"] == "'hermes'"
            assert cols["listing_image_project_id"]["nullable"] is True
            assert inspect(sync).has_table("agent_job_links")
            assert sync.execute(text("SELECT controller_type,title FROM hermes_conversations WHERE id=:id"), {"id": legacy_id}).one() == ("hermes", "Legacy saved conversation")
            agent_id = str(uuid4())
            sync.execute(text("INSERT INTO hermes_conversations (id,organization_id,user_id,controller_type,title,mode,status,created_at,updated_at) VALUES (:id,:org,:user,'langgraph','Agent test','suggest','active',NOW(),NOW())"),
                {"id": agent_id, "org": org_id, "user": user_id})
            with pytest.raises(RuntimeError):
                migration.downgrade()
            assert inspect(sync).has_table("agent_runs")
            sync.execute(text("DELETE FROM hermes_conversations WHERE id=:id"), {"id": agent_id})
            migration.downgrade()
            assert "controller_type" not in {c["name"] for c in inspect(sync).get_columns("hermes_conversations")}
            assert not inspect(sync).has_table("agent_runs")
            assert sync.scalar(text("SELECT title FROM hermes_conversations WHERE id=:id"), {"id": legacy_id}) == "Legacy saved conversation"
            migration.upgrade()
        await conn.run_sync(rehearsal)
    await engine.dispose()
