from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.schemas.health import ComponentHealth


def healthy_components() -> dict[str, ComponentHealth]:
    return {
        "database": ComponentHealth(status="ok", latency_ms=1),
        "redis": ComponentHealth(status="ok", latency_ms=1),
        "storage": ComponentHealth(status="ok", latency_ms=1),
    }


@pytest.mark.asyncio
async def test_liveness_and_request_id() -> None:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get("/api/v1/health/live", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"] == "test-request"


@pytest.mark.asyncio
async def test_readiness_is_ok_when_dependencies_are_healthy(monkeypatch) -> None:
    monkeypatch.setattr("app.api.health.check_dependencies", AsyncMock(return_value=healthy_components()))
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_is_degraded_when_a_dependency_fails(monkeypatch) -> None:
    components = healthy_components()
    components["storage"] = ComponentHealth(status="error", latency_ms=2, message="ConnectionError")
    monkeypatch.setattr("app.api.health.check_dependencies", AsyncMock(return_value=components))
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["components"]["storage"]["message"] == "ConnectionError"
