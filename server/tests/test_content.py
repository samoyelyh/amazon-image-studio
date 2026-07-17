from base64 import b64decode

from httpx import AsyncClient


PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


async def auth_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def upload(client: AsyncClient, headers: dict[str, str], filename: str = "product.png"):
    return await client.post(
        "/api/v1/assets",
        headers=headers,
        data={"category": "product_reference"},
        files={"file": (filename, PNG, "image/png")},
    )


async def test_asset_upload_list_and_private_url(identity_test_context) -> None:
    client = identity_test_context["client"]
    headers = await auth_headers(client, "first-admin@example.com", "correct-password")
    response = await upload(client, headers)
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["width"] == 1 and asset["height"] == 1
    assert asset["url"].startswith("https://storage.test/private/organizations/")
    assert len(identity_test_context["storage"].objects) == 1

    listing = await client.get("/api/v1/assets?category=product_reference", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    url = await client.get(f"/api/v1/assets/{asset['id']}/url", headers=headers)
    assert url.status_code == 200
    assert url.json()["asset_id"] == asset["id"]


async def test_invalid_image_and_viewer_write_permissions(identity_test_context) -> None:
    client = identity_test_context["client"]
    admin = await auth_headers(client, "first-admin@example.com", "correct-password")
    invalid = await client.post(
        "/api/v1/assets", headers=admin, data={"category": "garment"},
        files={"file": ("fake.png", b"not-an-image", "image/png")},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "asset.invalid_image"
    assert not identity_test_context["storage"].objects

    viewer = await auth_headers(client, "first-viewer@example.com", "viewer-password")
    forbidden = await upload(client, viewer)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "auth.permission_denied"


async def test_assets_are_tenant_isolated(identity_test_context) -> None:
    client = identity_test_context["client"]
    first = await auth_headers(client, "first-admin@example.com", "correct-password")
    asset = (await upload(client, first)).json()
    second = await auth_headers(client, "second-admin@example.com", "second-password")
    hidden = await client.get(f"/api/v1/assets/{asset['id']}", headers=second)
    assert hidden.status_code == 404
    assert (await client.get("/api/v1/assets", headers=second)).json()["total"] == 0


async def test_project_versions_are_immutable_and_conflict_checked(identity_test_context) -> None:
    client = identity_test_context["client"]
    headers = await auth_headers(client, "first-admin@example.com", "correct-password")
    created = await client.post("/api/v1/projects", headers=headers, json={
        "project_type": "listing", "name": "Summer Listing", "draft": {"title": "v1"},
    })
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["latest_version"]["version_number"] == 1

    saved = await client.post(f"/api/v1/projects/{project['id']}/versions", headers=headers, json={
        "draft": {"title": "v2"}, "expected_version": 1,
    })
    assert saved.status_code == 201, saved.text
    assert saved.json()["version_number"] == 2
    conflict = await client.post(f"/api/v1/projects/{project['id']}/versions", headers=headers, json={
        "draft": {"title": "stale"}, "expected_version": 1,
    })
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "project.version_conflict"
    versions = await client.get(f"/api/v1/projects/{project['id']}/versions", headers=headers)
    assert [item["draft_json"]["title"] for item in versions.json()] == ["v2", "v1"]


async def test_project_asset_reference_blocks_delete_and_project_delete_keeps_object(identity_test_context) -> None:
    client = identity_test_context["client"]
    headers = await auth_headers(client, "first-admin@example.com", "correct-password")
    asset = (await upload(client, headers)).json()
    project = (await client.post("/api/v1/projects", headers=headers, json={
        "project_type": "batch_tryon", "name": "Try-on Batch", "draft": {},
    })).json()
    linked = await client.post(f"/api/v1/projects/{project['id']}/assets", headers=headers, json={
        "asset_id": asset["id"], "role": "garment", "sort_order": 0,
    })
    assert linked.status_code == 201, linked.text
    blocked = await client.delete(f"/api/v1/assets/{asset['id']}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "asset.in_use"

    deleted_project = await client.delete(f"/api/v1/projects/{project['id']}", headers=headers)
    assert deleted_project.status_code == 204
    assert len(identity_test_context["storage"].objects) == 1
    assert (await client.get(f"/api/v1/projects/{project['id']}", headers=headers)).status_code == 404
    deleted_asset = await client.delete(f"/api/v1/assets/{asset['id']}", headers=headers)
    assert deleted_asset.status_code == 204
    assert not identity_test_context["storage"].objects


async def test_projects_are_tenant_isolated_and_viewer_read_only(identity_test_context) -> None:
    client = identity_test_context["client"]
    first = await auth_headers(client, "first-admin@example.com", "correct-password")
    project = (await client.post("/api/v1/projects", headers=first, json={
        "project_type": "aplus", "name": "A+ Draft", "draft": {},
    })).json()
    viewer = await auth_headers(client, "first-viewer@example.com", "viewer-password")
    assert (await client.get(f"/api/v1/projects/{project['id']}", headers=viewer)).status_code == 200
    denied = await client.post("/api/v1/projects", headers=viewer, json={
        "project_type": "listing", "name": "Denied", "draft": {},
    })
    assert denied.status_code == 403
    second = await auth_headers(client, "second-admin@example.com", "second-password")
    assert (await client.get(f"/api/v1/projects/{project['id']}", headers=second)).status_code == 404
