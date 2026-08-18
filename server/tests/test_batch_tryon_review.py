from base64 import b64decode
from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZipFile

from sqlalchemy import func, select

from app.models.content import Asset, GeneratedOutput
from app.models.quota import QuotaAccount, QuotaReservation
from app.models.tasks import (
    BatchTryOnReviewItem,
    BatchTryOnVersion,
    Job,
    JobBatch,
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
from app.schemas.batch_tryon_review import (
    BatchTryOnBatchRegenerateRequest,
    BatchTryOnRegionReplaceRequest,
    BatchTryOnRegenerateRequest,
)
from app.services.batch_tryon_review_service import compose_region_replace_prompt
from app.services.batch_tryon_prompt_template_service import prompt_analysis_preset_only
from app.schemas.tasks import JobSubmitRequest


PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def test_detailed_prompt_legacy_wrappers_are_removed_without_changing_preset() -> None:
    preset = "这是用户维护的系统预设。\n只按这里的规则分析并返回中文结果。"
    legacy = (
        preset
        + "\n\n精细逐图分析要求：图A是当前组合的模板图，图B是当前组合的服装图。"
        + "\n\nREFERENCE IMAGE ORDER:\nReference Image B is the garment."
    )

    assert prompt_analysis_preset_only(legacy) == preset
    assert prompt_analysis_preset_only(preset) == preset


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
        luna_model = ProviderModel(
            provider_id=provider.id, code="review-luna-model", upstream_model="gpt-5.6-luna",
            name="Review Luna model", config_json={},
        )
        session.add(luna_model)
        await session.flush()
        session.add_all([
            ModelCapability(model_id=model.id, capability="image_edit"),
            ModelCapability(model_id=model.id, capability="mask_edit"),
            ModelCapability(model_id=luna_model.id, capability="text_generation"),
            ModelCapability(model_id=luna_model.id, capability="vision_input"),
        ])
        pool = ResourcePool(model_id=model.id, code="review-pool", name="Review pool")
        session.add(pool)
        await session.flush()
        luna_pool = ResourcePool(model_id=luna_model.id, code="review-luna-pool", name="Review Luna pool")
        session.add(luna_pool)
        await session.flush()
        session.add(OperationResourcePool(
            operation_code="batch_tryon.generate",
            resource_pool_id=pool.id,
            required_capability="image_edit",
            priority=100,
        ))
        session.add(OperationResourcePool(
            operation_code="batch_tryon.prompt_analyze_detailed",
            resource_pool_id=luna_pool.id,
            required_capability="text_generation",
            priority=100,
        ))
        session.add(OperationResourcePool(
            operation_code="batch_tryon.region_replace",
            resource_pool_id=pool.id,
            required_capability="mask_edit",
            priority=100,
        ))
        await session.commit()
        return model.code


def test_region_replace_job_contract_requires_mask_and_dedicated_operation() -> None:
    payload = JobSubmitRequest(
        operation_code="batch_tryon.region_replace",
        workspace_type="batch_tryon",
        queue_name="batch_tryon_queue",
        capability="mask_edit",
        model_code="image-model",
        idempotency_key="region-replace-contract",
        input={
            "prompt": "Edit only the selected number.",
            "reference_asset_ids": ["base-output", "reference-patch"],
            "mask_asset_id": "target-mask",
            "size": "1024x1024",
            "aspect_ratio": "1:1",
        },
    )

    assert payload.operation_code == "batch_tryon.region_replace"
    assert payload.capability == "mask_edit"
    assert payload.input["mask_asset_id"] == "target-mask"
    assert payload.input["reference_asset_ids"] == ["base-output", "reference-patch"]


def test_region_replace_prompt_protects_unmasked_content() -> None:
    prompt = compose_region_replace_prompt("Use number 06 from Image C.", "back_number")

    assert "Preserve every unmasked area" in prompt
    assert "one indivisible product-surface structure" in prompt
    assert "Do not semantically reinterpret" in prompt
    assert "back number print" in prompt
    assert "Use number 06 from Image C." in prompt


def test_region_replace_request_keeps_mask_and_patch_roles_separate() -> None:
    payload = BatchTryOnRegionReplaceRequest(
        source_version_id="source-version",
        target_mask_asset_id="target-mask",
        image_c_asset_id="image-c",
        source_reference_mask_asset_id="source-mask",
        reference_patch_asset_id="reference-patch",
        edit_region_type="back_number",
        edit_prompt="Transfer the selected number only.",
        target_mask_metadata={"mask_semantics": "transparent_is_editable"},
        source_reference_metadata={"normalized_bounds": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}},
        idempotency_key="region-role-separation",
    )

    assert payload.target_mask_asset_id != payload.source_reference_mask_asset_id
    assert payload.reference_patch_asset_id != payload.source_reference_mask_asset_id


async def test_region_replace_stays_candidate_until_dedicated_approval(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    admin = await auth_headers(client, "first-admin@example.com", "correct-password")
    model_code = await seed_batch_try_on_pool(identity_test_context)
    model = await upload_asset(client, admin, "model_template", "model.png")
    garment = await upload_asset(client, admin, "garment", "jersey-06.png")
    submitted = await client.post("/api/v1/job-batches", headers=admin, json={
        "name": "Region candidate batch",
        "workspace_type": "batch_tryon",
        "operation_code": "batch_tryon.generate",
        "capability": "image_edit",
        "model_code": model_code,
        "idempotency_key": "region-candidate-batch-001",
        "concurrency": 1,
        "items": [{
            "client_item_id": "region-candidate-item",
            "prompt": "BASE TRY-ON PROMPT",
            "reference_asset_ids": [model["id"], garment["id"]],
            "size": "1024x1024",
            "aspect_ratio": "1:1",
            "output_format": "png",
            "metadata": {"garment_filename": "jersey-06.png", "index": 0},
        }],
    })
    assert submitted.status_code == 202, submitted.text
    original_job = submitted.json()["jobs"][0]
    item_id = original_job["review_item_id"]
    original_version_id = original_job["current_version_id"]
    base_output = await upload_asset(client, admin, "batch_tryon_output", "base.png")
    target_mask = await upload_asset(client, admin, "temporary", "target-mask.png")
    reference_patch = await upload_asset(client, admin, "temporary", "reference-patch.png")
    async with identity_test_context["session_factory"]() as session:
        job = await session.get(Job, original_job["id"], with_for_update=True)
        job.status = "succeeded"
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        await sync_batch_try_on_version_for_job(session, job, generated_asset_id=base_output["id"])
        mask_asset = await session.get(Asset, target_mask["id"], with_for_update=True)
        mask_asset.source_asset_id = base_output["id"]
        mask_asset.metadata_json = {"asset_role": "target_edit_mask"}
        patch_asset = await session.get(Asset, reference_patch["id"], with_for_update=True)
        patch_asset.source_asset_id = garment["id"]
        patch_asset.metadata_json = {"asset_role": "reference_patch"}
        await session.commit()

    unapproved = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/region-replace",
        headers=admin,
        json={
            "source_version_id": original_version_id,
            "target_mask_asset_id": target_mask["id"],
            "image_c_asset_id": garment["id"],
            "source_reference_mask_asset_id": None,
            "reference_patch_asset_id": reference_patch["id"],
            "edit_region_type": "back_number",
            "edit_prompt": "Replace number 06 only.",
            "target_mask_metadata": {"mask_semantics": "transparent_is_editable"},
            "source_reference_metadata": {"full_image_fallback": True},
            "idempotency_key": "region-before-base-approval-001",
        },
    )
    assert unapproved.status_code == 409
    assert unapproved.json()["error"]["code"] == "batch_tryon.region_replace_requires_approved_base"

    base_approved = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/approve",
        headers=admin,
        json={"source_version_id": original_version_id},
    )
    assert base_approved.status_code == 200, base_approved.text

    region = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/region-replace",
        headers=admin,
        json={
            "source_version_id": original_version_id,
            "target_mask_asset_id": target_mask["id"],
            "image_c_asset_id": garment["id"],
            "source_reference_mask_asset_id": None,
            "reference_patch_asset_id": reference_patch["id"],
            "edit_region_type": "back_number",
            "edit_prompt": "Replace number 06 only.",
            "target_mask_metadata": {"mask_semantics": "transparent_is_editable"},
            "source_reference_metadata": {"full_image_fallback": True},
            "idempotency_key": "region-candidate-submit-001",
        },
    )
    assert region.status_code == 202, region.text
    region_body = region.json()
    candidate_id = region_body["job"]["review_version_id"]
    assert candidate_id and candidate_id != original_version_id
    assert region_body["review"]["current_version_id"] == original_version_id
    assert region_body["review"]["current_version"]["generated_asset"]["id"] == base_output["id"]

    refined_output = await upload_asset(client, admin, "batch_tryon_output", "refined.png")
    async with identity_test_context["session_factory"]() as session:
        job = await session.get(Job, region_body["job"]["id"], with_for_update=True)
        job.status = "succeeded"
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        await sync_batch_try_on_version_for_job(session, job, generated_asset_id=refined_output["id"])
        await session.commit()

    detail = (await client.get(
        f"/api/v1/batch-tryon/items/{item_id}/review-detail", headers=admin,
    )).json()
    candidate = next(version for version in detail["versions"] if version["id"] == candidate_id)
    assert detail["current_version_id"] == original_version_id
    assert candidate["generated_asset"]["id"] == refined_output["id"]
    duplicate = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/region-replace",
        headers=admin,
        json={
            "source_version_id": original_version_id,
            "target_mask_asset_id": target_mask["id"],
            "image_c_asset_id": garment["id"],
            "source_reference_mask_asset_id": None,
            "reference_patch_asset_id": reference_patch["id"],
            "edit_region_type": "back_number",
            "edit_prompt": "Replace number 06 only.",
            "target_mask_metadata": {"mask_semantics": "transparent_is_editable"},
            "source_reference_metadata": {"full_image_fallback": True},
            "idempotency_key": "region-candidate-submit-duplicate-001",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "batch_tryon.region_replace_confirmation_required"
    bypass = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/select-version",
        headers=admin,
        json={"version_id": candidate_id},
    )
    assert bypass.status_code == 409

    approved = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/region-replace/approve",
        headers=admin,
        json={"source_version_id": candidate_id},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["current_version_id"] == candidate_id
    assert approved.json()["approved_version_id"] == candidate_id
    assert approved.json()["review_status"] == "approved"
    assert approved.json()["current_version"]["generated_asset"]["id"] == refined_output["id"]


async def test_region_replace_candidate_can_be_discarded_before_retry(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    admin = await auth_headers(client, "first-admin@example.com", "correct-password")
    model_code = await seed_batch_try_on_pool(identity_test_context)
    model = await upload_asset(client, admin, "model_template", "model-discard.png")
    garment = await upload_asset(client, admin, "garment", "jersey-discard.png")
    submitted = await client.post("/api/v1/job-batches", headers=admin, json={
        "name": "Region discard batch", "workspace_type": "batch_tryon",
        "operation_code": "batch_tryon.generate", "capability": "image_edit",
        "model_code": model_code, "idempotency_key": "region-discard-batch-001",
        "concurrency": 1, "items": [{
            "client_item_id": "region-discard-item", "prompt": "BASE",
            "reference_asset_ids": [model["id"], garment["id"]], "size": "1024x1024",
            "aspect_ratio": "1:1", "output_format": "png",
            "metadata": {"garment_filename": "jersey-discard.png", "index": 0},
        }],
    })
    original = submitted.json()["jobs"][0]
    base = await upload_asset(client, admin, "batch_tryon_output", "base-discard.png")
    mask = await upload_asset(client, admin, "temporary", "mask-discard.png")
    patch = await upload_asset(client, admin, "temporary", "patch-discard.png")
    async with identity_test_context["session_factory"]() as session:
        job = await session.get(Job, original["id"], with_for_update=True)
        job.status = "succeeded"; job.progress = 100; job.finished_at = datetime.now(timezone.utc)
        await sync_batch_try_on_version_for_job(session, job, generated_asset_id=base["id"])
        mask_asset = await session.get(Asset, mask["id"], with_for_update=True)
        mask_asset.source_asset_id = base["id"]; mask_asset.metadata_json = {"asset_role": "target_edit_mask"}
        patch_asset = await session.get(Asset, patch["id"], with_for_update=True)
        patch_asset.source_asset_id = garment["id"]; patch_asset.metadata_json = {"asset_role": "reference_patch"}
        await session.commit()
    approved = await client.post(
        f"/api/v1/batch-tryon/items/{original['review_item_id']}/approve", headers=admin,
        json={"source_version_id": original["current_version_id"]},
    )
    assert approved.status_code == 200
    payload = {
        "source_version_id": original["current_version_id"], "target_mask_asset_id": mask["id"],
        "image_c_asset_id": garment["id"], "source_reference_mask_asset_id": None,
        "reference_patch_asset_id": patch["id"], "edit_region_type": "back_number",
        "edit_prompt": "Replace selected artwork.", "target_mask_metadata": {},
        "source_reference_metadata": {}, "idempotency_key": "region-discard-first-001",
    }
    first = await client.post(
        f"/api/v1/batch-tryon/items/{original['review_item_id']}/region-replace",
        headers=admin, json=payload,
    )
    assert first.status_code == 202, first.text
    candidate_id = first.json()["job"]["review_version_id"]
    async with identity_test_context["session_factory"]() as session:
        job = await session.get(Job, first.json()["job"]["id"], with_for_update=True)
        job.status = "failed"; job.finished_at = datetime.now(timezone.utc)
        await sync_batch_try_on_version_for_job(session, job)
        await session.commit()
    discarded = await client.post(
        f"/api/v1/batch-tryon/items/{original['review_item_id']}/region-replace/discard",
        headers=admin, json={"source_version_id": candidate_id},
    )
    assert discarded.status_code == 200, discarded.text
    discarded_candidate = next(v for v in discarded.json()["versions"] if v["id"] == candidate_id)
    assert discarded_candidate["review_status"] == "rejected"
    retry = await client.post(
        f"/api/v1/batch-tryon/items/{original['review_item_id']}/region-replace",
        headers=admin, json={**payload, "idempotency_key": "region-discard-retry-001"},
    )
    assert retry.status_code == 202, retry.text


def test_review_notes_are_additive_and_optional() -> None:
    base = "MANDATORY BASE PROMPT\nKeep garment fidelity."
    assert append_batch_try_on_review_requirements(base, None) == base
    prompt = append_batch_try_on_review_requirements(base, "Keep 06 with its leading zero.")
    assert prompt.startswith(base)
    assert "REVIEW CORRECTION REQUIREMENTS:" in prompt
    assert "Keep 06 with its leading zero." in prompt
    assert "must not replace or weaken" in prompt


def test_review_notes_accept_up_to_ten_thousand_characters() -> None:
    notes = "A" * 10_000
    single = BatchTryOnRegenerateRequest(
        source_version_id="version-id",
        retry_mode="with_review_notes",
        review_notes=notes,
        idempotency_key="review-notes-10000",
    )
    batch = BatchTryOnBatchRegenerateRequest(
        items=[{"item_id": "item-id", "version_id": "version-id"}],
        review_notes=notes,
        idempotency_key="batch-notes-10000",
    )

    assert len(single.review_notes or "") == 10_000
    assert len(batch.review_notes) == 10_000


async def test_normal_tryon_submission_contract_preserves_matrix_jobs_reviews_versions_and_quota(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    admin = await auth_headers(client, "first-admin@example.com", "correct-password")
    model_code = await seed_batch_try_on_pool(identity_test_context)
    templates = [
        await upload_asset(client, admin, "model_template", "model-front.png"),
        await upload_asset(client, admin, "model_template", "model-back.png"),
    ]
    garments = [
        await upload_asset(client, admin, "garment", "01-red-shirt.png"),
        await upload_asset(client, admin, "garment", "02-blue-shirt.png"),
    ]
    matrix = [
        ("front-red", 0, 0),
        ("front-blue", 0, 1),
        ("back-red", 1, 0),
        ("back-blue", 1, 1),
    ]
    items = []
    for index, (client_item_id, template_index, garment_index) in enumerate(matrix):
        items.append({
            "client_item_id": client_item_id,
            "prompt": f"NORMAL TRY-ON CONTRACT PROMPT {index + 1}",
            "reference_asset_ids": [templates[template_index]["id"], garments[garment_index]["id"]],
            "size": "1024x1024",
            "aspect_ratio": "1:1",
            "output_format": "png",
            "metadata": {
                "index": index,
                "template_id": f"template-{template_index + 1}",
                "template_name": f"model-{'front' if template_index == 0 else 'back'}",
                "template_order": template_index + 1,
                "template_count": 2,
                "garment_filename": garments[garment_index]["filename"],
            },
        })

    submitted = await client.post("/api/v1/job-batches", headers=admin, json={
        "name": "Normal try-on contract baseline",
        "workspace_type": "batch_tryon",
        "operation_code": "batch_tryon.generate",
        "capability": "image_edit",
        "model_code": model_code,
        "idempotency_key": "normal-tryon-contract-001",
        "concurrency": 2,
        "items": items,
    })
    assert submitted.status_code == 202, submitted.text
    body = submitted.json()
    assert body["workspace_type"] == "batch_tryon"
    assert body["operation_code"] == "batch_tryon.generate"
    assert body["total_jobs"] == 4
    assert len(body["jobs"]) == 4
    batch_id = body["id"]

    async with identity_test_context["session_factory"]() as session:
        batch = await session.get(JobBatch, batch_id)
        jobs = list((await session.scalars(
            select(Job).where(Job.batch_id == batch_id).order_by(Job.client_item_id)
        )).all())
        reviews = list((await session.scalars(
            select(BatchTryOnReviewItem)
            .where(BatchTryOnReviewItem.batch_id == batch_id)
            .order_by(BatchTryOnReviewItem.client_item_id)
        )).all())
        versions = list((await session.scalars(
            select(BatchTryOnVersion)
            .join(BatchTryOnReviewItem, BatchTryOnReviewItem.id == BatchTryOnVersion.item_id)
            .where(BatchTryOnReviewItem.batch_id == batch_id)
        )).all())
        reservations = list((await session.scalars(
            select(QuotaReservation).where(QuotaReservation.reference_id.in_([job.id for job in jobs]))
        )).all())
        account = await session.scalar(select(QuotaAccount).where(
            QuotaAccount.organization_id == identity_test_context["first_org"]
        ))

        assert batch is not None
        assert batch.concurrency == 2
        assert len(jobs) == len(reviews) == len(versions) == len(reservations) == 4
        expected_by_client_id = {item["client_item_id"]: item for item in items}
        review_by_client_id = {item.client_item_id: item for item in reviews}
        version_by_item_id = {item.item_id: item for item in versions}
        for job in jobs:
            expected = expected_by_client_id[job.client_item_id]
            review = review_by_client_id[job.client_item_id]
            version = version_by_item_id[review.id]
            assert job.queue_name == "batch_tryon_queue"
            assert job.input_json["reference_asset_ids"] == expected["reference_asset_ids"]
            for key, value in expected["metadata"].items():
                assert job.input_json["metadata"][key] == value
            assert job.input_json["metadata"]["batch_tryon_review_item_id"] == review.id
            assert job.input_json["metadata"]["batch_tryon_version_id"] == version.id
            assert job.input_json["metadata"]["source_filename"] == expected["metadata"]["garment_filename"]
            assert review.model_asset_id == expected["reference_asset_ids"][0]
            assert review.garment_asset_id == expected["reference_asset_ids"][1]
            assert review.current_version_id == version.id
            assert version.task_id == job.id
            assert version.version_number == 1
            assert version.prompt_snapshot == expected["prompt"]
        assert account.balance == 1000
        assert account.reserved_balance == 40
        assert all(item.status == "reserved" and item.reserved_amount == 10 for item in reservations)

    active_delete = await client.delete(
        f"/api/v1/job-batches/{batch_id}/hard?confirmation=PERMANENT_DELETE",
        headers=admin,
    )
    assert active_delete.status_code == 409
    assert active_delete.json()["error"]["code"] == "job.batch_delete_active"

    cancelled = await client.post(f"/api/v1/job-batches/{batch_id}/cancel", headers=admin)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancelled_jobs"] == 4

    async with identity_test_context["session_factory"]() as session:
        account = await session.scalar(select(QuotaAccount).where(
            QuotaAccount.organization_id == identity_test_context["first_org"]
        ))
        reservations = list((await session.scalars(
            select(QuotaReservation).where(QuotaReservation.reference_id.in_([
                item["id"] for item in body["jobs"]
            ]))
        )).all())
        versions = list((await session.scalars(
            select(BatchTryOnVersion)
            .join(BatchTryOnReviewItem, BatchTryOnReviewItem.id == BatchTryOnVersion.item_id)
            .where(BatchTryOnReviewItem.batch_id == batch_id)
        )).all())
        assert account.balance == 1000
        assert account.reserved_balance == 0
        assert all(item.status == "released" for item in reservations)
        assert all(item.generation_status == "cancelled" for item in versions)

    permanent = await client.delete(
        f"/api/v1/job-batches/{batch_id}/hard?confirmation=PERMANENT_DELETE",
        headers=admin,
    )
    assert permanent.status_code == 200, permanent.text
    assert permanent.json()["deleted_batches"] == 1
    assert permanent.json()["deleted_jobs"] == 4
    async with identity_test_context["session_factory"]() as session:
        assert await session.get(JobBatch, batch_id) is None
        assert await session.scalar(select(func.count()).select_from(Job).where(Job.batch_id == batch_id)) == 0
        assert await session.scalar(
            select(func.count()).select_from(BatchTryOnReviewItem).where(
                BatchTryOnReviewItem.batch_id == batch_id,
            )
        ) == 0
        reservations = list((await session.scalars(
            select(QuotaReservation).where(QuotaReservation.reference_id.in_([
                item["id"] for item in body["jobs"]
            ]))
        )).all())
        assert len(reservations) == 4
        assert all(item.status == "released" for item in reservations)


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
    assert (await client.get(f"/api/v1/batch-tryon/items/{item_id}/review-detail", headers=viewer)).status_code == 404
    assert (await client.get(
        f"/api/v1/job-batches/{submitted.json()['id']}", headers=viewer,
    )).status_code == 404
    viewer_batches = await client.get(
        "/api/v1/job-batches?workspace_type=batch_tryon&include_jobs=false",
        headers=viewer,
    )
    assert viewer_batches.status_code == 200
    assert submitted.json()["id"] not in {
        item["id"] for item in viewer_batches.json()["items"]
    }
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
    assert version_v1["source_filename"] == "jersey-06.png"
    assert version_v1["display_filename"] == "model-jersey-06.png"
    assert version_v1["download_filename"] == "model-jersey-06.png"
    pending_download = await client.get(
        f"/api/v1/assets/{output['id']}/download", headers=admin,
    )
    assert pending_download.status_code == 200
    assert "model-jersey-06.png" in pending_download.headers["content-disposition"]

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
    assert approved.json()["current_version"]["download_filename"] == "model-jersey-06.png"
    approved_download = await client.get(
        f"/api/v1/assets/{output['id']}/download", headers=admin,
    )
    assert "model-jersey-06.png" in approved_download.headers["content-disposition"]
    assert "model-jersey-06-v1.png" not in approved_download.headers["content-disposition"]

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
        assert versions[0].review_status == "approved"
        assert item.approved_version_id == versions[0].id
        assert versions[1].generated_asset_id is None
        assert item.source_filename == "jersey-06.png"
        assert versions[0].source_filename == "jersey-06.png"
        assert versions[0].display_filename == "model-jersey-06.png"
        assert versions[0].download_filename == "model-jersey-06-v1.png"
        assert versions[1].download_filename == "model-jersey-06-v2.png"
        assert versions[1].prompt_snapshot.startswith("BASE TRY-ON PROMPT")
        assert "REVIEW CORRECTION REQUIREMENTS:" in versions[1].prompt_snapshot
        assert "胸前数字必须保持为06" in versions[1].prompt_snapshot
        assert await session.get(Asset, output["id"]) is not None

    batch_id = submitted.json()["id"]
    regenerating_batch = await client.get(f"/api/v1/job-batches/{batch_id}", headers=admin)
    assert regenerating_batch.status_code == 200, regenerating_batch.text
    assert regenerating_batch.json()["total_jobs"] == 1
    assert regenerating_batch.json()["succeeded_jobs"] == 0
    assert regenerating_batch.json()["status"] == "queued"
    assert [job["id"] for job in regenerating_batch.json()["jobs"]] == [regenerated_body["job"]["id"]]

    output_v2 = await upload_asset(client, admin, "batch_tryon_output", "result-v2.png")
    async with identity_test_context["session_factory"]() as session:
        job = await session.get(Job, regenerated_body["job"]["id"], with_for_update=True)
        job.status = "succeeded"
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        session.add(GeneratedOutput(
            organization_id=job.organization_id,
            project_id=None,
            project_version_id=None,
            asset_id=output_v2["id"],
            job_id=job.id,
            batch_id=job.batch_id,
            sequence_number=0,
            output_type="batch_tryon_output",
            module_key=None,
            metadata_json={"client_item_id": job.client_item_id},
            created_by=job.created_by,
            created_at=datetime.now(timezone.utc),
        ))
        await sync_batch_try_on_version_for_job(session, job, generated_asset_id=output_v2["id"])

        # Reproduce the production symptom: a historical regeneration job made
        # the denormalized batch counters read 1/2 and left the batch running.
        batch = await session.get(JobBatch, batch_id, with_for_update=True)
        batch.total_jobs = 2
        batch.succeeded_jobs = 1
        batch.status = "running"
        await session.commit()

    version_v2_id = regenerated_body["review"]["current_version_id"]
    approved_v2 = await client.post(
        f"/api/v1/batch-tryon/items/{item_id}/approve",
        headers=admin,
        json={"source_version_id": version_v2_id},
    )
    assert approved_v2.status_code == 200, approved_v2.text
    assert approved_v2.json()["review_status"] == "approved"
    assert approved_v2.json()["current_version"]["display_filename"] == "model-jersey-06.png"
    assert approved_v2.json()["current_version"]["download_filename"] == "model-jersey-06.png"
    history_download = await client.get(
        f"/api/v1/assets/{output['id']}/download", headers=admin,
    )
    assert "model-jersey-06-v1.png" in history_download.headers["content-disposition"]
    final_download = await client.get(
        f"/api/v1/assets/{output_v2['id']}/download", headers=admin,
    )
    assert "model-jersey-06.png" in final_download.headers["content-disposition"]

    completed_batch = await client.get(f"/api/v1/job-batches/{batch_id}", headers=admin)
    assert completed_batch.status_code == 200, completed_batch.text
    completed_body = completed_batch.json()
    assert completed_body["total_jobs"] == 1
    assert completed_body["succeeded_jobs"] == 1
    assert completed_body["failed_jobs"] == 0
    assert completed_body["cancelled_jobs"] == 0
    assert completed_body["status"] == "succeeded"
    assert [job["id"] for job in completed_body["jobs"]] == [regenerated_body["job"]["id"]]
    assert completed_body["jobs"][0]["outputs"][0]["display_filename"] == "model-jersey-06.png"
    assert completed_body["jobs"][0]["outputs"][0]["download_filename"] == "model-jersey-06.png"

    zipped = await client.get(
        f"/api/v1/job-batches/{batch_id}/batch-tryon-results.zip", headers=admin,
    )
    assert zipped.status_code == 200, zipped.text
    with ZipFile(BytesIO(zipped.content)) as archive:
        assert archive.namelist() == ["model-jersey-06.png"]

    async with identity_test_context["session_factory"]() as session:
        asset_v1 = await session.get(Asset, output["id"])
        asset_v2 = await session.get(Asset, output_v2["id"])
        assert asset_v1.storage_key != asset_v2.storage_key
        assert "jersey-06" not in asset_v1.storage_key


async def test_batch_try_on_zip_deduplicates_names_from_garment_assets(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    admin = await auth_headers(client, "first-admin@example.com", "correct-password")
    model_code = await seed_batch_try_on_pool(identity_test_context)
    model = await upload_asset(client, admin, "model_template", "model.png")
    garments = [
        await upload_asset(client, admin, "garment", filename)
        for filename in ("shirt.png", "shirt.jpg", "shirt.webp")
    ]
    submitted = await client.post("/api/v1/job-batches", headers=admin, json={
        "name": "Duplicate filename batch",
        "workspace_type": "batch_tryon",
        "operation_code": "batch_tryon.generate",
        "capability": "image_edit",
        "model_code": model_code,
        "idempotency_key": "batch-filename-duplicates-001",
        "concurrency": 2,
        "items": [{
            "client_item_id": f"duplicate-{index}",
            "prompt": "BASE TRY-ON PROMPT",
            "reference_asset_ids": [model["id"], garment["id"]],
            "size": "1024x1024",
            "aspect_ratio": "1:1",
            "output_format": "png",
            "metadata": {"garment_filename": garment["filename"]},
        } for index, garment in enumerate(garments)],
    })
    assert submitted.status_code == 202, submitted.text
    body = submitted.json()
    outputs = [
        await upload_asset(client, admin, "batch_tryon_output", f"provider-{index}.png")
        for index in range(3)
    ]
    async with identity_test_context["session_factory"]() as session:
        for job_body, output in zip(body["jobs"], outputs, strict=True):
            job = await session.get(Job, job_body["id"], with_for_update=True)
            job.status = "succeeded"
            job.progress = 100
            job.finished_at = datetime.now(timezone.utc)
            session.add(GeneratedOutput(
                organization_id=job.organization_id,
                asset_id=output["id"],
                job_id=job.id,
                batch_id=job.batch_id,
                sequence_number=0,
                output_type="batch_tryon_output",
                metadata_json={"client_item_id": job.client_item_id},
                created_by=job.created_by,
                created_at=datetime.now(timezone.utc),
            ))
            await sync_batch_try_on_version_for_job(session, job, generated_asset_id=output["id"])
        await session.commit()

    for job_body in body["jobs"]:
        approved = await client.post(
            f"/api/v1/batch-tryon/items/{job_body['review_item_id']}/approve",
            headers=admin,
            json={"source_version_id": job_body["current_version_id"]},
        )
        assert approved.status_code == 200, approved.text

    zipped = await client.get(
        f"/api/v1/job-batches/{body['id']}/batch-tryon-results.zip", headers=admin,
    )
    assert zipped.status_code == 200, zipped.text
    with ZipFile(BytesIO(zipped.content)) as archive:
        assert set(archive.namelist()) == {"model-shirt.png", "model-shirt-2.png", "model-shirt-3.png"}


async def test_multi_template_cartesian_outputs_combine_template_and_garment_names(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    admin = await auth_headers(client, "first-admin@example.com", "correct-password")
    model_code = await seed_batch_try_on_pool(identity_test_context)
    templates = [
        await upload_asset(client, admin, "model_template", f"long-template-name-{index}.png")
        for index in (1, 2)
    ]
    garment = await upload_asset(client, admin, "garment", "06-blue-jersey.webp")
    submitted = await client.post("/api/v1/job-batches", headers=admin, json={
        "name": "Compact Cartesian filenames",
        "workspace_type": "batch_tryon",
        "operation_code": "batch_tryon.generate",
        "capability": "image_edit",
        "model_code": model_code,
        "idempotency_key": "batch-filename-template-suffixes-001",
        "concurrency": 2,
        "items": [{
            "client_item_id": f"template-suffix-{index}",
            "prompt": "BASE TRY-ON PROMPT",
            "reference_asset_ids": [template["id"], garment["id"]],
            "size": "1024x1024",
            "aspect_ratio": "1:1",
            "output_format": "png",
            # Deliberately omit the new template_index/template_count fields to
            # verify that historical Cartesian tasks derive stable order from
            # their saved template_id and matrix index.
            "metadata": {
                "garment_filename": "06-blue-jersey.webp",
                "template_id": f"template-{index}",
                "template_name": f"非常冗长的模板名称-{index}",
                "index": index - 1,
            },
        } for index, template in enumerate(templates, start=1)],
    })
    assert submitted.status_code == 202, submitted.text
    body = submitted.json()
    outputs = [
        await upload_asset(client, admin, "batch_tryon_output", f"provider-template-{index}.png")
        for index in (1, 2)
    ]

    async with identity_test_context["session_factory"]() as session:
        for job_body, output in zip(body["jobs"], outputs, strict=True):
            job = await session.get(Job, job_body["id"], with_for_update=True)
            job.status = "succeeded"
            job.progress = 100
            job.finished_at = datetime.now(timezone.utc)
            session.add(GeneratedOutput(
                organization_id=job.organization_id,
                asset_id=output["id"],
                job_id=job.id,
                batch_id=job.batch_id,
                sequence_number=0,
                output_type="batch_tryon_output",
                metadata_json={"client_item_id": job.client_item_id},
                created_by=job.created_by,
                created_at=datetime.now(timezone.utc),
            ))
            await sync_batch_try_on_version_for_job(session, job, generated_asset_id=output["id"])
        await session.commit()

    for job_body in body["jobs"]:
        index = int(job_body["client_item_id"].rsplit("-", 1)[-1])
        detail = await client.get(
            f"/api/v1/batch-tryon/items/{job_body['review_item_id']}/review-detail",
            headers=admin,
        )
        assert detail.status_code == 200, detail.text
        current = detail.json()["current_version"]
        assert current["display_filename"] == f"非常冗长的模板名称-{index}-06-blue-jersey.png"
        assert current["download_filename"] == f"非常冗长的模板名称-{index}-06-blue-jersey.png"
        approved = await client.post(
            f"/api/v1/batch-tryon/items/{job_body['review_item_id']}/approve",
            headers=admin,
            json={"source_version_id": job_body["current_version_id"]},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["current_version"]["download_filename"] == f"非常冗长的模板名称-{index}-06-blue-jersey.png"

    zipped = await client.get(
        f"/api/v1/job-batches/{body['id']}/batch-tryon-results.zip", headers=admin,
    )
    assert zipped.status_code == 200, zipped.text
    with ZipFile(BytesIO(zipped.content)) as archive:
        assert set(archive.namelist()) == {
            "非常冗长的模板名称-1-06-blue-jersey.png",
            "非常冗长的模板名称-2-06-blue-jersey.png",
        }


async def test_old_batch_try_on_task_lazily_restores_filename_from_job_snapshot(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    admin = await auth_headers(client, "first-admin@example.com", "correct-password")
    model_code = await seed_batch_try_on_pool(identity_test_context)
    model = await upload_asset(client, admin, "model_template", "model.png")
    garment = await upload_asset(client, admin, "garment", "06-blue-jersey.webp")
    submitted = await client.post("/api/v1/job-batches", headers=admin, json={
        "name": "Legacy filename batch",
        "workspace_type": "batch_tryon",
        "operation_code": "batch_tryon.generate",
        "capability": "image_edit",
        "model_code": model_code,
        "idempotency_key": "batch-filename-legacy-001",
        "concurrency": 1,
        "items": [{
            "client_item_id": "legacy-item",
            "prompt": "BASE TRY-ON PROMPT",
            "reference_asset_ids": [model["id"], garment["id"]],
            "size": "1024x1024",
            "aspect_ratio": "1:1",
            "output_format": "png",
            "metadata": {"garment_filename": "06-blue-jersey.webp"},
        }],
    })
    assert submitted.status_code == 202, submitted.text
    job_body = submitted.json()["jobs"][0]
    async with identity_test_context["session_factory"]() as session:
        item = await session.get(BatchTryOnReviewItem, job_body["review_item_id"])
        version = await session.get(BatchTryOnVersion, job_body["current_version_id"])
        asset = await session.get(Asset, garment["id"])
        item.source_filename = None
        version.source_filename = None
        version.display_filename = None
        version.download_filename = None
        version.output_format = None
        asset.filename = "06-blue-jersey"
        await session.commit()

    detail = await client.get(
        f"/api/v1/batch-tryon/items/{job_body['review_item_id']}/review-detail",
        headers=admin,
    )
    assert detail.status_code == 200, detail.text
    current = detail.json()["current_version"]
    assert current["source_filename"] == "06-blue-jersey.webp"
    assert current["display_filename"] == "model-06-blue-jersey.png"
    assert current["download_filename"] == "model-06-blue-jersey.png"


async def test_bulk_regeneration_and_per_template_zip_are_stable_and_idempotent(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    send_calls: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "app.workers.celery_app.celery_app.send_task",
        lambda *args, **kwargs: send_calls.append((args, kwargs)),
    )
    admin = await auth_headers(client, "first-admin@example.com", "correct-password")
    model_code = await seed_batch_try_on_pool(identity_test_context)
    templates = [
        await upload_asset(client, admin, "model_template", filename)
        for filename in ("欧美男模-01.png", "欧美女模-02.png")
    ]
    garments = [
        await upload_asset(client, admin, "garment", filename)
        for filename in ("A001-shirt.png", "A002-shirt.jpg", "B001-shirt.webp")
    ]
    request_items = [
        {
            "client_item_id": f"bulk-item-{index}",
            "prompt": f"MANDATORY PROMPT {index}",
            "reference_asset_ids": [templates[template_index]["id"], garments[index]["id"]],
            "size": "1024x1024",
            "aspect_ratio": "1:1",
            "output_format": "png",
            "metadata": {
                "garment_filename": garments[index]["filename"],
                "template_id": f"template-{template_index + 1}",
                "template_name": "欧美男模-01" if template_index == 0 else "欧美女模-02",
                "template_index": template_index + 1,
                "template_count": 2,
                "index": index,
            },
        }
        for index, template_index in enumerate((0, 0, 1))
    ]
    submitted = await client.post("/api/v1/job-batches", headers=admin, json={
        "name": "Bulk review and template archive",
        "workspace_type": "batch_tryon",
        "operation_code": "batch_tryon.generate",
        "capability": "image_edit",
        "model_code": model_code,
        "idempotency_key": "batch-review-bulk-template-001",
        "concurrency": 2,
        "items": request_items,
    })
    assert submitted.status_code == 202, submitted.text
    body = submitted.json()
    outputs = [
        await upload_asset(client, admin, "batch_tryon_output", f"provider-{index}.png")
        for index in range(3)
    ]
    async with identity_test_context["session_factory"]() as session:
        for job_body, output in zip(body["jobs"], outputs, strict=True):
            job = await session.get(Job, job_body["id"], with_for_update=True)
            job.status = "succeeded"
            job.progress = 100
            job.finished_at = datetime.now(timezone.utc)
            session.add(GeneratedOutput(
                organization_id=job.organization_id,
                project_id=job.project_id,
                asset_id=output["id"],
                job_id=job.id,
                batch_id=job.batch_id,
                sequence_number=0,
                output_type="batch_tryon_output",
                metadata_json={"client_item_id": job.client_item_id},
                created_by=job.created_by,
                created_at=datetime.now(timezone.utc),
            ))
            await sync_batch_try_on_version_for_job(
                session,
                job,
                generated_asset_id=output["id"],
            )
        await session.commit()

    first_job = next(
        job for job in body["jobs"] if job["client_item_id"] == "bulk-item-0"
    )
    approved = await client.post(
        f"/api/v1/batch-tryon/items/{first_job['review_item_id']}/approve",
        headers=admin,
        json={"source_version_id": first_job["current_version_id"]},
    )
    assert approved.status_code == 200, approved.text

    approved_zip = await client.get(
        f"/api/v1/batch-tryon/batches/{body['id']}/templates/template-1/download"
        "?scope=approved",
        headers=admin,
    )
    assert approved_zip.status_code == 200, approved_zip.text
    assert "filename*=UTF-8''" in approved_zip.headers["content-disposition"]
    assert "%E6%AC%A7%E7%BE%8E%E7%94%B7%E6%A8%A1-01" in approved_zip.headers[
        "content-disposition"
    ]
    with ZipFile(BytesIO(approved_zip.content)) as archive:
        assert archive.namelist() == ["欧美男模-01-A001-shirt.png"]

    all_template_one = await client.get(
        f"/api/v1/batch-tryon/batches/{body['id']}/templates/template-1/download"
        "?scope=all_succeeded",
        headers=admin,
    )
    assert all_template_one.status_code == 200, all_template_one.text
    with ZipFile(BytesIO(all_template_one.content)) as archive:
        assert set(archive.namelist()) == {
            "欧美男模-01-A001-shirt.png",
            "欧美男模-01-A002-shirt.png",
        }

    all_template_two = await client.get(
        f"/api/v1/batch-tryon/batches/{body['id']}/templates/template-2/download"
        "?scope=all_succeeded",
        headers=admin,
    )
    assert all_template_two.status_code == 200, all_template_two.text
    with ZipFile(BytesIO(all_template_two.content)) as archive:
        assert archive.namelist() == ["欧美女模-02-B001-shirt.png"]

    retry_batch = await client.post("/api/v1/job-batches", headers=admin, json={
        "name": "Later partial retry batch",
        "workspace_type": "batch_tryon",
        "operation_code": "batch_tryon.generate",
        "capability": "image_edit",
        "model_code": model_code,
        "idempotency_key": "batch-review-template-cross-batch-001",
        "concurrency": 1,
        "items": [{
            "client_item_id": "bulk-item-later-retry",
            "prompt": "MANDATORY RETRY PROMPT",
            "reference_asset_ids": [templates[0]["id"], garments[1]["id"]],
            "size": "1024x1024",
            "aspect_ratio": "1:1",
            "output_format": "png",
            "metadata": {
                "garment_filename": garments[1]["filename"],
                "template_id": "template-1",
                "template_name": "欧美男模-01",
                "template_index": 1,
                "template_count": 2,
                "index": 99,
            },
        }],
    })
    assert retry_batch.status_code == 202, retry_batch.text
    retry_job_body = retry_batch.json()["jobs"][0]
    retry_output = await upload_asset(
        client, admin, "batch_tryon_output", "provider-later-retry.png"
    )
    async with identity_test_context["session_factory"]() as session:
        retry_job = await session.get(Job, retry_job_body["id"], with_for_update=True)
        retry_job.status = "succeeded"
        retry_job.progress = 100
        retry_job.finished_at = datetime.now(timezone.utc)
        session.add(GeneratedOutput(
            organization_id=retry_job.organization_id,
            project_id=retry_job.project_id,
            asset_id=retry_output["id"],
            job_id=retry_job.id,
            batch_id=retry_job.batch_id,
            sequence_number=0,
            output_type="batch_tryon_output",
            metadata_json={"client_item_id": retry_job.client_item_id},
            created_by=retry_job.created_by,
            created_at=datetime.now(timezone.utc),
        ))
        await sync_batch_try_on_version_for_job(
            session,
            retry_job,
            generated_asset_id=retry_output["id"],
        )
        await session.commit()

    selected_cross_batch_zip = await client.post(
        "/api/v1/batch-tryon/templates/template-1/download",
        headers=admin,
        json={
            "item_ids": [
                first_job["review_item_id"],
                retry_job_body["review_item_id"],
            ],
            "scope": "all_succeeded",
        },
    )
    assert selected_cross_batch_zip.status_code == 200, selected_cross_batch_zip.text
    with ZipFile(BytesIO(selected_cross_batch_zip.content)) as archive:
        assert set(archive.namelist()) == {
            "欧美男模-01-A001-shirt.png",
            "欧美男模-01-A002-shirt.png",
        }

    send_calls.clear()
    selected_jobs = [
        job for job in body["jobs"]
        if job["client_item_id"] in {"bulk-item-0", "bulk-item-1"}
    ]
    payload = {
        "items": [
            {
                "item_id": job["review_item_id"],
                "version_id": job["current_version_id"],
            }
            for job in selected_jobs
        ],
        "review_notes": "Keep the model identity and background unchanged.",
        "idempotency_key": "batch-review-notes-bulk-001",
    }
    regenerated = await client.post(
        "/api/v1/batch-tryon/items/batch-regenerate-with-notes",
        headers=admin,
        json=payload,
    )
    assert regenerated.status_code == 202, regenerated.text
    regenerated_body = regenerated.json()
    assert regenerated_body["requested_count"] == 2
    assert regenerated_body["created_count"] == 2
    assert regenerated_body["failed_count"] == 0
    assert send_calls == [], "batch endpoint must commit before scheduler dispatch"
    batch_status = await client.post(
        "/api/v1/jobs/batch-status",
        headers=admin,
        json={
            "job_ids": [
                task["task_id"] for task in regenerated_body["created_tasks"]
            ],
        },
    )
    assert batch_status.status_code == 200, batch_status.text
    assert {
        job["id"] for job in batch_status.json()
    } == {
        task["task_id"] for task in regenerated_body["created_tasks"]
    }
    cross_tenant_status = await client.post(
        "/api/v1/jobs/batch-status",
        headers=await auth_headers(
            client, "second-admin@example.com", "second-password"
        ),
        json={
            "job_ids": [
                task["task_id"] for task in regenerated_body["created_tasks"]
            ],
        },
    )
    assert cross_tenant_status.status_code == 404
    assert {
        task["template_id"] for task in regenerated_body["created_tasks"]
    } == {"template-1"}
    assert {
        task["garment_asset_id"] for task in regenerated_body["created_tasks"]
    } == {garments[0]["id"], garments[1]["id"]}

    async with identity_test_context["session_factory"]() as session:
        review_items = list((await session.scalars(
            select(BatchTryOnReviewItem).where(
                BatchTryOnReviewItem.id.in_([
                    job["review_item_id"] for job in selected_jobs
                ])
            )
        )).all())
        assert all(item.current_version_id for item in review_items)
        approved_item = next(
            item for item in review_items if item.id == first_job["review_item_id"]
        )
        assert approved_item.approved_version_id == first_job["current_version_id"]
        versions = list((await session.scalars(
            select(BatchTryOnVersion).where(
                BatchTryOnVersion.item_id.in_([item.id for item in review_items])
            )
        )).all())
        assert len(versions) == 4
        new_versions = [version for version in versions if version.version_number == 2]
        assert len(new_versions) == 2
        assert all(version.retry_mode == "batch_review_notes" for version in new_versions)
        assert all(version.created_by for version in new_versions)
        assert all(
            "Keep the model identity and background unchanged."
            in version.prompt_snapshot
            for version in new_versions
        )
        assert all(version.parent_version_id for version in new_versions)

    replay = await client.post(
        "/api/v1/batch-tryon/items/batch-regenerate-with-notes",
        headers=admin,
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["created_count"] == 0
    assert replay.json()["replayed_count"] == 2
    async with identity_test_context["session_factory"]() as session:
        assert int(await session.scalar(
            select(func.count()).select_from(BatchTryOnVersion).where(
                BatchTryOnVersion.item_id.in_([
                    job["review_item_id"] for job in selected_jobs
                ])
            )
        ) or 0) == 4

    partial = await client.post(
        "/api/v1/batch-tryon/items/batch-regenerate-with-notes",
        headers=admin,
        json={
            **payload,
            "items": [
                payload["items"][0],
                {"item_id": "missing-review-item", "version_id": "missing-version"},
            ],
        },
    )
    assert partial.status_code == 207, partial.text
    assert partial.json()["replayed_count"] == 1
    assert partial.json()["failed_count"] == 1
    assert partial.json()["errors"][0]["code"] == "batch_tryon.review_item_not_found"
