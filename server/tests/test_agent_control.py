"""No live model or image requests. Uses real services with isolated ORM/storage."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, func

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.models.agent_control import AgentRun, AgentEvent
from app.models.hermes_agent import HermesConversation, HermesProposal, HermesToolAudit
from app.models.content import Asset
from app.models.tasks import Job
from app.agents.contracts import MessageCreate, ToolAction
from app.agents.tool_registry import execute, validate_action
from app.agents.planner import mock_intent
from tests.test_batch_tryon_workflow import auth_headers, upload, seed_workflow_resources, PNG


@pytest.fixture
async def agent_context(identity_test_context, tmp_path, monkeypatch):
    ctx = identity_test_context
    settings = Settings(_env_file=None, environment="test", agent_control_enabled=True,
        agent_dynamic_capabilities_enabled=False,  # Legacy graph remains replayable; new capability tests opt in.
        agent_checkpoint_url=SecretStr(f"sqlite:///{tmp_path / 'checkpoints.sqlite'}"))
    ctx["app"].dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *a, **k: None)
    await seed_workflow_resources(ctx)
    client = ctx["client"]
    headers = await auth_headers(client)
    project = (await client.post("/api/v1/projects", headers=headers,
        json={"project_type": "batch_tryon", "name": "Agent test", "draft": {}})).json()
    template = await upload(client, headers, "model_template", "template.png")
    garment = await upload(client, headers, "garment", "garment.png")
    for asset, role in ((template, "model_template"), (garment, "garment")):
        linked = await client.post(f"/api/v1/projects/{project['id']}/assets", headers=headers,
            json={"asset_id": asset["id"], "role": role, "sort_order": 0})
        assert linked.status_code == 201, linked.text
    conv = await client.post("/api/v1/agent/conversations", headers=headers, json={"project_id": project["id"]})
    assert conv.status_code == 201, conv.text
    yield {**ctx, "settings": settings, "headers": headers, "project": project, "template": template,
           "garment": garment, "conversation": conv.json()}


def request(ctx, content="生成套图", key=None):
    return {"content": content, "client_request_id": key or str(uuid4()),
            "template_asset_ids": [ctx["template"]["id"]], "garment_asset_ids": [ctx["garment"]["id"]],
            "prompt": "将当前服装替换到模板中，准确保留商品颜色文字号码，背景构图不变。"}


async def plan(ctx, **kwargs):
    result = await ctx["client"].post(f"/api/v1/agent/conversations/{ctx['conversation']['id']}/messages",
        headers=ctx["headers"], json=request(ctx, **kwargs))
    assert result.status_code == 200, result.text
    return result.json()


def ticket(run):
    return {"expected_revision": run["revision"], "state_signature": run["state_signature"],
            "confirmation_token": run["confirmation_token"]}


@pytest.mark.parametrize("text,intent", [("全员队列", "queue"), ("生成套图", "generate"),
    ("Luna分析", "analyze"), ("查看项目", "context"), ("任务状态", "jobs"), ("运行SQL", "clarify")])
def test_mock_intents_are_structured_and_labelled(text, intent):
    assert mock_intent(text).intent == intent


def test_no_arbitrary_tools_or_arguments():
    with pytest.raises(ValidationError):
        ToolAction(tool="run_shell", arguments={"cmd": "whoami"})
    with pytest.raises(ValidationError):
        validate_action(ToolAction(tool="read_business_context", arguments={"project_id": str(uuid4()), "url": "https://bad.test"}))
    with pytest.raises(ValidationError):
        MessageCreate(content="a", client_request_id="bad", user_id="forged")


async def test_feature_off_does_not_use_new_tables(identity_test_context):
    ctx = identity_test_context
    ctx["app"].dependency_overrides[get_settings] = lambda: Settings(_env_file=None, agent_control_enabled=False)
    headers = await auth_headers(ctx["client"])
    assert (await ctx["client"].get("/api/v1/agent/status", headers=headers)).json()["enabled"] is False
    assert (await ctx["client"].get("/api/v1/agent/contexts", headers=headers)).status_code == 503
    assert (await ctx["client"].get("/api/v1/projects", headers=headers)).status_code == 200


async def test_plan_persists_and_recovers_without_job_submission(agent_context):
    ctx = agent_context
    first = await plan(ctx)
    assert first["status"] == "awaiting_confirmation"
    assert first["planner_mode"] == "mock" and first["plan"]["image_count"] == 1
    # A fresh HTTP call and a fresh checkpointer connection, not in-process memory.
    restored = (await ctx["client"].get(f"/api/v1/agent/runs/{first['id']}", headers=ctx["headers"])).json()
    assert restored["confirmation_token"] == first["confirmation_token"]
    assert restored["plan"] == first["plan"]
    history = (await ctx["client"].get(f"/api/v1/agent/conversations/{first['conversation_id']}", headers=ctx["headers"])).json()
    assert history["runs"][0]["id"] == first["id"]
    async with ctx["session_factory"]() as db:
        assert await db.scalar(select(func.count(Job.id))) == 0


async def test_real_b_submission_and_duplicate_confirmation(agent_context):
    ctx = agent_context
    # Test-only: writes go to SQLite and no Celery publish / HTTP provider occurs.
    ctx["settings"].agent_control_writes_enabled = True
    ctx["settings"].agent_control_model_calls_enabled = True
    first = await plan(ctx)
    url = f"/api/v1/agent/runs/{first['id']}/confirm"
    sent = await ctx["client"].post(url, headers=ctx["headers"], json=ticket(first))
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["status"] == "waiting_jobs" and len(body["jobs"]) == 1
    assert body["workspace_url"].startswith("/tasks?batch_id=")
    replay = await ctx["client"].post(url, headers=ctx["headers"], json=ticket(first))
    assert replay.status_code == 200, replay.text
    assert replay.json()["result"] == body["result"]
    async with ctx["session_factory"]() as db:
        jobs = (await db.scalars(select(Job))).all()
        assert len(jobs) == 2  # Local prompt anchor + one real B image Job.
        image = next(j for j in jobs if j.capability == "image_edit")
        assert image.input_json["n"] == 1
        assert image.status == "queued"
        # Mock completion: real Job record remains the source of status.
        image.status, image.progress = "succeeded", 100
        await db.commit()
    restored = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/resume", headers=ctx["headers"])
    assert restored.json()["status"] == "completed"
    async with ctx["session_factory"]() as db:
        assert await db.scalar(select(func.count(HermesToolAudit.id))) == 1


async def test_default_writes_disabled_prevents_any_job(agent_context):
    ctx = agent_context
    first = await plan(ctx)
    denied = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))
    assert denied.status_code == 409, denied.text
    assert denied.json()["error"]["code"] == "agent.writes_disabled"
    async with ctx["session_factory"]() as db:
        assert await db.scalar(select(func.count(Job.id))) == 0


async def test_stale_assets_block_confirmation(agent_context):
    ctx = agent_context
    first = await plan(ctx)
    async with ctx["session_factory"]() as db:
        asset = await db.get(Asset, ctx["garment"]["id"])
        asset.sha256 = "1" * 64
        await db.commit()
    stale = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "agent.plan_stale"


async def test_cancel_cannot_be_confirmed_or_resubmitted(agent_context):
    ctx = agent_context
    first = await plan(ctx)
    url = f"/api/v1/agent/runs/{first['id']}"
    assert (await ctx["client"].post(url + "/stop", headers=ctx["headers"])).json()["status"] == "cancelled"
    assert (await ctx["client"].post(url + "/confirm", headers=ctx["headers"], json=ticket(first))).status_code == 409
    assert (await ctx["client"].post(url + "/resume", headers=ctx["headers"])).json()["status"] == "cancelled"


async def test_confirmation_token_is_not_interchangeable(agent_context):
    ctx = agent_context
    first, second = await plan(ctx), await plan(ctx)
    wrong = {**ticket(first), "confirmation_token": second["confirmation_token"]}
    response = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=wrong)
    assert response.status_code == 403


async def test_cross_user_org_and_asset_access_blocked(agent_context):
    ctx = agent_context
    first = await plan(ctx)
    for account, password in (("first-viewer", "viewer-password"), ("second-admin", "second-password")):
        login = (await ctx["client"].post("/api/v1/auth/login", json={"account": account, "password": password})).json()
        other = {"Authorization": f"Bearer {login['access_token']}"}
        for suffix in ("", "/events"):
            assert (await ctx["client"].get(f"/api/v1/agent/runs/{first['id']}" + suffix, headers=other)).status_code == 404
        assert (await ctx["client"].get(f"/api/v1/agent/contexts/{ctx['project']['id']}", headers=other)).status_code == 404
        assert (await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=other, json=ticket(first))).status_code == 404


async def test_request_id_replay_and_conflict(agent_context):
    ctx = agent_context
    first = await plan(ctx, key="same-request-123")
    replay = await plan(ctx, key="same-request-123")
    assert first["id"] == replay["id"]
    conflict = await ctx["client"].post(f"/api/v1/agent/conversations/{ctx['conversation']['id']}/messages",
        headers=ctx["headers"], json=request(ctx, content="查看项目", key="same-request-123"))
    assert conflict.status_code == 409


async def test_compile_uses_existing_composer_without_provider(agent_context):
    ctx = agent_context
    first = await plan(ctx, content="检查提示词")
    done = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    assert done.json()["result"]["actions"][0]["result"]["prompts"][0]["effective_prompt"] == request(ctx)["prompt"]


async def test_model_planner_has_separate_confirmation_and_no_live_call(agent_context):
    ctx = agent_context
    ctx["settings"].agent_control_planner = "existing_text"
    first = await plan(ctx)
    assert first["plan"]["actions"][0]["tool"] == "plan_intent"
    assert first["plan"]["image_count"] == 0
    blocked = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))
    assert blocked.status_code == 409
    async with ctx["session_factory"]() as db:
        assert await db.scalar(select(func.count(Job.id))) == 0


async def test_missing_checkpoint_does_not_fall_back_to_memory(agent_context):
    ctx = agent_context
    ctx["settings"].agent_checkpoint_url = None
    failed = await ctx["client"].post(f"/api/v1/agent/conversations/{ctx['conversation']['id']}/messages",
        headers=ctx["headers"], json=request(ctx))
    assert failed.status_code == 503 and failed.json()["error"]["code"] == "agent.checkpoint_required"


async def test_denied_confirmation_can_recover_without_new_plan(agent_context):
    ctx = agent_context
    first = await plan(ctx)
    url = f"/api/v1/agent/runs/{first['id']}/confirm"
    assert (await ctx["client"].post(url, headers=ctx["headers"], json=ticket(first))).status_code == 409
    ctx["settings"].agent_control_writes_enabled = True
    ctx["settings"].agent_control_model_calls_enabled = True
    resumed = await ctx["client"].post(url, headers=ctx["headers"], json=ticket(first))
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "waiting_jobs"


async def test_checkpoint_crash_after_business_commit_does_not_resubmit(agent_context, monkeypatch):
    from app.agents import runtime
    ctx = agent_context
    ctx["settings"].agent_control_writes_enabled = ctx["settings"].agent_control_model_calls_enabled = True
    first = await plan(ctx)
    original = runtime._execute_committed
    async def crash(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("simulated checkpoint failure after durable commit")
    monkeypatch.setattr(runtime, "_execute_committed", crash)
    result = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))
    assert result.status_code == 200, result.text
    replay = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))
    assert replay.status_code == 200
    async with ctx["session_factory"]() as db:
        assert await db.scalar(select(func.count(Job.id))) == 2


async def test_mock_provider_runs_on_real_worker_and_returns_downloadable_output(agent_context, monkeypatch):
    from app.workers.tasks import jobs as worker
    from app.providers.base import ProviderOutput, ProviderResult
    from app.models.content import GeneratedOutput
    ctx = agent_context
    ctx["settings"].agent_control_writes_enabled = ctx["settings"].agent_control_model_calls_enabled = True
    first = await plan(ctx)
    submitted = (await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))).json()
    calls = []
    class MockProvider:
        async def execute(self, **kwargs):
            calls.append(kwargs["capability"])
            return ProviderResult([ProviderOutput(PNG, "image/png", "mock.png")], provider_request_id="mock-only")
    monkeypatch.setattr(worker, "get_settings", lambda: ctx["settings"])
    monkeypatch.setattr(worker, "get_engine", lambda: ctx["engine"])
    monkeypatch.setattr(worker, "get_redis_client", lambda: ctx["redis"])
    monkeypatch.setattr(worker, "get_storage_service", lambda: ctx["storage"])
    monkeypatch.setattr(worker, "get_provider_adapter", lambda *args: MockProvider())
    await worker._execute_job(submitted["jobs"][0]["id"])
    async with ctx["session_factory"]() as db:
        output = await db.scalar(select(GeneratedOutput))
        assert output is not None
        asset_id = output.asset_id
    assert calls == ["image_edit"]
    downloaded = await ctx["client"].get(f"/api/v1/assets/{asset_id}/download", headers=ctx["headers"])
    assert downloaded.status_code == 200 and downloaded.content.startswith(b"\x89PNG")
    resumed = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/resume", headers=ctx["headers"])
    assert resumed.json()["status"] == "completed"


async def test_text_planner_result_needs_a_new_image_confirmation(agent_context):
    import json
    ctx = agent_context
    ctx["settings"].agent_control_planner = "existing_text"
    ctx["settings"].agent_control_writes_enabled = ctx["settings"].agent_control_model_calls_enabled = True
    first = await plan(ctx)
    sent = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))
    assert sent.status_code == 200, sent.text
    planner_id = sent.json()["jobs"][0]["id"]
    async with ctx["session_factory"]() as db:
        planner = await db.get(Job, planner_id)
        assert planner.capability == "text_generation" and planner.max_attempts == 1
        planner.status = "succeeded"
        planner.result_json = {"metadata": {"text": json.dumps({"intent": "generate", "summary": "生成已选套图"})}}
        await db.commit()
    reviewed = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/resume", headers=ctx["headers"])
    assert reviewed.status_code == 200, reviewed.text
    second = reviewed.json()
    assert second["status"] == "awaiting_confirmation"
    assert second["plan"]["actions"][0]["tool"] == "submit_tryon_batch"
    assert second["confirmation_token"] != first["confirmation_token"]
    old = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))
    assert old.status_code == 403
    image = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(second))
    assert image.status_code == 200, image.text
    async with ctx["session_factory"]() as db:
        jobs = (await db.scalars(select(Job).where(Job.capability == "image_edit"))).all()
        assert len(jobs) == 1
        jobs[0].status = "succeeded"
        await db.commit()
    # Consumed planner results must never produce an endless sequence of new image plans.
    done = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/resume", headers=ctx["headers"])
    assert done.json()["status"] == "completed"


async def test_detailed_analysis_uses_existing_workflow_not_a_new_provider(agent_context):
    ctx = agent_context
    ctx["settings"].agent_control_writes_enabled = ctx["settings"].agent_control_model_calls_enabled = True
    payload = {**request(ctx, content="Luna分析"), "prompt_kind": "analysis"}
    pending = await ctx["client"].post(f"/api/v1/agent/conversations/{ctx['conversation']['id']}/messages", headers=ctx["headers"], json=payload)
    assert pending.status_code == 200, pending.text
    first = pending.json()
    confirmed = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))
    assert confirmed.status_code == 200, confirmed.text
    async with ctx["session_factory"]() as db:
        jobs = (await db.scalars(select(Job))).all()
        assert len(jobs) == 1 and jobs[0].operation_code == "batch_tryon.prompt_analyze_detailed"
        assert jobs[0].input_json["system_prompt"] == payload["prompt"]


async def test_font_references_are_never_silently_dropped(agent_context):
    ctx = agent_context
    font = await upload(ctx["client"], ctx["headers"], "style_reference", "font.png")
    await ctx["client"].post(f"/api/v1/projects/{ctx['project']['id']}/assets", headers=ctx["headers"], json={"asset_id": font["id"], "role": "font_reference"})
    blocked = await ctx["client"].post(f"/api/v1/agent/conversations/{ctx['conversation']['id']}/messages", headers=ctx["headers"], json=request(ctx))
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "agent.font_context_required"


async def test_attachment_adapter_reuses_hermes_without_creating_duplicate_plans(agent_context):
    from tests.test_hermes_agent import _project
    from app.services.hermes_tool_registry import load_hermes_workbench_context
    from app.models.attachment_planning import AttachmentWorkbenchPlan
    ctx = agent_context
    project_id, user_id = await _project(ctx)
    async with ctx["session_factory"]() as db:
        await load_hermes_workbench_context(db, organization_id=ctx["first_org"], project_id=project_id, user_id=user_id)
        await db.commit()
        before = await db.scalar(select(func.count(AttachmentWorkbenchPlan.id)))
    conv = await ctx["client"].post("/api/v1/agent/conversations", headers=ctx["headers"], json={"project_id": project_id, "context_kind": "attachment"})
    assert conv.status_code == 201, conv.text
    first = await ctx["client"].post(f"/api/v1/agent/conversations/{conv.json()['id']}/messages", headers=ctx["headers"],
        json={"content": "查看项目", "client_request_id": str(uuid4())})
    assert first.status_code == 200, first.text
    read = await ctx["client"].post(f"/api/v1/agent/runs/{first.json()['id']}/confirm", headers=ctx["headers"], json=ticket(first.json()))
    assert read.status_code == 200, read.text
    assert read.json()["result"]["actions"][0]["result"]["legacy_tools"]
    async with ctx["session_factory"]() as db:
        assert await db.scalar(select(func.count(AttachmentWorkbenchPlan.id))) == before
    old = await ctx["client"].get(f"/api/v1/attachment-workbench/projects/{project_id}/hermes/conversations/{conv.json()['id']}", headers=ctx["headers"])
    assert old.status_code == 404


async def test_wrong_prompt_kind_does_not_send_analysis_instructions_to_image_model(agent_context):
    ctx = agent_context
    payload = {**request(ctx), "prompt_kind": "analysis"}
    blocked = await ctx["client"].post(f"/api/v1/agent/conversations/{ctx['conversation']['id']}/messages", headers=ctx["headers"], json=payload)
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "agent.prompt_kind_mismatch"


async def test_agent_audits_and_events_redact_credentials(agent_context):
    ctx = agent_context
    payload = {**request(ctx, content="检查提示词"), "prompt": "保留当前服装 sk-12345678901234567890 Authorization: Bearer hidden-value"}
    first = (await ctx["client"].post(f"/api/v1/agent/conversations/{ctx['conversation']['id']}/messages", headers=ctx["headers"], json=payload)).json()
    sent = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))
    assert sent.status_code == 200, sent.text
    async with ctx["session_factory"]() as db:
        audits = (await db.scalars(select(HermesToolAudit))).all()
        events = (await db.scalars(select(AgentEvent))).all()
        logs = str([(a.arguments_json, a.result_json) for a in audits]) + str([e.payload for e in events])
        assert "sk-12345678901234567890" not in logs and "hidden-value" not in logs


async def test_remote_unknown_is_observed_without_any_resubmission(agent_context):
    ctx = agent_context
    ctx["settings"].agent_control_writes_enabled = ctx["settings"].agent_control_model_calls_enabled = True
    first = await plan(ctx)
    result = (await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/confirm", headers=ctx["headers"], json=ticket(first))).json()
    async with ctx["session_factory"]() as db:
        job = await db.get(Job, result["jobs"][0]["id"])
        job.status, job.error_code = "failed", "provider.request_timeout"
        assert job.max_attempts == 1
        await db.commit()
    for _ in range(2):
        observed = await ctx["client"].post(f"/api/v1/agent/runs/{first['id']}/resume", headers=ctx["headers"])
        assert observed.json()["status"] == "remote_unknown"
    async with ctx["session_factory"]() as db:
        assert await db.scalar(select(func.count(Job.id))) == 2
