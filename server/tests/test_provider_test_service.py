import httpx

from app.services.provider_test_service import probe_provider_models


async def test_provider_model_discovery_returns_only_model_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(200, json={"data": [{"id": "text-model"}, {"id": "image-model"}]})

    result = await probe_provider_models(
        base_url="https://relay.example/v1", api_key="sk-test-secret",
        timeout_seconds=1, transport=httpx.MockTransport(handler),
    )

    assert result.success is True
    assert result.models == ["image-model", "text-model"]
    assert "sk-test-secret" not in result.message


async def test_provider_model_discovery_maps_cloudflare_timeout() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(522, text="cloudflare error page"))

    result = await probe_provider_models(
        base_url="https://relay.example/v1", api_key="sk-test-secret",
        timeout_seconds=1, transport=transport,
    )

    assert result.success is False
    assert result.status_code == 522
    assert result.error_code == "provider.origin_timeout"
    assert "cloudflare error page" not in result.message
