from base64 import b64decode
from datetime import datetime, timezone

from httpx import AsyncClient

from app.models.content import Asset, GeneratedOutput


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


async def test_asset_upload_list_and_authenticated_content(identity_test_context) -> None:
    client = identity_test_context["client"]
    headers = await auth_headers(client, "first-admin@example.com", "correct-password")
    response = await upload(client, headers)
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["width"] == 1 and asset["height"] == 1
    assert asset["url"] == f"/api/v1/assets/{asset['id']}/content"
    assert asset["url_expires_at"] is None
    assert "localhost" not in asset["url"] and "127.0.0.1" not in asset["url"] and "minio" not in asset["url"]
    assert len(identity_test_context["storage"].objects) == 1

    unauthenticated = await client.get(asset["url"])
    assert unauthenticated.status_code == 401
    content = await client.get(asset["url"], headers=headers)
    assert content.status_code == 200
    assert content.content == PNG
    assert content.headers["content-type"] == "image/png"
    assert content.headers["cache-control"] == "private, max-age=300"
    assert content.headers["x-content-type-options"] == "nosniff"
    viewer = await auth_headers(client, "first-viewer@example.com", "viewer-password")
    same_team_content = await client.get(asset["url"], headers=viewer)
    assert same_team_content.status_code == 200
    assert same_team_content.content == PNG

    listing = await client.get("/api/v1/assets", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 0
    invalid_filter = await client.get("/api/v1/assets?category=product_reference", headers=headers)
    assert invalid_filter.status_code == 422

    async with identity_test_context["session_factory"]() as session:
        stored_asset = await session.get(Asset, asset["id"])
        assert stored_asset is not None
        assert "/assets/product_reference/" in stored_asset.storage_key
        stored_asset.category = "listing_output"
        session.add(GeneratedOutput(
            organization_id=stored_asset.organization_id,
            project_id=None,
            project_version_id=None,
            asset_id=stored_asset.id,
            job_id=None,
            batch_id=None,
            sequence_number=0,
            output_type="listing_output",
            module_key=None,
            metadata_json=None,
            created_by=stored_asset.created_by,
            created_at=datetime.now(timezone.utc),
        ))
        await session.commit()

    generated_listing = await client.get("/api/v1/assets?category=listing_output", headers=headers)
    assert generated_listing.status_code == 200
    assert generated_listing.json()["total"] == 1
    assert generated_listing.json()["items"][0]["id"] == asset["id"]
    other_module = await client.get("/api/v1/assets?category=aplus_output", headers=headers)
    assert other_module.status_code == 200
    assert other_module.json()["total"] == 0
    url = await client.get(f"/api/v1/assets/{asset['id']}/url", headers=headers)
    assert url.status_code == 200
    assert url.json()["asset_id"] == asset["id"]
    assert url.json()["url"] == asset["url"]
    assert url.json()["expires_at"] is None


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
    hidden_content = await client.get(f"/api/v1/assets/{asset['id']}/content", headers=second)
    assert hidden_content.status_code == 404
    assert (await client.get("/api/v1/assets", headers=second)).json()["total"] == 0


async def test_missing_asset_content_returns_clear_error(identity_test_context) -> None:
    client = identity_test_context["client"]
    headers = await auth_headers(client, "first-admin@example.com", "correct-password")
    asset = (await upload(client, headers)).json()
    identity_test_context["storage"].objects.clear()
    response = await client.get(asset["url"], headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "asset.content_missing"


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
        "display_name": "蓝色球衣", "is_default": True,
    })
    assert linked.status_code == 201, linked.text
    link = linked.json()["assets"][0]
    assert link["display_name"] == "蓝色球衣"
    assert link["is_default"] is True
    updated = await client.patch(
        f"/api/v1/projects/{project['id']}/assets/{link['id']}",
        headers=headers,
        json={"display_name": "主款蓝色球衣", "is_default": True},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["assets"][0]["display_name"] == "主款蓝色球衣"
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


async def test_project_asset_links_sort_mixed_datetimes_and_retry_idempotently(identity_test_context) -> None:
    client = identity_test_context["client"]
    headers = await auth_headers(client, "first-admin@example.com", "correct-password")
    first_asset = (await upload(client, headers, filename="first.png")).json()
    second_asset = (await upload(client, headers, filename="second.png")).json()
    project = (await client.post("/api/v1/projects", headers=headers, json={
        "project_type": "batch_tryon", "name": "Multiple templates", "draft": {},
    })).json()

    first_payload = {
        "asset_id": first_asset["id"],
        "role": "model_template",
        "sort_order": 0,
        "display_name": "模板一",
        "is_default": True,
    }
    first = await client.post(
        f"/api/v1/projects/{project['id']}/assets",
        headers=headers,
        json=first_payload,
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        f"/api/v1/projects/{project['id']}/assets",
        headers=headers,
        json={
            "asset_id": second_asset["id"],
            "role": "model_template",
            "sort_order": 1,
            "display_name": "模板二",
        },
    )
    assert second.status_code == 201, second.text
    assert [item["display_name"] for item in second.json()["assets"]] == ["模板一", "模板二"]

    retried = await client.post(
        f"/api/v1/projects/{project['id']}/assets",
        headers=headers,
        json={**first_payload, "display_name": "模板一（重试）"},
    )
    assert retried.status_code == 201, retried.text
    assert len(retried.json()["assets"]) == 2
    assert retried.json()["assets"][0]["display_name"] == "模板一（重试）"


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
