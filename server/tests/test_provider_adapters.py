import base64
import json

import httpx

from app.core.config import Settings
from app.providers.openai_compatible import OpenAICompatibleProvider


def install_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr("app.providers.openai_compatible.httpx.AsyncClient", factory)


async def test_text_generation_uses_server_key_and_returns_json_text(monkeypatch) -> None:
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers.get("authorization")
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"product":{"title":"Test"}}'}}]}, headers={"x-request-id": "text-1"})

    install_transport(monkeypatch, handler)
    adapter = OpenAICompatibleProvider(Settings(_env_file=None))
    result = await adapter.execute(
        base_url="https://relay.example/v1", api_key="server-only-secret", upstream_model="chat-model",
        capability="text_generation",
        payload={"system_prompt": "Return JSON", "user_prompt": "Plan listing", "reference_images": [{"content": b"image", "mime_type": "image/png", "filename": "product.png"}]},
        config={},
    )
    assert observed["authorization"] == "Bearer server-only-secret"
    assert observed["body"]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result.outputs == [] and result.metadata["text"] == '{"product":{"title":"Test"}}'


async def test_multi_image_edit_uses_multipart_references(monkeypatch) -> None:
    observed = {}
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")

    def handler(request: httpx.Request) -> httpx.Response:
        observed["content_type"] = request.headers.get("content-type")
        observed["body"] = request.content
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png).decode("ascii")}]})

    install_transport(monkeypatch, handler)
    adapter = OpenAICompatibleProvider(Settings(_env_file=None))
    result = await adapter.execute(
        base_url="https://relay.example/v1", api_key="server-only-secret", upstream_model="image-model",
        capability="multi_image_reference",
        payload={"prompt": "Put garment on model", "reference_images": [
            {"content": png, "mime_type": "image/png", "filename": "model.png"},
            {"content": png, "mime_type": "image/png", "filename": "garment.png"},
        ]},
        config={},
    )
    assert observed["content_type"].startswith("multipart/form-data;")
    assert b'model.png' in observed["body"] and b'garment.png' in observed["body"]
    assert len(result.outputs) == 1 and result.outputs[0].content == png
