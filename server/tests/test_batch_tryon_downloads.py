"""Download regressions use only SQLite, FakeStorage and synthetic fixtures."""
from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZipFile
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.content import Asset, GeneratedOutput
from app.models.tasks import Job
from app.services.batch_tryon_review_service import sync_batch_try_on_version_for_job
from tests.test_batch_tryon_review import PNG, auth_headers, seed_batch_try_on_pool, upload_asset


async def ready_batch(context, monkeypatch, *, count=2, completed=None, model_code=None):
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *a, **kw: None)
    client = context["client"]
    headers = await auth_headers(client, "first-admin", "correct-password")
    model = model_code or await seed_batch_try_on_pool(context)
    template = await upload_asset(client, headers, "model_template", "模板.png")
    garment = await upload_asset(client, headers, "garment", "06-服装.png")
    response = await client.post("/api/v1/job-batches", headers=headers, json={
        "name": "Download fixture", "workspace_type": "batch_tryon", "operation_code": "batch_tryon.generate",
        "capability": "image_edit", "model_code": model, "concurrency": 2,
        "idempotency_key": f"download-fixture-{uuid4()}", "items": [{
            "client_item_id": f"item-{i}", "prompt": "synthetic fixture only", "size": "1024x1024",
            "reference_asset_ids": [template["id"], garment["id"]],
            "metadata": {"template_id": "template-1", "template_name": "模板", "garment_asset_id": garment["id"]},
        } for i in range(count)],
    })
    assert response.status_code == 202, response.text
    batch = response.json()
    outputs = []
    completed = count if completed is None else completed
    for job_body in batch["jobs"][:completed]:
        output = await upload_asset(client, headers, "batch_tryon_output", "generated.png")
        outputs.append(output)
        async with context["session_factory"]() as session:
            job = await session.get(Job, job_body["id"])
            job.status = "succeeded"
            job.finished_at = datetime.now(timezone.utc)
            session.add(GeneratedOutput(organization_id=job.organization_id, asset_id=output["id"], job_id=job.id,
                batch_id=job.batch_id, sequence_number=0, output_type="batch_tryon_output",
                created_by=job.created_by, created_at=datetime.now(timezone.utc)))
            await sync_batch_try_on_version_for_job(session, job, generated_asset_id=output["id"])
            await session.commit()
    return headers, batch, outputs


async def test_rejected_successful_image_is_not_exported(identity_test_context, monkeypatch):
    context = identity_test_context
    headers, batch, _ = await ready_batch(context, monkeypatch, count=1)
    job = batch["jobs"][0]
    discarded = await context["client"].post(f"/api/v1/batch-tryon/items/{job['review_item_id']}/discard",
        headers=headers, json={"source_version_id": job["current_version_id"]})
    assert discarded.status_code == 200
    response = await context["client"].get(
        f"/api/v1/batch-tryon/batches/{batch['id']}/templates/template-1/download?scope=all_succeeded", headers=headers)
    assert response.status_code == 409


async def test_missing_asset_record_is_not_silently_skipped(identity_test_context, monkeypatch):
    context = identity_test_context
    headers, batch, outputs = await ready_batch(context, monkeypatch)
    async with context["session_factory"]() as session:
        asset = await session.get(Asset, outputs[0]["id"])
        asset.deleted_at = datetime.now(timezone.utc)
        await session.commit()
    response = await context["client"].get(f"/api/v1/job-batches/{batch['id']}/batch-tryon-results.zip", headers=headers)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "batch_tryon.export_asset_missing"


async def test_unfinished_results_require_explicit_partial_export(identity_test_context, monkeypatch):
    context = identity_test_context
    headers, batch, _ = await ready_batch(context, monkeypatch, completed=1)
    url = f"/api/v1/job-batches/{batch['id']}/batch-tryon-results.zip"
    blocked = await context["client"].get(url, headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "batch_tryon.export_partial_confirmation_required"
    partial = await context["client"].get(url + "?allow_partial=true", headers=headers)
    assert partial.status_code == 200
    with ZipFile(BytesIO(partial.content)) as archive:
        assert archive.testzip() is None
        assert len([name for name in archive.namelist() if name.endswith(".png")]) == 1
        assert "_export-report.json" in archive.namelist()


async def test_missing_object_reports_export_phase_and_correlation(identity_test_context, monkeypatch):
    context = identity_test_context
    headers, batch, outputs = await ready_batch(context, monkeypatch)
    async with context["session_factory"]() as session:
        asset = await session.get(Asset, outputs[0]["id"])
        context["storage"].objects.pop(asset.storage_key)
    response = await context["client"].get(
        f"/api/v1/batch-tryon/batches/{batch['id']}/templates/template-1/download?scope=all_succeeded", headers=headers)
    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "batch_tryon.export_asset_missing"
    assert error["request_id"]
    assert error["details"]["stage"] == "read_asset"
    assert error["details"]["batch_id"] == batch["id"]
    assert error["details"]["template_id"] == "template-1"


async def test_complete_zip_is_valid_and_single_download_still_works(identity_test_context, monkeypatch):
    context = identity_test_context
    headers, batch, outputs = await ready_batch(context, monkeypatch)
    single = await context["client"].get(f"/api/v1/assets/{outputs[0]['id']}/download", headers=headers)
    assert single.status_code == 200 and single.content == PNG
    response = await context["client"].get(f"/api/v1/job-batches/{batch['id']}/batch-tryon-results.zip", headers=headers)
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.testzip() is None and len(archive.namelist()) == 2
        assert len(set(archive.namelist())) == 2
        assert all(archive.read(name) == PNG for name in archive.namelist())


async def test_cross_batch_zip_includes_both_submissions_and_deduplicates(identity_test_context, monkeypatch):
    context = identity_test_context
    headers, first, _ = await ready_batch(context, monkeypatch, count=2)
    _, second, _ = await ready_batch(context, monkeypatch, count=1, model_code="review-image-model")
    response = await context["client"].post("/api/v1/batch-tryon/exports/download", headers=headers,
        json={"batch_ids": [first["id"], second["id"], first["id"]]})
    assert response.status_code == 200, response.text
    assert response.headers["X-Batch-Try-On-Exported"] == "3"
    assert len(response.content) == int(response.headers["Content-Length"])
    with ZipFile(BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist())) == 3
        assert archive.testzip() is None
        assert all(archive.read(name) == PNG for name in archive.namelist())


async def test_spooled_archive_rollover_and_pack_failure(identity_test_context, monkeypatch):
    context = identity_test_context
    headers, batch, _ = await ready_batch(context, monkeypatch, count=64)
    from app.services import batch_tryon_export_service as exports
    monkeypatch.setattr(exports, "EXPORT_MEMORY_BYTES", 1)
    url = f"/api/v1/job-batches/{batch['id']}/batch-tryon-results.zip"
    response = await context["client"].get(url, headers=headers)
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 64 and archive.testzip() is None
    def fail_write(*args, **kwargs):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(exports.ZipFile, "writestr", fail_write)
    failure = await context["client"].get(url, headers={**headers, "X-Request-ID": "synthetic-pack-failure"})
    assert failure.status_code == 502
    error = failure.json()["error"]
    assert error["request_id"] == "synthetic-pack-failure" and error["details"]["stage"] == "zip_write"
    assert "synthetic disk failure" not in failure.text


async def test_oversized_export_is_explicit_not_truncated(identity_test_context, monkeypatch):
    headers, batch, _ = await ready_batch(identity_test_context, monkeypatch)
    monkeypatch.setattr("app.services.batch_tryon_export_service.MAX_SYNCHRONOUS_EXPORT_BYTES", 1)
    response = await identity_test_context["client"].get(f"/api/v1/job-batches/{batch['id']}/batch-tryon-results.zip", headers=headers)
    assert response.status_code == 413 and response.json()["error"]["code"] == "batch_tryon.export_too_large"
