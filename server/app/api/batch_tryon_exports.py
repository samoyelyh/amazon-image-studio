"""Owner-only cross-batch exports; no new task or storage subsystem."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.batch_tryon_review import organization_id, template_archive_response
from app.db.session import get_db_session
from app.security.principal import Principal, require_permissions
from app.services.batch_tryon_export_service import build_selected_batch_try_on_results_archive
from app.services.storage_service import StorageService, get_storage_service

router = APIRouter(prefix="/batch-tryon/exports", tags=["batch-tryon-export"])


class SelectedBatchExportRequest(BaseModel):
    batch_ids: list[str] = Field(min_length=1, max_length=100)
    allow_partial: bool = False


@router.post("/download")
async def download_selected_batches(
    payload: SelectedBatchExportRequest, request: Request,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read", "assets.read")),
):
    archive, filename, count, skipped = await build_selected_batch_try_on_results_archive(
        session, storage, organization_id=organization_id(principal), owner_user_id=principal.user.id,
        batch_ids=payload.batch_ids, allow_partial=payload.allow_partial,
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return template_archive_response(archive, filename=filename, success_count=count,
        skipped_count=skipped, template_id="", scope="all_succeeded")
