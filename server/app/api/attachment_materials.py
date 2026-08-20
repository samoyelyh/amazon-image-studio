from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.attachment_material import AttachmentMaterialSet, AttachmentMaterialSetVersion
from app.models.content import Asset
from app.schemas.attachment_material import (
    AttachmentMaterialItemResponse,
    AttachmentMaterialMetadataUpdateRequest,
    AttachmentMaterialSaveContextResponse,
    AttachmentMaterialSaveRequest,
    AttachmentMaterialSaveResponse,
    AttachmentMaterialSetDetailResponse,
    AttachmentMaterialSetPage,
    AttachmentMaterialSetSummaryResponse,
    AttachmentMaterialVersionResponse,
)
from app.security.principal import Principal, require_permissions
from app.services.asset_service import signed_asset_response
from app.services.attachment_material_service import (
    archive_material_set,
    build_material_zip,
    changed_modules,
    get_material_set,
    list_material_sets,
    material_items,
    material_save_context,
    material_versions,
    safe_download_stem,
    save_project_material_set,
    save_single_output,
    update_material_set_metadata,
)
from app.services.audit_service import add_audit_log
from app.services.storage_service import StorageService, get_storage_service


router = APIRouter(prefix="/attachment-materials", tags=["attachment-materials"])


def _organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "Please select an organization first", 400)
    return principal.organization.id


def _organization_scope(principal: Principal, scope: str) -> bool:
    if scope != "organization":
        return False
    if principal.is_platform_admin or "organization_admin" in principal.role_codes:
        return True
    raise AppError("attachment_material.organization_scope_denied", "当前账号不能查看团队全部素材", 403)


async def _version_response(
    db: AsyncSession, storage: StorageService, settings: Settings,
    version: AttachmentMaterialSetVersion,
) -> AttachmentMaterialVersionResponse:
    items: list[AttachmentMaterialItemResponse] = []
    for item in await material_items(db, version_id=version.id):
        asset = await db.get(Asset, item.source_asset_id)
        if asset is None:
            raise AppError("attachment_material.asset_missing", f"{item.module_key}素材不存在", 409)
        items.append(AttachmentMaterialItemResponse(
            id=item.id,
            module_key=item.module_key,
            source_output_id=item.source_output_id,
            source_asset_id=item.source_asset_id,
            source_task_group_id=item.source_task_group_id,
            source_job_id=item.source_job_id,
            plan_version_id=item.plan_version_id,
            prompt_version_id=item.prompt_version_id,
            reference_understanding_id=item.reference_understanding_id,
            product_composition_version_id=item.product_composition_version_id,
            aspect_ratio=item.aspect_ratio,
            output_size=item.output_size,
            generation_mode=item.generation_mode,
            product_mode=item.product_mode,
            is_manual_revision=item.is_manual_revision,
            created_at=item.created_at,
            asset=await signed_asset_response(asset, storage, settings),
        ))
    return AttachmentMaterialVersionResponse(
        id=version.id,
        version_number=version.version_number,
        content_hash=version.content_hash,
        selected_module_snapshot=list(version.selected_module_snapshot or []),
        module_count=version.module_count,
        target_module_count=version.target_module_count,
        is_complete=version.is_complete,
        changed_module_keys=await changed_modules(db, version=version),
        created_by=version.created_by,
        created_at=version.created_at,
        items=items,
    )


async def _summary_response(
    db: AsyncSession, storage: StorageService, settings: Settings,
    material_set: AttachmentMaterialSet,
) -> AttachmentMaterialSetSummaryResponse:
    current = await db.get(AttachmentMaterialSetVersion, material_set.current_version_id) if material_set.current_version_id else None
    cover = await db.get(Asset, material_set.cover_asset_id) if material_set.cover_asset_id else None
    return AttachmentMaterialSetSummaryResponse(
        id=material_set.id,
        category_key=material_set.category_key,
        category_name=material_set.category_name,
        product_name=material_set.product_name,
        display_name=material_set.display_name,
        source_session_id=material_set.source_session_id,
        source_project_id=material_set.source_project_id,
        cover_asset_id=material_set.cover_asset_id,
        selected_module_snapshot=list(material_set.selected_module_snapshot or []),
        tags=list(material_set.tags or []),
        note=material_set.note,
        is_complete=material_set.is_complete,
        status=material_set.status,
        current_version_number=current.version_number if current else 0,
        module_count=current.module_count if current else 0,
        target_module_count=current.target_module_count if current else len(material_set.selected_module_snapshot or []),
        owner_user_id=material_set.owner_user_id,
        created_at=material_set.created_at,
        updated_at=material_set.updated_at,
        cover_asset=await signed_asset_response(cover, storage, settings) if cover else None,
    )


async def _detail_response(
    db: AsyncSession, storage: StorageService, settings: Settings,
    material_set: AttachmentMaterialSet,
) -> AttachmentMaterialSetDetailResponse:
    summary = await _summary_response(db, storage, settings, material_set)
    versions = [
        await _version_response(db, storage, settings, version)
        for version in await material_versions(db, material_set_id=material_set.id)
    ]
    return AttachmentMaterialSetDetailResponse(
        **summary.model_dump(), current_version_id=material_set.current_version_id, versions=versions,
    )


@router.get("/projects/{project_id}/save-context", response_model=AttachmentMaterialSaveContextResponse)
async def get_save_context(
    project_id: str,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> AttachmentMaterialSaveContextResponse:
    default_name, existing, tags = await material_save_context(
        db, organization_id=_organization_id(principal), project_id=project_id, user_id=principal.user.id,
    )
    return AttachmentMaterialSaveContextResponse(
        project_id=project_id,
        default_name=default_name,
        existing_material_set_id=existing.id if existing else None,
        existing_display_name=existing.display_name if existing else None,
        suggested_tags=tags,
    )


@router.post("/projects/{project_id}/save", response_model=AttachmentMaterialSaveResponse)
async def save_project_set(
    project_id: str,
    payload: AttachmentMaterialSaveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.read", "assets.read")),
) -> AttachmentMaterialSaveResponse:
    result = await save_project_material_set(
        db, organization_id=_organization_id(principal), project_id=project_id,
        display_name=payload.display_name, tags=payload.tags, note=payload.note,
        material_set_id=payload.material_set_id, save_mode=payload.save_mode, user_id=principal.user.id,
    )
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=_organization_id(principal),
        action="attachment_material.save_set", resource_type="attachment_material_set",
        resource_id=result.material_set.id,
        metadata={"version_number": result.version.version_number, "created_version": result.created_version},
    )
    await db.commit()
    await db.refresh(result.material_set)
    return AttachmentMaterialSaveResponse(
        material_set=await _detail_response(db, storage, settings, result.material_set),
        created_set=result.created_set,
        created_version=result.created_version,
        unchanged=result.unchanged,
    )


@router.post("/projects/{project_id}/outputs/{output_id}/save", response_model=AttachmentMaterialSaveResponse)
async def save_output(
    project_id: str,
    output_id: str,
    payload: AttachmentMaterialSaveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.read", "assets.read")),
) -> AttachmentMaterialSaveResponse:
    result = await save_single_output(
        db, organization_id=_organization_id(principal), project_id=project_id, output_id=output_id,
        display_name=payload.display_name, tags=payload.tags, note=payload.note,
        material_set_id=payload.material_set_id, save_mode=payload.save_mode, user_id=principal.user.id,
    )
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=_organization_id(principal),
        action="attachment_material.save_output", resource_type="attachment_material_set",
        resource_id=result.material_set.id, metadata={"output_id": output_id},
    )
    await db.commit()
    await db.refresh(result.material_set)
    return AttachmentMaterialSaveResponse(
        material_set=await _detail_response(db, storage, settings, result.material_set),
        created_set=result.created_set,
        created_version=result.created_version,
        unchanged=result.unchanged,
    )


@router.get("", response_model=AttachmentMaterialSetPage)
async def get_material_sets(
    search: str | None = Query(default=None, max_length=255),
    category_key: str | None = Query(default=None, max_length=100),
    completion: str | None = Query(default=None, pattern=r"^(complete|incomplete)$"),
    include_archived: bool = False,
    scope: str = Query(default="mine", pattern=r"^(mine|organization)$"),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> AttachmentMaterialSetPage:
    rows, total = await list_material_sets(
        db, organization_id=_organization_id(principal), owner_user_id=principal.user.id,
        search=search, category_key=category_key, completion=completion,
        include_archived=include_archived,
        organization_scope=_organization_scope(principal, scope), limit=limit, offset=offset,
    )
    return AttachmentMaterialSetPage(
        items=[await _summary_response(db, storage, settings, row) for row in rows],
        total=total, limit=limit, offset=offset,
    )


@router.get("/{material_set_id}", response_model=AttachmentMaterialSetDetailResponse)
async def get_material_detail(
    material_set_id: str,
    scope: str = Query(default="mine", pattern=r"^(mine|organization)$"),
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> AttachmentMaterialSetDetailResponse:
    material_set = await get_material_set(
        db, organization_id=_organization_id(principal), material_set_id=material_set_id,
        owner_user_id=principal.user.id, organization_scope=_organization_scope(principal, scope),
    )
    return await _detail_response(db, storage, settings, material_set)


@router.patch("/{material_set_id}", response_model=AttachmentMaterialSetDetailResponse)
async def update_material_metadata(
    material_set_id: str,
    payload: AttachmentMaterialMetadataUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> AttachmentMaterialSetDetailResponse:
    material_set = await get_material_set(
        db, organization_id=_organization_id(principal), material_set_id=material_set_id,
        owner_user_id=principal.user.id, lock=True,
    )
    await update_material_set_metadata(
        db, material_set=material_set, display_name=payload.display_name,
        tags=payload.tags, note=payload.note, user_id=principal.user.id,
    )
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=_organization_id(principal),
        action="attachment_material.update", resource_type="attachment_material_set", resource_id=material_set.id,
    )
    await db.commit()
    await db.refresh(material_set)
    return await _detail_response(db, storage, settings, material_set)


@router.post("/{material_set_id}/archive", response_model=AttachmentMaterialSetDetailResponse)
async def archive_set(
    material_set_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> AttachmentMaterialSetDetailResponse:
    material_set = await get_material_set(
        db, organization_id=_organization_id(principal), material_set_id=material_set_id,
        owner_user_id=principal.user.id, lock=True,
    )
    await archive_material_set(db, material_set=material_set, user_id=principal.user.id)
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=_organization_id(principal),
        action="attachment_material.archive", resource_type="attachment_material_set", resource_id=material_set.id,
    )
    await db.commit()
    await db.refresh(material_set)
    return await _detail_response(db, storage, settings, material_set)


@router.get("/{material_set_id}/versions/{version_number}/download")
async def download_material_version(
    material_set_id: str,
    version_number: int,
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("assets.read")),
) -> Response:
    material_set = await get_material_set(
        db, organization_id=_organization_id(principal), material_set_id=material_set_id,
        owner_user_id=principal.user.id,
    )
    version = next((row for row in await material_versions(db, material_set_id=material_set.id) if row.version_number == version_number), None)
    if version is None:
        raise AppError("attachment_material.version_not_found", "素材包版本不存在", 404)
    content = await build_material_zip(db, storage, version=version)
    filename = f"{safe_download_stem(material_set.display_name)}_V{version.version_number}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
