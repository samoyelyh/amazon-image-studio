from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.batch_tryon_review import organization_id
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.infrastructure.redis import get_redis_client
from app.schemas.batch_tryon_queue import SharedQueueBoard
from app.security.principal import Principal, require_permissions
from app.services.batch_tryon_shared_queue_service import shared_queue_snapshot

router = APIRouter(prefix="/batch-tryon/queue", tags=["batch-tryon-queue"])


@router.get("", response_model=SharedQueueBoard)
async def queue_summary(
    response: Response,
    limit: int = Query(default=100, ge=1, le=200),
    include_archived: bool = False,
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    redis=Depends(get_redis_client), principal: Principal = Depends(require_permissions("jobs.read")),
):
    response.headers["Cache-Control"] = "private, no-store"
    return await shared_queue_snapshot(session, redis, settings,
        organization_id=organization_id(principal), user_id=principal.user.id, limit=limit, include_archived=include_archived)
