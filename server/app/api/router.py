from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.organizations import router as organizations_router
from app.api.rbac import router as rbac_router
from app.api.users import router as users_router
from app.api.assets import router as assets_router
from app.api.projects import router as projects_router
from app.api.quota import router as quota_router
from app.api.jobs import batch_router as job_batches_router, router as jobs_router
from app.api.resource_pools import router as resource_pools_router
from app.api.admin import router as admin_router
from app.api.batch_tryon_review import router as batch_tryon_review_router
from app.api.listing_transfer import router as listing_transfer_router
from app.core.config import get_settings


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(organizations_router)
api_router.include_router(rbac_router)
api_router.include_router(audit_router)
api_router.include_router(assets_router)
api_router.include_router(projects_router)
api_router.include_router(quota_router)
api_router.include_router(jobs_router)
api_router.include_router(job_batches_router)
api_router.include_router(batch_tryon_review_router)
api_router.include_router(listing_transfer_router)
api_router.include_router(resource_pools_router)
api_router.include_router(admin_router)


@api_router.get("", tags=["system"])
async def api_root() -> dict[str, str]:
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }
