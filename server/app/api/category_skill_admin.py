from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.listing_workflow import CategorySkill, CategorySkillVersion, ProductCategory
from app.schemas.listing_workflow import (
    CategorySkillAdminCreateRequest, CategorySkillAdminResponse, CategorySkillAdminUpdateRequest,
    CategorySkillTestRequest, CategorySkillTestResponse, CategorySkillValidationResponse,
    CategorySkillVersionCreateRequest, CategorySkillVersionResponse, CategorySkillVersionUpdateRequest,
)
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.category_skill_service import (
    complete_config, draft_preview, validate_skill_configuration, version_config,
)


router = APIRouter(prefix="/admin/category-skills", tags=["admin-category-skills"])
UTC = timezone.utc


def _starter_config() -> dict[str, object]:
    return complete_config(
        analysis_config={
            "system_prompt": "Analyze only visible product evidence and return one valid JSON object.",
            "task_prompt": "Extract the configured product attributes without inventing details.",
            "attribute_schema": [
                {"code": "product_type", "name": "产品类型", "type": "text", "required": True,
                 "default": "", "operator_editable": True, "sort_order": 10},
            ],
            "output_format": "bilingual_listing_json",
        },
        listing_config={
            "title": {"task_prompt": "Create a truthful Amazon title from verified attributes.", "target_language": "en-US", "max_characters": 200},
            "bullet_points": {"task_prompt": "Create five truthful Amazon bullets.", "target_language": "en-US", "count": 5},
            "description": {"task_prompt": "Create a concise truthful product description."},
            "search_terms": {"task_prompt": "Create relevant backend search terms."},
        },
        translation_config={
            "english_listing_rules": "Create natural Amazon US English copy from verified evidence.",
            "chinese_explanation_rules": "Use natural Chinese to explain the same meaning without adding claims.",
            "zh_to_en_rules": "Apply Chinese edits to the paired English field without literal translation or invention.",
            "compliance_rules": "Keep Chinese and English content paired one-to-one.",
        },
        image_prompt_config={
            "system_prompt": "Preserve the uploaded product faithfully.",
            "category_prompt": "Create commercially usable Amazon listing imagery.",
            "prompt_rules": {"preserve_text": True, "preserve_colors": True},
            "image_types": [
                {"code": "main", "name": "主图", "enabled": True, "default_selected": True,
                 "sort_order": 10, "prompt_template": "Create a clean product-focused main image."},
            ],
        },
        a_plus_config={"system_prompt": "Create truthful A+ content.", "modules": []},
    )


async def _skill_response(db: AsyncSession, skill: CategorySkill) -> CategorySkillAdminResponse:
    await db.refresh(skill)
    category = await db.get(ProductCategory, skill.category_id)
    if category is not None:
        await db.refresh(category)
    version_number = None
    if skill.default_published_version_id:
        version = await db.get(CategorySkillVersion, skill.default_published_version_id)
        version_number = version.version_number if version else None
    return CategorySkillAdminResponse(
        id=skill.id, category_id=skill.category_id,
        category_name=category.category_name if category else "",
        skill_name=skill.skill_name, skill_code=skill.skill_code, description=skill.description,
        marketplace=skill.marketplace, language=skill.language, status=skill.status,
        is_active=skill.is_active, default_published_version_id=skill.default_published_version_id,
        default_version_number=version_number,
        is_category_default=bool(category and category.default_skill_id == skill.id),
        created_at=skill.created_at, updated_at=skill.updated_at,
    )


def _version_response(version: CategorySkillVersion) -> CategorySkillVersionResponse:
    return CategorySkillVersionResponse.model_validate(version, from_attributes=True)


async def _get_skill(db: AsyncSession, skill_id: str) -> CategorySkill:
    skill = await db.get(CategorySkill, skill_id)
    if skill is None:
        raise AppError("category_skill.not_found", "品类 Skill 不存在", 404)
    return skill


async def _get_version(db: AsyncSession, skill_id: str, version_id: str) -> tuple[CategorySkill, CategorySkillVersion]:
    skill = await _get_skill(db, skill_id)
    version = await db.get(CategorySkillVersion, version_id)
    if version is None or version.skill_id != skill.id:
        raise AppError("category_skill.version_not_found", "Skill 版本不存在", 404)
    return skill, version


@router.get("", response_model=list[CategorySkillAdminResponse])
async def list_skills(
    category_id: str | None = Query(default=None), include_inactive: bool = Query(default=True),
    db: AsyncSession = Depends(get_db_session),
    _: Principal = Depends(require_permissions("platform.admin")),
) -> list[CategorySkillAdminResponse]:
    statement = select(CategorySkill)
    if category_id:
        statement = statement.where(CategorySkill.category_id == category_id)
    if not include_inactive:
        statement = statement.where(CategorySkill.is_active.is_(True))
    rows = list((await db.scalars(statement.order_by(CategorySkill.category_id, CategorySkill.skill_name))).all())
    return [await _skill_response(db, item) for item in rows]


@router.get("/{skill_id}", response_model=CategorySkillAdminResponse)
async def get_skill(
    skill_id: str, db: AsyncSession = Depends(get_db_session),
    _: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkillAdminResponse:
    return await _skill_response(db, await _get_skill(db, skill_id))


@router.post("", response_model=CategorySkillAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    payload: CategorySkillAdminCreateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkillAdminResponse:
    category = await db.get(ProductCategory, payload.category_id)
    if category is None:
        raise AppError("listing.category_not_found", "品类不存在", 404)
    if await db.scalar(select(CategorySkill.id).where(
        CategorySkill.category_id == payload.category_id, CategorySkill.skill_code == payload.skill_code,
    )):
        raise AppError("category_skill.code_exists", "该品类下的 Skill 编码已存在", 409)
    source = await db.get(CategorySkill, payload.source_skill_id) if payload.source_skill_id else None
    if source and source.category_id != category.id:
        raise AppError("category_skill.source_invalid", "复制来源必须属于同一品类", 422)
    source_version = await db.get(CategorySkillVersion, source.default_published_version_id) if source and source.default_published_version_id else None
    config = version_config(source_version) if source_version else _starter_config()
    analysis = dict(config["analysis_config"])
    listing = dict(config["listing_config"])
    image = dict(config["image_prompt_config"])
    a_plus = dict(config["a_plus_config"])
    skill = CategorySkill(
        category_id=category.id, skill_name=payload.skill_name, skill_code=payload.skill_code,
        description=payload.description, marketplace=payload.marketplace, language=payload.language,
        status="draft", is_active=True, version=1,
        analysis_prompt=str(analysis.get("task_prompt") or "Configure analysis rules in Skill V1."),
        listing_title_prompt=str((listing.get("title") or {}).get("task_prompt") or "Configure title rules."),
        bullet_points_prompt=str((listing.get("bullet_points") or {}).get("task_prompt") or "Configure bullet rules."),
        a_plus_prompt=str(a_plus.get("system_prompt") or "Configure A+ rules."),
        image_prompt_template=str(image.get("category_prompt") or "Configure image prompt rules."),
        image_types_config=list(image.get("image_types") or []), prompt_rules=dict(image.get("prompt_rules") or {}),
        created_by=principal.user.id, updated_by=principal.user.id,
    )
    db.add(skill)
    await db.flush()
    version = CategorySkillVersion(
        skill_id=skill.id, version_number=1, status="draft", **config,
        full_config_snapshot=config, change_summary="Initial draft",
        source_version_id=source_version.id if source_version else None, created_by=principal.user.id,
    )
    db.add(version)
    await db.flush()
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="category_skill.create", resource_type="category_skill", resource_id=skill.id,
                  metadata={"version_id": version.id, "category_id": category.id})
    await db.commit()
    return await _skill_response(db, skill)


@router.put("/{skill_id}", response_model=CategorySkillAdminResponse)
async def update_skill(
    skill_id: str, payload: CategorySkillAdminUpdateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkillAdminResponse:
    skill = await _get_skill(db, skill_id)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(skill, key, value)
    skill.updated_by = principal.user.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="category_skill.update", resource_type="category_skill", resource_id=skill.id,
                  metadata={"fields": sorted(values)})
    await db.commit()
    return await _skill_response(db, skill)


@router.get("/{skill_id}/versions", response_model=list[CategorySkillVersionResponse])
async def list_versions(
    skill_id: str, db: AsyncSession = Depends(get_db_session),
    _: Principal = Depends(require_permissions("platform.admin")),
) -> list[CategorySkillVersionResponse]:
    await _get_skill(db, skill_id)
    rows = list((await db.scalars(select(CategorySkillVersion).where(
        CategorySkillVersion.skill_id == skill_id,
    ).order_by(CategorySkillVersion.version_number.desc()))).all())
    return [_version_response(item) for item in rows]


@router.get("/{skill_id}/versions/{version_id}", response_model=CategorySkillVersionResponse)
async def get_version(
    skill_id: str, version_id: str, db: AsyncSession = Depends(get_db_session),
    _: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkillVersionResponse:
    _, version = await _get_version(db, skill_id, version_id)
    return _version_response(version)


@router.post("/{skill_id}/versions", response_model=CategorySkillVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_version(
    skill_id: str, payload: CategorySkillVersionCreateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkillVersionResponse:
    skill = await _get_skill(db, skill_id)
    source = await db.get(CategorySkillVersion, payload.source_version_id) if payload.source_version_id else None
    if source is None and skill.default_published_version_id:
        source = await db.get(CategorySkillVersion, skill.default_published_version_id)
    if source is None:
        source = await db.scalar(select(CategorySkillVersion).where(
            CategorySkillVersion.skill_id == skill.id,
        ).order_by(CategorySkillVersion.version_number.desc()).limit(1))
    if source is not None and source.skill_id != skill.id:
        raise AppError("category_skill.source_version_invalid", "来源版本不属于当前 Skill", 422)
    config = version_config(source) if source else _starter_config()
    number = int(await db.scalar(select(func.max(CategorySkillVersion.version_number)).where(
        CategorySkillVersion.skill_id == skill.id,
    )) or 0) + 1
    version = CategorySkillVersion(
        skill_id=skill.id, version_number=number, status="draft", **config,
        full_config_snapshot=config, change_summary=payload.change_summary,
        source_version_id=source.id if source else None, created_by=principal.user.id,
    )
    db.add(version)
    await db.flush()
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="category_skill.version_create", resource_type="category_skill_version", resource_id=version.id,
                  metadata={"skill_id": skill.id, "version_number": number, "source_version_id": version.source_version_id})
    await db.commit()
    await db.refresh(version)
    return _version_response(version)


@router.put("/{skill_id}/versions/{version_id}", response_model=CategorySkillVersionResponse)
async def update_version(
    skill_id: str, version_id: str, payload: CategorySkillVersionUpdateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkillVersionResponse:
    _, version = await _get_version(db, skill_id, version_id)
    if version.status not in {"draft", "testing"}:
        raise AppError("category_skill.published_read_only", "已发布版本不可直接修改，请创建新草稿", 409)
    config = complete_config(**payload.model_dump(exclude={"change_summary"}))
    version.analysis_config = config["analysis_config"]
    version.listing_config = config["listing_config"]
    version.translation_config = config["translation_config"]
    version.image_prompt_config = config["image_prompt_config"]
    version.a_plus_config = config["a_plus_config"]
    version.full_config_snapshot = config
    version.change_summary = payload.change_summary
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="category_skill.version_update", resource_type="category_skill_version", resource_id=version.id,
                  metadata={"skill_id": skill_id, "version_number": version.version_number})
    await db.commit()
    await db.refresh(version)
    return _version_response(version)


@router.post("/{skill_id}/versions/{version_id}/validate", response_model=CategorySkillValidationResponse)
async def validate_version(
    skill_id: str, version_id: str, db: AsyncSession = Depends(get_db_session),
    _: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkillValidationResponse:
    _, version = await _get_version(db, skill_id, version_id)
    errors, warnings, variables = validate_skill_configuration(version_config(version))
    return CategorySkillValidationResponse(valid=not errors, errors=errors, warnings=warnings, referenced_variables=variables)


@router.post("/{skill_id}/versions/{version_id}/test", response_model=CategorySkillTestResponse)
async def test_version(
    skill_id: str, version_id: str, payload: CategorySkillTestRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkillTestResponse:
    started = perf_counter()
    _, version = await _get_version(db, skill_id, version_id)
    config = version_config(version)
    errors, warnings, variables = validate_skill_configuration(config)
    validation = CategorySkillValidationResponse(valid=not errors, errors=errors, warnings=warnings, referenced_variables=variables)
    preview = draft_preview(config, payload.sample_analysis, payload.product_information)
    if version.status == "draft":
        version.status = "testing"
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="category_skill.version_test", resource_type="category_skill_version", resource_id=version.id,
                  metadata={"valid": not errors, "version_number": version.version_number})
    await db.commit()
    return CategorySkillTestResponse(
        validation=validation, **preview, model=None,
        elapsed_ms=max(1, int((perf_counter() - started) * 1000)),
    )


@router.post("/{skill_id}/versions/{version_id}/publish", response_model=CategorySkillVersionResponse)
async def publish_version(
    skill_id: str, version_id: str, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkillVersionResponse:
    skill, version = await _get_version(db, skill_id, version_id)
    if version.status == "published":
        return _version_response(version)
    if version.status not in {"draft", "testing"}:
        raise AppError("category_skill.version_not_publishable", "当前版本状态不可发布", 409)
    errors, _, _ = validate_skill_configuration(version_config(version))
    if errors:
        raise AppError("category_skill.validation_failed", "Skill 校验未通过，不能发布", 422, {"errors": errors})
    version.status = "published"
    version.published_by = principal.user.id
    version.published_at = datetime.now(UTC)
    skill.status = "published"
    skill.updated_by = principal.user.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="category_skill.version_publish", resource_type="category_skill_version", resource_id=version.id,
                  metadata={"skill_id": skill.id, "version_number": version.version_number, "change_summary": version.change_summary})
    await db.commit()
    await db.refresh(version)
    return _version_response(version)


@router.post("/{skill_id}/versions/{version_id}/set-default", response_model=CategorySkillAdminResponse)
async def set_default_version(
    skill_id: str, version_id: str, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkillAdminResponse:
    skill, version = await _get_version(db, skill_id, version_id)
    if version.status != "published":
        raise AppError("category_skill.default_requires_published", "只能将已发布版本设为默认", 409)
    category = await db.get(ProductCategory, skill.category_id)
    config = version_config(version)
    analysis = dict(config["analysis_config"])
    listing = dict(config["listing_config"])
    image = dict(config["image_prompt_config"])
    a_plus = dict(config["a_plus_config"])
    skill.default_published_version_id = version.id
    skill.status = "published"
    skill.version = version.version_number
    # Keep legacy readers compatible; runtime selection still reads the immutable version record.
    skill.analysis_prompt = str(analysis.get("task_prompt") or skill.analysis_prompt)
    skill.listing_title_prompt = str((listing.get("title") or {}).get("task_prompt") or skill.listing_title_prompt)
    skill.bullet_points_prompt = str((listing.get("bullet_points") or {}).get("task_prompt") or skill.bullet_points_prompt)
    skill.image_prompt_template = str(image.get("category_prompt") or skill.image_prompt_template)
    skill.image_types_config = list(image.get("image_types") or skill.image_types_config)
    skill.prompt_rules = dict(image.get("prompt_rules") or skill.prompt_rules)
    skill.a_plus_prompt = str(a_plus.get("system_prompt") or skill.a_plus_prompt)
    skill.updated_by = principal.user.id
    category.default_skill_id = skill.id
    category.updated_by = principal.user.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="category_skill.version_set_default", resource_type="category_skill_version", resource_id=version.id,
                  metadata={"skill_id": skill.id, "category_id": category.id, "version_number": version.version_number})
    await db.commit()
    return await _skill_response(db, skill)
