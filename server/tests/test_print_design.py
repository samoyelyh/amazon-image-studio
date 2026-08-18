from base64 import b64decode

from httpx import AsyncClient


PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


async def auth_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_print_asset_library_group_search_and_tenant_isolation(identity_test_context) -> None:
    client = identity_test_context["client"]
    first = await auth_headers(client, "first-admin@example.com", "correct-password")
    group = await client.post("/api/v1/print-design/asset-groups", headers=first, json={
        "code": "football-numbers", "name": "橄榄球号码", "product_type": "jersey",
    })
    assert group.status_code == 201, group.text
    uploaded = await client.post(
        "/api/v1/assets", headers=first, data={"category": "print_asset"},
        files={"file": ("number-12.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    registered = await client.post("/api/v1/print-design/assets", headers=first, json={
        "asset_id": uploaded.json()["id"], "asset_group_id": group.json()["id"],
        "asset_code": "NUM-12", "asset_name": "号码 12", "asset_type": "number",
        "tags": ["football", "outline"], "version": 1,
    })
    assert registered.status_code == 201, registered.text
    assert registered.json()["asset"]["category"] == "print_asset"
    page = await client.get("/api/v1/print-design/assets?search=NUM-12", headers=first)
    assert page.status_code == 200 and page.json()["total"] == 1
    mapping = await client.post("/api/v1/print-design/product-mappings", headers=first, json={
        "sku": "FOTJ-NF0000532", "asset_group_id": group.json()["id"],
        "style_code": "NF0000532",
    })
    assert mapping.status_code == 201, mapping.text
    matched = await client.get("/api/v1/print-design/product-mappings?code=NF0000532", headers=first)
    assert matched.status_code == 200 and matched.json()[0]["asset_group_id"] == group.json()["id"]
    renamed = await client.patch(
        f"/api/v1/print-design/assets/{registered.json()['id']}", headers=first,
        json={"asset_name": "号码 12 新版名称", "tags": ["football", "updated"]},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["asset_name"] == "号码 12 新版名称"
    assert renamed.json()["tags"] == ["football", "updated"]
    second = await auth_headers(client, "second-admin@example.com", "second-password")
    assert (await client.get("/api/v1/print-design/assets", headers=second)).json()["total"] == 0
    assert (await client.get("/api/v1/print-design/asset-groups", headers=second)).json() == []
    archived = await client.delete(f"/api/v1/print-design/assets/{registered.json()['id']}", headers=first)
    assert archived.status_code == 204
    assert (await client.get("/api/v1/print-design/assets", headers=first)).json()["total"] == 0


async def test_print_design_project_and_lossless_debug_assets(identity_test_context) -> None:
    client = identity_test_context["client"]
    admin = await auth_headers(client, "first-admin@example.com", "correct-password")
    source = await client.post(
        "/api/v1/assets", headers=admin, data={"category": "product_reference"},
        files={"file": ("base.png", PNG, "image/png")},
    )
    project = await client.post("/api/v1/projects", headers=admin, json={
        "project_type": "print_design", "name": "Print editor", "draft": {"schemaVersion": 2, "layers": []},
    })
    assert project.status_code == 201, project.text
    debug = await client.post(
        "/api/v1/assets/print-design-references", headers=admin,
        data={"source_asset_id": source.json()["id"], "asset_role": "blend_mask", "metadata": "{\"feather\":12}"},
        files={"file": ("blend-mask.png", PNG, "image/png")},
    )
    assert debug.status_code == 201, debug.text
    assert debug.json()["source_asset_id"] == source.json()["id"]
    assert debug.json()["metadata_json"]["workflow"] == "print_design"
    assert debug.json()["metadata_json"]["asset_role"] == "blend_mask"
