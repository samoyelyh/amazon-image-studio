import base64
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from app.core.config import Settings
from app.providers.base import ProviderError
from app.providers.openai_compatible import NewAPIProvider
from app.providers.openai_responses import build_responses_image_request, parse_responses_images
from tests.test_provider_adapters import install_transport


MODEL = "gpt-6.1-terra"
CONFIG = {"image_api_mode": "responses", "image_generation_model": "gpt-image-2.5-flare",
    "responses_multi_output_enabled": True}


def png(color):
    stream = BytesIO()
    Image.new("RGB", (4, 4), color).save(stream, "PNG")
    return stream.getvalue()


def payload(n=2):
    return {"prompt": "将图A和图B的编号组合生成独立结果，不要拼图。", "n": n,
        "size": "1536x2048", "quality": "high", "reference_images": [
            {"content": png("red"), "mime_type": "image/png"},
            {"content": png("blue"), "mime_type": "image/png"}]}


def response_body(colors=("red", "blue"), model=MODEL):
    return {"id": "resp-1", "status": "completed", "model": model, "output": [
        {"id": f"call-{i}", "type": "image_generation_call", "status": "completed",
            "result": base64.b64encode(png(color)).decode()} for i, color in enumerate(colors)]}


def parse(body):
    return parse_responses_images(body, expected_count=2, max_bytes=1024, requested_model=MODEL)


@pytest.mark.parametrize("model", [MODEL, "gpt-6-sol"])
async def test_online_multi_output_is_one_responses_post_with_exact_requested_model(monkeypatch, model):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        assert body["model"] == model
        assert body["max_tool_calls"] == 2
        assert body["store"] is False and body["stream"] is False
        assert "n" not in body
        assert body["tools"][0]["model"] == "gpt-image-2.5-flare"
        assert body["tools"][0]["quality"] == "high"
        assert body["tools"][0]["size"] == "1536x2048"
        assert [item["type"] for item in body["input"][0]["content"]] == ["input_text", "input_image", "input_image"]
        return httpx.Response(200, json=response_body(model=model))

    install_transport(monkeypatch, handler)
    result = await NewAPIProvider(Settings(_env_file=None)).execute(base_url="https://relay.example/v1",
        api_key="test-secret", upstream_model=model, capability="image_edit", payload=payload(), config=CONFIG)
    assert len(requests) == 1
    assert [out.content for out in result.outputs] == [png("red"), png("blue")]
    assert result.metadata["output_transform"] == "none"
    assert result.metadata["image_generation_call_count"] == 2
    assert result.metadata["mapping_status"] == "needs_visual_review"
    assert result.metadata["output_call_ids"] == ["call-0", "call-1"]
    assert result.metadata["controller_model"] == model


@pytest.mark.parametrize("count", [0, 1, 3])
def test_incorrect_result_count_does_not_pass_or_get_split(count):
    body = response_body(("red", "blue", "green")[:count])
    with pytest.raises(ProviderError) as error:
        parse(body)
    assert error.value.code == "provider.multi_output_count_mismatch"


def test_duplicate_images_do_not_pass():
    with pytest.raises(ProviderError) as error:
        parse(response_body(("red", "red")))
    assert error.value.code == "provider.multi_output_duplicate"


@pytest.mark.parametrize("status", ["incomplete", "failed", "in_progress"])
def test_partial_responses_do_not_pass_even_with_images(status):
    body = response_body(); body["status"] = status
    with pytest.raises(ProviderError) as error:
        parse(body)
    assert error.value.code == "provider.response_incomplete"


def test_model_cannot_silently_change_to_another_terra():
    body = response_body(); body["model"] = "gpt-5.6-terra"
    with pytest.raises(ProviderError) as error:
        parse(body)
    assert error.value.code == "provider.model_mismatch"


def test_unverified_multi_output_is_blocked_before_network():
    with pytest.raises(ProviderError) as error:
        build_responses_image_request(upstream_model=MODEL, capability="image_edit", payload=payload(), config={})
    assert error.value.code == "provider.multi_output_not_verified"


async def test_relay_compatibility_omits_only_explicitly_unsupported_call_limit(monkeypatch):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        body = json.loads(request.content)
        assert body["model"] == "gpt-6-sol"
        assert "max_tool_calls" not in body
        assert body["tool_choice"] == {"type": "image_generation"}
        assert "exactly 2" in body["instructions"]
        return httpx.Response(200, json=response_body(model="gpt-6-sol"))

    install_transport(monkeypatch, handler)
    result = await NewAPIProvider(Settings(_env_file=None)).execute(base_url="https://relay.example/v1",
        api_key="test-secret", upstream_model="gpt-6-sol", capability="image_edit", payload=payload(),
        config={**CONFIG, "responses_supports_max_tool_calls": False})
    assert count == 1 and len(result.outputs) == 2
    assert result.metadata["submitted_tool_call_limit"] is None


def test_mask_is_not_silently_ignored():
    inputs = {**payload(), "mask_image": {"content": png("white")}}
    with pytest.raises(ProviderError) as error:
        build_responses_image_request(upstream_model=MODEL, capability="mask_edit", payload=inputs, config=CONFIG)
    assert error.value.code == "provider.unsupported_capability"


def test_invalid_base64_and_non_image_bytes_are_rejected():
    for invalid in ("invalid**base64", base64.b64encode(b"not an image").decode()):
        body = response_body(); body["output"][0]["result"] = invalid
        with pytest.raises(ProviderError) as error:
            parse(body)
        assert error.value.code == "provider.invalid_image"


@pytest.mark.parametrize("n", [0, 11, True, 2.5, "4"])
def test_invalid_n_is_not_coerced(n):
    with pytest.raises(ProviderError) as error:
        build_responses_image_request(upstream_model=MODEL, capability="image_edit", payload=payload(n), config=CONFIG)
    assert error.value.code == "provider.invalid_output_count"


async def test_model_not_found_is_clear_non_retryable_and_has_no_fallback(monkeypatch):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        assert json.loads(request.content)["model"] == MODEL
        return httpx.Response(503, json={"error": {"code": "model_not_found",
            "message": "No available channel; test-secret sk-dont-print-1234567890"}})

    install_transport(monkeypatch, handler)
    with pytest.raises(ProviderError) as error:
        await NewAPIProvider(Settings(_env_file=None)).execute(base_url="https://relay.example/v1",
            api_key="test-secret", upstream_model=MODEL, capability="image_edit", payload=payload(), config=CONFIG)
    assert count == 1
    assert error.value.code == "provider.model_unavailable" and not error.value.retryable
    assert "未切换其他型号" in error.value.message
    assert "test-secret" not in error.value.message and "sk-dont" not in error.value.message


def test_safety_identifier_is_hashed_not_plaintext():
    inputs = {**payload(), "metadata": {"safety_identifier": "internal-user-id"}}
    request = build_responses_image_request(upstream_model=MODEL, capability="image_edit", payload=inputs, config=CONFIG)
    assert len(request["safety_identifier"]) == 64
    assert "internal-user-id" not in json.dumps(request)
