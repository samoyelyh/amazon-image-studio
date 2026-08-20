from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import re
import zipfile

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.attachment_material import (
    AttachmentMaterialItem,
    AttachmentMaterialSet,
    AttachmentMaterialSetVersion,
)
from app.models.attachment_planning import AttachmentModuleResultState
from app.models.content import Asset, GeneratedOutput
from app.models.listing_workflow import (
    ListingGenerationSession,
    ListingImageProject,
    ListingImageTaskGroup,
    ProductCategory,
)
from app.models.tasks import Job
from app.services.asset_service import read_asset_content
from app.services.storage_service import StorageService


UTC = timezone.utc
MODULE_ORDER = (
    "pure_white", "custom_process", "stadium_scene",
    "gift_scene", "detail_display", "casual_scene",
)
COVER_PRIORITY = (
    "pure_white", "gift_scene", "stadium_scene",
    "casual_scene", "detail_display", "custom_process",
)
MODULE_FILE_NAMES = {
    "pure_white": "01_white_background",
    "custom_process": "02_customization_process",
    "stadium_scene": "03_stadium_scene",
    "gift_scene": "04_gift_scene",
    "detail_display": "05_detail_showcase",
    "casual_scene": "06_casual_scene",
}


@dataclass(frozen=True)
class FinalMaterialSource:
    module_key: str
    output: GeneratedOutput
    asset: Asset
    job: Job | None
    task_group: ListingImageTaskGroup | None


@dataclass(frozen=True)
class MaterialSaveResult:
    material_set: AttachmentMaterialSet
    version: AttachmentMaterialSetVersion
    created_set: bool
    created_version: bool
    unchanged: bool


def _localized(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("zh") or value.get("en") or "").strip()
    return ""


def _product_name(session: ListingGenerationSession) -> str:
    listing = session.listing_content if isinstance(session.listing_content, dict) else {}
    return _localized(listing.get("title")) or f"商品 {session.id[:8]}"


def _selected_modules(project: ListingImageProject, final_modules: list[str]) -> list[str]:
    config = project.prompt_config if isinstance(project.prompt_config, dict) else {}
    workbench = config.get("attachment_workbench") if isinstance(config.get("attachment_workbench"), dict) else {}
    drafts = workbench.get("modules") if isinstance(workbench.get("modules"), dict) else {}
    selected = [key for key in MODULE_ORDER if isinstance(drafts.get(key), dict) and drafts[key].get("selected") is True]
    if selected:
        return selected
    fallback = [key for key in MODULE_ORDER if key in final_modules]
    return fallback or list(MODULE_ORDER)


def _job_metadata(job: Job | None) -> dict[str, object]:
    if job is None or not isinstance(job.input_json, dict):
        return {}
    metadata = job.input_json.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _content_hash(
    *, category_key: str, selected_modules: list[str], sources: list[FinalMaterialSource],
) -> str:
    payload = {
        "category_key": category_key,
        "selected_modules": selected_modules,
        "items": [{
            "module_key": item.module_key,
            "source_output_id": item.output.id,
            "source_asset_id": item.asset.id,
        } for item in sorted(sources, key=lambda row: MODULE_ORDER.index(row.module_key))],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _cover_asset_id(sources: list[FinalMaterialSource]) -> str:
    by_module = {item.module_key: item.asset.id for item in sources}
    return next((by_module[key] for key in COVER_PRIORITY if key in by_module), sources[0].asset.id)


async def _project_context(
    db: AsyncSession, *, organization_id: str, project_id: str, lock: bool,
) -> tuple[ListingImageProject, ListingGenerationSession, ProductCategory]:
    statement = select(ListingImageProject).where(
        ListingImageProject.id == project_id,
        ListingImageProject.organization_id == organization_id,
    )
    if lock:
        statement = statement.with_for_update()
    project = await db.scalar(statement)
    if project is None:
        raise AppError("attachment_material.project_not_found", "附图项目不存在或无权访问", 404)
    session = await db.scalar(select(ListingGenerationSession).where(
        ListingGenerationSession.id == project.session_id,
        ListingGenerationSession.organization_id == organization_id,
    ))
    if session is None:
        raise AppError("attachment_material.session_not_found", "来源商品会话不存在", 409)
    category = await db.get(ProductCategory, session.category_id)
    if category is None:
        raise AppError("attachment_material.category_not_found", "来源品类不存在", 409)
    return project, session, category


async def _final_sources(
    db: AsyncSession, *, project: ListingImageProject,
) -> list[FinalMaterialSource]:
    states = list((await db.scalars(select(AttachmentModuleResultState).where(
        AttachmentModuleResultState.organization_id == project.organization_id,
        AttachmentModuleResultState.listing_image_project_id == project.id,
        AttachmentModuleResultState.current_final_output_id.is_not(None),
    ).with_for_update())).all())
    sources: list[FinalMaterialSource] = []
    for state in states:
        output = await db.scalar(select(GeneratedOutput).where(
            GeneratedOutput.id == state.current_final_output_id,
            GeneratedOutput.organization_id == project.organization_id,
        ))
        if output is None:
            continue
        asset = await db.scalar(select(Asset).where(
            Asset.id == output.asset_id,
            Asset.organization_id == project.organization_id,
            Asset.deleted_at.is_(None),
        ))
        if asset is None:
            raise AppError("attachment_material.asset_missing", f"{state.module_key}最终图片素材不存在", 409)
        job = await db.get(Job, output.job_id) if output.job_id else None
        group = await db.scalar(select(ListingImageTaskGroup).where(
            ListingImageTaskGroup.organization_id == project.organization_id,
            ListingImageTaskGroup.listing_image_project_id == project.id,
            ListingImageTaskGroup.job_batch_id == output.batch_id,
        )) if output.batch_id else None
        sources.append(FinalMaterialSource(state.module_key, output, asset, job, group))
    return sorted(sources, key=lambda row: MODULE_ORDER.index(row.module_key))


async def _output_source(
    db: AsyncSession, *, project: ListingImageProject, output_id: str,
) -> FinalMaterialSource:
    output = await db.scalar(select(GeneratedOutput).where(
        GeneratedOutput.id == output_id,
        GeneratedOutput.organization_id == project.organization_id,
    ))
    if output is None or output.module_key not in MODULE_ORDER:
        raise AppError("attachment_material.output_not_found", "生成结果不存在或不属于附图工作台", 404)
    job = await db.get(Job, output.job_id) if output.job_id else None
    metadata = _job_metadata(job)
    if metadata.get("workflow") != "attachment_workbench_generation" or metadata.get("output_project_id") != project.id:
        raise AppError("attachment_material.output_not_found", "生成结果不存在或不属于当前附图项目", 404)
    asset = await db.scalar(select(Asset).where(
        Asset.id == output.asset_id,
        Asset.organization_id == project.organization_id,
        Asset.deleted_at.is_(None),
    ))
    if asset is None:
        raise AppError("attachment_material.asset_missing", "生成结果图片不存在", 409)
    group = await db.scalar(select(ListingImageTaskGroup).where(
        ListingImageTaskGroup.organization_id == project.organization_id,
        ListingImageTaskGroup.listing_image_project_id == project.id,
        ListingImageTaskGroup.job_batch_id == output.batch_id,
    )) if output.batch_id else None
    return FinalMaterialSource(str(output.module_key), output, asset, job, group)


async def _target_set(
    db: AsyncSession, *, organization_id: str, owner_user_id: str, project_id: str,
    material_set_id: str | None, save_mode: str,
) -> AttachmentMaterialSet | None:
    if material_set_id:
        material_set = await db.scalar(select(AttachmentMaterialSet).where(
            AttachmentMaterialSet.id == material_set_id,
            AttachmentMaterialSet.organization_id == organization_id,
            AttachmentMaterialSet.owner_user_id == owner_user_id,
            AttachmentMaterialSet.status == "active",
        ).with_for_update())
        if material_set is None:
            raise AppError("attachment_material.set_not_found", "素材包不存在或无权访问", 404)
        return material_set
    if save_mode == "new":
        return None
    return await db.scalar(select(AttachmentMaterialSet).where(
        AttachmentMaterialSet.organization_id == organization_id,
        AttachmentMaterialSet.owner_user_id == owner_user_id,
        AttachmentMaterialSet.source_project_id == project_id,
        AttachmentMaterialSet.status == "active",
    ).order_by(AttachmentMaterialSet.updated_at.desc()).limit(1).with_for_update())


async def _create_items(
    db: AsyncSession, *, version: AttachmentMaterialSetVersion,
    sources: list[FinalMaterialSource], user_id: str,
) -> None:
    for source in sources:
        metadata = _job_metadata(source.job)
        db.add(AttachmentMaterialItem(
            organization_id=version.organization_id,
            material_version_id=version.id,
            module_key=source.module_key,
            source_output_id=source.output.id,
            source_asset_id=source.asset.id,
            source_task_group_id=source.task_group.id if source.task_group else None,
            source_job_id=source.job.id if source.job else None,
            plan_version_id=str(metadata.get("plan_version_id") or "") or None,
            prompt_version_id=str(metadata.get("prompt_version_id") or "") or None,
            reference_understanding_id=str(metadata.get("reference_understanding_id") or "") or None,
            product_composition_version_id=str(metadata.get("product_composition_version_id") or "") or None,
            aspect_ratio=str(metadata.get("requested_aspect_ratio") or "1:1"),
            output_size=f"{source.asset.width}x{source.asset.height}",
            generation_mode=str(metadata.get("generation_mode") or "standard").upper(),
            product_mode=str(metadata.get("product_mode") or "SINGLE").upper(),
            is_manual_revision=False,
            created_by=user_id,
            created_at=datetime.now(UTC),
        ))


async def save_material_sources(
    db: AsyncSession, *, project: ListingImageProject, session: ListingGenerationSession,
    category: ProductCategory, sources: list[FinalMaterialSource], selected_modules: list[str],
    display_name: str, tags: list[str], note: str, material_set_id: str | None,
    save_mode: str, user_id: str,
) -> MaterialSaveResult:
    if not sources:
        raise AppError("attachment_material.final_required", "当前还没有可保存的最终采用图片", 409)
    selected = [key for key in MODULE_ORDER if key in selected_modules]
    if not selected:
        selected = [item.module_key for item in sources]
    content_hash = _content_hash(category_key=category.category_code, selected_modules=selected, sources=sources)
    material_set = await _target_set(
        db, organization_id=project.organization_id, owner_user_id=user_id, project_id=project.id,
        material_set_id=material_set_id, save_mode=save_mode,
    )
    created_set = material_set is None
    if material_set is None:
        material_set = AttachmentMaterialSet(
            organization_id=project.organization_id,
            owner_user_id=user_id,
            category_key=category.category_code,
            category_name=category.category_name,
            product_name=_product_name(session),
            display_name=display_name,
            source_session_id=session.id,
            source_project_id=project.id,
            selected_module_snapshot=selected,
            tags=tags,
            note=note,
            is_complete=False,
            status="active",
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(material_set)
        await db.flush()
    existing = None
    if material_set.current_version_id:
        current_version = await db.get(AttachmentMaterialSetVersion, material_set.current_version_id)
        if current_version is not None and current_version.content_hash == content_hash:
            existing = current_version
    material_set.display_name = display_name
    material_set.tags = tags
    material_set.note = note
    material_set.updated_by = user_id
    material_set.category_key = category.category_code
    material_set.category_name = category.category_name
    material_set.product_name = _product_name(session)
    material_set.source_session_id = session.id
    material_set.source_project_id = project.id
    material_set.selected_module_snapshot = selected
    if existing is not None:
        material_set.current_version_id = existing.id
        material_set.cover_asset_id = _cover_asset_id(sources)
        material_set.is_complete = existing.is_complete
        await db.flush()
        return MaterialSaveResult(material_set, existing, created_set, False, True)

    latest_number = int(await db.scalar(select(func.max(AttachmentMaterialSetVersion.version_number)).where(
        AttachmentMaterialSetVersion.material_set_id == material_set.id,
    )) or 0)
    source_keys = {item.module_key for item in sources}
    is_complete = bool(selected) and all(key in source_keys for key in selected)
    version = AttachmentMaterialSetVersion(
        organization_id=project.organization_id,
        material_set_id=material_set.id,
        version_number=latest_number + 1,
        content_hash=content_hash,
        selected_module_snapshot=selected,
        module_count=len(sources),
        target_module_count=len(selected),
        is_complete=is_complete,
        created_by=user_id,
        created_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()
    await _create_items(db, version=version, sources=sources, user_id=user_id)
    material_set.current_version_id = version.id
    material_set.cover_asset_id = _cover_asset_id(sources)
    material_set.is_complete = is_complete
    await db.flush()
    return MaterialSaveResult(material_set, version, created_set, True, False)


async def save_project_material_set(
    db: AsyncSession, *, organization_id: str, project_id: str, display_name: str,
    tags: list[str], note: str, material_set_id: str | None, save_mode: str, user_id: str,
) -> MaterialSaveResult:
    project, session, category = await _project_context(
        db, organization_id=organization_id, project_id=project_id, lock=True,
    )
    sources = await _final_sources(db, project=project)
    selected = _selected_modules(project, [item.module_key for item in sources])
    return await save_material_sources(
        db, project=project, session=session, category=category, sources=sources,
        selected_modules=selected, display_name=display_name, tags=tags, note=note,
        material_set_id=material_set_id, save_mode=save_mode, user_id=user_id,
    )


async def material_save_context(
    db: AsyncSession, *, organization_id: str, project_id: str, user_id: str,
) -> tuple[str, AttachmentMaterialSet | None, list[str]]:
    project, session, category = await _project_context(
        db, organization_id=organization_id, project_id=project_id, lock=False,
    )
    existing = await db.scalar(select(AttachmentMaterialSet).where(
        AttachmentMaterialSet.organization_id == organization_id,
        AttachmentMaterialSet.owner_user_id == user_id,
        AttachmentMaterialSet.source_project_id == project.id,
        AttachmentMaterialSet.status == "active",
    ).order_by(AttachmentMaterialSet.updated_at.desc()).limit(1))
    count = int(await db.scalar(select(func.count()).select_from(AttachmentMaterialSet).where(
        AttachmentMaterialSet.organization_id == organization_id,
        AttachmentMaterialSet.owner_user_id == user_id,
        AttachmentMaterialSet.category_key == category.category_code,
    )) or 0)
    default_name = existing.display_name if existing else (
        f"{category.category_name}_Listing套图_{datetime.now(UTC).strftime('%Y%m%d')}_{count + 1:03d}"
    )
    return default_name, existing, [category.category_name, "Listing套图"]


async def save_single_output(
    db: AsyncSession, *, organization_id: str, project_id: str, output_id: str,
    display_name: str, tags: list[str], note: str, material_set_id: str | None,
    save_mode: str, user_id: str,
) -> MaterialSaveResult:
    project, session, category = await _project_context(
        db, organization_id=organization_id, project_id=project_id, lock=True,
    )
    source = await _output_source(db, project=project, output_id=output_id)
    return await save_material_sources(
        db, project=project, session=session, category=category, sources=[source],
        selected_modules=[source.module_key], display_name=display_name, tags=tags, note=note,
        material_set_id=material_set_id, save_mode=save_mode, user_id=user_id,
    )


async def list_material_sets(
    db: AsyncSession, *, organization_id: str, owner_user_id: str, search: str | None,
    category_key: str | None, completion: str | None, include_archived: bool,
    organization_scope: bool, limit: int, offset: int,
) -> tuple[list[AttachmentMaterialSet], int]:
    filters = [AttachmentMaterialSet.organization_id == organization_id]
    if not organization_scope:
        filters.append(AttachmentMaterialSet.owner_user_id == owner_user_id)
    if not include_archived:
        filters.append(AttachmentMaterialSet.status == "active")
    if category_key:
        filters.append(AttachmentMaterialSet.category_key == category_key)
    if completion == "complete":
        filters.append(AttachmentMaterialSet.is_complete.is_(True))
    elif completion == "incomplete":
        filters.append(AttachmentMaterialSet.is_complete.is_(False))
    if search:
        term = f"%{search.strip()}%"
        filters.append(or_(
            AttachmentMaterialSet.display_name.like(term),
            AttachmentMaterialSet.product_name.like(term),
            AttachmentMaterialSet.category_name.like(term),
        ))
    total = int(await db.scalar(select(func.count()).select_from(AttachmentMaterialSet).where(*filters)) or 0)
    rows = list((await db.scalars(select(AttachmentMaterialSet).where(*filters).order_by(
        AttachmentMaterialSet.updated_at.desc(), AttachmentMaterialSet.created_at.desc(),
    ).limit(limit).offset(offset))).all())
    return rows, total


async def get_material_set(
    db: AsyncSession, *, organization_id: str, material_set_id: str,
    owner_user_id: str, organization_scope: bool = False, lock: bool = False,
) -> AttachmentMaterialSet:
    statement = select(AttachmentMaterialSet).where(
        AttachmentMaterialSet.id == material_set_id,
        AttachmentMaterialSet.organization_id == organization_id,
    )
    if not organization_scope:
        statement = statement.where(AttachmentMaterialSet.owner_user_id == owner_user_id)
    if lock:
        statement = statement.with_for_update()
    material_set = await db.scalar(statement)
    if material_set is None:
        raise AppError("attachment_material.set_not_found", "素材包不存在或无权访问", 404)
    return material_set


async def material_versions(
    db: AsyncSession, *, material_set_id: str,
) -> list[AttachmentMaterialSetVersion]:
    return list((await db.scalars(select(AttachmentMaterialSetVersion).where(
        AttachmentMaterialSetVersion.material_set_id == material_set_id,
    ).order_by(AttachmentMaterialSetVersion.version_number.desc()))).all())


async def material_items(
    db: AsyncSession, *, version_id: str,
) -> list[AttachmentMaterialItem]:
    rows = list((await db.scalars(select(AttachmentMaterialItem).where(
        AttachmentMaterialItem.material_version_id == version_id,
    ))).all())
    return sorted(rows, key=lambda item: MODULE_ORDER.index(item.module_key))


async def changed_modules(
    db: AsyncSession, *, version: AttachmentMaterialSetVersion,
) -> list[str]:
    previous = await db.scalar(select(AttachmentMaterialSetVersion).where(
        AttachmentMaterialSetVersion.material_set_id == version.material_set_id,
        AttachmentMaterialSetVersion.version_number == version.version_number - 1,
    ))
    if previous is None:
        return [item.module_key for item in await material_items(db, version_id=version.id)]
    current = {item.module_key: item.source_asset_id for item in await material_items(db, version_id=version.id)}
    old = {item.module_key: item.source_asset_id for item in await material_items(db, version_id=previous.id)}
    return [key for key in MODULE_ORDER if current.get(key) != old.get(key)]


async def update_material_set_metadata(
    db: AsyncSession, *, material_set: AttachmentMaterialSet, display_name: str,
    tags: list[str], note: str, user_id: str,
) -> AttachmentMaterialSet:
    material_set.display_name = display_name
    material_set.tags = tags
    material_set.note = note
    material_set.updated_by = user_id
    await db.flush()
    return material_set


async def archive_material_set(
    db: AsyncSession, *, material_set: AttachmentMaterialSet, user_id: str,
) -> AttachmentMaterialSet:
    material_set.status = "archived"
    material_set.updated_by = user_id
    await db.flush()
    return material_set


def safe_download_stem(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "-", value.strip()).strip(" .")
    return (cleaned or "attachment-material")[:120]


async def build_material_zip(
    db: AsyncSession, storage: StorageService, *, version: AttachmentMaterialSetVersion,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in await material_items(db, version_id=version.id):
            asset = await db.get(Asset, item.source_asset_id)
            if asset is None or asset.deleted_at is not None:
                raise AppError("attachment_material.asset_missing", f"{item.module_key}素材文件不存在", 409)
            content = await read_asset_content(asset, storage)
            extension = "jpg" if asset.mime_type == "image/jpeg" else "webp" if asset.mime_type == "image/webp" else "png"
            archive.writestr(f"{MODULE_FILE_NAMES[item.module_key]}.{extension}", content)
    return buffer.getvalue()
