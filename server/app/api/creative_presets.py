from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.models.creative_presets import (
    AIModelIdentityVersion,
    AIModelPreset,
    AIModelPresetReference,
    ThemePreset,
    ThemePresetVersion,
    VisualPreset,
    VisualPresetVersion,
)
from app.schemas.creative_presets import (
    AIModelIdentityResponse,
    AIModelPresetResponse,
    AIModelPresetUpdateRequest,
    AIModelGenerateRequest,
    AIModelQuickCreateRequest,
    AIModelReferencePackRequest,
    AIModelReferenceResponse,
    ThemePresetCreateRequest,
    ThemePresetResponse,
    ThemePresetUpdateRequest,
    VisualPresetCreateRequest,
    VisualPresetResponse,
    VisualPresetUpdateRequest,
)
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.creative_preset_service import (
    default_visual_preset,
    next_version_number,
    visible_model_presets,
    visible_theme_presets,
    visible_visual_presets,
)
from app.services.ai_model_preset_service import (
    confirm_identity,
    get_model_preset,
    publish_identity,
    start_identity_generation,
    start_reference_pack_generation,
)
from app.services.task_service import dispatch_jobs, due_jobs


router = APIRouter(prefix="/creative-presets", tags=["creative-presets"])
admin_router = APIRouter(prefix="/admin/creative-presets", tags=["admin-creative-presets"])
UTC = timezone.utc


def _organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队", 409)
    return principal.organization.id


def visual_response(
    preset: VisualPreset, version: VisualPresetVersion, *, include_prompt: bool,
) -> VisualPresetResponse:
    return VisualPresetResponse(
        id=preset.id, code=preset.code, name=preset.name,
        short_description=preset.short_description,
        category_scope=list(preset.category_scope or []),
        recommended_modules=list(preset.recommended_modules or []),
        recommended_model_tags=list(preset.recommended_model_tags or []),
        tags=list(preset.tags or []), current_version_id=version.id,
        current_version_number=version.version_number, sort_order=preset.sort_order,
        is_active=preset.is_active, is_default=preset.is_default,
        prompt_template=version.full_prompt_template if include_prompt else None,
    )


def theme_response(
    preset: ThemePreset, version: ThemePresetVersion, *, include_prompt: bool,
) -> ThemePresetResponse:
    return ThemePresetResponse(
        id=preset.id, code=preset.code, name=preset.name,
        short_description=preset.short_description, tags=list(preset.tags or []),
        current_version_id=version.id, current_version_number=version.version_number,
        sort_order=preset.sort_order, is_active=preset.is_active,
        prompt_template=version.full_prompt_template if include_prompt else None,
    )


async def model_response(
    db: AsyncSession, preset: AIModelPreset, *, include_private: bool,
) -> AIModelPresetResponse:
    identity = await db.get(AIModelIdentityVersion, preset.current_identity_version_id) if preset.current_identity_version_id else None
    if identity is None and include_private:
        identity = await db.scalar(select(AIModelIdentityVersion).where(
            AIModelIdentityVersion.model_preset_id == preset.id,
        ).order_by(AIModelIdentityVersion.version_number.desc()).limit(1))
    references = list((await db.scalars(select(AIModelPresetReference).where(
        AIModelPresetReference.identity_version_id == identity.id,
    ).order_by(AIModelPresetReference.sort_order))).all()) if identity else []
    identity_response = AIModelIdentityResponse(
        id=identity.id, version_number=identity.version_number, status=identity.status,
        identity_prompt_snapshot=identity.identity_prompt_snapshot if include_private else "",
        identity_asset_id=identity.identity_asset_id, identity_job_id=identity.identity_job_id,
        reference_batch_id=identity.reference_batch_id, confirmed_at=identity.confirmed_at,
        published_at=identity.published_at,
        references=[AIModelReferenceResponse(
            id=item.id, reference_role=item.reference_role, asset_id=item.asset_id,
            source_job_id=item.source_job_id, sort_order=item.sort_order,
        ) for item in references],
    ) if identity else None
    return AIModelPresetResponse(
        id=preset.id, code=preset.code, name=preset.name, display_name=preset.display_name,
        gender_presentation=preset.gender_presentation, age_range=preset.age_range,
        body_type=preset.body_type, short_description=preset.short_description,
        recommended_visual_presets=list(preset.recommended_visual_presets or []),
        recommended_modules=list(preset.recommended_modules or []), tags=list(preset.tags or []),
        cover_asset_id=preset.cover_asset_id,
        current_identity_version_id=preset.current_identity_version_id,
        status=preset.status, sort_order=preset.sort_order,
        is_active=preset.is_active, is_published=preset.is_published,
        source_type=preset.source_type, owner_user_id=preset.owner_user_id,
        generation_parameters=dict(preset.generation_parameters or {}),
        identity_prompt=preset.identity_prompt if include_private else None,
        generation_prompt=preset.generation_prompt if include_private else None,
        negative_constraints=preset.negative_constraints if include_private else None,
        current_identity=identity_response,
    )


@router.get("/visual", response_model=list[VisualPresetResponse])
async def list_visual_presets(
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[VisualPresetResponse]:
    organization_id = _organization_id(principal)
    rows = await visible_visual_presets(db, organization_id=organization_id)
    if not rows:
        await default_visual_preset(db, organization_id=organization_id)
        rows = await visible_visual_presets(db, organization_id=organization_id)
    return [visual_response(preset, version, include_prompt=False) for preset, version in rows]


@router.get("/themes", response_model=list[ThemePresetResponse])
async def list_theme_presets(
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[ThemePresetResponse]:
    rows = await visible_theme_presets(db, organization_id=_organization_id(principal))
    return [theme_response(preset, version, include_prompt=False) for preset, version in rows]


@router.get("/models", response_model=list[AIModelPresetResponse])
async def list_models(
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[AIModelPresetResponse]:
    rows = await visible_model_presets(
        db, organization_id=_organization_id(principal), published_only=True, user_id=principal.user.id,
    )
    return [await model_response(db, item, include_private=False) for item in rows]


@router.post("/models/generate", response_model=AIModelPresetResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_personal_model(
    payload: AIModelQuickCreateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AIModelPresetResponse:
    organization_id = _organization_id(principal)
    parameters = payload.model_dump(exclude={"idempotency_key", "display_name"})
    prompt = (
        "Create one consistent adult commercial model identity on a clean light gray studio background. "
        "Full-body front view, neutral unbranded clothing, no logos, no text, no celebrity likeness. "
        f"Gender presentation: {payload.gender_presentation}. Age range: {payload.age_range}. "
        f"Body type: {payload.body_type}. Commercial style: {payload.commercial_style}. "
        f"Personality: {payload.personality}. Hair: {payload.hair_style}. Expression: {payload.expression}."
    )
    preset = AIModelPreset(
        organization_id=organization_id,
        code=f"user-{principal.user.id[:8]}-{payload.idempotency_key[-12:]}",
        name=payload.quick_type, display_name=payload.display_name,
        gender_presentation=payload.gender_presentation, age_range=payload.age_range,
        body_type=payload.body_type, short_description=f"{payload.commercial_style} · {payload.personality}",
        identity_prompt=prompt, generation_prompt=prompt,
        negative_constraints="No brand, logo, text, celebrity likeness, revealing clothing or identity drift.",
        recommended_visual_presets=[], recommended_modules=[], tags=list(payload.recommended_usage),
        source_type="USER_TEMPORARY", owner_user_id=principal.user.id, generation_parameters=parameters,
        status="GENERATING_IDENTITY", sort_order=100, is_active=True, is_published=False,
        created_by=principal.user.id, updated_by=principal.user.id,
    )
    db.add(preset)
    await db.flush()
    identity, job, created = await start_identity_generation(
        db, settings, preset=preset, organization_id=organization_id,
        user_id=principal.user.id, idempotency_key=payload.idempotency_key,
    )
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=organization_id,
        action="ai_model.personal.generate", resource_type="ai_model_identity_version", resource_id=identity.id,
        metadata={"model_preset_id": preset.id, "job_id": job.id, "quick_type": payload.quick_type},
    )
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return await model_response(db, preset, include_private=True)


@router.post("/models/{preset_id}/save-personal", response_model=AIModelPresetResponse)
async def save_personal_model(
    preset_id: str, request: Request, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AIModelPresetResponse:
    preset = await get_model_preset(db, preset_id)
    if preset.organization_id != _organization_id(principal) or preset.owner_user_id != principal.user.id:
        raise AppError("creative_preset.model_not_found", "AI模特不存在或无权访问", 404)
    if not preset.current_identity_version_id:
        raise AppError("creative_preset.identity_not_ready", "候选模特尚未生成完成", 409)
    preset.source_type = "USER_GENERATED"
    preset.status = "PERSONAL_SAVED"
    preset.updated_by = principal.user.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=preset.organization_id,
                  action="ai_model.personal.save", resource_type="ai_model_preset", resource_id=preset.id, metadata={})
    await db.commit()
    return await model_response(db, preset, include_private=True)


@router.get("/models/{preset_id}", response_model=AIModelPresetResponse)
async def get_personal_or_public_model(
    preset_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> AIModelPresetResponse:
    preset = await get_model_preset(db, preset_id)
    organization_id = _organization_id(principal)
    public = preset.is_published and preset.status == "PUBLISHED"
    owned = preset.organization_id == organization_id and preset.owner_user_id == principal.user.id
    if not public and not owned:
        raise AppError("creative_preset.model_not_found", "AI模特不存在或无权访问", 404)
    return await model_response(db, preset, include_private=owned)


@admin_router.get("/visual", response_model=list[VisualPresetResponse])
async def admin_list_visual(
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> list[VisualPresetResponse]:
    organization_id = _organization_id(principal)
    rows = await visible_visual_presets(db, organization_id=organization_id, include_inactive=True)
    if not rows:
        await default_visual_preset(db, organization_id=organization_id)
        rows = await visible_visual_presets(db, organization_id=organization_id, include_inactive=True)
    return [visual_response(preset, version, include_prompt=True) for preset, version in rows]


@admin_router.post("/visual", response_model=VisualPresetResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_visual(
    payload: VisualPresetCreateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> VisualPresetResponse:
    if await db.scalar(select(VisualPreset.id).where(VisualPreset.organization_id.is_(None), VisualPreset.code == payload.code)):
        raise AppError("creative_preset.code_exists", "视觉模板编码已存在", 409)
    preset = VisualPreset(
        organization_id=None, code=payload.code, name=payload.name,
        short_description=payload.short_description, category_scope=payload.category_scope,
        recommended_modules=payload.recommended_modules,
        recommended_model_tags=payload.recommended_model_tags, tags=payload.tags,
        sort_order=payload.sort_order, is_active=True, is_default=payload.is_default,
        created_by=principal.user.id, updated_by=principal.user.id,
    )
    db.add(preset)
    await db.flush()
    version = VisualPresetVersion(
        preset_id=preset.id, version_number=1, full_prompt_template=payload.full_prompt_template,
        change_summary="管理员创建", created_by=principal.user.id, created_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()
    preset.current_version_id = version.id
    if preset.is_default:
        rows = list((await db.scalars(select(VisualPreset).where(VisualPreset.id != preset.id))).all())
        for item in rows:
            item.is_default = False
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="visual_preset.create", resource_type="visual_preset", resource_id=preset.id,
                  metadata={"code": preset.code, "version": 1})
    await db.commit()
    return visual_response(preset, version, include_prompt=True)


@admin_router.put("/visual/{preset_id}", response_model=VisualPresetResponse)
async def admin_update_visual(
    preset_id: str, payload: VisualPresetUpdateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> VisualPresetResponse:
    preset = await db.get(VisualPreset, preset_id)
    if preset is None:
        raise AppError("creative_preset.visual_not_found", "视觉模板不存在", 404)
    values = payload.model_dump(exclude_unset=True, exclude={"full_prompt_template", "change_summary"})
    for key, value in values.items():
        setattr(preset, key, value)
    current = await db.get(VisualPresetVersion, preset.current_version_id)
    if payload.full_prompt_template is not None and (current is None or payload.full_prompt_template != current.full_prompt_template):
        current = VisualPresetVersion(
            preset_id=preset.id,
            version_number=await next_version_number(db, version_model=VisualPresetVersion, preset_id=preset.id),
            full_prompt_template=payload.full_prompt_template, change_summary=payload.change_summary,
            created_by=principal.user.id, created_at=datetime.now(UTC),
        )
        db.add(current)
        await db.flush()
        preset.current_version_id = current.id
    if payload.is_default:
        rows = list((await db.scalars(select(VisualPreset).where(VisualPreset.id != preset.id))).all())
        for item in rows:
            item.is_default = False
    preset.updated_by = principal.user.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="visual_preset.update", resource_type="visual_preset", resource_id=preset.id,
                  metadata={"version_id": preset.current_version_id, "fields": sorted(values)})
    await db.commit()
    if current is None:
        raise AppError("creative_preset.version_missing", "视觉模板缺少当前版本", 409)
    return visual_response(preset, current, include_prompt=True)


@admin_router.get("/themes", response_model=list[ThemePresetResponse])
async def admin_list_themes(
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> list[ThemePresetResponse]:
    rows = await visible_theme_presets(db, organization_id=_organization_id(principal), include_inactive=True)
    return [theme_response(preset, version, include_prompt=True) for preset, version in rows]


@admin_router.post("/themes", response_model=ThemePresetResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_theme(
    payload: ThemePresetCreateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> ThemePresetResponse:
    if await db.scalar(select(ThemePreset.id).where(ThemePreset.organization_id.is_(None), ThemePreset.code == payload.code)):
        raise AppError("creative_preset.code_exists", "主题模板编码已存在", 409)
    preset = ThemePreset(
        organization_id=None, code=payload.code, name=payload.name,
        short_description=payload.short_description, tags=payload.tags,
        sort_order=payload.sort_order, is_active=True,
        created_by=principal.user.id, updated_by=principal.user.id,
    )
    db.add(preset)
    await db.flush()
    version = ThemePresetVersion(
        preset_id=preset.id, version_number=1, full_prompt_template=payload.full_prompt_template,
        change_summary="管理员创建", created_by=principal.user.id, created_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()
    preset.current_version_id = version.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="theme_preset.create", resource_type="theme_preset", resource_id=preset.id,
                  metadata={"code": preset.code, "version": 1})
    await db.commit()
    return theme_response(preset, version, include_prompt=True)


@admin_router.put("/themes/{preset_id}", response_model=ThemePresetResponse)
async def admin_update_theme(
    preset_id: str, payload: ThemePresetUpdateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> ThemePresetResponse:
    preset = await db.get(ThemePreset, preset_id)
    if preset is None:
        raise AppError("creative_preset.theme_not_found", "主题模板不存在", 404)
    values = payload.model_dump(exclude_unset=True, exclude={"full_prompt_template", "change_summary"})
    for key, value in values.items():
        setattr(preset, key, value)
    current = await db.get(ThemePresetVersion, preset.current_version_id)
    if payload.full_prompt_template is not None and (current is None or payload.full_prompt_template != current.full_prompt_template):
        current = ThemePresetVersion(
            preset_id=preset.id,
            version_number=await next_version_number(db, version_model=ThemePresetVersion, preset_id=preset.id),
            full_prompt_template=payload.full_prompt_template, change_summary=payload.change_summary,
            created_by=principal.user.id, created_at=datetime.now(UTC),
        )
        db.add(current)
        await db.flush()
        preset.current_version_id = current.id
    preset.updated_by = principal.user.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="theme_preset.update", resource_type="theme_preset", resource_id=preset.id,
                  metadata={"version_id": preset.current_version_id, "fields": sorted(values)})
    await db.commit()
    if current is None:
        raise AppError("creative_preset.version_missing", "主题模板缺少当前版本", 409)
    return theme_response(preset, current, include_prompt=True)


@admin_router.get("/models", response_model=list[AIModelPresetResponse])
async def admin_list_models(
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> list[AIModelPresetResponse]:
    rows = await visible_model_presets(db, organization_id=_organization_id(principal), published_only=False)
    return [await model_response(db, item, include_private=True) for item in rows]


@admin_router.put("/models/{preset_id}", response_model=AIModelPresetResponse)
async def admin_update_model(
    preset_id: str, payload: AIModelPresetUpdateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> AIModelPresetResponse:
    preset = await db.get(AIModelPreset, preset_id)
    if preset is None:
        raise AppError("creative_preset.model_not_found", "AI模特预设不存在", 404)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(preset, key, value)
    preset.updated_by = principal.user.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="ai_model_preset.update", resource_type="ai_model_preset", resource_id=preset.id,
                  metadata={"fields": sorted(values)})
    await db.commit()
    return await model_response(db, preset, include_private=True)


@admin_router.post("/models/{preset_id}/identities", response_model=AIModelPresetResponse, status_code=status.HTTP_202_ACCEPTED)
async def admin_generate_model_identity(
    preset_id: str, payload: AIModelGenerateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> AIModelPresetResponse:
    preset = await get_model_preset(db, preset_id)
    identity, job, created = await start_identity_generation(
        db, settings, preset=preset, organization_id=_organization_id(principal),
        user_id=principal.user.id, idempotency_key=payload.idempotency_key,
    )
    add_audit_log(db, request=request, actor_user_id=principal.user.id,
                  organization_id=_organization_id(principal), action="ai_model.identity.generate",
                  resource_type="ai_model_identity_version", resource_id=identity.id,
                  metadata={"model_preset_id": preset.id, "job_id": job.id})
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return await model_response(db, preset, include_private=True)


@admin_router.post("/models/{preset_id}/identities/{identity_id}/confirm", response_model=AIModelPresetResponse)
async def admin_confirm_model_identity(
    preset_id: str, identity_id: str, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> AIModelPresetResponse:
    preset = await get_model_preset(db, preset_id)
    await confirm_identity(db, preset=preset, identity_id=identity_id, user_id=principal.user.id)
    add_audit_log(db, request=request, actor_user_id=principal.user.id,
                  organization_id=_organization_id(principal), action="ai_model.identity.confirm",
                  resource_type="ai_model_identity_version", resource_id=identity_id,
                  metadata={"model_preset_id": preset.id})
    await db.commit()
    return await model_response(db, preset, include_private=True)


@admin_router.post("/models/{preset_id}/identities/{identity_id}/references", response_model=AIModelPresetResponse, status_code=status.HTTP_202_ACCEPTED)
async def admin_generate_model_references(
    preset_id: str, identity_id: str, payload: AIModelReferencePackRequest, request: Request,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> AIModelPresetResponse:
    preset = await get_model_preset(db, preset_id)
    identity = await db.get(AIModelIdentityVersion, identity_id)
    if identity is None:
        raise AppError("creative_preset.identity_not_found", "模特身份版本不存在", 404)
    batch, jobs, created = await start_reference_pack_generation(
        db, settings, preset=preset, identity=identity, payload=payload,
        organization_id=_organization_id(principal), user_id=principal.user.id,
    )
    add_audit_log(db, request=request, actor_user_id=principal.user.id,
                  organization_id=_organization_id(principal), action="ai_model.references.generate",
                  resource_type="ai_model_identity_version", resource_id=identity.id,
                  metadata={"model_preset_id": preset.id, "batch_id": batch.id, "job_count": len(jobs)})
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=len(jobs), batch_id=batch.id))
    return await model_response(db, preset, include_private=True)


@admin_router.post("/models/{preset_id}/identities/{identity_id}/publish", response_model=AIModelPresetResponse)
async def admin_publish_model_identity(
    preset_id: str, identity_id: str, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> AIModelPresetResponse:
    preset = await get_model_preset(db, preset_id)
    await publish_identity(db, preset=preset, identity_id=identity_id, user_id=principal.user.id)
    add_audit_log(db, request=request, actor_user_id=principal.user.id,
                  organization_id=_organization_id(principal), action="ai_model.identity.publish",
                  resource_type="ai_model_identity_version", resource_id=identity_id,
                  metadata={"model_preset_id": preset.id})
    await db.commit()
    return await model_response(db, preset, include_private=True)
