from fastapi import APIRouter

from app.api.health import router as health_router
from app.core.config import get_settings


api_router = APIRouter()
api_router.include_router(health_router)


@api_router.get("", tags=["system"])
async def api_root() -> dict[str, str]:
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }
