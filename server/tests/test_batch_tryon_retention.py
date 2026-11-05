from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.models.tasks import Job, JobBatch
from app.models.content import Asset, GeneratedOutput
from app.models.identity import AuditLog
from app.models.quota import QuotaReservation
from app.models.batch_tryon_queue_policy import BatchTryOnQueuePolicy
from app.services.batch_tryon_retention_service import execute_retention, read_policy, retry_pending_storage
from tests.test_batch_tryon_downloads import ready_batch
from tests.test_batch_tryon_review import auth_headers
from tests.test_batch_tryon_shared_queue import colleague

UTC = timezone.utc


async def old_batch(context, monkeypatch, *, completed=1):
    # Production MySQL cascades child review/version rows; enable the same FK
    # behavior in this SQLite fixture instead of treating orphan rows as sharing.
    async with context["engine"].connect() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    headers, batch, outputs = await ready_batch(context, monkeypatch, count=2, completed=completed)
    old = datetime.now(UTC) - timedelta(days=5)
    async with context["session_factory"]() as session:
        b = await session.get(JobBatch, batch["id"])
        b.created_at = b.updated_at = old
        for job in (await session.scalars(select(Job).where(Job.batch_id == b.id))).all():
            job.created_at = job.updated_at = old
            if job.finished_at:
                job.finished_at = old
        await session.commit()
    return headers, batch, outputs


async def save(client, headers, action="delete", enabled=True, revision=0):
    result = await client.put("/api/v1/batch-tryon/queue/retention", headers=headers, json={
        "enabled": enabled, "days": 3, "age_basis": "last_activity", "action": action,
        "expected_revision": revision, "confirmation": "PERMANENT_DELETE"})
    assert result.status_code == 200, result.text
    return result.json()


async def perform(context, headers, settings):
    p = await context["client"].post("/api/v1/batch-tryon/queue/retention/preview", headers=headers, json=settings)
    assert p.status_code == 200, p.text
    submitted = await context["client"].post("/api/v1/batch-tryon/queue/retention/run", headers=headers, json={
        "expected_revision": settings["revision"], "preview_token": p.json()["preview_token"], "confirmation": "PERMANENT_DELETE"})
    assert submitted.status_code == 202, submitted.text
    assert submitted.json()["submitted"] is True
    # Execute the captured maintenance action locally; Celery publishing is mocked.
    from httpx import Response
    async with context["session_factory"]() as session:
        result = await execute_retention(session, context["storage"], context["first_org"],
            expected_revision=settings["revision"], preview_token=p.json()["preview_token"])
    return Response(200, json=result)


async def test_settings_default_disabled_and_admin_only(identity_test_context, monkeypatch):
    c = identity_test_context
    h, _, _ = await old_batch(c, monkeypatch)
    member = await colleague(c)
    initial = (await c["client"].get("/api/v1/batch-tryon/queue/retention", headers=h)).json()
    assert initial["days"] == 3 and initial["enabled"] is False and initial["can_manage"] is True
    assert (await c["client"].put("/api/v1/batch-tryon/queue/retention", headers=member,
        json={"expected_revision": 0})).status_code == 403
    rejected = await c["client"].put("/api/v1/batch-tryon/queue/retention", headers=h,
        json={"enabled": True, "action": "delete", "expected_revision": 0})
    assert rejected.status_code == 422
    settings = await save(c["client"], h)
    assert settings["revision"] == 1
    assert (await c["client"].put("/api/v1/batch-tryon/queue/retention", headers=h,
        json={"enabled": False, "expected_revision": 0})).status_code == 409
    outside = await auth_headers(c["client"], "second-admin", "second-password")
    assert (await c["client"].get("/api/v1/batch-tryon/queue/retention", headers=outside)).json()["revision"] == 0


async def test_permanent_cleanup_releases_pending_quota_and_preserves_inputs(identity_test_context, monkeypatch):
    c = identity_test_context
    h, batch, outputs = await old_batch(c, monkeypatch)
    settings = await save(c["client"], h)
    before_objects = set(c["storage"].objects)
    result = await perform(c, h, settings)
    assert result.status_code == 200, result.text
    assert result.json()["deleted_batches"] == 1 and result.json()["deleted_results"] == 1
    assert result.json()["cancelled_jobs"] == 1
    async with c["session_factory"]() as session:
        assert await session.get(JobBatch, batch["id"]) is None
        assert await session.get(Asset, outputs[0]["id"]) is None
        assert len((await session.scalars(select(Asset))).all()) == 2  # Original template + garment.
        reservations = list((await session.scalars(select(QuotaReservation))).all())
        assert any(r.status == "released" for r in reservations)
        assert await session.scalar(select(AuditLog.id).where(AuditLog.action == "batch_tryon.queue.retention"))
        assert len((await read_policy(session, c["first_org"])).pending_storage_keys) == 0
    assert len(before_objects - set(c["storage"].objects)) == 1


@pytest.mark.parametrize("status", ["running", "dispatching"])
async def test_active_jobs_are_never_deleted(identity_test_context, monkeypatch, status):
    c = identity_test_context
    h, batch, _ = await old_batch(c, monkeypatch)
    async with c["session_factory"]() as session:
        (await session.get(Job, batch["jobs"][1]["id"])).status = status
        await session.commit()
    settings = await save(c["client"], h)
    result = await perform(c, h, settings)
    assert result.status_code == 200 and result.json()["deleted_batches"] == 0
    async with c["session_factory"]() as session:
        assert await session.get(JobBatch, batch["id"])


async def test_recent_progress_protected_even_when_created_at_basis(identity_test_context, monkeypatch):
    c = identity_test_context
    h, batch, _ = await old_batch(c, monkeypatch)
    async with c["session_factory"]() as session:
        (await session.get(Job, batch["jobs"][1]["id"])).heartbeat_at = datetime.now(UTC)
        await session.commit()
    settings = await save(c["client"], h)
    settings["age_basis"] = "created_at"
    p = await c["client"].post("/api/v1/batch-tryon/queue/retention/preview", headers=h, json=settings)
    assert p.json()["eligible_count"] == 0


async def test_archive_pause_restore_and_other_owner_isolation(identity_test_context, monkeypatch):
    c = identity_test_context
    h, batch, _ = await old_batch(c, monkeypatch)
    settings = await save(c["client"], h, action="pause_archive")
    result = await perform(c, h, settings)
    assert result.status_code == 200 and result.json()["archived"] == 1
    assert not (await c["client"].get("/api/v1/batch-tryon/queue", headers=h)).json()["entries"]
    archived = (await c["client"].get("/api/v1/batch-tryon/queue?include_archived=true", headers=h)).json()
    assert archived["entries"][0]["archived"] is True and archived["waiting_count"] == 0
    other = await colleague(c)
    assert (await c["client"].post(f"/api/v1/batch-tryon/queue/{batch['id']}/restore", headers=other)).status_code == 404
    assert (await c["client"].post(f"/api/v1/batch-tryon/queue/{batch['id']}/restore", headers=h)).status_code == 200
    async with c["session_factory"]() as session:
        b = await session.get(JobBatch, batch["id"])
        assert b.status == "paused" and b.workspace_hidden is False
    assert (await c["client"].get("/api/v1/batch-tryon/queue", headers=h)).json()["entries"][0]["status"] == "paused"


async def test_storage_failure_is_persisted_and_retryable(identity_test_context, monkeypatch):
    c = identity_test_context
    h, batch, _ = await old_batch(c, monkeypatch)
    settings = await save(c["client"], h)
    original = c["storage"].delete
    def unavailable(key):
        raise OSError("synthetic storage outage")
    monkeypatch.setattr(c["storage"], "delete", unavailable)
    result = await perform(c, h, settings)
    assert result.json()["storage_pending"] == 1
    monkeypatch.setattr(c["storage"], "delete", original)
    async with c["session_factory"]() as session:
        policy = await read_policy(session, c["first_org"])
        await retry_pending_storage(session, policy, c["storage"])
        assert policy.pending_storage_keys == []


async def test_failed_database_deletion_does_not_remove_storage(identity_test_context, monkeypatch):
    c = identity_test_context
    h, batch, _ = await old_batch(c, monkeypatch)
    settings = await save(c["client"], h)
    original_objects = set(c["storage"].objects)
    async def broken(*args, **kwargs):
        raise ValueError("synthetic deletion failure")
    monkeypatch.setattr("app.services.batch_tryon_retention_service.hard_delete_job_batch", broken)
    result = await perform(c, h, settings)
    assert result.json()["errors"] == 1 and result.json()["deleted_batches"] == 0
    assert set(c["storage"].objects) == original_objects
    async with c["session_factory"]() as session:
        assert await session.get(JobBatch, batch["id"])
        assert (await session.get(Job, batch["jobs"][1]["id"])).status == "queued"


async def test_reused_result_is_preserved_as_other_task_json_input(identity_test_context, monkeypatch):
    c = identity_test_context
    h, batch, outputs = await old_batch(c, monkeypatch)
    async with c["session_factory"]() as session:
        first = await session.get(Job, batch["jobs"][0]["id"])
        session.add(Job(organization_id=first.organization_id, quota_reservation_id=first.quota_reservation_id,
            operation_code=first.operation_code, workspace_type="batch_tryon", queue_name=first.queue_name,
            capability=first.capability, model_code=first.model_code, input_json={"reference_asset_ids": [outputs[0]["id"]]},
            idempotency_key="external-reuse-fixture", request_hash=first.request_hash, max_attempts=3,
            created_by=first.created_by, updated_by=first.created_by))
        await session.commit()
    s = await save(c["client"], h)
    result = await perform(c, h, s)
    assert result.status_code == 200, result.text
    assert result.json()["retained_shared_assets"] == 1
    async with c["session_factory"]() as session:
        assert await session.get(JobBatch, batch["id"]) is None
        assert await session.get(Asset, outputs[0]["id"])


async def test_stale_preview_cannot_be_applied_and_disabled_rule_does_nothing(identity_test_context, monkeypatch):
    c = identity_test_context
    h, batch, _ = await old_batch(c, monkeypatch)
    async with c["session_factory"]() as session:
        assert (await execute_retention(session, c["storage"], c["first_org"]))["disabled"] is True
    s = await save(c["client"], h)
    p = (await c["client"].post("/api/v1/batch-tryon/queue/retention/preview", headers=h, json=s)).json()
    async with c["session_factory"]() as session:
        (await session.get(Job, batch["jobs"][1]["id"])).status = "running"
        await session.commit()
    result = await c["client"].post("/api/v1/batch-tryon/queue/retention/run", headers=h, json={
        "expected_revision": s["revision"], "preview_token": p["preview_token"], "confirmation": "PERMANENT_DELETE"})
    assert result.status_code == 409


def test_retention_migration_is_additive_and_reversible():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location("retention_migration", Path(__file__).parents[1] / "alembic/versions/0062_batch_tryon_queue_policy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert "batch_tryon_queue_policies" in inspect(connection).get_table_names()
        assert "pending_storage_keys" in {c["name"] for c in inspect(connection).get_columns("batch_tryon_queue_policies")}
        module.downgrade()
        assert "batch_tryon_queue_policies" not in inspect(connection).get_table_names()
    engine.dispose()


def test_retention_uses_dedicated_maintenance_queue_not_image_slots():
    from app.workers.celery_app import celery_app
    assert celery_app.conf.task_routes["system.batch_queue_retention"]["queue"] == "queue_retention"
    assert celery_app.conf.beat_schedule["batch-queue-retention"]["schedule"] == 300.0
