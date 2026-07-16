from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.schemas.health import LivenessResponse, ReadinessResponse
from app.services.health_service import check_dependencies


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    settings = get_settings()
    return LivenessResponse(service=settings.app_name, version=settings.app_version)


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(response: Response) -> ReadinessResponse:
    settings = get_settings()
    components = await check_dependencies()
    is_ready = all(component.status == "ok" for component in components.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if is_ready else "degraded",
        service=settings.app_name,
        version=settings.app_version,
        components=components,
    )
