"""No-fee Strategy A evidence: Mock HTTP + SQLite + the real S3 storage adapter.

All raster bytes in this module are synthetic test fixtures, not generated work.
No production credential, database, Redis, MinIO endpoint or Worker is used.
"""
import base64
from copy import deepcopy
from email.parser import BytesParser
from email.policy import default
from hashlib import sha256
from io import BytesIO
import json
import socket
from zipfile import ZipFile

import httpx
from PIL import Image
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.errors import AppError
from app.models.content import Asset, GeneratedOutput
from app.models.identity import User
from app.models.quota import QuotaAccount
from app.models.tasks import BatchTryOnReviewItem, BatchTryOnVersion, Job
from app.providers.base import ProviderError, ProviderOutput, ProviderResult
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.openai_responses import OpenAIResponsesImageProvider
from app.schemas.tasks import JobSubmitRequest
from app.services.asset_service import create_asset
from app.services.billing_service import reserve_quota, settle_reservation
from app.services.resource_pool_service import acquire_resource, release_resource
from app.services.storage_service import S3StorageService, get_storage_service
from tests import strategy_a_probe as probe
from tests.test_tasks_and_resource_pool import auth_headers, seed_pool

SETTINGS = Settings(_env_file=None, environment="test", s3_bucket="strategy-a-test-only")
BASE_CONFIG = {
    "edit_body_fields": ["model", "prompt", "aspect_ratio"],
    "edit_dimension_mode": "aspect_ratio", "supported_edit_aspect_ratios": ["3:4"],
}


@pytest.fixture(autouse=True)
def forbid_dns(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Strategy A tests must never resolve a real network destination")
    monkeypatch.setattr(socket, "getaddrinfo", fail)


def png(index=0, size=None):
    buffer = BytesIO()
    image = Image.new("RGB", size or (71 + index * 7, 97 + index * 11), (30 + index * 20, 80, 140))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def inputs():
    template = {"asset_id": "template-asset", "filename": "template.png", "content": png(0, (80, 120))}
    garments = [{"asset_id": f"garment-{i}", "filename": f"0{i}-服装.png", "content": png(i)} for i in range(1, 5)]
    return probe.build_input(template, garments)


def capabilities(**patch):
    return probe.ChannelCapabilities(**{
        "enabled": True, "supports_n": True, "supports_size": True,
        "supports_quality": True, "dimension_mode": "size", "max_outputs": 4, **patch,
    })


def install_http(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", factory)


def read_multipart(request):
    message = BytesParser(policy=default).parsebytes(
        ("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode() + request.content,
    )
    fields, files = {}, []
    for part in message.iter_parts():
        if part.get_filename():
            files.append((part.get_filename(), part.get_payload(decode=True)))
        else:
            fields[part.get_param("name", header="Content-Disposition")] = part.get_payload(decode=True).decode()
    return fields, files


async def mock_images(monkeypatch, mode, payload=None, config=None):
    requests = []
    def handler(request):
        assert request.url.host == "mock-relay.invalid"
        assert request.method == "POST" and request.url.path == "/v1/images/edits"
        requests.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if mode == "524":
            return httpx.Response(524, json={"error": {"message": "synthetic gateway timeout"}})
        count = {"one": 1, "four": 4, "empty": 0, "corrupt": 4, "five": 5, "bad-base64": 4}[mode]
        items = []
        for i in range(count):
            data = b"corrupt image fixture" if mode == "corrupt" and i == 1 else png(i)
            encoded = "not base64!" if mode == "bad-base64" and i == 1 else base64.b64encode(data).decode()
            items.append({"b64_json": encoded})
        return httpx.Response(200, json={"data": items}, headers={"x-request-id": "mock-request-group"})
    install_http(monkeypatch, handler)
    try:
        result = await OpenAICompatibleProvider(SETTINGS).execute(
            base_url="https://mock-relay.invalid/v1", api_key="mock-not-a-real-key",
            upstream_model="mock-image-model", capability="image_edit", payload=payload or inputs()[0],
            config=config if config is not None else probe.strategy_a_config(BASE_CONFIG, capabilities()),
        )
    except ProviderError as error:
        return None, probe.observe_error(error), requests
    return result, probe.observe(result, SETTINGS), requests


@pytest.mark.parametrize("caps,required,absent", [
    (capabilities(), {"n": "4", "size": "1536x2048", "quality": "high"}, {"aspect_ratio"}),
    (capabilities(supports_size=False, dimension_mode="aspect_ratio"),
     {"n": "4", "aspect_ratio": "3:4", "quality": "high"}, {"size"}),
    (capabilities(supports_size=False, supports_quality=False, dimension_mode="aspect_ratio"),
     {"n": "4", "aspect_ratio": "3:4"}, {"size", "quality"}),
])
async def test_a_only_wire_fields_follow_channel_capabilities(monkeypatch, caps, required, absent):
    original = deepcopy(BASE_CONFIG)
    payload, manifest, collage = inputs()
    _, observation, requests = await mock_images(monkeypatch, "four", payload, probe.strategy_a_config(BASE_CONFIG, caps))
    assert len(requests) == 1 and observation["returned_count"] == 4
    fields, files = read_multipart(requests[0])
    assert all(fields[key] == value for key, value in required.items())
    assert not set(fields).intersection(absent)
    assert [name for name, _ in files] == ["template.png", "garment-collage.png"]
    assert files[1][1] == collage
    assert manifest["panels"][3]["garment_asset_id"] == "garment-4"
    assert BASE_CONFIG == original


@pytest.mark.parametrize("caps", [probe.ChannelCapabilities(), capabilities(supports_n=False),
                                  capabilities(max_outputs=1), capabilities(supports_size=False)])
def test_undeclared_a_capability_fails_closed_without_network(caps):
    with pytest.raises(ValueError):
        probe.strategy_a_config(BASE_CONFIG, caps)


async def test_b_wire_whitelist_is_not_widened(monkeypatch):
    _, _, requests = await mock_images(monkeypatch, "one", config=BASE_CONFIG)
    fields, _ = read_multipart(requests[0])
    assert set(fields) == {"model", "prompt", "aspect_ratio"}
    assert BASE_CONFIG["edit_body_fields"] == ["model", "prompt", "aspect_ratio"]


def test_b_submission_schema_still_rejects_n_four():
    with pytest.raises(ValueError, match="exactly one image"):
        JobSubmitRequest(operation_code="batch_tryon.generate", workspace_type="batch_tryon",
            queue_name="batch_tryon_queue", capability="image_edit", model_code="mock-image-model",
            idempotency_key="strategy-a-not-enabled", input={
                "n": 4, "prompt": "fixture", "size": "1536x2048", "reference_asset_ids": ["a", "b"],
            })


@pytest.mark.parametrize("mode,status,count,valid", [
    ("one", "partial", 1, 1), ("four", "complete", 4, 4), ("empty", "failed", 0, 0),
    ("timeout", "remote_unknown", None, 0), ("524", "remote_unknown", None, 0),
    ("corrupt", "partial", 4, 3), ("five", "partial", 5, 5),
    ("bad-base64", "failed", None, 0),
])
async def test_response_counts_errors_and_no_automatic_retry(monkeypatch, mode, status, count, valid):
    _, observation, requests = await mock_images(monkeypatch, mode)
    assert len(requests) == 1
    assert observation["http_request_count"] == 1
    assert observation["image_generation_tool_call_count"] is None
    assert observation["group_status"] == status
    assert observation["returned_count"] == count and observation["valid_count"] == valid
    assert observation["auto_retry_allowed"] is False
    assert observation["upstream_actual_cost"] is None


async def test_images_http_count_does_not_invent_tool_call_count(monkeypatch):
    _, summary, _ = await mock_images(monkeypatch, "four")
    assert summary["http_request_count"] == 1 and summary["returned_count"] == 4
    assert summary["image_generation_tool_call_count"] is None


async def test_responses_mock_separately_observes_one_http_four_tools_four_images(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.path == "/v1/responses"
        return httpx.Response(200, json={"id": "mock-response", "model": "mock-controller", "status": "completed",
            "output": [{"id": f"tool-{i}", "type": "image_generation_call", "status": "completed",
                        "result": base64.b64encode(png(i)).decode()} for i in range(4)]})
    install_http(monkeypatch, handler)
    result = await OpenAIResponsesImageProvider(SETTINGS).execute(
        base_url="https://mock-relay.invalid/v1", api_key="mock-not-a-real-key",
        upstream_model="mock-controller", capability="image_edit", payload=inputs()[0],
        config={"responses_multi_output_enabled": True},
    )
    summary = probe.observe(result, SETTINGS)
    assert len(requests) == summary["http_request_count"] == 1
    assert summary["image_generation_tool_call_count"] == summary["returned_count"] == 4


def test_duplicate_outputs_remain_independent_evidence_not_four_distinct_products():
    outputs = [ProviderOutput(png(), "image/png", f"{i}.png") for i in range(4)]
    summary = probe.observe(ProviderResult(outputs), SETTINGS)
    assert summary["returned_count"] == 4 and summary["group_status"] == "partial"
    assert "duplicate_image" in summary["anomalies"]


class MemoryS3Client:
    """Mock boto3 client; actual app S3StorageService performs every S3 operation."""
    def __init__(self):
        self.objects = {}
        self.upload_count = 0
        self.fail_upload_number = None

    def upload_fileobj(self, body, bucket, key, ExtraArgs):
        self.upload_count += 1
        if self.upload_count == self.fail_upload_number:
            raise OSError("synthetic S3 upload failure")
        self.objects[bucket, key] = (body.read(), deepcopy(ExtraArgs))

    def get_object(self, *, Bucket, Key):
        return {"Body": BytesIO(self.objects[Bucket, Key][0])}

    def head_object(self, *, Bucket, Key):
        data, options = self.objects[Bucket, Key]
        return {"ContentLength": len(data), "ContentType": options["ContentType"],
                "Metadata": options.get("Metadata", {}), "ETag": '"mock-etag"'}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        return f"https://s3.invalid/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"


async def create_request_group(context, storage):
    async with context["session_factory"]() as session:
        user = await session.scalar(select(User).where(User.account == "first-admin"))
        async def asset(category, index):
            return await create_asset(session, storage, SETTINGS, organization_id=context["first_org"],
                user_id=user.id, category=category, filename=f"fixture-{index}.png",
                declared_mime="image/png", data=png(index))
        template = await asset("model_template", 0)
        garments = [await asset("garment", i) for i in range(1, 5)]
        payload, manifest, collage = probe.build_input(
            {"asset_id": template.id, "filename": template.filename, "content": png()},
            [{"asset_id": g.id, "filename": g.filename, "content": png(i)} for i, g in enumerate(garments, 1)],
        )
        collage_asset = await create_asset(session, storage, SETTINGS, organization_id=context["first_org"],
            user_id=user.id, category="garment_reference", filename="garment-collage.png",
            declared_mime="image/png", data=collage,
            metadata_json={"asset_role": "strategy_a_collage", "source_manifest": manifest})
        reservation = await reserve_quota(session, SETTINGS, organization_id=context["first_org"], user_id=user.id,
            operation_code="batch_tryon.generate", quantity=4, factors={}, idempotency_key="mock-a-reservation")
        # ORM-only fixture, not a successful POST /jobs(n=4). That API remains blocked.
        job = Job(organization_id=context["first_org"], created_by=user.id, updated_by=user.id,
            operation_code="batch_tryon.generate", workspace_type="batch_tryon", queue_name="batch_tryon_queue",
            capability="image_edit", model_code="mock-image-model", status="running",
            quota_reservation_id=reservation.id, max_attempts=1, idempotency_key="mock-a-job",
            request_hash="f" * 64, input_json={"n": 4, "prompt": payload["prompt"],
                "reference_asset_ids": [template.id, collage_asset.id], "metadata": {"strategy_a": {
                    "schema_version": 1, "source_manifest": manifest, "collage_asset_id": collage_asset.id,
                    "mock_only": True, "auto_retry_allowed": False,
                }}})
        session.add(job)
        await session.commit()
        return job.id, payload, manifest, collage


@pytest.mark.parametrize("mode,expected_saved,sequences", [
    ("four", 4, [0, 1, 2, 3]), ("one", 1, [0]), ("corrupt", 3, [0, 2, 3]),
    ("five", 5, [0, 1, 2, 3, 4]),
])
async def test_actual_models_s3_service_api_download_and_raw_export(
    identity_test_context, monkeypatch, mode, expected_saved, sequences,
):
    context = identity_test_context
    s3 = MemoryS3Client()
    storage = S3StorageService(SETTINGS, client=s3)
    context["app"].dependency_overrides[get_storage_service] = lambda: storage
    job_id, payload, manifest, collage = await create_request_group(context, storage)
    result, observation, requests = await mock_images(monkeypatch, mode, payload)
    assert len(requests) == 1
    async with context["session_factory"]() as session:
        job = await session.get(Job, job_id)
        summary = await probe.persist_mock_outputs(session, storage, SETTINGS, job=job, result=result, observation=observation)
        assert summary["saved_count"] == expected_saved
        assert await session.scalar(select(func.count()).select_from(Job)) == 1
        assert await session.scalar(select(func.count()).select_from(BatchTryOnVersion)) == 0
        assert await session.scalar(select(func.count()).select_from(BatchTryOnReviewItem)) == 0
        rows = list((await session.scalars(select(GeneratedOutput).where(GeneratedOutput.job_id == job_id)
            .order_by(GeneratedOutput.sequence_number))).all())
        assert [row.sequence_number for row in rows] == sequences
        assert len({row.asset_id for row in rows}) == expected_saved
    client = context["client"]
    headers = await auth_headers(client, "first-admin", "correct-password")
    response = await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert response.status_code == 200
    persisted_group = response.json()["result_json"]["metadata"]["strategy_a"]
    assert persisted_group["returned_count"] == observation["returned_count"]
    assert persisted_group["saved_count"] == expected_saved
    assert persisted_group["group_status"] == observation["group_status"]
    assert persisted_group["image_generation_tool_call_count"] is None
    outputs = response.json()["outputs"]
    assert len(outputs) == expected_saved
    for output in outputs:
        index = output["sequence_number"]
        download = await client.get(output["download_url"], headers=headers)
        assert download.status_code == 200 and download.content == png(index)
        assert (output["width"], output["height"]) == (71 + index * 7, 97 + index * 11)
        assert sha256(download.content).hexdigest() == sha256(result.outputs[index].content).hexdigest()
        assert download.headers["content-disposition"].startswith("attachment;")
    other = await auth_headers(client, "second-admin", "second-password")
    assert (await client.get(f"/api/v1/jobs/{job_id}", headers=other)).status_code == 404
    assert (await client.get(outputs[0]["download_url"], headers=other)).status_code == 404
    with ZipFile(BytesIO(probe.export_raw_results(storage, summary, manifest, collage))) as archive:
        assert archive.read("source/garment-collage.png") == collage
        restored = json.loads(archive.read("source/manifest.json"))
        assert restored["panels"] == manifest["panels"] and len(restored["panels"]) == 4
        for index in sequences:
            assert archive.read(f"outputs/output-{index:03d}.png") == png(index)
        if mode == "corrupt":
            assert archive.read("quarantine/output-001.bin") == b"corrupt image fixture"
    assert all(bucket == "strategy-a-test-only" for bucket, _ in s3.objects)


async def test_s3_failure_preserves_completed_outputs_and_replay_does_not_regenerate(identity_test_context, monkeypatch):
    context = identity_test_context
    s3 = MemoryS3Client()
    storage = S3StorageService(SETTINGS, client=s3)
    job_id, payload, _, _ = await create_request_group(context, storage)
    result, observation, requests = await mock_images(monkeypatch, "four", payload)
    s3.fail_upload_number = s3.upload_count + 2
    async with context["session_factory"]() as session:
        job = await session.get(Job, job_id)
        partial = await probe.persist_mock_outputs(session, storage, SETTINGS, job=job, result=result, observation=observation)
        assert partial["saved_count"] == 3 and "storage_save_failed" in partial["anomalies"]
        saved_ids = {e["sequence_number"]: e["asset_id"] for e in partial["entries"] if "asset_id" in e}
        recovered = await probe.persist_mock_outputs(session, storage, SETTINGS, job=job, result=result, observation=observation)
        assert recovered["saved_count"] == 4
        assert len(requests) == 1  # replay persisted bytes, never repeat the upstream request
        for entry in recovered["entries"]:
            if entry["sequence_number"] in saved_ids:
                assert entry["asset_id"] == saved_ids[entry["sequence_number"]]
        assert await session.scalar(select(func.count()).select_from(GeneratedOutput)) == 4


@pytest.mark.parametrize("accepted,consume,release", [(4, 40, 0), (1, 10, 30), (3, 30, 10), (0, 0, 40)])
async def test_existing_quota_supports_four_reserved_and_partial_settlement(
    identity_test_context, accepted, consume, release,
):
    context = identity_test_context
    async with context["session_factory"]() as session:
        user = await session.scalar(select(User).where(User.account == "first-admin"))
        reservation = await reserve_quota(session, SETTINGS, organization_id=context["first_org"], user_id=user.id,
            operation_code="batch_tryon.generate", quantity=4, factors={}, idempotency_key="mock-a-billing")
        await settle_reservation(session, organization_id=context["first_org"], reservation_id=reservation.id,
            user_id=user.id, actual_quantity=accepted, idempotency_key="mock-a-confirmed-settlement")
        await settle_reservation(session, organization_id=context["first_org"], reservation_id=reservation.id,
            user_id=user.id, actual_quantity=accepted, idempotency_key="mock-a-confirmed-settlement")
        account = await session.scalar(select(QuotaAccount).where(QuotaAccount.organization_id == context["first_org"]))
        assert account.balance == 1000 - consume and account.reserved_balance == 0
        assert reservation.consumed_amount == consume and reservation.released_amount == release


async def test_remote_unknown_does_not_infer_zero_cost_or_release_reservation(identity_test_context, monkeypatch):
    context = identity_test_context
    _, observation, requests = await mock_images(monkeypatch, "524")
    async with context["session_factory"]() as session:
        user = await session.scalar(select(User).where(User.account == "first-admin"))
        reservation = await reserve_quota(session, SETTINGS, organization_id=context["first_org"], user_id=user.id,
            operation_code="batch_tryon.generate", quantity=4, factors={}, idempotency_key="mock-a-unknown-cost")
        account = await session.scalar(select(QuotaAccount).where(QuotaAccount.organization_id == context["first_org"]))
        assert observation["group_status"] == "remote_unknown" and len(requests) == 1
        assert reservation.status == "reserved" and account.reserved_balance == 40 and account.balance == 1000
        assert observation["upstream_actual_cost"] is None


async def test_existing_resource_lease_counts_requests_not_output_images(identity_test_context, monkeypatch):
    context = identity_test_context
    _, model_code, _, key_ids = await seed_pool(
        context, capability="image_edit", max_concurrency=1, operation_code="batch_tryon.generate",
    )
    async with context["session_factory"]() as session:
        lease = await acquire_resource(session, context["redis"], SETTINGS,
            organization_id=context["first_org"], operation_code="batch_tryon.generate",
            model_code=model_code, capability="image_edit")
        try:
            _, observation, requests = await mock_images(monkeypatch, "four")
            assert observation["returned_count"] == 4 and len(requests) == 1
            assert await context["redis"].get(f"resource:key:{key_ids[0]}:inflight") == 1
            with pytest.raises(AppError, match="没有可用"):
                await acquire_resource(session, context["redis"], SETTINGS,
                    organization_id=context["first_org"], operation_code="batch_tryon.generate",
                    model_code=model_code, capability="image_edit")
        finally:
            await release_resource(context["redis"], lease)
        assert await context["redis"].get(f"resource:key:{key_ids[0]}:inflight") is None
