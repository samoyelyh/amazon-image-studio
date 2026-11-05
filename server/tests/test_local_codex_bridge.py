import asyncio
import base64
import json
import os
from pathlib import Path
from uuid import uuid4
from pydantic import ValidationError

import httpx
import pytest

from app.local_codex_bridge.api import create_bridge_app
from app.local_codex_bridge.core import (
    BridgeError, BridgeSettings, ExecutionInput, ExecutionManager, Reference,
    image_metadata, safe_environment, write_json,
    classify_failure,
)


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def settings(tmp_path):
    return BridgeSettings(access_token="test-bridge-token-" + "x" * 40, data_dir=tmp_path / "state", codex_home=tmp_path / "codex")


def payload(**kwargs):
    return ExecutionInput(job_id=uuid4(), model="gpt-6.1-terra", capability="image_edit", prompt="Keep the layout. Replace the garment.",
                          reference_images=[Reference(filename="shirt.png", mime_type="image/png", data_base64=base64.b64encode(PNG).decode())], **kwargs)


async def ready():
    return None


def test_concurrency_remains_opt_in_and_bounded(tmp_path):
    assert settings(tmp_path).max_concurrency == 1
    assert BridgeSettings(access_token="x" * 40, data_dir=tmp_path, max_concurrency=12).max_concurrency == 12
    with pytest.raises(ValidationError):
        BridgeSettings(access_token="x" * 40, data_dir=tmp_path, max_concurrency=13)


def test_numeric_token_counts_do_not_become_auth_failures():
    assert classify_failure('"input_tokens": 40123, "output_tokens": 401')['code'] == 'codex.no_output'
    assert classify_failure('connection failed: tls handshake eof; input_tokens=40123')['code'] == 'codex.connection'
    assert classify_failure('HTTP 401 Unauthorized')['code'] == 'codex.auth'
    assert classify_failure('status code: 401')['code'] == 'codex.auth'


async def test_twelve_native_slots_and_thirteenth_rejected(tmp_path, monkeypatch):
    manager = ExecutionManager(settings(tmp_path).model_copy(update={"max_concurrency": 12}))
    monkeypatch.setattr(manager, "ready", ready)
    gate = asyncio.Event()

    async def blocked(*args):
        await gate.wait()

    monkeypatch.setattr(manager, "execute", blocked)
    try:
        for _ in range(12):
            await manager.submit(payload())
        assert len(manager.tasks) == 12
        with pytest.raises(BridgeError) as error:
            await manager.submit(payload())
        assert error.value.code == "codex.busy"
    finally:
        for task in manager.tasks.values():
            task.cancel()
        await asyncio.gather(*manager.tasks.values(), return_exceptions=True)


def test_safe_environment_removes_api_credentials(monkeypatch):
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "AZURE_OPENAI_API_KEY"):
        monkeypatch.setenv(key, "must-not-be-forwarded")
    assert all(key not in safe_environment() for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "AZURE_OPENAI_API_KEY"))


def test_images_are_validated_without_transforming_bytes():
    assert image_metadata(PNG, 1000)["width"] == 1
    with pytest.raises(BridgeError):
        image_metadata(b"not an image", 1000)
    with pytest.raises(BridgeError):
        image_metadata(PNG, 1)


async def test_readiness_auth_and_no_generation(tmp_path, monkeypatch):
    app = create_bridge_app(settings(tmp_path))
    checks = []

    async def check():
        checks.append(True)

    monkeypatch.setattr(app.state.manager, "ready", check)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bridge") as client:
        assert (await client.get("/v1/models")).status_code == 401
        response = await client.get("/v1/models", headers={"Authorization": "Bearer " + app.state.manager.settings.access_token.get_secret_value()})
        assert response.status_code == 200 and response.json()["data"][0]["id"] == "gpt-6.1-terra"
    assert len(checks) == 1 and not app.state.manager.tasks


async def test_duplicate_and_conflict_do_not_start_another_process(tmp_path, monkeypatch):
    manager = ExecutionManager(settings(tmp_path))
    monkeypatch.setattr(manager, "ready", ready)
    gate = asyncio.Event()
    calls = []

    async def blocked(*args):
        calls.append(args)
        await gate.wait()

    monkeypatch.setattr(manager, "execute", blocked)
    request = payload()
    first = await manager.submit(request)
    second = await manager.submit(request)
    await asyncio.sleep(0)
    assert first == second and len(calls) == 1
    changed = request.model_copy(update={"prompt": "different prompt"})
    with pytest.raises(BridgeError, match="相同任务ID"):
        await manager.submit(changed)
    with pytest.raises(BridgeError) as full:
        await manager.submit(payload())
    assert full.value.status == 429
    await manager.cancel(str(request.job_id))
    assert manager.state(request.job_id)["status"] == "cancelled" and not manager.tasks


async def test_cancel_before_process_starts(tmp_path, monkeypatch):
    manager = ExecutionManager(settings(tmp_path))
    monkeypatch.setattr(manager, "ready", ready)
    request = payload()
    await manager.submit(request)
    state = await manager.cancel(str(request.job_id))
    assert state["status"] == "cancelled" and not manager.tasks


async def test_restart_is_fail_closed_not_automatic_regeneration(tmp_path, monkeypatch):
    config = settings(tmp_path)
    manager = ExecutionManager(config)
    request = payload()
    folder = manager.folder(request.job_id)
    folder.mkdir()
    write_json(folder / "state.json", {"job_id": str(request.job_id), "status": "running", "input_hash": "x"})
    restarted = ExecutionManager(config)
    monkeypatch.setattr(restarted, "ready", ready)
    assert restarted.state(request.job_id)["status"] == "interrupted" and not restarted.tasks
    with pytest.raises(BridgeError) as interrupted:
        await restarted.submit(payload())
    assert interrupted.value.code == "codex.execution_unknown"


async def test_real_artifact_required_and_copied_verbatim(tmp_path, monkeypatch):
    config = settings(tmp_path)
    manager = ExecutionManager(config)
    monkeypatch.setattr(manager, "ready", ready)
    thread = str(uuid4())
    output = config.codex_home / "generated_images" / thread / "new.png"

    class Process:
        returncode = 0
        pid = 12345

        async def communicate(self, prompt):
            assert b"<business_prompt>" in prompt
            output.parent.mkdir(parents=True)
            output.write_bytes(PNG)
            events = [{"type": "thread.started", "thread_id": thread}, {"type": "turn.completed"}]
            return "\n".join(json.dumps(e) for e in events).encode(), b""

    async def spawn(*args, **kwargs):
        assert "image_generation" in args and "--no-daemon" in args
        assert "OPENAI_API_KEY" not in kwargs["env"]
        return Process()

    (config.codex_home / "skills/.system/imagegen").mkdir(parents=True)
    (config.codex_home / "skills/.system/imagegen/SKILL.md").write_text("Built-in only", encoding="utf-8")
    monkeypatch.setattr("app.local_codex_bridge.core.asyncio.create_subprocess_exec", spawn)
    request = payload()
    await manager.submit(request)
    await manager.tasks[str(request.job_id)]
    state = manager.state(request.job_id)
    assert state["status"] == "succeeded" and state["metadata"]["output_count"] == 1
    assert (manager.folder(request.job_id) / "output.png").read_bytes() == PNG
    # Repeated delivery is a result replay, not another invocation.
    assert (await manager.submit(request))["status"] == "succeeded"


async def test_claimed_success_without_artifact_fails(tmp_path, monkeypatch):
    config = settings(tmp_path)
    manager = ExecutionManager(config)
    monkeypatch.setattr(manager, "ready", ready)
    (config.codex_home / "skills/.system/imagegen").mkdir(parents=True)
    (config.codex_home / "skills/.system/imagegen/SKILL.md").write_text("Built-in only", encoding="utf-8")

    class Process:
        returncode = 0
        pid = 12345

        async def communicate(self, prompt):
            events = [{"type": "thread.started", "thread_id": str(uuid4())},
                      {"type": "item.completed", "item": {"type": "agent_message", "text": '{"status":"generated","output_path":"C:/unrelated.png"}'}},
                      {"type": "turn.completed"}]
            return "\n".join(json.dumps(e) for e in events).encode(), b""

    async def spawn(*args, **kwargs):
        return Process()

    monkeypatch.setattr("app.local_codex_bridge.core.asyncio.create_subprocess_exec", spawn)
    request = payload()
    await manager.submit(request)
    await manager.tasks[str(request.job_id)]
    assert manager.state(request.job_id)["status"] == "failed"
    assert not (manager.folder(request.job_id) / "output.png").exists()


def test_cli_arguments_preserve_reference_order_and_disable_other_tools(tmp_path):
    manager = ExecutionManager(settings(tmp_path))
    paths = [tmp_path / "A.png", tmp_path / "B.png", tmp_path / "C.png"]
    args = manager.command(tmp_path, paths)
    assert args[-7:] == ["--image", str(paths[0]), "--image", str(paths[1]), "--image", str(paths[2]), "-"]
    for name in ("shell_tool", "hooks", "plugins", "multi_agent"):
        index = args.index(name)
        assert args[index - 1] == "--disable"
