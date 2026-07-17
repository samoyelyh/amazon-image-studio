import base64
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.models.quota import QuotaAccount, QuotaReservation
from app.models.tasks import ApiKey, BatchStatus, Job, JobBatch, JobStatus, ModelCapability, Provider, ProviderModel, ResourcePool, ResourcePoolKey
from app.providers.base import ProviderError, ProviderOutput, ProviderResult
from app.schemas.tasks import JobSubmitRequest
from app.services.resource_pool_service import (
    acquire_resource, cool_down_key, create_api_key, release_resource,
)
from app.services.billing_service import settle_reservation
from app.services.task_service import claim_job, recover_stale_jobs, refresh_batch_status, schedule_retry_or_fail, submit_job


async def auth_headers(client, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def seed_pool(context, *, key_values=("relay-key-one",), capability="image_generation", max_concurrency=1):
    settings = Settings(_env_file=None)
    async with context["session_factory"]() as session:
        provider = Provider(code=f"provider-{len(key_values)}-{capability}", name="Relay", provider_type="openai_compatible",
                            base_url="https://relay.example/v1", config_json={})
        session.add(provider)
        await session.flush()
        model = ProviderModel(provider_id=provider.id, code=f"test-model-{len(key_values)}-{capability}",
                              upstream_model="image-model", name="Image Model", config_json={})
        session.add(model)
        await session.flush()
        session.add(ModelCapability(model_id=model.id, capability=capability))
        pool = ResourcePool(model_id=model.id, code=f"pool-{len(key_values)}-{capability}", name="Pool")
        session.add(pool)
        await session.flush()
        keys = []
        for index, secret in enumerate(key_values):
            key = create_api_key(settings, provider_id=provider.id, label=f"Key {index}", secret=secret,
                                 organization_id=None, max_concurrency=max_concurrency,
                                 rpm_limit=None, daily_limit=None, user_id=None)
            session.add(key)
            await session.flush()
            session.add(ResourcePoolKey(resource_pool_id=pool.id, api_key_id=key.id, priority=index))
            keys.append(key)
        await session.commit()
        return provider.id, model.code, pool.id, [key.id for key in keys]


async def test_platform_key_is_encrypted_masked_and_never_returned(identity_test_context) -> None:
    client = identity_test_context["client"]
    headers = await auth_headers(client, "platform-admin@example.com", "platform-password")
    provider = await client.post("/api/v1/resource-pools/providers", headers=headers, json={
        "code": "newapi", "name": "Relay", "provider_type": "new_api", "base_url": "https://relay.example/v1",
    })
    assert provider.status_code == 201, provider.text
    secret = "sk-super-secret-relay-value"
    created = await client.post("/api/v1/resource-pools/keys", headers=headers, json={
        "provider_id": provider.json()["id"], "label": "Main relay", "secret": secret, "max_concurrency": 2,
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["masked_secret"] == "****alue"
    assert secret not in created.text
    listed = await client.get("/api/v1/resource-pools/keys", headers=headers)
    assert secret not in listed.text
    async with identity_test_context["session_factory"]() as session:
        key = await session.get(ApiKey, body["id"])
        assert secret not in key.secret_ciphertext


async def test_credentials_are_rejected_from_provider_config_and_job_input(identity_test_context) -> None:
    client = identity_test_context["client"]
    platform = await auth_headers(client, "platform-admin@example.com", "platform-password")
    provider = await client.post("/api/v1/resource-pools/providers", headers=platform, json={
        "code": "unsafe", "name": "Unsafe", "provider_type": "new_api", "base_url": "https://relay.example/v1",
        "config": {"api_key": "must-not-be-here"},
    })
    assert provider.status_code == 422
    first = await auth_headers(client, "first-admin@example.com", "correct-password")
    job = await client.post("/api/v1/jobs", headers=first, json={
        "operation_code": "listing.generate", "workspace_type": "listing", "queue_name": "listing_queue",
        "capability": "image_generation", "model_code": "standard", "idempotency_key": "unsafe-job-001",
        "input": {"prompt": "test", "nested": {"token": "must-not-be-here"}},
    })
    assert job.status_code == 422

    wrong_operation = await client.post("/api/v1/jobs", headers=first, json={
        "operation_code": "listing.plan", "workspace_type": "listing", "queue_name": "listing_queue",
        "capability": "image_generation", "model_code": "standard", "idempotency_key": "unsafe-job-002",
        "input": {"prompt": "test"},
    })
    assert wrong_operation.status_code == 422

    multiple = await client.post("/api/v1/jobs", headers=first, json={
        "operation_code": "listing.generate", "workspace_type": "listing", "queue_name": "listing_queue",
        "capability": "image_generation", "model_code": "standard", "idempotency_key": "unsafe-job-003",
        "input": {"prompt": "test", "n": 2},
    })
    assert multiple.status_code == 422


async def test_resource_pool_enforces_capability_concurrency_and_cooldown(identity_test_context) -> None:
    _, model_code, _, key_ids = await seed_pool(identity_test_context)
    settings = Settings(_env_file=None)
    async with identity_test_context["session_factory"]() as session:
        first = await acquire_resource(session, identity_test_context["redis"], settings,
            organization_id=identity_test_context["first_org"], model_code=model_code, capability="image_generation")
        assert first.api_key == "relay-key-one"
        with pytest.raises(AppError, match="No API key") as unavailable:
            await acquire_resource(session, identity_test_context["redis"], settings,
                organization_id=identity_test_context["first_org"], model_code=model_code, capability="image_generation")
        assert unavailable.value.code == "resource_pool.no_available_key"
        await release_resource(identity_test_context["redis"], first)
        with pytest.raises(AppError) as mismatch:
            await acquire_resource(session, identity_test_context["redis"], settings,
                organization_id=identity_test_context["first_org"], model_code=model_code, capability="image_edit")
        assert mismatch.value.code == "resource_pool.no_available_key"
        await cool_down_key(session, identity_test_context["redis"], settings, key_ids[0], seconds=60)
        with pytest.raises(AppError):
            await acquire_resource(session, identity_test_context["redis"], settings,
                organization_id=identity_test_context["first_org"], model_code=model_code, capability="image_generation")


async def test_job_submission_is_idempotent_tenant_scoped_and_cancel_refunds(identity_test_context, monkeypatch) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    first = await auth_headers(client, "first-admin@example.com", "correct-password")
    payload = {
        "operation_code": "listing.generate", "workspace_type": "listing", "queue_name": "listing_queue",
        "capability": "image_generation", "model_code": "standard", "idempotency_key": "job-submit-001",
        "input": {"prompt": "A product on white background"},
        "billing_factors": {"model": "free-model", "resource_pool": "personal"},
    }
    created = await client.post("/api/v1/jobs", headers=first, json=payload)
    assert created.status_code == 202, created.text
    repeated = await client.post("/api/v1/jobs", headers=first, json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["id"] == created.json()["id"]
    second = await auth_headers(client, "second-admin@example.com", "second-password")
    assert (await client.get(f"/api/v1/jobs/{created.json()['id']}", headers=second)).status_code == 404
    cancelled = await client.post(f"/api/v1/jobs/{created.json()['id']}/cancel", headers=first)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    async with identity_test_context["session_factory"]() as session:
        account = await session.scalar(select(QuotaAccount).where(QuotaAccount.organization_id == identity_test_context["first_org"]))
        assert account.balance == 1000 and account.reserved_balance == 0
        reservations = list((await session.scalars(select(QuotaReservation).where(
            QuotaReservation.organization_id == identity_test_context["first_org"]))).all())
        assert len(reservations) == 1 and reservations[0].status == "released"
        assert reservations[0].unit_cost == 10
        assert reservations[0].factors_json["model"] == "standard"
        assert reservations[0].factors_json["resource_pool"] == "platform"


async def test_batch_split_concurrency_partial_settlement_and_refresh_recovery(identity_test_context, monkeypatch) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    headers = await auth_headers(client, "first-admin@example.com", "correct-password")
    payload = {
        "name": "Listing batch", "workspace_type": "listing", "operation_code": "listing.generate",
        "capability": "image_generation", "model_code": "standard", "idempotency_key": "listing-batch-001",
        "concurrency": 1,
        "items": [
            {"client_item_id": "slot-1", "prompt": "First image", "reference_asset_ids": [], "size": "1024x1024", "output_format": "png"},
            {"client_item_id": "slot-2", "prompt": "Second image", "reference_asset_ids": [], "size": "1024x1024", "output_format": "png"},
        ],
    }
    created = await client.post("/api/v1/job-batches", headers=headers, json=payload)
    assert created.status_code == 202, created.text
    repeated = await client.post("/api/v1/job-batches", headers=headers, json=payload)
    assert repeated.status_code == 200 and repeated.json()["id"] == created.json()["id"]
    batch_id = created.json()["id"]
    job_ids = [item["id"] for item in created.json()["jobs"]]

    settings = Settings(_env_file=None)
    async with identity_test_context["session_factory"]() as session:
        first = await claim_job(session, settings, job_ids[0])
        assert first is not None
        await session.commit()
    async with identity_test_context["session_factory"]() as session:
        assert await claim_job(session, settings, job_ids[1]) is None
        deferred = await session.get(Job, job_ids[1])
        assert deferred.status == JobStatus.QUEUED.value and deferred.dispatched_at is None
        await session.commit()

    async with identity_test_context["session_factory"]() as session:
        first = await session.get(Job, job_ids[0], with_for_update=True)
        first.status = JobStatus.SUCCEEDED.value
        first.progress = 100
        await settle_reservation(
            session, organization_id=first.organization_id, reservation_id=first.quota_reservation_id,
            user_id=first.updated_by, actual_quantity=1, idempotency_key=f"test-success:{first.id}",
        )
        second = await session.get(Job, job_ids[1], with_for_update=True)
        second.attempts = second.max_attempts
        await schedule_retry_or_fail(session, second, code="provider.failed", message="upstream failed")
        batch = await refresh_batch_status(session, batch_id)
        await session.commit()
        assert batch.status == BatchStatus.PARTIALLY_SUCCEEDED.value

    detail = await client.get(f"/api/v1/job-batches/{batch_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "partially_succeeded"
    assert detail.json()["succeeded_jobs"] == 1 and detail.json()["failed_jobs"] == 1
    async with identity_test_context["session_factory"]() as session:
        account = await session.scalar(select(QuotaAccount).where(QuotaAccount.organization_id == identity_test_context["first_org"]))
        assert account.balance == 990 and account.reserved_balance == 0


async def test_duplicate_worker_claim_and_stale_recovery_are_idempotent(identity_test_context) -> None:
    settings = Settings(_env_file=None, job_heartbeat_timeout_seconds=10)
    from app.models.identity import User
    payload = JobSubmitRequest(
        operation_code="listing.generate", workspace_type="listing", queue_name="listing_queue",
        capability="image_generation", model_code="standard", idempotency_key="worker-claim-001",
        input={"prompt": "test"},
    )
    async with identity_test_context["session_factory"]() as session:
        user_id = await session.scalar(select(User.id).where(User.email == "first-admin@example.com"))
        job, _ = await submit_job(session, settings, organization_id=identity_test_context["first_org"],
                                  user_id=user_id, payload=payload)
        await session.commit()
        job_id = job.id
    async with identity_test_context["session_factory"]() as session:
        claimed = await claim_job(session, settings, job_id)
        assert claimed is not None
        await session.commit()
    async with identity_test_context["session_factory"]() as session:
        assert await claim_job(session, settings, job_id) is None
        stored = await session.get(Job, job_id)
        stored.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        await session.commit()
    async with identity_test_context["session_factory"]() as session:
        assert await recover_stale_jobs(session, settings) == 1
        await session.commit()
        recovered = await session.get(Job, job_id)
        assert recovered.status == JobStatus.RETRY_WAITING.value


async def test_429_cools_key_and_fails_over_to_next_key(identity_test_context, monkeypatch) -> None:
    _, model_code, _, key_ids = await seed_pool(identity_test_context, key_values=("relay-key-first", "relay-key-second"))
    settings = Settings(_env_file=None)
    from app.models.identity import User
    async with identity_test_context["session_factory"]() as session:
        user_id = await session.scalar(select(User.id).where(User.email == "first-admin@example.com"))
        job, _ = await submit_job(session, settings, organization_id=identity_test_context["first_org"], user_id=user_id,
            payload=JobSubmitRequest(operation_code="listing.generate", workspace_type="listing", queue_name="listing_queue",
                capability="image_generation", model_code=model_code, idempotency_key="failover-429-001",
                input={"prompt": "test"}))
        await session.commit()
        job_id = job.id

    class FailoverAdapter:
        async def execute(self, **kwargs):
            if kwargs["api_key"] == "relay-key-first":
                raise ProviderError("provider.rate_limited", "rate limited", http_status=429, retryable=True)
            image_bytes = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
            return ProviderResult([ProviderOutput(image_bytes, "image/png", "result.png")], "req-2")

    monkeypatch.setattr("app.workers.tasks.jobs.get_engine", lambda: identity_test_context["engine"])
    monkeypatch.setattr("app.workers.tasks.jobs.get_redis_client", lambda: identity_test_context["redis"])
    monkeypatch.setattr("app.workers.tasks.jobs.get_storage_service", lambda: identity_test_context["storage"])
    monkeypatch.setattr("app.workers.tasks.jobs.get_provider_adapter", lambda *args: FailoverAdapter())
    from app.workers.tasks.jobs import _execute_job
    result = await _execute_job(job_id)
    assert result["status"] == "succeeded"
    async with identity_test_context["session_factory"]() as session:
        job = await session.get(Job, job_id)
        first = await session.get(ApiKey, key_ids[0])
        assert job.status == "succeeded" and job.selected_key_id == key_ids[1]
        assert first.status == "cooling" and first.consecutive_failures == 1
        account = await session.scalar(select(QuotaAccount).where(QuotaAccount.organization_id == identity_test_context["first_org"]))
        assert account.balance == 990 and account.reserved_balance == 0
    assert not any(key.endswith(":inflight") and value for key, value in identity_test_context["redis"].values.items())
