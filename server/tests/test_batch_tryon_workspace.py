import pytest

from app.models.tasks import JobBatch


async def auth_headers(
    client, account: str = "first-admin", password: str = "correct-password",
) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={
        "account": account, "password": password,
    })
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_workspace_tabs_are_persistent_and_hide_is_not_delete(identity_test_context) -> None:
    client = identity_test_context["client"]
    headers = await auth_headers(client)
    project = (await client.post("/api/v1/projects", headers=headers, json={
        "project_type": "batch_tryon", "name": "Workspace project", "draft": {},
    })).json()

    created = await client.post("/api/v1/batch-tryon/workspaces", headers=headers, json={
        "project_id": project["id"],
        "name": "礼品图-01",
        "config": {"concurrency": 5, "batch": {"sampleGarmentId": "garment-1"}},
    })
    assert created.status_code == 201, created.text
    workspace = created.json()
    assert workspace["status"] == "draft"
    assert workspace["config"]["batch"]["sampleGarmentId"] == "garment-1"

    task_history = await client.get(
        f"/api/v1/job-batches?workspace_type=batch_tryon&project_id={project['id']}&include_jobs=false",
        headers=headers,
    )
    assert task_history.status_code == 200, task_history.text
    stored = next(item for item in task_history.json()["items"] if item["id"] == workspace["id"])
    assert stored["batch_kind"] == "workspace"
    assert stored["cancel_requested_jobs"] == 0

    invalid_cancel = await client.post(
        f"/api/v1/job-batches/{workspace['id']}/cancel", headers=headers,
    )
    assert invalid_cancel.status_code == 409
    assert invalid_cancel.json()["error"]["code"] == "job.workspace_batch_action_invalid"

    updated = await client.patch(
        f"/api/v1/batch-tryon/workspaces/{workspace['id']}", headers=headers,
        json={"name": "礼品图-已配置", "status": "ready", "config": {"concurrency": 12}},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "礼品图-已配置"
    assert updated.json()["status"] == "ready"

    visible = await client.get(
        f"/api/v1/batch-tryon/workspaces?project_id={project['id']}", headers=headers,
    )
    assert visible.json()["total"] == 1

    hidden = await client.post(
        f"/api/v1/batch-tryon/workspaces/{workspace['id']}/hide", headers=headers,
    )
    assert hidden.status_code == 200
    assert hidden.json()["hidden"] is True
    visible_after = await client.get(
        f"/api/v1/batch-tryon/workspaces?project_id={project['id']}", headers=headers,
    )
    assert visible_after.json()["total"] == 0
    including_hidden = await client.get(
        f"/api/v1/batch-tryon/workspaces?project_id={project['id']}&include_hidden=true", headers=headers,
    )
    assert including_hidden.json()["total"] == 1

    wrong_confirmation = await client.delete(
        f"/api/v1/batch-tryon/workspaces/{workspace['id']}/hard?confirmation=DELETE",
        headers=headers,
    )
    assert wrong_confirmation.status_code == 422
    permanent = await client.delete(
        f"/api/v1/batch-tryon/workspaces/{workspace['id']}/hard?confirmation=PERMANENT_DELETE",
        headers=headers,
    )
    assert permanent.status_code == 200, permanent.text
    assert permanent.json()["deleted_batches"] == 1
    async with identity_test_context["session_factory"]() as session:
        assert await session.get(JobBatch, workspace["id"]) is None


@pytest.mark.asyncio
async def test_batch_try_on_projects_workspaces_and_batches_are_account_isolated(
    identity_test_context,
) -> None:
    client = identity_test_context["client"]
    owner = await auth_headers(client)
    other_account = await auth_headers(
        client, "first-viewer", "viewer-password",
    )
    project = (await client.post("/api/v1/projects", headers=owner, json={
        "project_type": "batch_tryon", "name": "Private batch project", "draft": {},
    })).json()
    workspace = (await client.post("/api/v1/batch-tryon/workspaces", headers=owner, json={
        "project_id": project["id"], "name": "Private workspace", "config": {},
    })).json()

    assert (await client.get(
        f"/api/v1/projects/{project['id']}", headers=other_account,
    )).status_code == 404
    listed_projects = await client.get(
        "/api/v1/projects?project_type=batch_tryon", headers=other_account,
    )
    assert listed_projects.status_code == 200
    assert project["id"] not in {item["id"] for item in listed_projects.json()["items"]}
    assert (await client.get(
        f"/api/v1/batch-tryon/workspaces?project_id={project['id']}",
        headers=other_account,
    )).status_code == 404
    assert (await client.get(
        f"/api/v1/job-batches/{workspace['id']}", headers=other_account,
    )).status_code == 404
    listed_batches = await client.get(
        "/api/v1/job-batches?workspace_type=batch_tryon&include_jobs=false",
        headers=other_account,
    )
    assert listed_batches.status_code == 200
    assert workspace["id"] not in {item["id"] for item in listed_batches.json()["items"]}


@pytest.mark.asyncio
async def test_only_empty_draft_workspace_can_be_deleted(identity_test_context) -> None:
    client = identity_test_context["client"]
    headers = await auth_headers(client)
    project = (await client.post("/api/v1/projects", headers=headers, json={
        "project_type": "batch_tryon", "name": "Delete draft project", "draft": {},
    })).json()
    workspace = (await client.post("/api/v1/batch-tryon/workspaces", headers=headers, json={
        "project_id": project["id"], "config": {},
    })).json()
    async with identity_test_context["session_factory"]() as session:
        stored_workspace = await session.get(JobBatch, workspace["id"])
        assert stored_workspace is not None
        assert stored_workspace.concurrency == 12
    deleted = await client.delete(f"/api/v1/batch-tryon/workspaces/{workspace['id']}", headers=headers)
    assert deleted.status_code == 204, deleted.text
