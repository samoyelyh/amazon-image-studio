from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.attachment_planning import AttachmentReferenceLibraryItem
from app.models.attachment_material import AttachmentMaterialItem
from app.models.content import Asset, GeneratedOutput
from app.schemas.attachment_planning import (
    AttachmentReferenceLibraryCreateRequest,
    AttachmentReferenceLibraryItemResponse,
    AttachmentReferenceLibrarySourceCreateRequest,
    AttachmentReferenceLibraryUnderstandingResponse,
    AttachmentReferenceLibraryUpdateRequest,
)
from app.security.principal import Principal, require_permissions
from app.services.asset_service import signed_asset_response
from app.services.attachment_reference_library_service import (
    latest_library_understanding,
    reconcile_library_understanding,
    start_library_analysis,
)
from app.services.storage_service import StorageService, get_storage_service
from app.services.task_service import dispatch_jobs, due_jobs


router = APIRouter(prefix="/attachment-reference-library", tags=["attachment-reference-library"])
admin_router = APIRouter(prefix="/admin/attachment-reference-library", tags=["admin-attachment-reference-library"])


def _organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队", 409)
    return principal.organization.id


async def _response(
    db: AsyncSession, storage: StorageService, settings: Settings, item: AttachmentReferenceLibraryItem,
) -> AttachmentReferenceLibraryItemResponse:
    understanding = await latest_library_understanding(db, item.id)
    asset = await db.get(Asset, item.asset_id)
    if asset is None or asset.deleted_at is not None:
        raise AppError("asset.not_found", "参考图库图片不存在", 404)
    return AttachmentReferenceLibraryItemResponse(
        id=item.id, name=item.name, description=item.description, category_key=item.category_key,
        module_key=item.module_key, reference_role=item.reference_role,
        asset=await signed_asset_response(asset, storage, settings), guidance=item.guidance,
        tags=list(item.tags or []), is_featured=item.is_featured, is_active=item.is_active,
        sort_order=item.sort_order, state_version=item.state_version,
        understanding=AttachmentReferenceLibraryUnderstandingResponse(
            id=understanding.id, version_number=understanding.version_number, status=understanding.status,
            structured=dict(understanding.structured_json or {}), analysis_model=understanding.analysis_model,
            error_message=understanding.error_message,
        ) if understanding else None,
    )


async def _create_for_asset(
    db: AsyncSession, storage: StorageService, settings: Settings, principal: Principal,
    *, asset_id: str, payload: AttachmentReferenceLibrarySourceCreateRequest,
) -> AttachmentReferenceLibraryItemResponse:
    organization_id = _organization_id(principal)
    asset = await db.scalar(select(Asset).where(
        Asset.id == asset_id, Asset.organization_id == organization_id, Asset.deleted_at.is_(None),
    ))
    if asset is None:
        raise AppError("asset.not_found", "参考图库图片不存在或无权访问", 404)
    item = AttachmentReferenceLibraryItem(
        organization_id=organization_id, asset_id=asset.id,
        created_by=principal.user.id, updated_by=principal.user.id,
        **payload.model_dump(),
    )
    db.add(item)
    await db.flush()
    _, _, created = await start_library_analysis(db, settings, item=item, user_id=principal.user.id)
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return await _response(db, storage, settings, item)


async def _list(
    db: AsyncSession, storage: StorageService, settings: Settings, organization_id: str,
    *, module_key: str | None, category_key: str | None, include_inactive: bool,
) -> list[AttachmentReferenceLibraryItemResponse]:
    query = select(AttachmentReferenceLibraryItem).where(AttachmentReferenceLibraryItem.organization_id == organization_id)
    if module_key:
        query = query.where(AttachmentReferenceLibraryItem.module_key == module_key)
    if category_key:
        query = query.where(AttachmentReferenceLibraryItem.category_key.in_([None, category_key]))
    if not include_inactive:
        query = query.where(AttachmentReferenceLibraryItem.is_active.is_(True))
    rows = list((await db.scalars(query.order_by(
        AttachmentReferenceLibraryItem.is_featured.desc(), AttachmentReferenceLibraryItem.sort_order,
        AttachmentReferenceLibraryItem.name,
    ))).all())
    retry_jobs_created = 0
    for item in rows:
        retry_jobs_created += await reconcile_library_understanding(db, settings, item)
    result = [await _response(db, storage, settings, item) for item in rows]
    await db.commit()
    if retry_jobs_created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=retry_jobs_created))
    return result


@router.get("", response_model=list[AttachmentReferenceLibraryItemResponse])
async def list_reference_library(
    module_key: str | None = Query(default=None), category_key: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session), storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings), principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[AttachmentReferenceLibraryItemResponse]:
    return await _list(db, storage, settings, _organization_id(principal), module_key=module_key, category_key=category_key, include_inactive=False)


@admin_router.get("", response_model=list[AttachmentReferenceLibraryItemResponse])
async def admin_list_reference_library(
    module_key: str | None = Query(default=None), category_key: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session), storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings), principal: Principal = Depends(require_permissions("platform.admin")),
) -> list[AttachmentReferenceLibraryItemResponse]:
    return await _list(db, storage, settings, _organization_id(principal), module_key=module_key, category_key=category_key, include_inactive=True)


@admin_router.post("", response_model=AttachmentReferenceLibraryItemResponse, status_code=status.HTTP_201_CREATED)
async def create_reference_library_item(
    payload: AttachmentReferenceLibraryCreateRequest,
    db: AsyncSession = Depends(get_db_session), storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings), principal: Principal = Depends(require_permissions("platform.admin")),
) -> AttachmentReferenceLibraryItemResponse:
    organization_id = _organization_id(principal)
    asset = await db.scalar(select(Asset).where(Asset.id == payload.asset_id, Asset.organization_id == organization_id, Asset.deleted_at.is_(None)))
    if asset is None:
        raise AppError("asset.not_found", "参考图库图片不存在或无权访问", 404)
    item = AttachmentReferenceLibraryItem(
        organization_id=organization_id, created_by=principal.user.id, updated_by=principal.user.id,
        **payload.model_dump(),
    )
    db.add(item); await db.flush()
    _, _, created = await start_library_analysis(db, settings, item=item, user_id=principal.user.id)
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return await _response(db, storage, settings, item)


@admin_router.post(
    "/from-output/{output_id}", response_model=AttachmentReferenceLibraryItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reference_library_item_from_output(
    output_id: str, payload: AttachmentReferenceLibrarySourceCreateRequest,
    db: AsyncSession = Depends(get_db_session), storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings), principal: Principal = Depends(require_permissions("platform.admin")),
) -> AttachmentReferenceLibraryItemResponse:
    output = await db.scalar(select(GeneratedOutput).where(
        GeneratedOutput.id == output_id,
        GeneratedOutput.organization_id == _organization_id(principal),
        GeneratedOutput.discarded_at.is_(None),
    ))
    if output is None:
        raise AppError("generated_output.not_found", "生成结果不存在或无权访问", 404)
    return await _create_for_asset(
        db, storage, settings, principal, asset_id=output.asset_id, payload=payload,
    )


@admin_router.post(
    "/from-material-item/{material_item_id}", response_model=AttachmentReferenceLibraryItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reference_library_item_from_material(
    material_item_id: str, payload: AttachmentReferenceLibrarySourceCreateRequest,
    db: AsyncSession = Depends(get_db_session), storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings), principal: Principal = Depends(require_permissions("platform.admin")),
) -> AttachmentReferenceLibraryItemResponse:
    material_item = await db.scalar(select(AttachmentMaterialItem).where(
        AttachmentMaterialItem.id == material_item_id,
        AttachmentMaterialItem.organization_id == _organization_id(principal),
    ))
    if material_item is None:
        raise AppError("attachment_material.item_not_found", "个人素材不存在或无权访问", 404)
    return await _create_for_asset(
        db, storage, settings, principal, asset_id=material_item.source_asset_id, payload=payload,
    )


@admin_router.patch("/{item_id}", response_model=AttachmentReferenceLibraryItemResponse)
async def update_reference_library_item(
    item_id: str, payload: AttachmentReferenceLibraryUpdateRequest,
    db: AsyncSession = Depends(get_db_session), storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings), principal: Principal = Depends(require_permissions("platform.admin")),
) -> AttachmentReferenceLibraryItemResponse:
    item = await db.scalar(select(AttachmentReferenceLibraryItem).where(
        AttachmentReferenceLibraryItem.id == item_id,
        AttachmentReferenceLibraryItem.organization_id == _organization_id(principal),
    ).with_for_update())
    if item is None:
        raise AppError("reference_library.not_found", "参考图库项目不存在", 404)
    values = payload.model_dump(exclude_unset=True)
    analysis_changed = any(key in values for key in {"module_key", "reference_role", "guidance", "tags"})
    for key, value in values.items():
        setattr(item, key, value)
    item.updated_by = principal.user.id; item.state_version += 1
    created = False
    if analysis_changed:
        _, _, created = await start_library_analysis(db, settings, item=item, user_id=principal.user.id, force=True)
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return await _response(db, storage, settings, item)


@admin_router.post("/{item_id}/reanalyze", response_model=AttachmentReferenceLibraryItemResponse, status_code=status.HTTP_202_ACCEPTED)
async def reanalyze_reference_library_item(
    item_id: str, db: AsyncSession = Depends(get_db_session), storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings), principal: Principal = Depends(require_permissions("platform.admin")),
) -> AttachmentReferenceLibraryItemResponse:
    item = await db.scalar(select(AttachmentReferenceLibraryItem).where(
        AttachmentReferenceLibraryItem.id == item_id,
        AttachmentReferenceLibraryItem.organization_id == _organization_id(principal),
    ))
    if item is None:
        raise AppError("reference_library.not_found", "参考图库项目不存在", 404)
    _, _, created = await start_library_analysis(db, settings, item=item, user_id=principal.user.id, force=True)
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return await _response(db, storage, settings, item)
