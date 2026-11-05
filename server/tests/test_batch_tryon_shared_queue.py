"""Offline cross-account regression: SQLite + fake Redis/storage, no Worker/upstream."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, text, update

from app.models.identity import OrganizationMember, Role, User
from app.models.content import Asset, Project, ProjectAsset
from app.models.tasks import ApiKey, Job, JobAttempt, JobBatch, ResourcePool, ResourcePoolKey, BatchTryOnReviewItem, BatchTryOnVersion, OperationResourcePool
from app.schemas.batch_tryon_queue import SharedQueueCapacity
from app.services.batch_tryon_shared_queue_service import estimate_wait
from tests.test_batch_tryon_downloads import ready_batch
from tests.test_batch_tryon_review import auth_headers, upload_asset

UTC = timezone.utc


@pytest.mark.companydb
async def test_large_config_is_never_part_of_ordered_queue_projection(identity_test_context, monkeypatch):
    """Also runs on explicitly isolated MySQL 8.4 with its real 256 KB buffer."""
    context = identity_test_context
    own, batch, _ = await ready_batch(context, monkeypatch, count=2)
    private_padding = 'private-workspace-config-' + 'x' * (2 * 1024 * 1024)
    async with context['session_factory']() as session:
        await session.execute(update(JobBatch).where(JobBatch.id == batch['id']).values(
            workspace_config_json={'private_padding': private_padding}).execution_options(synchronize_session=False))
        await session.commit()
        if context['company_database_url']:
            assert await session.scalar(text('SELECT @@session.sort_buffer_size')) == 262144
    statements = []
    def record(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith('select'):
            statements.append(statement.lower())
    event.listen(context['engine'].sync_engine, 'before_cursor_execute', record)
    try:
        for _ in range(2):
            response = await context['client'].get('/api/v1/batch-tryon/queue', headers=own)
            assert response.status_code == 200, response.text
            entry = next(e for e in response.json()['entries'] if e['id'] == batch['id'])
            assert entry['total_count'] == entry['completed_count'] == 2
            assert entry['archived'] is False
            assert 'private-workspace-config' not in response.text
        async with context['session_factory']() as session:
            await session.execute(update(JobBatch).where(JobBatch.id == batch['id']).values(
                workspace_config_json={'private_padding': private_padding,
                    'queue_retention': {'archived_at': '2026-11-02T00:00:00+00:00'}}
                ).execution_options(synchronize_session=False))
            await session.commit()
        hidden = await context['client'].get('/api/v1/batch-tryon/queue', headers=own)
        assert hidden.status_code == 200 and not hidden.json()['entries']
        shown = await context['client'].get('/api/v1/batch-tryon/queue?include_archived=true', headers=own)
        assert shown.status_code == 200, shown.text
        entry = next(e for e in shown.json()['entries'] if e['id'] == batch['id'])
        assert entry['archived'] and entry['status'] == 'archived'
        assert entry['completed_count'] == 2 and 'private-workspace-config' not in shown.text
    finally:
        event.remove(context['engine'].sync_engine, 'before_cursor_execute', record)
    ordered = [sql for sql in statements if 'from job_batches' in sql and 'order by' in sql]
    assert ordered and all('workspace_config' not in sql and 'json_extract' not in sql for sql in ordered)
    flags = [sql for sql in statements if 'from job_batches' in sql and 'json_extract' in sql]
    assert flags and all('order by' not in sql and 'job_batches.organization_id' in sql for sql in flags)


async def colleague(context):
    async with context["session_factory"]() as session:
        member = await session.get(OrganizationMember, context["first_viewer_membership"])
        member.role_id = await session.scalar(select(Role.id).where(Role.code == "manager"))
        await session.commit()
    return await auth_headers(context["client"], "first-viewer", "viewer-password")


async def add_shared_key(context, used=0, cooldown=False):
    async with context["session_factory"]() as session:
        pools = list((await session.scalars(select(ResourcePool))).all())
        key = ApiKey(provider_id=(await session.get(ResourcePool, pools[0].id)).model.provider_id,
            label="Synthetic six-slot key", secret_ciphertext="not-a-real-secret", fingerprint="synthetic-fingerprint",
            secret_suffix="test", max_concurrency=6,
            cooldown_until=datetime.now(UTC) + timedelta(minutes=1) if cooldown else None)
        session.add(key)
        await session.flush()
        for pool in pools:
            session.add(ResourcePoolKey(resource_pool_id=pool.id, api_key_id=key.id))
        await session.commit()
        key_id = key.id
    context["redis"].values[f"resource:key:{key_id}:inflight"] = used
    return key_id


async def test_summary_visible_to_colleague_but_all_details_remain_private(identity_test_context, monkeypatch):
    context = identity_test_context
    own, batch, outputs = await ready_batch(context, monkeypatch)
    other = await colleague(context)
    client = context["client"]
    response = await client.get("/api/v1/batch-tryon/queue", headers=other)
    assert response.status_code == 200, response.text
    entry = next(e for e in response.json()["entries"] if e["id"] == batch["id"])
    assert entry["completed_count"] == entry["total_count"] == 2
    assert entry["can_open"] is False and entry["navigation"] is None
    for secret in ["synthetic fixture only", outputs[0]["id"], "reference_asset_ids", "download_url", "review_status"]:
        assert secret not in response.text
    job = batch["jobs"][0]
    forbidden = [f"/api/v1/jobs/{job['id']}", f"/api/v1/job-batches/{batch['id']}",
        f"/api/v1/batch-tryon/items/{job['review_item_id']}/review-detail",
        f"/api/v1/job-batches/{batch['id']}/batch-tryon-results.zip",
        f"/api/v1/assets/{outputs[0]['id']}", f"/api/v1/assets/{outputs[0]['id']}/content",
        f"/api/v1/assets/{outputs[0]['id']}/url", f"/api/v1/assets/{outputs[0]['id']}/download"]
    for path in forbidden:
        result = await client.get(path, headers=other)
        assert result.status_code == 404, (path, result.status_code, result.text)
    for action in ["pause", "resume", "cancel"]:
        result = await client.post(f"/api/v1/job-batches/{batch['id']}/{action}", headers=other)
        assert result.status_code == 404
    for action in ["approve", "discard", "regenerate"]:
        result = await client.post(f"/api/v1/batch-tryon/items/{job['review_item_id']}/{action}", headers=other,
            json={"source_version_id": job["current_version_id"], "retry_mode": "direct", "idempotency_key": "forbidden-regenerate"})
        assert result.status_code == 404, result.text
    assert (await client.delete(f"/api/v1/job-batches/{batch['id']}/hard?confirmation=PERMANENT_DELETE", headers=other)).status_code == 404
    assert (await client.post("/api/v1/batch-tryon/exports/download", headers=other, json={"batch_ids": [batch["id"]]})).status_code == 404
    assert (await client.post(f"/api/v1/batch-tryon/templates/template-1/download", headers=other,
        json={"item_ids": [job["review_item_id"]], "scope": "all_succeeded"})).status_code == 404
    assert (await client.get(forbidden[0], headers=own)).status_code == 200
    assert (await client.get(forbidden[-1], headers=own)).status_code == 200
    own_image = await client.get(f"/api/v1/assets/{outputs[0]['id']}/content", headers=own)
    assert own_image.headers["Cache-Control"] == "private, no-store"
    assert "Authorization" in own_image.headers["Vary"]
    mine = (await client.get("/api/v1/batch-tryon/queue", headers=own)).json()["entries"][0]
    assert mine["can_open"] is True and mine["navigation"]["batch_id"] == batch["id"]
    outside = await auth_headers(client, "second-admin", "second-password")
    assert (await client.get("/api/v1/batch-tryon/queue", headers=outside)).json()["entries"] == []
    assert (await client.get(forbidden[-1], headers=outside)).status_code == 404


async def test_private_input_and_derived_asset_cannot_be_reused_by_colleague(identity_test_context, monkeypatch):
    context = identity_test_context
    own, batch, outputs = await ready_batch(context, monkeypatch, count=1)
    other = await colleague(context)
    template = await upload_asset(context["client"], own, "model_template", "private.png")
    async with context["session_factory"]() as session:
        asset = await session.get(Asset, outputs[0]["id"])
        derived = Asset(organization_id=asset.organization_id, category="temporary", filename="mask.png",
            mime_type="image/png", size=asset.size, width=asset.width, height=asset.height, sha256=asset.sha256,
            storage_key="synthetic-mask", source_asset_id=asset.id, created_by=asset.created_by, updated_by=asset.created_by)
        session.add(derived)
        await session.commit()
        derived_id = derived.id
    for asset_id in [template["id"], derived_id]:
        assert (await context["client"].get(f"/api/v1/assets/{asset_id}", headers=other)).status_code == 404
    response = await context["client"].post("/api/v1/jobs", headers=other, json={
        "workspace_type": "batch_tryon", "operation_code": "batch_tryon.generate", "capability": "image_edit",
        "model_code": "review-image-model", "queue_name": "batch_tryon_queue", "idempotency_key": "forbidden-private-reference",
        "input": {"prompt": "test", "size": "1024x1024", "reference_asset_ids": [template["id"]]},
    })
    assert response.status_code == 404, response.text
    # Using another valid workspace cannot copy a private batch input either.
    async with context["session_factory"]() as session:
        pool = await session.scalar(select(ResourcePool).where(ResourcePool.code == "review-pool"))
        session.add(OperationResourcePool(operation_code="listing.generate", resource_pool_id=pool.id, required_capability="image_edit"))
        await session.commit()
    response = await context["client"].post("/api/v1/jobs", headers=other, json={
        "workspace_type": "listing", "operation_code": "listing.generate", "capability": "image_edit",
        "queue_name": "listing_queue", "model_code": "review-image-model", "idempotency_key": "forged-workspace-fixture",
        "input": {"prompt": "test", "size": "1024x1024", "reference_asset_ids": [template["id"]]},
    })
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "asset.not_found"


async def test_workspace_counts_only_production_and_refresh_is_read_only(identity_test_context, monkeypatch):
    context = identity_test_context
    own, batch, _ = await ready_batch(context, monkeypatch, count=3, completed=1)
    key_id = await add_shared_key(context, used=2)
    async with context["session_factory"]() as session:
        production = await session.get(JobBatch, batch["id"])
        workspace = JobBatch(organization_id=production.organization_id, workspace_type="batch_tryon", batch_kind="workspace",
            operation_code="batch_tryon.generate", name="Shared workspace", created_by=production.created_by, updated_by=production.created_by)
        session.add(workspace)
        await session.flush()
        production.parent_batch_id = workspace.id
        pending = await session.get(Job, batch["jobs"][1]["id"])
        pending.status = "running"
        pending.started_at = datetime.now(UTC)
        session.add(JobAttempt(organization_id=pending.organization_id, job_id=pending.id, attempt_number=1,
            api_key_id=key_id, status="running", started_at=datetime.now(UTC), provider_requested_at=datetime.now(UTC)))
        validation = JobBatch(organization_id=production.organization_id, workspace_type="batch_tryon", batch_kind="validation",
            parent_batch_id=workspace.id, operation_code="batch_tryon.generate", name="Sample", total_jobs=99,
            created_by=production.created_by, updated_by=production.created_by)
        session.add(validation)
        await session.commit()
        workspace_id = workspace.id
    before = dict(context["redis"].values)
    for _ in range(2):
        response = await context["client"].get("/api/v1/batch-tryon/queue", headers=own)
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["entries"]) == 1
        row = body["entries"][0]
        assert row["id"] == workspace_id and row["total_count"] == 3
        assert row["completed_count"] == row["running_count"] == row["waiting_count"] == 1
        assert body["capacity"]["configured"] == body["capacity"]["effective"] == 6
        assert body["capacity"]["in_use"] == 2  # Shared key in two pools counted once.
    assert before == context["redis"].values
    other = await colleague(context)
    assert (await context["client"].patch(f"/api/v1/batch-tryon/workspaces/{workspace_id}", headers=other,
        json={"name": "forbidden"})).status_code == 404


@pytest.mark.parametrize("job_status,batch_status,expected", [
    ("queued", "paused", "paused"), ("retry_waiting", "running", "queued"),
    ("cancelled", "cancelled", "cancelled"), ("failed", "failed", "failed"),
])
async def test_paused_cancelled_failed_retry_states(identity_test_context, monkeypatch, job_status, batch_status, expected):
    context = identity_test_context
    own, batch, _ = await ready_batch(context, monkeypatch, count=1, completed=0)
    await add_shared_key(context, cooldown=True)
    async with context["session_factory"]() as session:
        job = await session.get(Job, batch["jobs"][0]["id"])
        job.status = job_status
        if job_status == "retry_waiting":
            job.next_retry_at = datetime.now(UTC) + timedelta(minutes=1)
        (await session.get(JobBatch, batch["id"])).status = batch_status
        await session.commit()
    body = (await context["client"].get("/api/v1/batch-tryon/queue", headers=own)).json()
    assert body["entries"][0]["status"] == expected
    assert body["capacity"]["effective"] == 0
    assert body["entries"][0]["estimate"]["minimum_seconds"] is None


def test_wait_estimate_uses_real_six_slots_and_requires_samples():
    now = datetime.now(UTC)
    capacity = SharedQueueCapacity(configured=6, effective=6, in_use=6, source="redis_lease", reason="test")
    attempts = [SimpleNamespace(operation_code="image", provider_requested_at=now) for _ in range(6)]
    args = dict(capacity=capacity, active_attempts=attempts, ahead=[], now=now)
    assert estimate_wait(**args, samples={}).minimum_seconds is None
    estimate = estimate_wait(**args, samples={"image": [200] * 8})
    assert estimate.minimum_seconds == 90 and estimate.maximum_seconds == 360
    assert estimate.sample_count == 8


async def test_latest_version_and_luna_have_separate_counts(identity_test_context, monkeypatch):
    context = identity_test_context
    own, batch, _ = await ready_batch(context, monkeypatch, count=1)
    async with context["session_factory"]() as session:
        original = await session.get(Job, batch["jobs"][0]["id"])
        workspace = JobBatch(organization_id=original.organization_id, workspace_type="batch_tryon", batch_kind="workspace",
            operation_code="batch_tryon.generate", name="Luna workspace", created_by=original.created_by, updated_by=original.created_by)
        session.add(workspace)
        await session.flush()
        (await session.get(JobBatch, batch["id"])).parent_batch_id = workspace.id
        retry = Job(organization_id=original.organization_id, batch_id=original.batch_id,
            quota_reservation_id=original.quota_reservation_id, operation_code=original.operation_code,
            workspace_type=original.workspace_type, queue_name=original.queue_name, capability=original.capability,
            model_code=original.model_code, status="queued", input_json={"metadata": {"awaiting_luna": True}},
            idempotency_key="latest-version-fixture", request_hash=original.request_hash, max_attempts=3,
            created_by=original.created_by, updated_by=original.created_by)
        session.add(retry)
        await session.flush()
        review = await session.get(BatchTryOnReviewItem, batch["jobs"][0]["review_item_id"])
        version = BatchTryOnVersion(organization_id=review.organization_id, item_id=review.id, version_number=2,
            task_id=retry.id, prompt_snapshot="private prompt", generation_status="queued", created_at=datetime.now(UTC), created_by=review.created_by)
        session.add(version)
        await session.flush()
        review.current_version_id = version.id
        analysis = Job(organization_id=original.organization_id, quota_reservation_id=original.quota_reservation_id,
            operation_code="batch_tryon.prompt_analyze_detailed", workspace_type="batch_tryon", queue_name="planning_queue",
            capability="text_generation", model_code="review-luna-model", status="running",
            input_json={"metadata": {"workflow_request": {"workspace_batch_id": workspace.id}, "prompt": "private analysis"}},
            idempotency_key="analysis-fixture", request_hash=original.request_hash, max_attempts=3,
            created_by=original.created_by, updated_by=original.created_by)
        session.add(analysis)
        await session.commit()
    body = (await context["client"].get("/api/v1/batch-tryon/queue", headers=own)).json()
    row = body["entries"][0]
    assert row["total_count"] == 1 and row["completed_count"] == 0 and row["waiting_count"] == 1
    assert row["analysis_running"] == 1 and row["running_count"] == 0
    assert row["estimate"]["reason"] == "等待AI分析完成"


async def test_two_users_have_independent_summaries_and_foreign_project_is_private(identity_test_context, monkeypatch):
    context = identity_test_context
    own, first, _ = await ready_batch(context, monkeypatch, count=1)
    other = await colleague(context)
    template = await upload_asset(context["client"], other, "model_template", "colleague.png")
    garment = await upload_asset(context["client"], other, "garment", "other.png")
    second = await context["client"].post("/api/v1/job-batches", headers=other, json={
        "name": "Colleague batch", "workspace_type": "batch_tryon", "operation_code": "batch_tryon.generate",
        "capability": "image_edit", "model_code": "review-image-model", "concurrency": 2,
        "idempotency_key": "colleague-fixture", "items": [{"client_item_id": "colleague-item", "prompt": "private colleague prompt",
            "size": "1024x1024", "reference_asset_ids": [template["id"], garment["id"]],
            "metadata": {"template_id": "other-template", "garment_asset_id": garment["id"]}}]})
    assert second.status_code == 202, second.text
    for headers in [own, other]:
        rows = (await context["client"].get("/api/v1/batch-tryon/queue", headers=headers)).json()["entries"]
        assert len(rows) == 2 and sum(r["total_count"] for r in rows) == 2
        assert sum(r["can_open"] for r in rows) == 1
    async with context["session_factory"]() as session:
        job = await session.get(Job, first["jobs"][0]["id"])
        project = Project(organization_id=job.organization_id, project_type="batch_tryon", name="Private project",
            created_by=job.created_by, updated_by=job.created_by)
        session.add(project)
        await session.commit()
        project_id = project.id
    assert (await context["client"].get(f"/api/v1/projects/{project_id}", headers=other)).status_code == 404


@pytest.mark.parametrize("category", ["style_reference", "model_template"])
async def test_published_shared_reference_keeps_existing_access(identity_test_context, monkeypatch, category):
    from app.models.attachment_planning import AttachmentReferenceLibraryItem
    context = identity_test_context
    own, batch, _ = await ready_batch(context, monkeypatch, count=1)
    other = await colleague(context)
    shared = await upload_asset(context["client"], own, category, "shared-reference.png")
    async with context["session_factory"]() as session:
        asset = await session.get(Asset, shared["id"])
        project = Project(organization_id=asset.organization_id, project_type="batch_tryon", name="Fixture project",
            created_by=asset.created_by, updated_by=asset.created_by)
        session.add(project)
        await session.flush()
        session.add(ProjectAsset(organization_id=asset.organization_id, project_id=project.id, asset_id=asset.id,
            role="font_reference", created_by=asset.created_by, created_at=datetime.now(UTC)))
        session.add(AttachmentReferenceLibraryItem(organization_id=asset.organization_id, name="Published fixture",
            module_key="scene", reference_role="SCENE", asset_id=asset.id, created_by=asset.created_by, updated_by=asset.created_by))
        await session.commit()
    assert (await context["client"].get(f"/api/v1/assets/{shared['id']}/content", headers=other)).status_code == 200
