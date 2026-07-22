from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.identity import User
from app.models.content import Asset, GeneratedOutput
from app.models.quota import QuotaAccount
from app.services.provider_test_service import ProviderConnectionResult


async def auth_headers(client, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_admin_endpoints_require_platform_permission(identity_test_context) -> None:
    client = identity_test_context["client"]
    organization_admin = await auth_headers(client, "first-admin@example.com", "correct-password")

    response = await client.get("/api/v1/admin/overview", headers=organization_admin)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.permission_denied"


async def test_admin_overview_users_and_self_lockout(identity_test_context) -> None:
    client = identity_test_context["client"]
    platform = await auth_headers(client, "platform-admin@example.com", "platform-password")

    overview = await client.get("/api/v1/admin/overview", headers=platform)
    assert overview.status_code == 200, overview.text
    assert overview.json()["users_total"] == 4
    assert overview.json()["organizations_total"] == 2
    assert overview.json()["quota_balance_total"] == 1050

    page = await client.get("/api/v1/admin/users?search=first-admin", headers=platform)
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 1
    user = page.json()["items"][0]
    assert user["memberships"][0]["organization_name"] == "First Team"

    me = await client.get("/api/v1/auth/me", headers=platform)
    self_disable = await client.patch(
        f"/api/v1/admin/users/{me.json()['user']['id']}", headers=platform, json={"status": "disabled"}
    )
    assert self_disable.status_code == 409
    assert self_disable.json()["error"]["code"] == "admin.self_lockout"


async def test_admin_can_disable_and_restore_user(identity_test_context) -> None:
    client = identity_test_context["client"]
    platform = await auth_headers(client, "platform-admin@example.com", "platform-password")
    async with identity_test_context["session_factory"]() as session:
        user_id = await session.scalar(select(User.id).where(User.email == "first-viewer@example.com"))

    disabled = await client.patch(
        f"/api/v1/admin/users/{user_id}", headers=platform, json={"status": "disabled"}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"
    rejected = await client.post("/api/v1/auth/login", json={
        "email": "first-viewer@example.com", "password": "viewer-password",
    })
    assert rejected.status_code == 401

    restored = await client.patch(
        f"/api/v1/admin/users/{user_id}", headers=platform, json={"status": "active"}
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"


async def test_admin_organization_quota_and_audit(identity_test_context) -> None:
    client = identity_test_context["client"]
    platform = await auth_headers(client, "platform-admin@example.com", "platform-password")
    second_org = identity_test_context["second_org"]

    organizations = await client.get("/api/v1/admin/organizations", headers=platform)
    assert organizations.status_code == 200, organizations.text
    second = next(item for item in organizations.json()["items"] if item["id"] == second_org)
    assert second["quota_balance"] == 50

    adjusted = await client.post(
        f"/api/v1/admin/organizations/{second_org}/quota-adjustments",
        headers=platform,
        json={
            "transaction_type": "grant", "amount": 25,
            "idempotency_key": f"admin-test:{uuid4()}", "reason": "admin acceptance",
        },
    )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["account"]["balance"] == 75
    async with identity_test_context["session_factory"]() as session:
        account = await session.scalar(select(QuotaAccount).where(QuotaAccount.organization_id == second_org))
        assert account.balance == 75

    audit = await client.get(
        f"/api/v1/admin/audit-logs?organization_id={second_org}&action=admin.quota.adjust",
        headers=platform,
    )
    assert audit.status_code == 200
    assert audit.json()["total"] == 1
    assert audit.json()["items"][0]["resource_type"] == "quota_account"


async def test_admin_resource_inventory_never_returns_secret(identity_test_context) -> None:
    client = identity_test_context["client"]
    platform = await auth_headers(client, "platform-admin@example.com", "platform-password")
    provider = await client.post("/api/v1/resource-pools/providers", headers=platform, json={
        "code": "admin-relay", "name": "Admin Relay", "provider_type": "openai_compatible",
        "base_url": "https://relay.example/v1", "config": {},
    })
    assert provider.status_code == 201, provider.text
    model = await client.post(
        f"/api/v1/resource-pools/providers/{provider.json()['id']}/models", headers=platform,
        json={
            "code": "admin-image", "upstream_model": "image-v1", "name": "Image",
            "capabilities": ["image_generation", "image_edit"], "config": {},
        },
    )
    assert model.status_code == 201, model.text
    pool = await client.post("/api/v1/resource-pools", headers=platform, json={
        "model_id": model.json()["id"], "code": "admin-pool", "name": "Admin Pool",
    })
    assert pool.status_code == 201, pool.text
    secret = "sk-admin-resource-secret"
    key = await client.post("/api/v1/resource-pools/keys", headers=platform, json={
        "provider_id": provider.json()["id"], "label": "Admin Key", "secret": secret,
        "max_concurrency": 2,
    })
    assert key.status_code == 201, key.text
    attached = await client.post(
        f"/api/v1/resource-pools/{pool.json()['id']}/keys", headers=platform,
        json={"api_key_id": key.json()["id"]},
    )
    assert attached.status_code == 204

    inventory = await client.get("/api/v1/admin/resources", headers=platform)
    assert inventory.status_code == 200, inventory.text
    assert secret not in inventory.text
    assert inventory.json()["keys"][0]["masked_secret"] == "****cret"
    assert inventory.json()["pools"][0]["key_ids"] == [key.json()["id"]]

    disabled = await client.patch(
        f"/api/v1/admin/api-keys/{key.json()['id']}", headers=platform, json={"enabled": False}
    )
    assert disabled.status_code == 200
    inventory = await client.get("/api/v1/admin/resources", headers=platform)
    assert inventory.json()["keys"][0]["enabled"] is False
    assert inventory.json()["keys"][0]["status"] == "disabled"


async def test_admin_global_jobs_queues_and_login_audits(identity_test_context) -> None:
    client = identity_test_context["client"]
    platform = await auth_headers(client, "platform-admin@example.com", "platform-password")

    jobs = await client.get("/api/v1/admin/jobs", headers=platform)
    queues = await client.get("/api/v1/admin/queues", headers=platform)
    logins = await client.get("/api/v1/admin/login-audits", headers=platform)

    assert jobs.status_code == 200
    assert jobs.json()["items"] == []
    assert queues.status_code == 200
    assert {item["name"] for item in queues.json()["items"]} == {
        "planning_queue", "listing_queue", "batch_tryon_queue", "aplus_queue", "maintenance",
    }
    assert logins.status_code == 200
    assert logins.json()["total"] >= 1


async def test_admin_generated_output_diagnostics_are_safe(identity_test_context) -> None:
    client = identity_test_context["client"]
    platform = await auth_headers(client, "platform-admin@example.com", "platform-password")
    first = await auth_headers(client, "first-admin@example.com", "correct-password")
    asset_response = await client.post(
        "/api/v1/assets", headers=first, data={"category": "listing_output"},
        files={"file": ("diagnostic.png", __import__("base64").b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        ), "image/png")},
    )
    assert asset_response.status_code == 201
    asset_id = asset_response.json()["id"]
    async with identity_test_context["session_factory"]() as session:
        asset = await session.get(Asset, asset_id)
        output = GeneratedOutput(
            organization_id=asset.organization_id, asset_id=asset.id, job_id=None, batch_id=None,
            project_id=None, project_version_id=None, sequence_number=1, output_type="listing_output",
            module_key=None, metadata_json=None, created_by=asset.created_by,
            created_at=datetime.now(timezone.utc),
        )
        session.add(output)
        await session.commit()
        output_id = output.id

    diagnostic = await client.get(f"/api/v1/admin/generated-outputs/{output_id}/diagnostics", headers=platform)
    assert diagnostic.status_code == 200, diagnostic.text
    body = diagnostic.json()
    assert body["file_exists"] is True and body["backend_can_read"] is True
    assert body["returned_url_path"] == f"/api/v1/assets/{asset_id}/content"
    assert body["returned_url_scheme"] == "relative" and body["returned_url_host"] is None
    assert body["image_access_mode"] == "authenticated_backend_stream"
    assert "secret" not in diagnostic.text.lower() and "signature" not in diagnostic.text.lower()


async def test_admin_provider_test_uses_encrypted_key_and_masks_response(identity_test_context, monkeypatch) -> None:
    client = identity_test_context["client"]
    platform = await auth_headers(client, "platform-admin@example.com", "platform-password")
    provider = await client.post("/api/v1/resource-pools/providers", headers=platform, json={
        "code": "probe-relay", "name": "Probe Relay", "provider_type": "openai_compatible",
        "base_url": "https://relay.example/v1", "config": {},
    })
    assert provider.status_code == 201, provider.text
    secret = "sk-provider-probe-secret"
    key = await client.post("/api/v1/resource-pools/keys", headers=platform, json={
        "provider_id": provider.json()["id"], "label": "Probe Key", "secret": secret,
        "max_concurrency": 2,
    })
    assert key.status_code == 201, key.text

    async def fake_probe(**kwargs):
        assert kwargs["api_key"] == secret
        assert kwargs["base_url"] == "https://relay.example/v1"
        return ProviderConnectionResult(True, 200, None, "连接成功，发现 2 个模型", ["image-model", "text-model"])

    monkeypatch.setattr("app.api.admin.probe_provider_models", fake_probe)
    response = await client.post(f"/api/v1/admin/providers/{provider.json()['id']}/test", headers=platform)

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert response.json()["models"] == ["image-model", "text-model"]
    assert secret not in response.text
