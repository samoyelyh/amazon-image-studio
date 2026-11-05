import asyncio
import base64
import json
from uuid import UUID

import httpx
import pytest

from app.core.config import Settings
from app.models.tasks import ProviderType
from app.providers import CodexLocalProvider, ProviderError, ProviderOutput, ProviderResult
from app.providers import codex_local
from app.providers.registry import get_provider_adapter
from app.schemas.tasks import ProviderCreateRequest
from app.services.provider_test_service import probe_provider_models, probe_provider_operation


JOB_ID = "12345678-1234-4234-8234-123456789abc"
TOKEN = "internal-bridge-test-token-not-openai-1234"
BASE_URL = "http://bridge.test:8765/v1"
EXECUTION = f"/v1/executions/{JOB_ID}"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
PRIVATE = f"{TOKEN} C:\\private\\bridge.log data_base64=private-image"


def state(status="succeeded", **extra):
    return httpx.Response(200, json={"job_id": JOB_ID, "status": status, **extra})


def image_response(**kwargs):
    return httpx.Response(200, content=PNG, headers={"content-type": "image/png"}, **kwargs)


@pytest.fixture
def settings():
    return Settings(_env_file=None)


@pytest.fixture(autouse=True)
def bridge_http(monkeypatch):
    """Fail closed: every client in this file is mocked, including diagnostics."""
    original_client = httpx.AsyncClient
    observed = {"requests": [], "clients": [], "sleeps": []}

    def unexpected(request):
        raise AssertionError(f"Unexpected mocked request: {request.method} {request.url.path}")

    observed["handler"] = unexpected

    async def handle(request):
        observed["requests"].append(request)
        result = observed["handler"](request)
        return await result if hasattr(result, "__await__") else result

    def factory(*args, **kwargs):
        observed["clients"].append(kwargs.copy())
        if kwargs.get("transport") is None:
            kwargs["transport"] = httpx.MockTransport(handle)
        return original_client(*args, **kwargs)

    async def quick_sleep(seconds):
        observed["sleeps"].append(seconds)
        await asyncio.sleep(0)

    monkeypatch.setattr(codex_local.httpx, "AsyncClient", factory)
    monkeypatch.setattr(codex_local, "sleep", quick_sleep)
    return observed


async def execute(settings, *, payload=None, capability="image_generation", config=None, **kwargs):
    return await CodexLocalProvider(settings).execute(
        base_url=kwargs.pop("base_url", BASE_URL), api_key=kwargs.pop("api_key", TOKEN),
        upstream_model="native-image-model", capability=capability,
        payload={"job_id": JOB_ID, "prompt": "Test image", **(payload or {})},
        config=config or {}, **kwargs,
    )


def test_registry_exports_enum_and_create_schema(settings):
    assert ProviderType.CODEX_LOCAL.value == "codex_local"
    assert isinstance(get_provider_adapter("codex_local", settings), CodexLocalProvider)
    parsed = ProviderCreateRequest(
        code="native-codex", name="Native Codex", provider_type="codex_local", base_url=BASE_URL,
    )
    assert parsed.provider_type == "codex_local"
    for provider_type in ("openai_compatible", "new_api", "custom"):
        assert not isinstance(get_provider_adapter(provider_type, settings), CodexLocalProvider)


async def test_ordered_references_contract_no_secrets_or_untrusted_metadata(settings, bridge_http, caplog):
    polls = 0

    def handler(request):
        nonlocal polls
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if request.method == "POST":
            body = json.loads(request.content)
            assert body == {
                "job_id": JOB_ID, "model": "native-image-model", "capability": "multi_image_reference",
                "prompt": "Test image", "n": 1, "size": "1024x1536", "quality": "high",
                "reference_images": [
                    {"filename": "model.png", "mime_type": "image/png", "data_base64": base64.b64encode(b"model").decode()},
                    {"filename": "garment.jpg", "mime_type": "image/jpeg", "data_base64": base64.b64encode(b"garment").decode()},
                ],
            }
            assert TOKEN not in request.content.decode()
            assert "api_key" not in body and "_cancel_requested" not in body
            return state("running")
        if request.url.path.endswith("/output"):
            return image_response()
        assert request.url.path == EXECUTION
        polls += 1
        return state("running" if polls == 1 else "succeeded", metadata={"stderr": PRIVATE, "data_base64": PRIVATE})

    async def not_cancelled():
        return False

    bridge_http["handler"] = handler
    result = await execute(settings, capability="multi_image_reference", payload={
        "size": "1024x1536", "quality": "high", "api_key": TOKEN, "extra": "ignored",
        "_cancel_requested": not_cancelled,
        "reference_images": [
            {"content": b"model", "filename": r"C:\private\model.png", "mime_type": "image/png"},
            {"content": b"garment", "filename": "/private/garment.jpg", "mime_type": "image/jpeg"},
        ],
    })
    assert result.outputs == [ProviderOutput(PNG, "image/png", "generated-1.png")]
    assert result.provider_request_id == JOB_ID
    assert result.metadata == {"job_id": JOB_ID, "status": "succeeded"}
    assert TOKEN not in repr(result) + caplog.text and PRIVATE not in repr(result) + caplog.text
    assert bridge_http["sleeps"] and set(bridge_http["sleeps"]) == {1.0}
    assert bridge_http["clients"][0]["trust_env"] is False


@pytest.mark.parametrize(("status", "host_code", "expected", "retryable"), [
    (429, "codex.busy", "provider.rate_limited", True),
    (503, "codex.auth", "provider.invalid_api_key", False),
    (409, "codex.idempotency_conflict", "provider.idempotency_conflict", False),
    (409, "codex.execution_unknown", "provider.execution_unknown", False),
])
async def test_explicit_admission_failure_is_not_polled_forever(settings, bridge_http, status, host_code, expected, retryable):
    bridge_http["handler"] = lambda request: httpx.Response(status, json={"error": {"code": host_code, "message": PRIVATE}})
    with pytest.raises(ProviderError) as error:
        await execute(settings)
    assert error.value.code == expected and error.value.retryable is retryable
    assert len(bridge_http["requests"]) == 1 and PRIVATE not in str(error.value)
    assert bridge_http["clients"][0]["follow_redirects"] is False


async def test_generation_and_edit_submit_one_image_without_extra_fields(settings, bridge_http):
    bodies = []

    def handler(request):
        if request.method == "POST":
            bodies.append(json.loads(request.content))
            return state()
        return image_response()

    bridge_http["handler"] = handler
    await execute(settings)
    await execute(settings, capability="image_edit", payload={"reference_images": [{"content": PNG}]})
    assert bodies[0]["n"] == 1 and bodies[0]["reference_images"] == []
    assert "size" not in bodies[0] and "quality" not in bodies[0]
    assert bodies[1]["reference_images"][0]["filename"] == "reference-1.png"
    assert all(request.url.path != EXECUTION for request in bridge_http["requests"])


@pytest.mark.parametrize("job_id", [None, "", "bad", JOB_ID.upper(), JOB_ID.replace("-", ""), 123])
async def test_requires_caller_canonical_uuid(settings, bridge_http, job_id):
    with pytest.raises(ProviderError) as error:
        await execute(settings, payload={"job_id": job_id})
    assert error.value.code == "provider.invalid_job_id"
    assert bridge_http["requests"] == []


async def test_missing_job_id_is_not_generated_by_adapter(settings, bridge_http):
    with pytest.raises(ProviderError, match="UUID"):
        await CodexLocalProvider(settings).execute(
            base_url=BASE_URL, api_key=TOKEN, upstream_model="native", capability="image_generation",
            payload={"prompt": "Test"}, config={},
        )
    assert not bridge_http["requests"]


@pytest.mark.parametrize(("capability", "payload"), [
    ("mask_edit", {}), ("text_generation", {}), ("image_edit", {"mask_image": None}),
    ("image_generation", {"mask_image": {"content": PNG}}), ("image_edit", {"mask_asset_id": "asset"}),
])
async def test_unsupported_capabilities_and_masks_rejected(settings, bridge_http, capability, payload):
    with pytest.raises(ProviderError) as error:
        await execute(settings, capability=capability, payload=payload)
    assert error.value.code == "provider.unsupported_capability"
    assert not bridge_http["requests"]


@pytest.mark.parametrize(("capability", "payload", "code"), [
    ("image_generation", {"n": 2}, "provider.invalid_payload"),
    ("image_generation", {"n": True}, "provider.invalid_payload"),
    ("image_generation", {"prompt": " "}, "provider.invalid_payload"),
    ("image_generation", {"size": {}}, "provider.invalid_payload"),
    ("image_generation", {"quality": 1}, "provider.invalid_payload"),
    ("image_generation", {"_cancel_requested": True}, "provider.invalid_payload"),
    ("image_edit", {}, "provider.missing_reference"),
    ("multi_image_reference", {"reference_images": [{"content": PNG}]}, "provider.missing_reference"),
    ("image_edit", {"reference_images": "bad"}, "provider.invalid_reference"),
    ("image_edit", {"reference_images": [None]}, "provider.invalid_reference"),
    ("image_edit", {"reference_images": [{"content": b""}]}, "provider.invalid_reference"),
    ("image_edit", {"reference_images": [{"content": "encoded"}]}, "provider.invalid_reference"),
    ("image_edit", {"reference_images": [{"content": PNG, "mime_type": "text/html"}]}, "provider.invalid_reference"),
])
async def test_payload_validation_before_network(settings, bridge_http, capability, payload, code):
    with pytest.raises(ProviderError) as error:
        await execute(settings, capability=capability, payload=payload)
    assert error.value.code == code
    assert not bridge_http["requests"]


@pytest.mark.parametrize("base_url", ["http://bridge.test", "file:///v1", "http://user:password@bridge.test/v1", "http://bridge.test/v1?key=secret"])
async def test_invalid_base_url_is_safe(settings, bridge_http, base_url):
    with pytest.raises(ProviderError) as error:
        await execute(settings, base_url=base_url)
    assert error.value.code == "provider.invalid_base_url" and base_url not in error.value.message
    assert not bridge_http["requests"]


async def test_internal_token_validation(settings, bridge_http):
    with pytest.raises(ProviderError) as error:
        await execute(settings, api_key="x" * 31)
    assert error.value.code == "provider.invalid_api_key" and not bridge_http["requests"]


@pytest.mark.parametrize(("status", "code"), [(401, "provider.invalid_api_key"), (403, "provider.model_forbidden"), (404, "provider.endpoint_not_found"), (302, "provider.upstream_error"), (422, "provider.upstream_error")])
async def test_http_errors_are_fixed_safe_chinese_and_redirects_not_followed(settings, bridge_http, status, code):
    bridge_http["handler"] = lambda request: httpx.Response(status, text=PRIVATE, headers={"location": "https://external.invalid/leak"})
    with pytest.raises(ProviderError) as error:
        await execute(settings)
    assert error.value.code == code and error.value.http_status == status
    assert error.value.retryable is False and PRIVATE not in str(error.value)
    assert len(bridge_http["requests"]) == 1


@pytest.mark.parametrize("body", [
    [], {}, {"job_id": "another", "status": "succeeded"}, {"job_id": JOB_ID, "status": "queued"},
    {"job_id": JOB_ID, "status": []}, {"job_id": JOB_ID, "status": "succeeded", "metadata": "bad"},
    {"job_id": JOB_ID, "status": "failed", "error": {}},
    {"job_id": JOB_ID, "status": "failed", "error": {"code": "bad", "message": PRIVATE, "retryable": "true"}},
])
async def test_malformed_states_never_download_or_leak(settings, bridge_http, body):
    bridge_http["handler"] = lambda request: httpx.Response(200, json=body)
    with pytest.raises(ProviderError) as error:
        await execute(settings)
    assert error.value.code == "provider.invalid_response" and not error.value.retryable
    assert PRIVATE not in str(error.value) and len(bridge_http["requests"]) == 1


async def test_non_json_state(settings, bridge_http):
    bridge_http["handler"] = lambda request: httpx.Response(200, text=PRIVATE)
    with pytest.raises(ProviderError) as error:
        await execute(settings)
    assert error.value.code == "provider.invalid_response" and PRIVATE not in str(error.value)


@pytest.mark.parametrize(("status", "retryable", "code"), [("failed", False, "provider.execution_failed"), ("failed", True, "provider.execution_failed"), ("interrupted", False, "provider.interrupted"), ("cancelled", True, "provider.cancelled")])
async def test_terminal_states_use_safe_errors(settings, bridge_http, status, retryable, code):
    bridge_http["handler"] = lambda request: state(status, error={"code": PRIVATE, "message": PRIVATE, "retryable": retryable})
    with pytest.raises(ProviderError) as error:
        await execute(settings)
    assert error.value.code == code
    assert error.value.retryable is (retryable if status != "cancelled" else False)
    assert PRIVATE not in str(error.value)
    assert not any(request.url.path.endswith("/output") for request in bridge_http["requests"])


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


@pytest.mark.parametrize(("mime", "content", "length", "code"), [
    ("image/jpeg", PNG, None, "provider.invalid_output_type"),
    (None, PNG, None, "provider.invalid_output_type"),
    ("image/png", b"not-png", None, "provider.invalid_image"),
    ("image/png", b"\x89PNG\r\n\x1a\n", None, "provider.invalid_image"),
    ("image/png", PNG, "999999", "provider.output_too_large"),
    ("image/png", PNG + b"x" * 200, None, "provider.output_too_large"),
    ("image/png", PNG, "invalid", "provider.invalid_response"),
    ("image/png", PNG, "-1", "provider.invalid_response"),
])
async def test_output_mime_magic_length_and_stream_limit(settings, bridge_http, mime, content, length, code):
    settings = settings.model_copy(update={"provider_output_max_bytes": 100})

    def handler(request):
        if request.method == "POST":
            return state()
        headers = {}
        if mime is not None:
            headers["content-type"] = mime
        if length is not None:
            headers["content-length"] = length
        return httpx.Response(200, stream=Chunks([content[:10], content[10:]]), headers=headers)

    bridge_http["handler"] = handler
    with pytest.raises(ProviderError) as error:
        await execute(settings)
    assert error.value.code == code and not error.value.retryable


@pytest.mark.parametrize("phase", ["submit", "poll", "output", "submit-503", "poll-404", "poll-429", "output-503"])
async def test_ambiguous_communication_recovers_same_job_without_resubmitting(settings, bridge_http, phase):
    failed = False

    def handler(request):
        nonlocal failed
        target = "submit" if request.method == "POST" else "output" if request.url.path.endswith("/output") else "poll"
        if not failed and phase.startswith(target):
            failed = True
            if "-" in phase:
                return httpx.Response(int(phase.split("-")[1]), text=PRIVATE)
            raise httpx.ReadTimeout(PRIVATE, request=request)
        if target == "submit":
            return state("running")
        return image_response() if target == "output" else state()

    bridge_http["handler"] = handler
    result = await execute(settings)
    assert result.provider_request_id == JOB_ID
    posts = [request for request in bridge_http["requests"] if request.method == "POST"]
    assert len(posts) == 1 and json.loads(posts[0].content)["job_id"] == JOB_ID
    assert all(request.url.path.startswith(EXECUTION) for request in bridge_http["requests"] if request.method == "GET")


@pytest.mark.parametrize("failure", ["timeout", "network", "running", "503", "404", "poll-timeout", "output-timeout"])
async def test_final_unknown_is_nonretryable_and_explicit_retry_reuses_id(settings, bridge_http, failure):
    settings = settings.model_copy(update={"provider_request_timeout_seconds": 0.015})

    def handler(request):
        if failure in {"poll-timeout", "output-timeout"}:
            if request.method == "POST":
                return state("running" if failure == "poll-timeout" else "succeeded")
            if failure == "output-timeout" and not request.url.path.endswith("/output"):
                return state()
            raise httpx.ReadTimeout(PRIVATE, request=request)
        if failure == "running":
            return state("running")
        if failure in {"503", "404"}:
            # Admission may succeed even when a later poll is missing/unavailable.
            return state("running") if request.method == "POST" else httpx.Response(int(failure), text=PRIVATE)
        exception = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
        raise exception(PRIVATE, request=request)

    bridge_http["handler"] = handler
    for _ in range(2):
        with pytest.raises(ProviderError) as error:
            await execute(settings)
        assert error.value.code == "provider.execution_unknown"
        assert error.value.retryable is False and PRIVATE not in str(error.value)
    posts = [request for request in bridge_http["requests"] if request.method == "POST"]
    assert len(posts) == 2 and {json.loads(request.content)["job_id"] for request in posts} == {JOB_ID}
    assert all(request.url.path.startswith(EXECUTION) for request in bridge_http["requests"] if request.method == "GET")


async def test_total_timeout_bounds_stalled_submit(settings, bridge_http):
    settings = settings.model_copy(update={"provider_request_timeout_seconds": 0.015})

    async def handler(request):
        await asyncio.sleep(10)

    bridge_http["handler"] = handler
    with pytest.raises(ProviderError) as error:
        await asyncio.wait_for(execute(settings), timeout=0.5)
    assert error.value.code == "provider.execution_unknown" and not error.value.retryable
    assert len(bridge_http["requests"]) == 1


@pytest.mark.parametrize(("config", "expected"), [({}, 1.0), ({"poll_interval_seconds": 0}, 0.1), ({"poll_interval_seconds": 999}, 5.0), ({"poll_interval_seconds": "0.5"}, 0.5)])
def test_poll_interval_is_bounded(config, expected):
    assert CodexLocalProvider._poll_interval(config) == expected


@pytest.mark.parametrize("value", [None, "invalid", float("nan"), float("inf"), {}])
async def test_invalid_poll_config_is_safe(settings, bridge_http, value):
    with pytest.raises(ProviderError) as error:
        await execute(settings, config={"poll_interval_seconds": value})
    assert error.value.code == "provider.invalid_config" and not bridge_http["requests"]


@pytest.mark.parametrize("phase", ["submit", "poll", "output"])
async def test_callback_cancels_after_submission_even_when_cancel_fails(settings, bridge_http, phase):
    submitted = False

    async def cancelled():
        return submitted

    async def handler(request):
        nonlocal submitted
        if request.url.path.endswith("/cancel"):
            raise httpx.ConnectError(PRIVATE, request=request)
        if request.method == "POST" and phase != "submit":
            return state("running" if phase == "poll" else "succeeded")
        submitted = True
        await asyncio.sleep(10)  # Callback must be checked even during a stalled request.

    bridge_http["handler"] = handler
    with pytest.raises(ProviderError) as error:
        await execute(settings, payload={"_cancel_requested": cancelled})
    assert error.value.code == "provider.cancelled" and not error.value.retryable
    calls = [(request.method, request.url.path) for request in bridge_http["requests"]]
    assert calls[0] == ("POST", "/v1/executions")
    assert calls[-1] == ("POST", f"{EXECUTION}/cancel")
    assert len(calls) == (2 if phase == "submit" else 3)
    assert PRIVATE not in str(error.value)


async def test_callback_cancellation_before_submit_never_generates(settings, bridge_http):
    async def cancelled():
        return True

    bridge_http["handler"] = lambda request: state("cancelled")
    with pytest.raises(ProviderError) as error:
        await execute(settings, payload={"_cancel_requested": cancelled})
    assert error.value.code == "provider.cancelled"
    assert [(request.method, request.url.path) for request in bridge_http["requests"]] == [("POST", f"{EXECUTION}/cancel")]


async def test_output_http_auth_error_is_safe(settings, bridge_http):
    bridge_http["handler"] = lambda request: state() if request.method == "POST" else httpx.Response(401, text=PRIVATE)
    with pytest.raises(ProviderError) as error:
        await execute(settings)
    assert error.value.code == "provider.invalid_api_key" and error.value.retryable is False
    assert PRIVATE not in str(error.value)


async def test_output_stream_total_deadline_does_not_fail_over(settings, bridge_http):
    settings = settings.model_copy(update={"provider_request_timeout_seconds": 0.015})

    class StalledOutput(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield PNG[:8]
            await asyncio.sleep(10)
            yield PNG[8:]

    bridge_http["handler"] = lambda request: state() if request.method == "POST" else httpx.Response(
        200, headers={"content-type": "image/png"}, stream=StalledOutput(),
    )
    with pytest.raises(ProviderError) as error:
        await asyncio.wait_for(execute(settings), timeout=0.5)
    assert error.value.code == "provider.execution_unknown" and error.value.retryable is False
    assert len([request for request in bridge_http["requests"] if request.method == "POST"]) == 1


@pytest.mark.parametrize("stall_cancel", [False, True])
async def test_coroutine_cancellation_attempts_bounded_remote_cancel(settings, bridge_http, stall_cancel):
    settings = settings.model_copy(update={"provider_request_timeout_seconds": 0.05})
    entered_poll = asyncio.Event()

    async def handler(request):
        if request.url.path.endswith("/cancel"):
            if stall_cancel:
                await asyncio.sleep(10)
            return state("cancelled")
        if request.method == "POST":
            return state("running")
        entered_poll.set()
        await asyncio.sleep(10)

    bridge_http["handler"] = handler
    task = asyncio.create_task(execute(settings))
    await asyncio.wait_for(entered_poll.wait(), timeout=0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.5)
    assert [(request.method, request.url.path) for request in bridge_http["requests"]][-1] == ("POST", f"{EXECUTION}/cancel")


@pytest.mark.parametrize("provider_type", ["codex_local", "openai_compatible", "new_api", "custom"])
async def test_diagnostic_assigns_uuid_only_for_codex_local(settings, monkeypatch, provider_type):
    observed = {}

    class FakeAdapter:
        async def execute(self, **kwargs):
            observed.update(kwargs)
            return ProviderResult([ProviderOutput(PNG, "image/png", "test.png")])

    monkeypatch.setattr("app.services.provider_test_service.get_provider_adapter", lambda *args: FakeAdapter())
    result = await probe_provider_operation(
        settings=settings, provider_type=provider_type, base_url=BASE_URL, api_key=TOKEN,
        upstream_model="native", capability="image_generation", provider_config={}, model_config={},
    )
    assert result.success
    if provider_type == "codex_local":
        job_id = observed["payload"]["job_id"]
        assert str(UUID(job_id)) == job_id
        await probe_provider_operation(
            settings=settings, provider_type=provider_type, base_url=BASE_URL, api_key=TOKEN,
            upstream_model="native", capability="image_generation", provider_config={}, model_config={},
        )
        assert observed["payload"]["job_id"] != job_id
    else:
        assert "job_id" not in observed["payload"]


async def test_base_health_uses_authenticated_non_generating_models_only(bridge_http):
    def handler(request):
        assert request.method == "GET" and request.url.path == "/v1/models"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(200, json={"data": [{"id": "native-image-model"}]})

    bridge_http["handler"] = handler
    result = await probe_provider_models(base_url=BASE_URL, api_key=TOKEN, timeout_seconds=1)
    assert result.success and result.models == ["native-image-model"]
    assert len(bridge_http["requests"]) == 1
    assert bridge_http["clients"][0]["trust_env"] is False


async def test_native_reference_limit_rejected_before_network(settings, bridge_http):
    references = [{"content": PNG, "mime_type": "image/png", "filename": "ref.png"}] * 6
    with pytest.raises(ProviderError) as error:
        await execute(settings, capability="multi_image_reference", payload={"reference_images": references})
    assert error.value.code == "provider.too_many_references"
    assert bridge_http["requests"] == []
