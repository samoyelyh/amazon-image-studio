from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.attachment_planning import AttachmentReferenceLibraryItem, AttachmentReferenceLibraryItemModule
from app.models.attachment_material import AttachmentMaterialItem
from app.models.content import Asset, GeneratedOutput
from app.models.listing_workflow import CategorySkill, CategorySkillVersion, ProductCategory
from app.schemas.attachment_planning import (
    AttachmentReferenceLibraryCreateRequest,
    AttachmentReferenceLibraryItemResponse,
    AttachmentReferenceLibrarySourceCreateRequest,
    AttachmentReferenceLibraryUnderstandingResponse,
    AttachmentReferenceLibraryUpdateRequest,
    AttachmentReferenceLibraryCategoryOptionResponse,
)
from app.security.principal import Principal, require_permissions
from app.services.asset_service import signed_asset_response
from app.services.attachment_reference_library_service import (
    latest_library_understanding,
    reconcile_library_understanding,
    start_library_analysis,
)
from app.services.attachment_planning_service import attachment_module_definitions
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
    module_keys = list((await db.scalars(select(AttachmentReferenceLibraryItemModule.module_key).where(
        AttachmentReferenceLibraryItemModule.library_item_id == item.id,
    ).order_by(AttachmentReferenceLibraryItemModule.created_at))).all()) or [item.module_key]
    return AttachmentReferenceLibraryItemResponse(
        id=item.id, name=item.name, description=item.description, category_key=item.category_key,
        module_key=item.module_key, module_keys=module_keys, reference_role=item.reference_role,
        asset=await signed_asset_response(asset, storage, settings), guidance=item.guidance,
        tags=list(item.tags or []), is_featured=item.is_featured, is_active=item.is_active,
        sort_order=item.sort_order, state_version=item.state_version,
        created_by=item.created_by, created_at=item.created_at, updated_at=item.updated_at,
        understanding=AttachmentReferenceLibraryUnderstandingResponse(
            id=understanding.id, version_number=understanding.version_number, status=understanding.status,
            structured=dict(understanding.structured_json or {}), analysis_model=understanding.analysis_model,
            error_message=understanding.error_message,
        ) if understanding else None,
    )


def _normalized_module_keys(payload: object) -> list[str]:
    values = list(dict.fromkeys(str(item).strip() for item in getattr(payload, "module_keys", []) if str(item).strip()))
    legacy = str(getattr(payload, "module_key", "") or "").strip()
    if legacy and legacy not in values:
        values.insert(0, legacy)
    if not values:
        raise AppError("reference_library.modules_required", "请至少选择一个适用模块", 422)
    return values


async def _set_modules(
    db: AsyncSession, item: AttachmentReferenceLibraryItem, module_keys: list[str], user_id: str,
) -> None:
    await db.execute(delete(AttachmentReferenceLibraryItemModule).where(
        AttachmentReferenceLibraryItemModule.library_item_id == item.id,
    ))
    for module_key in module_keys:
        db.add(AttachmentReferenceLibraryItemModule(
            organization_id=item.organization_id, library_item_id=item.id,
            module_key=module_key, created_by=user_id,
        ))
    item.module_key = module_keys[0]


async def _ensure_duplicate_allowed(
    db: AsyncSession, *, organization_id: str, asset_id: str, allow_duplicate: bool,
) -> None:
    existing = list((await db.scalars(select(AttachmentReferenceLibraryItem).where(
        AttachmentReferenceLibraryItem.organization_id == organization_id,
        AttachmentReferenceLibraryItem.asset_id == asset_id,
    ).order_by(AttachmentReferenceLibraryItem.created_at))).all())
    if existing and not allow_duplicate:
        raise AppError(
            "reference_library.duplicate_confirmation_required",
            "该图片已经存在于公共参考图库。若要为它配置另一套用途规则，请确认后继续。",
            409,
            {"existing_item_ids": [item.id for item in existing]},
        )


async def _start_analysis_without_blocking_save(
    db: AsyncSession, settings: Settings, *, item: AttachmentReferenceLibraryItem, user_id: str,
    force: bool = False,
) -> bool:
    try:
        _, _, created = await start_library_analysis(db, settings, item=item, user_id=user_id, force=force)
        return created
    except AppError:
        # Library metadata and the Asset link are valid independently of an
        # optional intrinsic-understanding channel. Admins can retry later.
        return False


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
    await _ensure_duplicate_allowed(
        db, organization_id=organization_id, asset_id=asset.id,
        allow_duplicate=payload.allow_duplicate_asset,
    )
    module_keys = _normalized_module_keys(payload)
    values = payload.model_dump(exclude={"module_key", "module_keys", "allow_duplicate_asset"})
    item = AttachmentReferenceLibraryItem(
        organization_id=organization_id, asset_id=asset.id,
        created_by=principal.user.id, updated_by=principal.user.id,
        module_key=module_keys[0], **values,
    )
    db.add(item)
    await db.flush()
    await _set_modules(db, item, module_keys, principal.user.id)
    created = await _start_analysis_without_blocking_save(db, settings, item=item, user_id=principal.user.id)
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
        query = query.where(AttachmentReferenceLibraryItem.id.in_(
            select(AttachmentReferenceLibraryItemModule.library_item_id).where(
                AttachmentReferenceLibraryItemModule.module_key == module_key,
            )
        ))
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


@admin_router.get("/options", response_model=list[AttachmentReferenceLibraryCategoryOptionResponse])
async def reference_library_options(
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> list[AttachmentReferenceLibraryCategoryOptionResponse]:
    rows = (await db.execute(
        select(ProductCategory, CategorySkill, CategorySkillVersion)
        .join(CategorySkill, ProductCategory.default_skill_id == CategorySkill.id)
        .join(CategorySkillVersion, CategorySkill.default_published_version_id == CategorySkillVersion.id)
        .where(ProductCategory.is_active.is_(True), CategorySkill.is_active.is_(True), CategorySkillVersion.status == "published")
        .order_by(ProductCategory.sort_order, ProductCategory.category_name)
    )).all()
    result: list[AttachmentReferenceLibraryCategoryOptionResponse] = []
    for category, _, version in rows:
        definitions = attachment_module_definitions({"image_prompt_config": dict(version.image_prompt_config or {})})
        modules = [
            {"code": str(item.get("code")), "name": str(item.get("name") or item.get("code")),
             "sort_order": int(item.get("sort_order") or 100)}
            for item in definitions
            if item.get("code") and item.get("enabled", True)
        ]
        result.append(AttachmentReferenceLibraryCategoryOptionResponse(
            category_key=category.category_code, category_name=category.category_name,
            modules=sorted(modules, key=lambda item: (int(item["sort_order"]), str(item["name"]))),
        ))
    return result


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
    await _ensure_duplicate_allowed(
        db, organization_id=organization_id, asset_id=asset.id,
        allow_duplicate=payload.allow_duplicate_asset,
    )
    module_keys = _normalized_module_keys(payload)
    values = payload.model_dump(exclude={"module_key", "module_keys", "allow_duplicate_asset"})
    item = AttachmentReferenceLibraryItem(
        organization_id=organization_id, created_by=principal.user.id, updated_by=principal.user.id,
        module_key=module_keys[0], **values,
    )
    db.add(item); await db.flush(); await _set_modules(db, item, module_keys, principal.user.id)
    created = await _start_analysis_without_blocking_save(db, settings, item=item, user_id=principal.user.id)
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
    module_keys = None
    if "module_keys" in values or "module_key" in values:
        module_keys = _normalized_module_keys(payload)
        values.pop("module_keys", None); values.pop("module_key", None)
    analysis_changed = any(key in values for key in {"reference_role", "guidance", "tags"})
    for key, value in values.items():
        setattr(item, key, value)
    if module_keys is not None:
        await _set_modules(db, item, module_keys, principal.user.id)
    item.updated_by = principal.user.id; item.state_version += 1
    created = False
    if analysis_changed:
        created = await _start_analysis_without_blocking_save(
            db, settings, item=item, user_id=principal.user.id, force=True,
        )
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
