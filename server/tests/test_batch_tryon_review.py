from base64 import b64decode
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.models.content import Asset, GeneratedOutput
from app.models.quota import QuotaAccount
from app.models.tasks import (
    BatchTryOnReviewItem,
    BatchTryOnVersion,
    Job,
    ModelCapability,
    OperationResourcePool,
    Provider,
    ProviderModel,
    ResourcePool,
)
from app.services.batch_tryon_review_service import (
    append_batch_try_on_review_requirements,
    sync_batch_try_on_version_for_job,
)


PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


async def auth_headers(client, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def upload_asset(client, headers, category: str, filename: str) -> dict:
    response = await client.post(
        "/api/v1/assets",
        headers=headers,
        data={"category": category},
        files={"file": (filename, PNG, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def seed_batch_try_on_pool(context) -> str:
    async with context["session_factory"]() as session:
        provider = Provider(
            code="review-provider", name="Review provider", provider_type="openai_compatible",
            base_url="https://relay.example/v1", config_json={},
        )
        session.add(provider)
        await session.flush()
        model = ProviderModel(
            provider_id=provider.id, code="review-image-model", upstream_model="image-2",
            name="Review image model", config_json={},
        )
        session.add(model)
        await session.flush()
        session.add(ModelCapability(model_id=model.id, capability="image_edit"))
        pool = ResourcePool(model_id=model.id, code="review-pool", name="Review pool")
        session.add(pool)
        await session.flush()
        session.add(OperationResourcePool(
            operation_code="batch_tryon.generate",
            resource_pool_id=pool.id,
            required_capability="image_edit",
            priority=100,
        ))
        await session.commit()
        return model.code


def test_review_notes_are_additive_and_optional() -> None:
    base = "MANDATORY BASE PROMPT\nKeep garment fidelity."
    assert append_batch_try_on_review_requirements(base, None) == base
    prompt = append_batch_try_on_review_requirements(base, "Keep 06 with its leading zero.")
    assert prompt.startswith(base)
    assert "REVIEW CORRECTION REQUIREMENTS:" in prompt
    assert "Keep 06 with its leading zero." in prompt
    assert "must not replace or weaken" in prompt


async def test_batch_try_on_review_approve_regenerate_versions_and_tenant_permissions(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    admin = await auth_headers(client, "first-admin@example.com", "correct-password")
    viewer = await auth_headers(client, "first-viewer@example.com", "viewer-password")
    second = await auth_headers(client, "second-admin@example.com", "second-password")
    model_code = await seed_batch_try_on_pool(identity_test_context)
    model = await upload_asset(client, admin, "model_template", "model.png")
    garment = await upload_asset(client, admin, "garment", "jersey-06.png")

    submitted = await client.post("/api/v1/job-batches", headers=admin, json={
        "name": "Review batch",
        "workspace_type": "batch_tryon",
        "operation_code": "batch_tryon.generate",
        "capability": "image_edit",
        "model_code": model_code,
        "idempotency_key": "batch-review-submit-001",
        "concurrency": 2,
        "items": [{
            "client_item_id": "browser-item-001",
            "prompt": "BASE TRY-ON PROMPT",
            "reference_asset_ids": [model["id"], garment["id"]],
            "size": "1024x1024",
            "aspect_ratio": "1:1",
            "output_format": "png",
            "metadata": {"garment_filename": "jersey-06.png", "index": 0},
        }],
    })
    assert submitted.status_code == 202, submitted.text
    job_body = submitted.json()["jobs"][0]
    item_id = job_body["review_item_id"]
    assert item_id and job_body["current_version_id"]

    initial = await client.get(f"/api/v1/batch-tryon/items/{item_id}/review-detail", headers=admin)
    assert initial.status_code == 200, initial.text
    assert initial.json()["garment_asset"]["id"] == garment["id"]
    assert initial.json()["model_asset"]["id"] == model["id"]
    assert initial.json()["current_version"]["version_number"] == 1
    assert (await client.get(f"/api/v1/batch-tryon/items/{item_id}/review-detail", headers=viewer)).status_code == 200
    assert (await client.get(f"/api/v1/batch-tryon/items/{item_id}/review-detail", headers=second)).status_code == 404

    output = await upload_asset(client, admin, "batch_tryon_output", "result-v1.png")
    async with identity_test_context["session_factory"]() as session:
        job = await session.get(Job, job_body["id"], with_for_update=True)
        job.status = "succeeded"
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        session.add(GeneratedOutput(
            organization_id=job.organization_id,
            project_id=None,
            project_version_id=None,
            asset_id=output["id"],
            job_id=job.id,
            batch_id=job.batch_id,
            sequence_number=0,
            output_type="batch_tryon_output",
            module_key=None,
            metadata_json={"client_item_id": job.client_item_id},
            created_by=job.created_by,
            created_at=datetime.now(timezone.utc),
        ))
        await sync_batch_try_on_version_for_job(session, job, generated_asset_id=output["id"])
        await session.commit()

    pending = (await client.get(f"/api/v1/batch-tryon/items/{item_id}/review-detail", headers=admin)).json()
    version_v1 = pending["current_version"]
    assert pending["review_status"] == "pending"
    assert version_v1["generated_asset"]["id"] == output["id"]

    denied = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/approve",
        headers=viewer,
        json={"source_version_id": version_v1["id"]},
    )
    assert denied.status_code == 403
    approved = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/approve",
        headers=admin,
        json={"source_version_id": version_v1["id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["review_status"] == "approved"
    assert approved.json()["approved_version_id"] == version_v1["id"]

    async with identity_test_context["session_factory"]() as session:
        account = await session.scalar(select(QuotaAccount).where(
            QuotaAccount.organization_id == identity_test_context["first_org"]
        ))
        original_balance = account.balance
        account.balance = account.reserved_balance
        await session.commit()
    insufficient = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/regenerate",
        headers=admin,
        json={
            "source_version_id": version_v1["id"],
            "retry_mode": "direct",
            "review_notes": None,
            "idempotency_key": "review-insufficient-001",
        },
    )
    assert insufficient.status_code == 402
    async with identity_test_context["session_factory"]() as session:
        assert int(await session.scalar(select(func.count()).select_from(BatchTryOnVersion).where(
            BatchTryOnVersion.item_id == item_id
        )) or 0) == 1
        account = await session.scalar(select(QuotaAccount).where(
            QuotaAccount.organization_id == identity_test_context["first_org"]
        ))
        account.balance = original_balance
        await session.commit()

    regeneration_payload = {
        "source_version_id": version_v1["id"],
        "retry_mode": "with_review_notes",
        "review_notes": "胸前数字必须保持为06，不得丢失前置0。",
        "idempotency_key": "review-regenerate-001",
    }
    regenerated = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/regenerate",
        headers=admin,
        json=regeneration_payload,
    )
    assert regenerated.status_code == 202, regenerated.text
    regenerated_body = regenerated.json()
    assert regenerated_body["review"]["review_status"] == "regenerating"
    assert regenerated_body["review"]["regeneration_count"] == 1
    assert len(regenerated_body["review"]["versions"]) == 2
    assert regenerated_body["review"]["versions"][1]["generated_asset"]["id"] == output["id"]

    replay = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/regenerate",
        headers=admin,
        json=regeneration_payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["job"]["id"] == regenerated_body["job"]["id"]
    assert len(replay.json()["review"]["versions"]) == 2

    async with identity_test_context["session_factory"]() as session:
        item = await session.get(BatchTryOnReviewItem, item_id)
        versions = list((await session.scalars(
            select(BatchTryOnVersion).where(BatchTryOnVersion.item_id == item_id)
            .order_by(BatchTryOnVersion.version_number)
        )).all())
        assert item.current_version_id == versions[1].id
        assert versions[0].generated_asset_id == output["id"]
        assert versions[0].review_status == "rejected"
        assert versions[1].generated_asset_id is None
        assert versions[1].prompt_snapshot.startswith("BASE TRY-ON PROMPT")
        assert "REVIEW CORRECTION REQUIREMENTS:" in versions[1].prompt_snapshot
        assert "胸前数字必须保持为06" in versions[1].prompt_snapshot
        assert await session.get(Asset, output["id"]) is not None
