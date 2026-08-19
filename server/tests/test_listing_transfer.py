from base64 import b64decode
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.models.content import Asset, GeneratedOutput, ListingOutputTransfer, Project, ProjectAsset
from app.models.identity import OrganizationMember, Role, User
from app.models.tasks import Job, ModelCapability, OperationResourcePool, Provider, ProviderModel, ResourcePool
from app.security.passwords import hash_password


PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


async def auth_headers(client, account: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"account": account, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def upload(client, headers, filename: str):
    response = await client.post(
        "/api/v1/assets",
        headers=headers,
        data={"category": "product_reference"},
        files={"file": (filename, PNG, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def seed_listing_pool(context) -> str:
    async with context["session_factory"]() as session:
        provider = Provider(
            code="listing-transfer-provider",
            name="Listing transfer provider",
            provider_type="openai_compatible",
            base_url="https://relay.example/v1",
            config_json={},
        )
        session.add(provider)
        await session.flush()
        model = ProviderModel(
            provider_id=provider.id,
            code="listing-transfer-model",
            upstream_model="image-2",
            name="Listing transfer model",
            config_json={},
        )
        session.add(model)
        await session.flush()
        session.add(ModelCapability(model_id=model.id, capability="image_generation"))
        pool = ResourcePool(model_id=model.id, code="listing-transfer-pool", name="Listing transfer pool")
        session.add(pool)
        await session.flush()
        session.add(OperationResourcePool(
            operation_code="listing.generate",
            resource_pool_id=pool.id,
            required_capability="image_generation",
            priority=100,
        ))
        await session.commit()
        return model.code


async def test_listing_output_send_create_replace_idempotency_and_isolation(identity_test_context, monkeypatch) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    admin = await auth_headers(client, "first-admin", "correct-password")
    viewer = await auth_headers(client, "first-viewer", "viewer-password")
    second = await auth_headers(client, "second-admin", "second-password")
    async with identity_test_context["session_factory"]() as session:
        member_role = await session.scalar(select(Role).where(Role.code == "member"))
        member = User(
            account="listing-member",
            display_name="Listing Member",
            password_hash=hash_password("member-password"),
        )
        session.add(member)
        await session.flush()
        session.add(OrganizationMember(
            organization_id=identity_test_context["first_org"],
            user_id=member.id,
            role_id=member_role.id,
        ))
        await session.commit()
    member_headers = await auth_headers(client, "listing-member", "member-password")
    member_probe = await client.post(
        "/api/v1/listing/generated-outputs/missing-output/send-to-batch-tryon",
        headers=member_headers,
        json={
            "target_mode": "create_project",
            "project_name": "Member permission probe",
            "idempotency_key": "member-transfer-probe-001",
        },
    )
    assert member_probe.status_code == 404
    assert member_probe.json()["error"]["code"] == "listing.output_not_found"
    model_code = await seed_listing_pool(identity_test_context)

    listing_project = (await client.post("/api/v1/projects", headers=admin, json={
        "project_type": "listing",
        "name": "Summer Listing",
        "draft": {"title": "Summer Listing"},
    })).json()
    submitted = await client.post("/api/v1/jobs", headers=admin, json={
        "operation_code": "listing.generate",
        "workspace_type": "listing",
        "queue_name": "listing_queue",
        "capability": "image_generation",
        "model_code": model_code,
        "idempotency_key": "listing-transfer-source-job",
        "project_id": listing_project["id"],
        "input": {"prompt": "model listing image", "n": 1, "size": "1024x1024", "aspect_ratio": "1:1"},
    })
    assert submitted.status_code == 202, submitted.text
    source_asset = await upload(client, admin, "listing-result.png")
    async with identity_test_context["session_factory"]() as session:
        job = await session.get(Job, submitted.json()["id"], with_for_update=True)
        job.status = "succeeded"
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        asset = await session.get(Asset, source_asset["id"], with_for_update=True)
        asset.category = "listing_output"
        output = GeneratedOutput(
            organization_id=job.organization_id,
            project_id=listing_project["id"],
            project_version_id=listing_project["latest_version"]["id"],
            asset_id=asset.id,
            job_id=job.id,
            batch_id=None,
            sequence_number=0,
            output_type="listing_output",
            module_key="MAIN",
            metadata_json={"version": 1},
            created_by=job.created_by,
            created_at=datetime.now(timezone.utc),
        )
        session.add(output)
        await session.commit()
        output_id = output.id

    create_payload = {
        "target_mode": "create_project",
        "project_name": "Summer Listing-批量套图",
        "project_description": "Created from Listing",
        "idempotency_key": "listing-transfer-create-001",
    }
    created = await client.post(
        f"/api/v1/listing/generated-outputs/{output_id}/send-to-batch-tryon",
        headers=admin,
        json=create_payload,
    )
    assert created.status_code == 201, created.text
    created_body = created.json()
    assert created_body["model_asset_id"] == source_asset["id"]
    assert created_body["created_project"] is True
    assert "image_url" not in created_body["redirect_path"] and "blob:" not in created_body["redirect_path"]

    project_detail = await client.get(f"/api/v1/projects/{created_body['batch_project_id']}", headers=admin)
    assert project_detail.status_code == 200, project_detail.text
    detail = project_detail.json()
    assert detail["project_type"] == "batch_tryon"
    assert detail["latest_version"]["draft_json"]["model_asset_id"] == source_asset["id"]
    assert detail["latest_version"]["draft_json"]["template_source_id"] == output_id
    template = next(link for link in detail["assets"] if link["role"] == "model_template")
    assert template["asset"]["id"] == source_asset["id"]
    assert template["asset"]["url"] == f"/api/v1/assets/{source_asset['id']}/content"

    replay = await client.post(
        f"/api/v1/listing/generated-outputs/{output_id}/send-to-batch-tryon",
        headers=admin,
        json=create_payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["batch_project_id"] == created_body["batch_project_id"]
    assert replay.json()["replayed"] is True
    conflict = await client.post(
        f"/api/v1/listing/generated-outputs/{output_id}/send-to-batch-tryon",
        headers=admin,
        json={**create_payload, "project_name": "Different name"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "listing.transfer_idempotency_conflict"

    assert (await client.post(
        f"/api/v1/listing/generated-outputs/{output_id}/send-to-batch-tryon",
        headers=viewer,
        json={**create_payload, "idempotency_key": "viewer-transfer-001"},
    )).status_code == 403
    assert (await client.post(
        f"/api/v1/listing/generated-outputs/{output_id}/send-to-batch-tryon",
        headers=second,
        json={**create_payload, "idempotency_key": "other-org-transfer-001"},
    )).status_code == 404

    old_asset = await upload(client, admin, "old-model.png")
    existing_project = (await client.post("/api/v1/projects", headers=admin, json={
        "project_type": "batch_tryon", "name": "Existing batch", "draft": {"model_asset_id": old_asset["id"]},
    })).json()
    linked = await client.post(f"/api/v1/projects/{existing_project['id']}/assets", headers=admin, json={
        "asset_id": old_asset["id"], "role": "model_template", "sort_order": 0,
    })
    assert linked.status_code == 201, linked.text
    existing_payload = {
        "target_mode": "existing_project",
        "target_project_id": existing_project["id"],
        "replace_existing_template": False,
        "idempotency_key": "listing-transfer-existing-001",
    }
    confirmation = await client.post(
        f"/api/v1/listing/generated-outputs/{output_id}/send-to-batch-tryon",
        headers=admin,
        json=existing_payload,
    )
    assert confirmation.status_code == 409
    assert confirmation.json()["error"]["code"] == "batch_tryon.template_replace_confirmation_required"
    replaced = await client.post(
        f"/api/v1/listing/generated-outputs/{output_id}/send-to-batch-tryon",
        headers=admin,
        json={**existing_payload, "replace_existing_template": True},
    )
    assert replaced.status_code == 201, replaced.text
    assert replaced.json()["template_replaced"] is True

    async with identity_test_context["session_factory"]() as session:
        links = list((await session.scalars(select(ProjectAsset).where(
            ProjectAsset.project_id == existing_project["id"], ProjectAsset.role == "model_template",
        ))).all())
        assert [link.asset_id for link in links] == [source_asset["id"]]
        assert await session.get(Asset, old_asset["id"]) is not None
        assert await session.get(GeneratedOutput, output_id) is not None
        assert int(await session.scalar(select(func.count()).select_from(ListingOutputTransfer)) or 0) == 2
        assert int(await session.scalar(select(func.count()).select_from(Project).where(
            Project.name == "Summer Listing-批量套图",
        )) or 0) == 1

        source = await session.get(Asset, source_asset["id"])
        storage_key = source.storage_key

    identity_test_context["storage"].delete(storage_key)
    missing_content = await client.post(
        f"/api/v1/listing/generated-outputs/{output_id}/send-to-batch-tryon",
        headers=admin,
        json={**create_payload, "idempotency_key": "listing-transfer-missing-content-001"},
    )
    assert missing_content.status_code == 404
    assert missing_content.json()["error"]["code"] == "asset.content_missing"
