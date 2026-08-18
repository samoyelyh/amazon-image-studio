from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.content import Asset, GeneratedOutput, Project, ProjectVersion
from app.models.listing_workflow import (
    APlusProject,
    CategoryImageTemplate,
    CategorySkill,
    CategorySkillVersion,
    ImagePromptItem,
    ListingImageProject,
    ListingImageTaskGroup,
    ListingGenerationSession,
    ListingVersion,
    ProductAnalysisResult,
    ProductCategory,
    PromptDebugConfig,
)
from app.models.tasks import Job, JobBatch
from app.schemas.listing_workflow import (
    APlusBuildModulesRequest,
    APlusBuildModulesResponse,
    AnalyzeProductRequest,
    AnalyzeProductResponse,
    BuildImagePromptsRequest,
    BuildImagePromptsResponse,
    CategoryCreateRequest,
    CategoryImageTemplateCreateRequest,
    CategoryImageTemplateResponse,
    CategoryImageTemplateUpdateRequest,
    CategoryRecommendationResponse,
    CategoryResponse,
    CategorySkillCreateRequest,
    CategorySkillResponse,
    CategorySkillUpdateRequest,
    CategoryUpdateRequest,
    ConfirmListingRequest,
    FreeVariationContextResponse,
    FreeVariationContextUpdateRequest,
    FreeVariationGenerateRequest,
    FreeVariationProjectRequest,
    FreeVariationPromptBuildRequest,
    FreeVariationPromptBuildResponse,
    FreeVariationRecommendationResponse,
    GenerateListingImagesRequest,
    GenerateListingImagesResponse,
    ImageVariationGenerateRequest,
    ImageVariationOptionsResponse,
    ImageVariationPromptBuildRequest,
    ImageVariationPromptBuildResponse,
    ListingSessionResponse,
    ListingSessionSummaryResponse,
    ListingSessionUpdateRequest,
    ListingContentOptimizationRequest,
    ListingContentOptimizationResponse,
    OutputOptionsResponse,
    OutputProjectCreateRequest,
    OutputProjectGenerateRequest,
    OutputProjectGenerateResponse,
    OutputProjectResponse,
    OutputProjectSummary,
    OutputProjectUpdateRequest,
    ListingImageTaskGroupPage,
    ListingImageTaskGroupResponse,
    ListingImageTaskGroupRetryRequest,
    PromptSnapshotResponse,
    ProjectPromptBuildRequest,
    ProjectPromptBuildResponse,
    RecommendationJobResponse,
    RecommendCategoryRequest,
    QuickListingGenerateRequest,
    QuickListingGenerateResponse,
    QuickListingOptionsResponse,
    QuickListingStatusResponse,
)
from app.schemas.tasks import BatchJobItemRequest, JobBatchSubmitRequest, JobSubmitRequest
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.category_listing_service import (
    build_analysis_segment,
    build_category_analysis_prompts,
    build_category_recommendation_prompts,
    build_listing_content_optimization_prompts,
    build_listing_version_image_prompts,
    build_image_prompts,
    category_bundle,
    get_listing_session,
    parse_json_object,
    normalize_bilingual_listing_content,
    listing_english_text,
    resolve_bound_model_code,
    quick_category_bundle,
)
from app.services.task_service import cancel_job, dispatch_jobs, due_jobs, refresh_batch_status, submit_batch, submit_job
from app.services.prompt_optimizer_service import reconcile_prompt_item, usable_project_prompts
from app.services.category_skill_service import build_skill_snapshot
from app.services.listing_image_task_group_service import (
    build_input_asset_snapshot, create_group_for_batch, ensure_legacy_groups, task_group_response,
)
from app.services.listing_image_module_service import (
    STANDARD_MODULE_CODES,
    build_listing_image_modules,
)
from app.services.storage_service import StorageService, get_storage_service
from app.services.quick_listing_service import (
    continue_quick_listing_generation,
    mark_quick_generation_failed,
    quick_job_metadata,
)
from app.services.smart_image_variation_service import (
    FREE_ITEM_CODE,
    build_and_save_free_variation_prompt,
    build_and_save_variation_prompts,
    create_free_variation_project,
    enabled_variation_types,
    optional_skill_recommendations,
    variation_config,
)


categories_router = APIRouter(prefix="/categories", tags=["product-categories"])
skills_router = APIRouter(prefix="/category-skills", tags=["category-skills"])
templates_router = APIRouter(prefix="/category-image-templates", tags=["category-image-templates"])
workbench_router = APIRouter(prefix="/listing-workbench", tags=["listing-workbench"])
listing_image_router = APIRouter(prefix="/listing-image-projects", tags=["listing-image-projects"])
listing_image_task_group_router = APIRouter(prefix="/listing-image-task-groups", tags=["listing-image-task-groups"])
a_plus_router = APIRouter(prefix="/a-plus-projects", tags=["a-plus-projects"])
UTC = timezone.utc


def _organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队", 409)
    return principal.organization.id


async def _category_response(db: AsyncSession, category: ProductCategory) -> CategoryResponse:
    await db.refresh(category)
    skill = await db.get(CategorySkill, category.default_skill_id) if category.default_skill_id else None
    template = await db.get(CategoryImageTemplate, category.default_image_template_id) if category.default_image_template_id else None
    return CategoryResponse.model_validate(category).model_copy(update={
        "default_skill_name": skill.skill_name if skill else None,
        "default_image_template_name": template.template_name if template else None,
        "default_image_types": list(template.default_image_types or []) if template else [],
    })


async def _verify_assets(db: AsyncSession, organization_id: str, asset_ids: list[str]) -> None:
    found = set((await db.scalars(select(Asset.id).where(
        Asset.organization_id == organization_id,
        Asset.id.in_(set(asset_ids)),
        Asset.deleted_at.is_(None),
    ))).all())
    if found != set(asset_ids):
        raise AppError("asset.not_found", "一个或多个产品图不存在或无权访问", 404)


@categories_router.get("", response_model=list[CategoryResponse])
async def list_categories(
    include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[CategoryResponse]:
    statement = select(ProductCategory)
    if not (include_inactive and principal.is_platform_admin):
        statement = statement.where(ProductCategory.is_active.is_(True))
    categories = (await db.scalars(statement.order_by(ProductCategory.sort_order, ProductCategory.category_name))).all()
    return [await _category_response(db, item) for item in categories]


@categories_router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: str,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> CategoryResponse:
    category = await db.get(ProductCategory, category_id)
    if category is None or (not category.is_active and not principal.is_platform_admin):
        raise AppError("listing.category_not_found", "品类不存在或已停用", 404)
    return await _category_response(db, category)


@categories_router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategoryResponse:
    if await db.scalar(select(ProductCategory.id).where(ProductCategory.category_code == payload.category_code)):
        raise AppError("listing.category_code_exists", "品类代码已存在", 409)
    category = ProductCategory(**payload.model_dump(), created_by=principal.user.id, updated_by=principal.user.id)
    db.add(category)
    await db.flush()
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="listing_category.create", resource_type="product_category", resource_id=category.id)
    await db.commit()
    return await _category_response(db, category)


@categories_router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str, payload: CategoryUpdateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategoryResponse:
    category = await db.get(ProductCategory, category_id)
    if category is None:
        raise AppError("listing.category_not_found", "品类不存在", 404)
    values = payload.model_dump(exclude_unset=True)
    if values.get("default_skill_id"):
        skill = await db.get(CategorySkill, values["default_skill_id"])
        if skill is None or skill.category_id != category.id:
            raise AppError("listing.default_skill_invalid", "默认 Skill 不属于当前品类", 422)
    if values.get("default_image_template_id"):
        template = await db.get(CategoryImageTemplate, values["default_image_template_id"])
        if template is None or template.category_id != category.id:
            raise AppError("listing.default_template_invalid", "默认图片模板不属于当前品类", 422)
    for key, value in values.items():
        setattr(category, key, value)
    category.updated_by = principal.user.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="listing_category.update", resource_type="product_category", resource_id=category.id,
                  metadata={"fields": sorted(values)})
    await db.commit()
    return await _category_response(db, category)


@skills_router.get("", response_model=list[CategorySkillResponse])
async def list_category_skills(
    category_id: str | None = Query(default=None), include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[CategorySkillResponse]:
    statement = select(CategorySkill)
    if category_id:
        statement = statement.where(CategorySkill.category_id == category_id)
    if not (include_inactive and principal.is_platform_admin):
        statement = statement.where(CategorySkill.is_active.is_(True))
    return list((await db.scalars(statement.order_by(CategorySkill.category_id, CategorySkill.skill_code, CategorySkill.version.desc()))).all())


@skills_router.post("", response_model=CategorySkillResponse, status_code=status.HTTP_201_CREATED)
async def create_category_skill(
    payload: CategorySkillCreateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkill:
    if await db.get(ProductCategory, payload.category_id) is None:
        raise AppError("listing.category_not_found", "品类不存在", 404)
    existing = await db.scalar(select(CategorySkill.id).where(
        CategorySkill.category_id == payload.category_id,
        CategorySkill.skill_code == payload.skill_code,
        CategorySkill.version == payload.version,
    ))
    if existing:
        raise AppError("listing.skill_version_exists", "该 Skill 版本已存在", 409)
    skill = CategorySkill(**payload.model_dump(), created_by=principal.user.id, updated_by=principal.user.id)
    db.add(skill)
    await db.flush()
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="listing_skill.create", resource_type="category_skill", resource_id=skill.id)
    await db.commit()
    await db.refresh(skill)
    return skill


@skills_router.post("/{skill_id}/copy", response_model=CategorySkillResponse, status_code=status.HTTP_201_CREATED)
async def copy_category_skill(
    skill_id: str, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkill:
    source = await db.get(CategorySkill, skill_id)
    if source is None:
        raise AppError("listing.skill_not_found", "Skill 不存在", 404)
    latest = int(await db.scalar(select(CategorySkill.version).where(
        CategorySkill.category_id == source.category_id, CategorySkill.skill_code == source.skill_code,
    ).order_by(CategorySkill.version.desc()).limit(1)) or source.version)
    copy = CategorySkill(
        category_id=source.category_id, skill_name=f"{source.skill_name} v{latest + 1}",
        skill_code=source.skill_code, is_active=False, version=latest + 1,
        analysis_prompt=source.analysis_prompt, listing_title_prompt=source.listing_title_prompt,
        bullet_points_prompt=source.bullet_points_prompt, a_plus_prompt=source.a_plus_prompt,
        image_prompt_template=source.image_prompt_template,
        image_types_config=source.image_types_config, prompt_rules=source.prompt_rules,
        created_by=principal.user.id, updated_by=principal.user.id,
    )
    db.add(copy)
    await db.flush()
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="listing_skill.copy", resource_type="category_skill", resource_id=copy.id,
                  metadata={"source_skill_id": source.id})
    await db.commit()
    await db.refresh(copy)
    return copy


@skills_router.put("/{skill_id}", response_model=CategorySkillResponse)
async def update_category_skill(
    skill_id: str, payload: CategorySkillUpdateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategorySkill:
    skill = await db.get(CategorySkill, skill_id)
    if skill is None:
        raise AppError("listing.skill_not_found", "Skill 不存在", 404)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(skill, key, value)
    skill.updated_by = principal.user.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="listing_skill.update", resource_type="category_skill", resource_id=skill.id,
                  metadata={"fields": sorted(values)})
    await db.commit()
    await db.refresh(skill)
    return skill


@templates_router.get("", response_model=list[CategoryImageTemplateResponse])
async def list_category_image_templates(
    category_id: str | None = Query(default=None), include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[CategoryImageTemplate]:
    statement = select(CategoryImageTemplate)
    if category_id:
        statement = statement.where(CategoryImageTemplate.category_id == category_id)
    if not (include_inactive and principal.is_platform_admin):
        statement = statement.where(CategoryImageTemplate.is_active.is_(True))
    return list((await db.scalars(statement.order_by(CategoryImageTemplate.category_id, CategoryImageTemplate.version.desc()))).all())


@templates_router.post("", response_model=CategoryImageTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_category_image_template(
    payload: CategoryImageTemplateCreateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategoryImageTemplate:
    if await db.get(ProductCategory, payload.category_id) is None:
        raise AppError("listing.category_not_found", "品类不存在", 404)
    template = CategoryImageTemplate(**payload.model_dump(), created_by=principal.user.id, updated_by=principal.user.id)
    db.add(template)
    await db.flush()
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="listing_image_template.create", resource_type="category_image_template", resource_id=template.id)
    await db.commit()
    await db.refresh(template)
    return template


@templates_router.put("/{template_id}", response_model=CategoryImageTemplateResponse)
async def update_category_image_template(
    template_id: str, payload: CategoryImageTemplateUpdateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("platform.admin")),
) -> CategoryImageTemplate:
    template = await db.get(CategoryImageTemplate, template_id)
    if template is None:
        raise AppError("listing.template_not_found", "图片模板不存在", 404)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(template, key, value)
    template.updated_by = principal.user.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=None,
                  action="listing_image_template.update", resource_type="category_image_template", resource_id=template.id,
                  metadata={"fields": sorted(values)})
    await db.commit()
    await db.refresh(template)
    return template


@workbench_router.post("/recommend-category", response_model=RecommendationJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def recommend_category(
    payload: RecommendCategoryRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> RecommendationJobResponse:
    organization_id = _organization_id(principal)
    await _verify_assets(db, organization_id, payload.product_image_asset_ids)
    categories = list((await db.scalars(select(ProductCategory).where(
        ProductCategory.is_active.is_(True),
    ).order_by(ProductCategory.sort_order))).all())
    if not categories:
        raise AppError("listing.categories_empty", "当前没有可用的 Listing 品类", 422)
    system_prompt, user_prompt = build_category_recommendation_prompts(categories)
    model_code = await resolve_bound_model_code(
        db, organization_id=organization_id, operation_code="listing.plan", capability="text_generation",
        additional_capabilities={"vision_input"},
    )
    job, created = await submit_job(db, settings, organization_id=organization_id, user_id=principal.user.id, payload=JobSubmitRequest(
        operation_code="listing.plan", workspace_type="listing", queue_name="planning_queue",
        capability="text_generation", model_code=model_code, idempotency_key=payload.idempotency_key,
        input={
            "system_prompt": system_prompt, "user_prompt": user_prompt,
            "reference_asset_ids": payload.product_image_asset_ids, "temperature": 0.1,
            "metadata": {"workflow": "category_recommendation"},
        },
        billing_factors={"quality": "standard", "resolution": "text"},
    ))
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return RecommendationJobResponse(job_id=job.id, status=job.status)


@workbench_router.get("/recommendations/{job_id}", response_model=CategoryRecommendationResponse)
async def get_category_recommendation(
    job_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> CategoryRecommendationResponse:
    organization_id = _organization_id(principal)
    job = await db.scalar(select(Job).where(Job.id == job_id, Job.organization_id == organization_id))
    if job is None:
        raise AppError("job.not_found", "推荐任务不存在或无权访问", 404)
    if job.status == "failed":
        return CategoryRecommendationResponse(job_id=job.id, status=job.status, error_message=job.error_message)
    if job.status != "succeeded":
        return CategoryRecommendationResponse(job_id=job.id, status=job.status)
    metadata = (job.result_json or {}).get("metadata")
    text = str(metadata.get("text") or "") if isinstance(metadata, dict) else ""
    parsed = parse_json_object(text)
    code = str(parsed.get("category_code") or "").strip()
    category = await db.scalar(select(ProductCategory).where(
        ProductCategory.category_code == code, ProductCategory.is_active.is_(True),
    )) if code else None
    confidence_value = parsed.get("confidence")
    try:
        confidence = max(0.0, min(1.0, float(confidence_value)))
    except (TypeError, ValueError):
        confidence = 0.0
    return CategoryRecommendationResponse(
        job_id=job.id, status=job.status,
        category_id=category.id if category else None,
        category_code=category.category_code if category else None,
        category_name=category.category_name if category else None,
        confidence=confidence, reason=str(parsed.get("reason") or "").strip() or None,
    )


@workbench_router.post("/analyze-product", response_model=AnalyzeProductResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_product(
    payload: AnalyzeProductRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AnalyzeProductResponse:
    organization_id = _organization_id(principal)
    await _verify_assets(db, organization_id, payload.product_image_asset_ids)
    category, skill, template = await category_bundle(db, payload.selected_category_id)
    skill_version_id = getattr(skill, "_runtime_skill_version_id", None)
    skill_version = await db.get(CategorySkillVersion, skill_version_id) if skill_version_id else None
    skill_snapshot = build_skill_snapshot(category, skill, template, skill_version)
    project_id = payload.project_id
    if project_id:
        project = await db.scalar(select(Project).where(
            Project.id == project_id, Project.organization_id == organization_id,
            Project.project_type == "listing", Project.deleted_at.is_(None),
        ))
        if project is None:
            raise AppError("project.not_found", "Listing 项目不存在或无权访问", 404)
    else:
        project = Project(
            organization_id=organization_id, project_type="listing",
            name=f"{category.category_name} Listing {datetime.now(UTC):%Y-%m-%d %H:%M}",
            description="按品类驱动的 Listing 生成会话",
            created_by=principal.user.id, updated_by=principal.user.id,
        )
        db.add(project)
        await db.flush()
        db.add(ProjectVersion(
            organization_id=organization_id, project_id=project.id, version_number=1,
            draft_json={"workflow": "category_listing", "category_id": category.id},
            change_summary="创建品类 Listing 分析会话", created_by=principal.user.id, created_at=datetime.now(UTC),
        ))
        project_id = project.id
    system_prompt, user_prompt = build_category_analysis_prompts(category, skill)
    model_code = await resolve_bound_model_code(
        db, organization_id=organization_id, operation_code="listing.plan", capability="text_generation",
        additional_capabilities={"vision_input"},
    )
    job, created = await submit_job(db, settings, organization_id=organization_id, user_id=principal.user.id, payload=JobSubmitRequest(
        operation_code="listing.plan", workspace_type="listing", queue_name="planning_queue",
        capability="text_generation", model_code=model_code, idempotency_key=payload.idempotency_key,
        project_id=project_id,
        input={
            "system_prompt": system_prompt, "user_prompt": user_prompt,
            "reference_asset_ids": payload.product_image_asset_ids, "temperature": 0.2,
            "metadata": {"workflow": "category_listing_analysis", "category_id": category.id, "skill_id": skill.id},
        },
        billing_factors={"quality": "standard", "resolution": "text"},
    ))
    listing_session = await db.scalar(select(ListingGenerationSession).where(
        ListingGenerationSession.organization_id == organization_id,
        ListingGenerationSession.planning_job_id == job.id,
    ))
    if listing_session is None:
        listing_session = ListingGenerationSession(
            organization_id=organization_id, project_id=project_id,
            category_id=category.id, skill_id=skill.id, skill_version_id=skill_version_id,
            category_skill_snapshot=skill_snapshot, planning_job_id=job.id,
            status="analyzing", source_asset_ids=payload.product_image_asset_ids,
            primary_asset_id=payload.primary_asset_id or payload.product_image_asset_ids[0],
            created_by=principal.user.id, updated_by=principal.user.id,
        )
        db.add(listing_session)
        await db.flush()
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return AnalyzeProductResponse(session_id=listing_session.id, project_id=project_id, job_id=job.id, status=job.status)


@workbench_router.get("/quick-options", response_model=QuickListingOptionsResponse)
async def get_quick_listing_options(
    category_id: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> QuickListingOptionsResponse:
    _organization_id(principal)
    category, skill, template, version = await quick_category_bundle(db, category_id)
    snapshot = build_skill_snapshot(category, skill, template, version)
    image_config = snapshot.get("image_prompt_config")
    variation = image_config.get("variation_config") if isinstance(image_config, dict) else None
    quick_defaults = variation.get("quick_defaults") if isinstance(variation, dict) and variation.get("enabled", True) else []
    quick_defaults = quick_defaults if isinstance(quick_defaults, list) else []
    default_variation_plan_count = sum(
        len(item.get("plan_codes") or []) for item in quick_defaults if isinstance(item, dict)
    )
    default_variation_image_count = sum(
        len(item.get("plan_codes") or []) * max(1, int(item.get("count") or 1))
        for item in quick_defaults if isinstance(item, dict)
    )
    return QuickListingOptionsResponse(
        category_id=category.id,
        category_name=category.category_name,
        skill_id=skill.id,
        skill_name=skill.skill_name,
        skill_version_id=version.id,
        skill_version_number=version.version_number,
        default_image_types=[str(item) for item in snapshot.get("default_image_types", [])],
        default_variation_plan_count=default_variation_plan_count,
        default_variation_image_count=default_variation_image_count,
    )


@workbench_router.post("/quick-generate", response_model=QuickListingGenerateResponse, status_code=status.HTTP_202_ACCEPTED)
async def quick_generate_listing(
    payload: QuickListingGenerateRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> QuickListingGenerateResponse:
    organization_id = _organization_id(principal)
    await _verify_assets(db, organization_id, payload.product_image_asset_ids)
    category, skill, template, skill_version = await quick_category_bundle(db, payload.selected_category_id)
    skill_snapshot = build_skill_snapshot(category, skill, template, skill_version)
    defaults = [str(item) for item in skill_snapshot.get("default_image_types", [])]
    selected = payload.selected_image_types or defaults
    if not selected:
        raise AppError("listing.image_types_empty", "当前默认 Skill 没有启用可生成的图片类型。", 422)
    invalid = sorted(set(selected) - set(defaults))
    if invalid:
        raise AppError("listing.image_type_invalid", "选择了当前默认 Skill 未启用的图片类型。", 422, {"invalid": invalid})
    if len(selected) != len(set(selected)):
        raise AppError("listing.image_type_duplicate", "图片类型不能重复。", 422)

    delivery = {
        "concurrency": min(payload.concurrency, len(selected)),
        "size": payload.size,
        "aspect_ratio": payload.aspect_ratio,
        "requested_width": payload.requested_width,
        "requested_height": payload.requested_height,
        "quality": payload.quality,
        "output_format": payload.output_format,
        "include_default_variations": payload.include_default_variations,
    }
    existing_job = await db.scalar(select(Job).where(
        Job.organization_id == organization_id,
        Job.idempotency_key == payload.idempotency_key,
    ))
    if existing_job is not None:
        existing_metadata = quick_job_metadata(existing_job)
        same_request = (
            existing_metadata is not None
            and str(existing_metadata.get("category_id") or "") == category.id
            and list(existing_metadata.get("quick_selected_image_types") or []) == selected
            and dict(existing_metadata.get("quick_delivery") or {}) == delivery
            and list(existing_job.input_json.get("reference_asset_ids") or []) == payload.product_image_asset_ids
        )
        if not same_request:
            raise AppError("job.idempotency_conflict", "幂等键已用于不同的快速生成请求。", 409)
        existing_session = await db.scalar(select(ListingGenerationSession).where(
            ListingGenerationSession.organization_id == organization_id,
            ListingGenerationSession.planning_job_id == existing_job.id,
        ))
        if existing_session is None:
            raise AppError("listing.quick_session_missing", "快速生成任务缺少 Listing Session。", 409)
        return QuickListingGenerateResponse(
            session_id=existing_session.id,
            planning_job_id=existing_job.id,
            status=existing_job.status,
            category_name=category.category_name,
            skill_name=skill.skill_name,
            skill_version_number=skill_version.version_number,
            selected_image_types=selected,
        )

    project = Project(
        organization_id=organization_id,
        project_type="listing",
        name=f"{category.category_name} Listing 快速生成 {datetime.now(UTC):%Y-%m-%d %H:%M}",
        description="品类 Listing 快速生成会话",
        created_by=principal.user.id,
        updated_by=principal.user.id,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectVersion(
        organization_id=organization_id,
        project_id=project.id,
        version_number=1,
        draft_json={"workflow": "category_listing", "category_id": category.id, "mode": "quick"},
        change_summary="创建品类 Listing 快速生成会话",
        created_by=principal.user.id,
        created_at=datetime.now(UTC),
    ))
    system_prompt, user_prompt = build_category_analysis_prompts(category, skill)
    model_code = await resolve_bound_model_code(
        db,
        organization_id=organization_id,
        operation_code="listing.plan",
        capability="text_generation",
        additional_capabilities={"vision_input"},
    )
    job, created = await submit_job(
        db,
        settings,
        organization_id=organization_id,
        user_id=principal.user.id,
        payload=JobSubmitRequest(
            operation_code="listing.plan",
            workspace_type="listing",
            queue_name="planning_queue",
            capability="text_generation",
            model_code=model_code,
            idempotency_key=payload.idempotency_key,
            project_id=project.id,
            input={
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "reference_asset_ids": payload.product_image_asset_ids,
                "temperature": 0.2,
                "metadata": {
                    "workflow": "category_listing_analysis",
                    "quick_mode": True,
                    "category_id": category.id,
                    "skill_id": skill.id,
                    "quick_selected_image_types": selected,
                    "quick_delivery": delivery,
                },
            },
            billing_factors={"quality": "standard", "resolution": "text"},
        ),
    )
    listing_session = ListingGenerationSession(
        organization_id=organization_id,
        project_id=project.id,
        category_id=category.id,
        skill_id=skill.id,
        skill_version_id=skill_version.id,
        category_skill_snapshot=skill_snapshot,
        planning_job_id=job.id,
        status="analyzing",
        source_asset_ids=payload.product_image_asset_ids,
        primary_asset_id=payload.primary_asset_id or payload.product_image_asset_ids[0],
        created_by=principal.user.id,
        updated_by=principal.user.id,
    )
    db.add(listing_session)
    await db.flush()
    job_metadata = job.input_json.get("metadata")
    job.input_json = {
        **job.input_json,
        "metadata": {
            **(job_metadata if isinstance(job_metadata, dict) else {}),
            "listing_session_id": listing_session.id,
            "quick_image_idempotency_key": f"quick-images:{job.id}",
        },
    }
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return QuickListingGenerateResponse(
        session_id=listing_session.id,
        planning_job_id=job.id,
        status=job.status,
        category_name=category.category_name,
        skill_name=skill.skill_name,
        skill_version_number=skill_version.version_number,
        selected_image_types=selected,
    )


@workbench_router.get("/quick-generations/{session_id}", response_model=QuickListingStatusResponse)
async def get_quick_listing_status(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> QuickListingStatusResponse:
    organization_id = _organization_id(principal)
    workflow = await get_listing_session(db, organization_id=organization_id, session_id=session_id)
    planning_job = await db.get(Job, workflow.planning_job_id) if workflow.planning_job_id else None
    metadata = quick_job_metadata(planning_job) if planning_job else None
    if planning_job is None or metadata is None or str(metadata.get("listing_session_id") or "") != workflow.id:
        raise AppError("listing.quick_not_found", "快速生成任务不存在或无权访问。", 404)
    if planning_job.status == "succeeded" and workflow.image_batch_id is None and workflow.status != "failed":
        try:
            await continue_quick_listing_generation(db, settings, planning_job=planning_job)
        except AppError as error:
            await mark_quick_generation_failed(db, planning_job=planning_job, message=error.message)
        workflow = await get_listing_session(db, organization_id=organization_id, session_id=session_id)
    version = await db.get(ListingVersion, workflow.current_listing_version_id) if workflow.current_listing_version_id else None
    project = await db.scalar(select(ListingImageProject).where(ListingImageProject.session_id == workflow.id))
    group = await db.scalar(select(ListingImageTaskGroup).where(
        ListingImageTaskGroup.listing_image_project_id == project.id,
        ListingImageTaskGroup.job_batch_id == workflow.image_batch_id,
    )) if project and workflow.image_batch_id else None
    group_response = await task_group_response(db, storage, settings, group) if group else None
    if workflow.status in {"failed", "analysis_failed"} or planning_job.status == "failed":
        stage = "failed"
    elif group_response:
        stage = group_response.status
    elif planning_job.status in {"queued", "waiting_for_resource", "dispatching", "running", "retry_waiting"}:
        stage = "analyzing"
    else:
        stage = "preparing_images"
    snapshot = dict(workflow.category_skill_snapshot or {})
    selected = [str(item) for item in (metadata.get("quick_selected_image_types") or snapshot.get("default_image_types") or [])]
    response = QuickListingStatusResponse(
        session_id=workflow.id,
        stage=stage,
        status=workflow.status,
        category_name=str(snapshot.get("category_name") or ""),
        skill_name=str(snapshot.get("skill_name") or ""),
        skill_version_number=int(snapshot.get("skill_version") or 0) or None,
        selected_image_types=selected,
        listing_version_id=version.id if version else None,
        listing_version_number=version.version_number if version else None,
        listing_summary=dict(version.listing_snapshot or {}) if version else None,
        listing_image_project_id=project.id if project else None,
        task_group_id=group.id if group else None,
        task_group_status=group_response.status if group_response else None,
        target_url=f"/listing-image-workbench/{workflow.id}?group={group.id}&source=quick" if group else None,
        error_message=workflow.error_message or planning_job.error_message,
    )
    await db.commit()
    return response


async def _listing_session_response(db: AsyncSession, value: ListingGenerationSession) -> ListingSessionResponse:
    await db.refresh(value)
    category, skill, template = await category_bundle(db, value.category_id, active_only=False)
    analysis = await db.get(ProductAnalysisResult, value.analysis_result_id) if value.analysis_result_id else None
    prompt = await db.scalar(select(PromptDebugConfig).where(PromptDebugConfig.session_id == value.id))
    planning_job = await db.get(Job, value.planning_job_id) if value.planning_job_id else None
    batch = await db.get(JobBatch, value.image_batch_id) if value.image_batch_id else None
    listing_version = await db.get(ListingVersion, value.current_listing_version_id) if value.current_listing_version_id else None
    prompt_response = PromptSnapshotResponse(
        system_prompt=prompt.system_prompt_snapshot,
        skill_prompt=prompt.skill_prompt_snapshot,
        analysis_segment=prompt.analysis_prompt_segment,
        user_prompt=prompt.user_prompt,
        final_prompt=prompt.final_prompt,
        final_prompts=prompt.final_prompts,
    ) if prompt else None
    snapshot = dict(value.category_skill_snapshot or {})
    return ListingSessionResponse(
        id=value.id, project_id=value.project_id,
        category_id=category.id, category_code=category.category_code, category_name=category.category_name,
        skill_id=skill.id, skill_name=skill.skill_name,
        skill_version_id=value.skill_version_id,
        skill_version_number=int(snapshot.get("skill_version") or skill.version),
        category_skill_snapshot=snapshot or None,
        status=value.status,
        listing_version_id=listing_version.id if listing_version else None,
        listing_version_number=listing_version.version_number if listing_version else None,
        confirmed_at=value.confirmed_at, confirmed_by=value.confirmed_by,
        planning_job_id=value.planning_job_id,
        planning_job_status=planning_job.status if planning_job else None,
        image_batch_id=value.image_batch_id, image_batch_status=batch.status if batch else None,
        source_asset_ids=list(value.source_asset_ids), primary_asset_id=value.primary_asset_id,
        structured_attributes=dict(analysis.structured_attributes) if analysis else {},
        listing_content=normalize_bilingual_listing_content(value.listing_content or (analysis.listing_content if analysis else {})),
        default_image_types=list(snapshot.get("default_image_types") or template.default_image_types or []), prompt=prompt_response,
        error_message=value.error_message, state_version=value.state_version, current_step=value.current_step,
        last_saved_at=value.last_saved_at, created_at=value.created_at, updated_at=value.updated_at,
    )


@workbench_router.get("/sessions", response_model=list[ListingSessionSummaryResponse])
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[ListingSessionSummaryResponse]:
    rows = (await db.execute(
        select(ListingGenerationSession, ProductCategory, CategorySkill, ListingVersion)
        .join(ProductCategory, ProductCategory.id == ListingGenerationSession.category_id)
        .join(CategorySkill, CategorySkill.id == ListingGenerationSession.skill_id)
        .outerjoin(ListingVersion, ListingVersion.id == ListingGenerationSession.current_listing_version_id)
        .where(ListingGenerationSession.organization_id == _organization_id(principal))
        .order_by(ListingGenerationSession.updated_at.desc())
        .limit(limit)
    )).all()
    result: list[ListingSessionSummaryResponse] = []
    for session, category, skill, version in rows:
        snapshot = dict(session.category_skill_snapshot or {})
        image_config = snapshot.get("image_prompt_config")
        image_config = image_config if isinstance(image_config, dict) else {}
        variation = image_config.get("variation_config")
        variation = variation if isinstance(variation, dict) else {}
        enabled_types = [
            item for item in (variation.get("types") or [])
            if isinstance(item, dict) and item.get("enabled", True)
        ]
        listing = normalize_bilingual_listing_content(
            version.listing_snapshot if version else (session.listing_content or {})
        )
        title = listing.get("title") if isinstance(listing, dict) else {}
        title = title if isinstance(title, dict) else {}
        result.append(ListingSessionSummaryResponse(
            id=session.id,
            category_name=category.category_name,
            skill_name=skill.skill_name,
            skill_version_number=int(snapshot.get("skill_version") or skill.version),
            status=session.status,
            listing_version_number=version.version_number if version else None,
            confirmed_at=session.confirmed_at,
            primary_asset_id=session.primary_asset_id,
            source_asset_ids=list(session.source_asset_ids or []),
            listing_title_en=str(title.get("en") or ""),
            listing_title_zh=str(title.get("zh") or ""),
            variation_enabled=variation.get("enabled", True) is not False and bool(enabled_types),
            updated_at=session.updated_at,
        ))
    return result


@workbench_router.get("/sessions/{session_id}", response_model=ListingSessionResponse)
async def get_session(
    session_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> ListingSessionResponse:
    value = await get_listing_session(db, organization_id=_organization_id(principal), session_id=session_id)
    await db.flush()
    response = await _listing_session_response(db, value)
    await db.commit()
    return response


@workbench_router.patch("/sessions/{session_id}", response_model=ListingSessionResponse)
async def update_session(
    session_id: str, payload: ListingSessionUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> ListingSessionResponse:
    value = await get_listing_session(db, organization_id=_organization_id(principal), session_id=session_id)
    if payload.expected_state_version is not None and payload.expected_state_version != value.state_version:
        raise AppError(
            "listing.state_version_conflict", "该草稿已被更新，请刷新后合并修改", 409,
            {"expected": payload.expected_state_version, "actual": value.state_version},
        )
    if value.analysis_result_id is None:
        raise AppError("listing.analysis_pending", "商品分析尚未完成", 409)
    analysis = await db.get(ProductAnalysisResult, value.analysis_result_id)
    prompt = await db.scalar(select(PromptDebugConfig).where(PromptDebugConfig.session_id == value.id))
    _, skill, template = await category_bundle(db, value.category_id)
    snapshot = dict(value.category_skill_snapshot or {})
    if snapshot:
        skill._runtime_skill_config = {
            key: snapshot.get(key, {}) for key in (
                "analysis_config", "listing_config", "translation_config", "image_prompt_config", "a_plus_config"
            )
        }
    if payload.structured_attributes is not None:
        analysis.structured_attributes = payload.structured_attributes
        analysis.updated_by = principal.user.id
    if payload.listing_content is not None:
        normalized_listing = normalize_bilingual_listing_content(payload.listing_content)
        analysis.listing_content = normalized_listing
        value.listing_content = normalized_listing
        analysis.updated_by = principal.user.id
    if value.status == "confirmed" and (payload.structured_attributes is not None or payload.listing_content is not None):
        value.status = "editing"
    user_prompt = payload.user_prompt if payload.user_prompt is not None else (prompt.user_prompt if prompt else "")
    image_types, prompts, segment = build_image_prompts(
        template=template, skill=skill, attributes=analysis.structured_attributes, user_prompt=user_prompt,
        snapshot=snapshot or None,
    )
    if prompt is None:
        prompt = PromptDebugConfig(
            organization_id=value.organization_id, session_id=value.id, category_id=value.category_id, skill_id=value.skill_id,
            system_prompt_snapshot=str(snapshot.get("system_prompt") or template.system_prompt),
            skill_prompt_snapshot=str(snapshot.get("image_prompt_template") or skill.image_prompt_template),
            analysis_prompt_segment=segment, user_prompt=user_prompt, final_prompt=prompts[image_types[0]], final_prompts=prompts,
            created_by=principal.user.id, updated_by=principal.user.id,
        )
        db.add(prompt)
    else:
        prompt.analysis_prompt_segment = segment
        prompt.user_prompt = user_prompt
        prompt.final_prompt = prompts[image_types[0]]
        prompt.final_prompts = prompts
        prompt.updated_by = principal.user.id
    value.updated_by = principal.user.id
    if payload.current_step is not None:
        value.current_step = payload.current_step
    value.state_version += 1
    value.last_saved_at = datetime.now(UTC)
    await db.commit()
    return await _listing_session_response(db, value)


@workbench_router.post("/build-image-prompts", response_model=BuildImagePromptsResponse)
async def build_prompts(
    payload: BuildImagePromptsRequest,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> BuildImagePromptsResponse:
    value = await get_listing_session(db, organization_id=_organization_id(principal), session_id=payload.session_id)
    _require_confirmed(value)
    if value.analysis_result_id is None:
        raise AppError("listing.analysis_pending", "商品分析尚未完成", 409)
    analysis = await db.get(ProductAnalysisResult, value.analysis_result_id)
    _, skill, template = await category_bundle(db, value.category_id)
    snapshot = dict(value.category_skill_snapshot or {})
    prompt_config = await db.scalar(select(PromptDebugConfig).where(PromptDebugConfig.session_id == value.id))
    user_prompt = payload.user_prompt_override if payload.user_prompt_override is not None else (prompt_config.user_prompt if prompt_config else "")
    image_types, prompts, segment = build_image_prompts(
        template=template, skill=skill, attributes=analysis.structured_attributes,
        selected_image_types=payload.selected_image_types, user_prompt=user_prompt, snapshot=snapshot or None,
    )
    if prompt_config:
        prompt_config.user_prompt = user_prompt
        prompt_config.analysis_prompt_segment = segment
        prompt_config.final_prompt = prompts[image_types[0]]
        prompt_config.final_prompts = prompts
        prompt_config.updated_by = principal.user.id
    await db.commit()
    return BuildImagePromptsResponse(
        session_id=value.id, image_types=image_types, prompts=prompts,
        system_prompt=str(snapshot.get("system_prompt") or template.system_prompt),
        skill_prompt=str(snapshot.get("image_prompt_template") or skill.image_prompt_template),
        analysis_segment=segment, user_prompt=user_prompt,
    )


@workbench_router.post(
    "/sessions/{session_id}/optimize-listing",
    response_model=ListingContentOptimizationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def optimize_listing_content(
    session_id: str, payload: ListingContentOptimizationRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> ListingContentOptimizationResponse:
    organization_id = _organization_id(principal)
    value = await get_listing_session(db, organization_id=organization_id, session_id=session_id)
    if value.analysis_result_id is None:
        raise AppError("listing.analysis_pending", "商品分析尚未完成", 409)
    analysis = await db.get(ProductAnalysisResult, value.analysis_result_id)
    category, skill, _ = await category_bundle(db, value.category_id)
    snapshot = dict(value.category_skill_snapshot or {})
    if snapshot:
        skill._runtime_skill_config = {
            key: snapshot.get(key, {}) for key in (
                "analysis_config", "listing_config", "translation_config", "image_prompt_config", "a_plus_config"
            )
        }
    content = normalize_bilingual_listing_content(payload.listing_content)
    system_prompt, user_prompt = build_listing_content_optimization_prompts(
        direction=payload.direction, listing_content=content, category_name=category.category_name,
        analysis=dict(analysis.structured_attributes or {}), skill=skill,
    )
    model_code = await resolve_bound_model_code(
        db, organization_id=organization_id, operation_code="listing.plan", capability="text_generation",
    )
    job, created = await submit_job(db, settings, organization_id=organization_id, user_id=principal.user.id, payload=JobSubmitRequest(
        operation_code="listing.plan", workspace_type="listing", queue_name="planning_queue",
        capability="text_generation", model_code=model_code, idempotency_key=payload.idempotency_key,
        project_id=value.project_id,
        input={"system_prompt": system_prompt, "user_prompt": user_prompt, "temperature": 0.2,
               "reference_asset_ids": [], "metadata": {"workflow": "bilingual_listing_optimizer",
               "session_id": value.id, "direction": payload.direction}},
        billing_factors={"quality": "standard", "resolution": "text"},
        client_item_id=f"listing:{payload.direction}",
    ))
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return ListingContentOptimizationResponse(
        session_id=value.id, job_id=job.id, status=job.status, direction=payload.direction,
    )


@workbench_router.get(
    "/sessions/{session_id}/listing-optimizations/{job_id}",
    response_model=ListingContentOptimizationResponse,
)
async def get_listing_content_optimization(
    session_id: str, job_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> ListingContentOptimizationResponse:
    organization_id = _organization_id(principal)
    value = await get_listing_session(db, organization_id=organization_id, session_id=session_id)
    job = await db.scalar(select(Job).where(Job.id == job_id, Job.organization_id == organization_id))
    metadata = job.input_json.get("metadata") if job else None
    if job is None or not isinstance(metadata, dict) or metadata.get("workflow") != "bilingual_listing_optimizer" or metadata.get("session_id") != value.id:
        raise AppError("listing.optimization_not_found", "Listing优化任务不存在或无权访问", 404)
    direction = str(metadata.get("direction") or "")
    if direction not in {"en_to_zh", "zh_to_en"}:
        raise AppError("listing.optimization_invalid", "Listing优化任务上下文无效", 422)
    if job.status == "failed":
        return ListingContentOptimizationResponse(
            session_id=value.id, job_id=job.id, status=job.status, direction=direction,
            error_message=job.error_message or "Listing AI优化失败，请重试",
        )
    if job.status != "succeeded":
        return ListingContentOptimizationResponse(session_id=value.id, job_id=job.id, status=job.status, direction=direction)
    result_metadata = (job.result_json or {}).get("metadata")
    text = str(result_metadata.get("text") or "") if isinstance(result_metadata, dict) else ""
    parsed = parse_json_object(text)
    optimized = normalize_bilingual_listing_content(parsed.get("listing_content") or parsed)
    analysis = await db.get(ProductAnalysisResult, value.analysis_result_id)
    analysis.listing_content = optimized
    analysis.updated_by = principal.user.id
    value.listing_content = optimized
    if value.status == "confirmed":
        value.status = "editing"
    value.updated_by = principal.user.id
    value.state_version += 1
    value.last_saved_at = datetime.now(UTC)
    await db.commit()
    return ListingContentOptimizationResponse(
        session_id=value.id, job_id=job.id, status=job.status, direction=direction, listing_content=optimized,
    )
@workbench_router.post("/generate-images", response_model=GenerateListingImagesResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_images(
    payload: GenerateListingImagesRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> GenerateListingImagesResponse:
    organization_id = _organization_id(principal)
    value = await get_listing_session(db, organization_id=organization_id, session_id=payload.session_id)
    _require_confirmed(value)
    if value.analysis_result_id is None:
        raise AppError("listing.analysis_pending", "请先完成商品分析", 409)
    analysis = await db.get(ProductAnalysisResult, value.analysis_result_id)
    category, skill, template = await category_bundle(db, value.category_id)
    snapshot = dict(value.category_skill_snapshot or {})
    prompt_config = await db.scalar(select(PromptDebugConfig).where(PromptDebugConfig.session_id == value.id))
    user_prompt = payload.user_prompt_override if payload.user_prompt_override is not None else (prompt_config.user_prompt if prompt_config else "")
    image_types, prompts, segment = build_image_prompts(
        template=template, skill=skill, attributes=analysis.structured_attributes,
        selected_image_types=payload.selected_image_types, user_prompt=user_prompt, snapshot=snapshot or None,
    )
    model_code = payload.model_code or await resolve_bound_model_code(
        db, organization_id=organization_id, operation_code="listing.generate", capability="image_edit",
    )
    batch_payload = JobBatchSubmitRequest(
        name=f"{category.category_name} 品类 Listing 整套生成",
        workspace_type="listing", operation_code="listing.generate", capability="image_edit",
        model_code=model_code, idempotency_key=payload.idempotency_key,
        project_id=value.project_id, concurrency=min(payload.concurrency, len(image_types)),
        items=[BatchJobItemRequest(
            client_item_id=f"{value.id}:{image_type}", prompt=prompts[image_type],
            reference_asset_ids=list(value.source_asset_ids), size=payload.size, aspect_ratio=payload.aspect_ratio,
            requested_width=payload.requested_width, requested_height=payload.requested_height,
            quality=payload.quality, output_format=payload.output_format,
            output_compression=payload.output_compression,
            metadata={
                "workflow": "category_listing", "listing_session_id": value.id,
                "category_code": category.category_code, "image_type": image_type,
                "slot": f"category:{image_type}",
            },
        ) for image_type in image_types],
    )
    batch, jobs, created = await submit_batch(
        db, settings, organization_id=organization_id, user_id=principal.user.id, payload=batch_payload,
    )
    value.image_batch_id = batch.id
    value.status = "generating"
    value.updated_by = principal.user.id
    if prompt_config:
        prompt_config.user_prompt = user_prompt
        prompt_config.analysis_prompt_segment = segment
        prompt_config.final_prompt = prompts[image_types[0]]
        prompt_config.final_prompts = prompts
        prompt_config.updated_by = principal.user.id
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=len(jobs), batch_id=batch.id))
    return GenerateListingImagesResponse(
        session_id=value.id, batch_id=batch.id, status=batch.status,
        job_ids=[job.id for job in jobs], image_types=image_types,
    )


def _require_confirmed(value: ListingGenerationSession) -> None:
    # Image generation advances the Session status beyond ``confirmed``.
    # The confirmation timestamp/version are the durable authorization facts.
    if not value.confirmed_at or not value.current_listing_version_id:
        raise AppError("listing.not_confirmed", "请先完成并确认Listing内容。", 409)


def _skill_snapshot(category: ProductCategory, skill: CategorySkill, template: CategoryImageTemplate) -> dict[str, object]:
    return build_skill_snapshot(category, skill, template)


@workbench_router.post("/sessions/{session_id}/confirm", response_model=ListingSessionResponse)
async def confirm_listing(
    session_id: str, payload: ConfirmListingRequest,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> ListingSessionResponse:
    value = await get_listing_session(db, organization_id=_organization_id(principal), session_id=session_id)
    if value.analysis_result_id is None:
        raise AppError("listing.analysis_pending", "商品分析和Listing文案尚未生成", 409)
    analysis = await db.get(ProductAnalysisResult, value.analysis_result_id)
    if payload.structured_attributes is not None:
        analysis.structured_attributes = payload.structured_attributes
    if payload.listing_content is not None:
        normalized_listing = normalize_bilingual_listing_content(payload.listing_content)
        analysis.listing_content = normalized_listing
        value.listing_content = normalized_listing
    listing_content = normalize_bilingual_listing_content(value.listing_content or analysis.listing_content or {})
    if not listing_english_text(listing_content, "title") or not listing_content.get("bullet_points"):
        raise AppError("listing.content_incomplete", "请先填写Listing标题和五点描述", 422)
    category, skill, template = await category_bundle(db, value.category_id, active_only=False)
    latest_number = await db.scalar(select(func.max(ListingVersion.version_number)).where(ListingVersion.session_id == value.id)) or 0
    now = datetime.now(UTC)
    listing_version = ListingVersion(
        organization_id=value.organization_id, session_id=value.id, version_number=latest_number + 1,
        source_listing_version_id=value.current_listing_version_id,
        listing_snapshot=listing_content, analysis_snapshot=dict(analysis.structured_attributes or {}),
        category_skill_snapshot=dict(value.category_skill_snapshot or _skill_snapshot(category, skill, template)),
        confirmed_at=now, confirmed_by=principal.user.id, created_by=principal.user.id,
    )
    db.add(listing_version)
    await db.flush()
    value.current_listing_version_id = listing_version.id
    value.status = "confirmed"
    value.confirmed_at = now
    value.confirmed_by = principal.user.id
    value.updated_by = principal.user.id
    value.state_version += 1
    value.last_saved_at = now
    analysis.updated_by = principal.user.id
    await db.commit()
    return await _listing_session_response(db, value)


async def _project_summary(db: AsyncSession, project: ListingImageProject | APlusProject | None, current: ListingVersion | None) -> OutputProjectSummary:
    if project is None:
        return OutputProjectSummary(exists=False)
    version = await db.get(ListingVersion, project.listing_version_id)
    batch = await db.get(JobBatch, project.last_batch_id) if project.last_batch_id else None
    project_status = batch.status if batch else project.status
    return OutputProjectSummary(
        exists=True, project_id=project.id, status=project_status,
        listing_version_number=version.version_number if version else None,
        outdated=bool(current and version and current.id != version.id),
    )


@workbench_router.get("/sessions/{session_id}/output-options", response_model=OutputOptionsResponse)
async def get_output_options(
    session_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> OutputOptionsResponse:
    value = await get_listing_session(db, organization_id=_organization_id(principal), session_id=session_id)
    current = await db.get(ListingVersion, value.current_listing_version_id) if value.current_listing_version_id else None
    category = await db.get(ProductCategory, value.category_id)
    skill = await db.get(CategorySkill, value.skill_id)
    listing_project = await db.scalar(select(ListingImageProject).where(ListingImageProject.session_id == value.id))
    a_plus_project = await db.scalar(select(APlusProject).where(APlusProject.session_id == value.id))
    return OutputOptionsResponse(
        # Session status advances to generating/generated after image work, so
        # confirmation must be derived from the immutable Listing version.
        session_id=value.id, listing_confirmed=current is not None and current.confirmed_at is not None,
        listing_version_id=current.id if current else None,
        listing_version_number=current.version_number if current else None,
        listing_snapshot=dict(current.listing_snapshot) if current else {},
        category_name=category.category_name if category else "",
        skill_name=skill.skill_name if skill else "",
        skill_version_number=int((current.category_skill_snapshot if current else {}).get("skill_version") or 0) or None,
        primary_asset_id=value.primary_asset_id, source_asset_ids=list(value.source_asset_ids or []),
        confirmed_at=current.confirmed_at if current else None,
        listing_image_project=await _project_summary(db, listing_project, current),
        a_plus_project=await _project_summary(db, a_plus_project, current),
    )


async def _get_output_project(
    db: AsyncSession, *, organization_id: str, project_id: str, kind: str,
) -> ListingImageProject | APlusProject:
    model = ListingImageProject if kind == "listing_image" else APlusProject
    project = await db.scalar(select(model).where(model.id == project_id, model.organization_id == organization_id))
    if project is None:
        raise AppError(f"{kind}.project_not_found", "图片项目不存在或无权访问", 404)
    return project


async def _output_project_response(
    db: AsyncSession, project: ListingImageProject | APlusProject, kind: str,
) -> OutputProjectResponse:
    await db.refresh(project)
    # Status/result synchronization below may autoflush before subsequent
    # SELECTs. ``updated_at`` is server-managed and becomes expired after that
    # flush, so preserve the loaded values for async-safe serialization.
    created_at = project.created_at
    updated_at = project.updated_at
    version = await db.get(ListingVersion, project.listing_version_id)
    session = await db.get(ListingGenerationSession, project.session_id)
    current = await db.get(ListingVersion, session.current_listing_version_id) if session.current_listing_version_id else version
    category = await db.get(ProductCategory, session.category_id)
    skill = await db.get(CategorySkill, session.skill_id)
    batch = await db.get(JobBatch, project.last_batch_id) if project.last_batch_id else None
    if batch:
        project.status = batch.status
        generated_asset_ids = list((await db.scalars(select(GeneratedOutput.asset_id).where(
            GeneratedOutput.batch_id == batch.id,
            GeneratedOutput.organization_id == project.organization_id,
        ))).all())
        if generated_asset_ids:
            project.generated_asset_ids = list(dict.fromkeys(generated_asset_ids))
    project_modules: list[dict[str, object]] = []
    if kind == "listing_image":
        saved_attribute_overrides = project.prompt_config.get("module_attribute_overrides")
        saved_attribute_overrides = saved_attribute_overrides if isinstance(saved_attribute_overrides, dict) else {}
        project_modules, _ = build_listing_image_modules(
            analysis_snapshot=dict(version.analysis_snapshot or {}),
            listing_snapshot=dict(version.listing_snapshot or {}),
            skill_snapshot=dict(version.category_skill_snapshot or {}),
            selected_codes=["pure_white"],
            attribute_overrides=saved_attribute_overrides,
        )
        saved_prompts = project.prompt_config.get("prompts")
        saved_prompts = saved_prompts if isinstance(saved_prompts, dict) else {}
        project_modules = [
            {**module, "prompt": str(saved_prompts.get(str(module.get("code"))) or module.get("prompt") or "")}
            for module in project_modules
        ]
    return OutputProjectResponse(
        id=project.id, session_id=project.session_id, kind=kind, status=project.status,
        selected_template=project.selected_template, prompt_config=dict(project.prompt_config or {}),
        modules=list(project.modules or []) if isinstance(project, APlusProject) else project_modules,
        task_count=project.task_count, generated_asset_ids=list(project.generated_asset_ids or []),
        last_batch_id=project.last_batch_id, last_batch_status=batch.status if batch else None,
        listing_version_id=version.id, listing_version_number=version.version_number,
        latest_listing_version_number=current.version_number, outdated=version.id != current.id,
        listing_snapshot=dict(version.listing_snapshot), analysis_snapshot=dict(version.analysis_snapshot),
        category_skill_snapshot=dict(version.category_skill_snapshot), source_asset_ids=list(session.source_asset_ids),
        primary_asset_id=session.primary_asset_id, category_name=category.category_name, skill_name=skill.skill_name,
        state_version=project.state_version, last_saved_at=project.last_saved_at,
        created_at=created_at, updated_at=updated_at,
    )


async def _create_output_project(
    db: AsyncSession, *, payload: OutputProjectCreateRequest, principal: Principal, kind: str,
) -> ListingImageProject | APlusProject:
    value = await get_listing_session(db, organization_id=_organization_id(principal), session_id=payload.session_id)
    _require_confirmed(value)
    model = ListingImageProject if kind == "listing_image" else APlusProject
    project = await db.scalar(select(model).where(model.session_id == value.id))
    if project:
        if payload.adopt_latest_listing and project.listing_version_id != value.current_listing_version_id:
            project.listing_version_id = value.current_listing_version_id
            project.status = "editing"
            project.updated_by = principal.user.id
        return project
    values = dict(
        organization_id=value.organization_id, session_id=value.id,
        listing_version_id=value.current_listing_version_id, status="editing", selected_template=None,
        prompt_config={}, task_count=0, generated_asset_ids=[], created_by=principal.user.id, updated_by=principal.user.id,
    )
    project = model(**values, **({"modules": []} if kind == "a_plus" else {}))
    db.add(project)
    await db.flush()
    return project


async def _free_variation_context_response(
    db: AsyncSession, project: ListingImageProject,
) -> FreeVariationContextResponse:
    session = await db.get(ListingGenerationSession, project.session_id)
    if session is None:
        raise AppError("free_variation.session_missing", "自由裂变项目缺少Session上下文", 409)
    item = await db.scalar(select(ImagePromptItem).where(
        ImagePromptItem.organization_id == project.organization_id,
        ImagePromptItem.project_type == "listing_image",
        ImagePromptItem.project_id == project.id,
        ImagePromptItem.item_code == FREE_ITEM_CODE,
    ))
    if item is not None:
        await reconcile_prompt_item(db, item)
    current = dict(project.prompt_config or {})
    free = current.get("free_variation")
    free = free if isinstance(free, dict) else {}
    asset_ids = [str(value) for value in (free.get("asset_ids") or session.source_asset_ids or [])]
    primary_asset_id = str(free.get("primary_asset_id") or session.primary_asset_id or "") or None
    return FreeVariationContextResponse(
        project_id=project.id,
        session_id=session.id,
        category_id=session.category_id,
        asset_ids=asset_ids,
        primary_asset_id=primary_asset_id,
        chinese_prompt=str(free.get("chinese_prompt") or (item.chinese_editing_instruction if item else "")),
        final_english_prompt=item.optimized_english_prompt if item else "",
        prompt_item_id=item.id if item else None,
        prompt_status=item.status if item else None,
        selected_category_id=str(free.get("selected_category_id") or "") or None,
        template_fragments=[str(value) for value in (free.get("template_fragments") or [])],
    )


@workbench_router.post(
    "/free-variation-projects", response_model=FreeVariationContextResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_free_variation_workspace(
    payload: FreeVariationProjectRequest,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> FreeVariationContextResponse:
    organization_id = _organization_id(principal)
    if payload.source_session_id:
        session = await get_listing_session(
            db, organization_id=organization_id, session_id=payload.source_session_id,
        )
        _require_confirmed(session)
        project = await db.scalar(select(ListingImageProject).where(
            ListingImageProject.organization_id == organization_id,
            ListingImageProject.session_id == session.id,
        ))
        if project is None:
            project = ListingImageProject(
                organization_id=organization_id,
                session_id=session.id,
                listing_version_id=session.current_listing_version_id,
                status="editing",
                selected_template=None,
                prompt_config={},
                task_count=0,
                generated_asset_ids=[],
                state_version=0,
                last_saved_at=datetime.now(UTC),
                created_by=principal.user.id,
                updated_by=principal.user.id,
            )
            db.add(project)
            await db.flush()
        asset_ids = payload.asset_ids or list(session.source_asset_ids or [])
        primary_asset_id = payload.primary_asset_id or session.primary_asset_id or (asset_ids[0] if asset_ids else None)
        if not asset_ids or not primary_asset_id:
            raise AppError("free_variation.assets_required", "请至少上传一张参考图片", 422)
        await _verify_assets(db, organization_id, asset_ids)
        current = dict(project.prompt_config or {})
        free = dict(current.get("free_variation") or {})
        free.update({
            "mode": "free", "asset_ids": asset_ids, "primary_asset_id": primary_asset_id,
            "chinese_prompt": str(free.get("chinese_prompt") or ""),
        })
        project.prompt_config = {**current, "free_variation": free}
        project.updated_by = principal.user.id
        project.last_saved_at = datetime.now(UTC)
    else:
        await _verify_assets(db, organization_id, payload.asset_ids)
        session, _, project = await create_free_variation_project(
            db,
            organization_id=organization_id,
            user_id=principal.user.id,
            asset_ids=payload.asset_ids,
            primary_asset_id=payload.primary_asset_id or payload.asset_ids[0],
        )
    await db.commit()
    return await _free_variation_context_response(db, project)


@workbench_router.get(
    "/free-variation-projects/{project_id}", response_model=FreeVariationContextResponse,
)
async def get_free_variation_workspace(
    project_id: str,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> FreeVariationContextResponse:
    project = await _get_output_project(
        db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image",
    )
    response = await _free_variation_context_response(db, project)
    await db.commit()
    return response


@workbench_router.put(
    "/free-variation-projects/{project_id}", response_model=FreeVariationContextResponse,
)
async def update_free_variation_workspace(
    project_id: str,
    payload: FreeVariationContextUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> FreeVariationContextResponse:
    organization_id = _organization_id(principal)
    project = await _get_output_project(db, organization_id=organization_id, project_id=project_id, kind="listing_image")
    session = await get_listing_session(db, organization_id=organization_id, session_id=project.session_id)
    await _verify_assets(db, organization_id, payload.asset_ids)
    current = dict(project.prompt_config or {})
    free = dict(current.get("free_variation") or {})
    free.update({"mode": "free", "asset_ids": list(payload.asset_ids), "primary_asset_id": payload.primary_asset_id})
    project.prompt_config = {**current, "free_variation": free}
    project.updated_by = principal.user.id
    project.state_version += 1
    project.last_saved_at = datetime.now(UTC)
    await db.commit()
    return await _free_variation_context_response(db, project)


@workbench_router.get(
    "/free-variation-recommendations", response_model=FreeVariationRecommendationResponse,
)
async def get_free_variation_recommendations(
    category_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> FreeVariationRecommendationResponse:
    _organization_id(principal)
    return FreeVariationRecommendationResponse(**await optional_skill_recommendations(db, category_id))


def _snapshot_listing_prompts(
    version: ListingVersion, selected: list[str] | None, overrides: dict[str, str],
    module_attribute_overrides: dict[str, dict[str, object]] | None = None,
) -> dict[str, str]:
    if selected and set(selected).issubset(set(STANDARD_MODULE_CODES)):
        _, prompts = build_listing_image_modules(
            analysis_snapshot=dict(version.analysis_snapshot or {}),
            listing_snapshot=dict(version.listing_snapshot or {}),
            skill_snapshot=dict(version.category_skill_snapshot or {}),
            selected_codes=selected,
            attribute_overrides=module_attribute_overrides,
            prompt_overrides=overrides,
        )
        return prompts
    return build_listing_version_image_prompts(version, selected, overrides)


def _default_a_plus_modules(version: ListingVersion, template_code: str, module_codes: list[str] | None) -> list[dict[str, object]]:
    defaults = [
        ("brand_banner", "品牌展示", "Present the product as a cohesive e-commerce brand hero banner."),
        ("key_benefits", "核心卖点", "Visualize verified product benefits with a clean modular layout."),
        ("detail_story", "细节说明", "Show faithful close-up product details and construction."),
        ("lifestyle", "场景展示", "Create a commercially attractive lifestyle scene for the confirmed product."),
    ]
    allowed = set(module_codes or [item[0] for item in defaults])
    title = listing_english_text(version.listing_snapshot, "title")
    return [{"code": code, "name": name, "title": name, "body": title, "image_prompt": prompt, "template_code": template_code}
            for code, name, prompt in defaults if code in allowed]


def _a_plus_prompts(project: APlusProject, version: ListingVersion, selected: list[str] | None, overrides: dict[str, str]) -> dict[str, str]:
    modules = list(project.modules or _default_a_plus_modules(version, project.selected_template or "standard", None))
    wanted = set(selected or [str(item.get("code")) for item in modules])
    skill = version.category_skill_snapshot
    analysis_segment = build_analysis_segment(version.analysis_snapshot)
    prompts: dict[str, str] = {}
    for module in modules:
        code = str(module.get("code") or "")
        if code not in wanted:
            continue
        prompts[code] = "\n\n".join(filter(None, [
            str(skill.get("system_prompt") or ""), str(skill.get("a_plus_prompt") or ""), analysis_segment,
            f"Confirmed Listing: {version.listing_snapshot}", str(module.get("image_prompt") or ""),
            f"Module copy: {module.get('title', '')} / {module.get('body', '')}", str(overrides.get(code) or ""),
        ]))
    if not prompts:
        raise AppError("aplus.modules_empty", "请至少选择一个A+模块", 422)
    return prompts


@listing_image_router.post("", response_model=OutputProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_listing_image_project(payload: OutputProjectCreateRequest, db: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.submit"))) -> OutputProjectResponse:
    project = await _create_output_project(db, payload=payload, principal=principal, kind="listing_image")
    await db.commit()
    return await _output_project_response(db, project, "listing_image")


@listing_image_router.get("/{project_id}", response_model=OutputProjectResponse)
async def get_listing_image_project(project_id: str, db: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.read"))) -> OutputProjectResponse:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image")
    response = await _output_project_response(db, project, "listing_image")
    await db.commit()
    return response


@listing_image_router.patch("/{project_id}", response_model=OutputProjectResponse)
async def update_listing_image_project(project_id: str, payload: OutputProjectUpdateRequest, db: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.submit"))) -> OutputProjectResponse:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image")
    session = await get_listing_session(db, organization_id=project.organization_id, session_id=project.session_id)
    _require_confirmed(session)
    if payload.expected_state_version is not None and payload.expected_state_version != project.state_version:
        raise AppError("listing_image.state_version_conflict", "图片工作台草稿已被更新，请刷新后合并修改", 409,
                       {"expected": payload.expected_state_version, "actual": project.state_version})
    if payload.adopt_latest_listing:
        project.listing_version_id = session.current_listing_version_id
    if payload.selected_template is not None: project.selected_template = payload.selected_template
    if payload.prompt_config is not None: project.prompt_config = payload.prompt_config
    project.updated_by = principal.user.id
    project.state_version += 1
    project.last_saved_at = datetime.now(UTC)
    await db.commit()
    return await _output_project_response(db, project, "listing_image")


@listing_image_router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_listing_image_project(project_id: str, db: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.submit"))) -> None:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image")
    await db.delete(project)
    await db.commit()


@listing_image_router.post("/{project_id}/build-prompts", response_model=ProjectPromptBuildResponse)
async def build_listing_project_prompts(project_id: str, payload: ProjectPromptBuildRequest, db: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.submit"))) -> ProjectPromptBuildResponse:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image")
    version = await db.get(ListingVersion, project.listing_version_id)
    session = await get_listing_session(db, organization_id=project.organization_id, session_id=project.session_id)
    modules, prompts = build_listing_image_modules(
        analysis_snapshot=dict(version.analysis_snapshot or {}),
        listing_snapshot=dict(version.listing_snapshot or {}),
        skill_snapshot=dict(version.category_skill_snapshot or {}),
        selected_codes=payload.selected_items,
        attribute_overrides=payload.module_attribute_overrides,
        prompt_overrides=payload.prompt_overrides,
    )
    current_config = dict(project.prompt_config or {})
    current_prompts = current_config.get("prompts")
    current_prompts = current_prompts if isinstance(current_prompts, dict) else {}
    saved_selection = current_config.get("selected_items")
    saved_selection = saved_selection if isinstance(saved_selection, list) else list(prompts)
    project.prompt_config = {
        **current_config, "selected_items": saved_selection, "prompts": {**current_prompts, **prompts},
        "module_attribute_overrides": payload.module_attribute_overrides,
    }
    project.updated_by = principal.user.id
    existing_items = list((await db.scalars(select(ImagePromptItem).where(
        ImagePromptItem.organization_id == project.organization_id,
        ImagePromptItem.project_type == "listing_image",
        ImagePromptItem.project_id == project.id,
        ImagePromptItem.item_code.in_(list(prompts)),
    ))).all())
    indexed_items = {item.item_code: item for item in existing_items}
    now = datetime.now(UTC)
    for item_code, prompt in prompts.items():
        item = indexed_items.get(item_code)
        if item is None:
            db.add(ImagePromptItem(
                organization_id=project.organization_id, project_type="listing_image", project_id=project.id,
                session_id=session.id, category_id=session.category_id, skill_id=session.skill_id,
                item_code=item_code, image_type=item_code, original_english_prompt=prompt,
                chinese_editing_instruction="", optimized_english_prompt=prompt, status="draft",
                current_version_number=0, state_version=0, last_saved_at=now,
                created_by=principal.user.id, updated_by=principal.user.id,
            ))
            continue
        if item.original_english_prompt == prompt:
            continue
        item.original_english_prompt = prompt
        item.updated_by = principal.user.id
        item.optimizer_job_id = None
        item.optimizer_model = None
        item.optimized_at = None
        item.error_message = None
        if item.chinese_editing_instruction.strip():
            item.status = "needs_optimization"
        else:
            item.optimized_english_prompt = prompt
            item.status = "draft"
        item.state_version += 1
        item.last_saved_at = now
    await db.commit()
    return ProjectPromptBuildResponse(project_id=project.id, prompts=prompts, modules=modules)


@listing_image_router.post(
    "/{project_id}/free-variation-prompt", response_model=FreeVariationPromptBuildResponse,
)
async def build_free_variation_prompt(
    project_id: str,
    payload: FreeVariationPromptBuildRequest,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> FreeVariationPromptBuildResponse:
    project = await _get_output_project(
        db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image",
    )
    session = await get_listing_session(db, organization_id=project.organization_id, session_id=project.session_id)
    free = (project.prompt_config or {}).get("free_variation")
    free = free if isinstance(free, dict) else {}
    if not (free.get("asset_ids") or session.source_asset_ids):
        raise AppError("free_variation.assets_required", "请至少上传一张参考图片", 422)
    item, recommendation = await build_and_save_free_variation_prompt(
        db,
        project=project,
        session=session,
        chinese_prompt=payload.chinese_prompt.strip(),
        selected_category_id=payload.selected_category_id,
        template_fragments=payload.template_fragments,
        user_id=principal.user.id,
    )
    await db.commit()
    return FreeVariationPromptBuildResponse(
        project_id=project.id,
        session_id=session.id,
        category_id=session.category_id,
        prompt_item_id=item.id,
        item_code=item.item_code,
        image_type=item.image_type,
        base_prompt=item.original_english_prompt,
        chinese_prompt=item.chinese_editing_instruction,
        optimized_english_prompt=item.optimized_english_prompt,
        prompt_status=item.status,
        recommendation=FreeVariationRecommendationResponse(**recommendation),
    )


@listing_image_router.post(
    "/{project_id}/free-variations/generate", response_model=OutputProjectGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_free_variations(
    project_id: str,
    payload: FreeVariationGenerateRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> OutputProjectGenerateResponse:
    project = await _get_output_project(
        db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image",
    )
    session = await get_listing_session(db, organization_id=project.organization_id, session_id=project.session_id)
    _require_confirmed(session)
    version = await db.get(ListingVersion, project.listing_version_id)
    item = await db.scalar(select(ImagePromptItem).where(
        ImagePromptItem.organization_id == project.organization_id,
        ImagePromptItem.project_type == "listing_image",
        ImagePromptItem.project_id == project.id,
        ImagePromptItem.item_code == FREE_ITEM_CODE,
    ))
    if item is None:
        raise AppError("free_variation.prompt_missing", "请先填写中文提示词并执行AI优化", 409)
    prompts = await usable_project_prompts(
        db,
        organization_id=project.organization_id,
        project_type="listing_image",
        project_id=project.id,
        base_prompts={FREE_ITEM_CODE: item.original_english_prompt},
        selected_items=[FREE_ITEM_CODE],
    )
    current = dict(project.prompt_config or {})
    free = current.get("free_variation")
    free = free if isinstance(free, dict) else {}
    asset_ids = [str(value) for value in (free.get("asset_ids") or session.source_asset_ids or [])]
    if not asset_ids:
        raise AppError("free_variation.assets_required", "请至少上传一张参考图片", 422)
    await _verify_assets(db, project.organization_id, asset_ids)
    model_code = await resolve_bound_model_code(
        db,
        organization_id=project.organization_id,
        operation_code="listing.generate",
        capability="image_edit",
    )
    chinese_prompt = str(free.get("chinese_prompt") or item.chinese_editing_instruction)
    skill_context = free.get("skill_recommendation")
    skill_context = skill_context if isinstance(skill_context, dict) else {}
    batch_items = [
        BatchJobItemRequest(
            client_item_id=f"{FREE_ITEM_CODE}:{number}:{payload.idempotency_key[-12:]}",
            prompt=prompts[FREE_ITEM_CODE],
            reference_asset_ids=asset_ids,
            size=payload.size,
            aspect_ratio=payload.aspect_ratio,
            requested_width=payload.requested_width,
            requested_height=payload.requested_height,
            quality=payload.quality,
            output_format=payload.output_format,
            metadata={
                "workflow": "smart_image_variation",
                "variation_mode": "free",
                "output_project_id": project.id,
                "listing_session_id": session.id,
                "listing_version_id": version.id,
                "listing_version_number": version.version_number,
                "item_code": FREE_ITEM_CODE,
                "variation_type_code": "free",
                "variation_type_name": "自由裂变",
                "variation_plan_code": "free_prompt",
                "variation_plan_name": "自由提示词",
                "variation_version": number,
                "chinese_prompt": chinese_prompt,
                "selected_category_id": free.get("selected_category_id"),
                "recommended_skill_name": skill_context.get("skill_name"),
                "recommended_skill_version": skill_context.get("skill_version_number"),
            },
        )
        for number in range(1, payload.count + 1)
    ]
    batch, jobs, created = await submit_batch(
        db,
        settings,
        organization_id=project.organization_id,
        user_id=principal.user.id,
        payload=JobBatchSubmitRequest(
            name=f"自由图片裂变 · {payload.count}张",
            workspace_type="listing",
            operation_code="listing.generate",
            capability="image_edit",
            model_code=model_code,
            idempotency_key=payload.idempotency_key,
            project_id=session.project_id,
            concurrency=min(payload.concurrency, len(batch_items)),
            items=batch_items,
        ),
    )
    snapshot = await build_input_asset_snapshot(
        db,
        organization_id=project.organization_id,
        product_asset_ids=asset_ids,
        reference_asset_ids=[],
        template_asset_ids=[],
        primary_asset_id=str(free.get("primary_asset_id") or session.primary_asset_id or "") or None,
    )
    group = await create_group_for_batch(
        db,
        project=project,
        batch=batch,
        version=version,
        selected_image_types=[FREE_ITEM_CODE],
        product_asset_ids=asset_ids,
        reference_asset_ids=[],
        template_asset_ids=[],
        input_asset_snapshot=snapshot,
        user_id=principal.user.id,
    )
    group.group_name = f"自由图片裂变任务组 #{group.group_number}"
    for job in jobs:
        metadata = job.input_json.get("metadata")
        job.input_json = {
            **job.input_json,
            "metadata": {
                **(metadata if isinstance(metadata, dict) else {}),
                "listing_image_task_group_id": group.id,
            },
        }
    free = {**free, "final_english_prompt": prompts[FREE_ITEM_CODE], "last_task_group_id": group.id}
    project.prompt_config = {**current, "free_variation": free}
    project.last_batch_id = batch.id
    project.task_count = len(jobs)
    project.status = "generating"
    project.updated_by = principal.user.id
    project.last_saved_at = datetime.now(UTC)
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=len(jobs), batch_id=batch.id))
    return OutputProjectGenerateResponse(
        project_id=project.id,
        batch_id=batch.id,
        task_group_id=group.id,
        group_number=group.group_number,
        status=batch.status,
        job_ids=[job.id for job in jobs],
        items=[FREE_ITEM_CODE],
    )


@listing_image_router.get("/{project_id}/variation-options", response_model=ImageVariationOptionsResponse)
async def get_image_variation_options(
    project_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> ImageVariationOptionsResponse:
    project = await _get_output_project(
        db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image",
    )
    version = await db.get(ListingVersion, project.listing_version_id)
    session = await get_listing_session(db, organization_id=project.organization_id, session_id=project.session_id)
    config = variation_config(dict(version.category_skill_snapshot or {}))
    return ImageVariationOptionsResponse(
        project_id=project.id, session_id=project.session_id,
        category_name=str(version.category_skill_snapshot.get("category_name") or ""),
        skill_name=str(version.category_skill_snapshot.get("skill_name") or ""),
        skill_version_id=version.category_skill_snapshot.get("skill_version_id"),
        skill_version_number=int(version.category_skill_snapshot.get("skill_version") or 0) or None,
        product_asset_ids=list(session.source_asset_ids or []), primary_asset_id=session.primary_asset_id,
        max_total_images=max(1, min(30, int(config.get("max_total_images") or 20))),
        quick_defaults=list(config.get("quick_defaults") or []),
        types=enabled_variation_types(dict(version.category_skill_snapshot or {})),
    )


@listing_image_router.post(
    "/{project_id}/variation-prompts", response_model=ImageVariationPromptBuildResponse,
)
async def build_image_variation_prompts(
    project_id: str, payload: ImageVariationPromptBuildRequest,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> ImageVariationPromptBuildResponse:
    project = await _get_output_project(
        db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image",
    )
    version = await db.get(ListingVersion, project.listing_version_id)
    plans = await build_and_save_variation_prompts(
        db, project=project, version=version,
        plans=[item.model_dump() for item in payload.plans], user_id=principal.user.id,
    )
    await db.commit()
    return ImageVariationPromptBuildResponse(project_id=project.id, plans=plans)


@listing_image_router.post(
    "/{project_id}/variations/generate", response_model=OutputProjectGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_image_variations(
    project_id: str, payload: ImageVariationGenerateRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> OutputProjectGenerateResponse:
    project = await _get_output_project(
        db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image",
    )
    session = await get_listing_session(db, organization_id=project.organization_id, session_id=project.session_id)
    _require_confirmed(session)
    version = await db.get(ListingVersion, project.listing_version_id)
    config = variation_config(dict(version.category_skill_snapshot or {}))
    requested = {item.item_code: item.count for item in payload.plans}
    total = sum(requested.values())
    max_total = max(1, min(30, int(config.get("max_total_images") or 20)))
    if total > max_total:
        raise AppError(
            "listing_variation.too_many_images", f"当前Skill单次最多生成{max_total}张裂变图片，请减少方案或数量。", 422,
            {"requested": total, "maximum": max_total},
        )
    saved_plans = project.prompt_config.get("variation_plans")
    saved_plans = saved_plans if isinstance(saved_plans, dict) else {}
    missing = [code for code in requested if code not in saved_plans]
    if missing:
        raise AppError("listing_variation.plan_not_built", "部分裂变方案尚未构建提示词。", 409, {"items": missing})
    rows = list((await db.scalars(select(ImagePromptItem).where(
        ImagePromptItem.organization_id == project.organization_id,
        ImagePromptItem.project_type == "listing_image",
        ImagePromptItem.project_id == project.id,
        ImagePromptItem.item_code.in_(list(requested)),
    ))).all())
    indexed = {item.item_code: item for item in rows}
    if len(indexed) != len(requested):
        raise AppError("listing_variation.prompt_missing", "部分裂变提示词记录不存在，请重新构建。", 409)
    prompts = await usable_project_prompts(
        db, organization_id=project.organization_id, project_type="listing_image", project_id=project.id,
        base_prompts={code: indexed[code].original_english_prompt for code in requested}, selected_items=list(requested),
    )
    product_asset_ids = list(session.source_asset_ids or [])
    reference_asset_ids = [payload.source_asset_id] if payload.source_asset_id else []
    all_asset_ids = list(dict.fromkeys(product_asset_ids + reference_asset_ids))
    await _verify_assets(db, project.organization_id, all_asset_ids)
    source_group = None
    if payload.source_task_group_id:
        source_group = await _get_listing_task_group(
            db, organization_id=project.organization_id, group_id=payload.source_task_group_id,
        )
        if source_group.listing_image_project_id != project.id:
            raise AppError("listing_variation.source_group_mismatch", "来源任务组不属于当前图片项目。", 422)
    model_code = await resolve_bound_model_code(
        db, organization_id=project.organization_id, operation_code="listing.generate", capability="image_edit",
    )
    batch_items: list[BatchJobItemRequest] = []
    for item_code, count in requested.items():
        plan = dict(saved_plans[item_code])
        for version_number in range(1, count + 1):
            batch_items.append(BatchJobItemRequest(
                client_item_id=f"{item_code}:{version_number}:{payload.idempotency_key[-12:]}",
                prompt=prompts[item_code], reference_asset_ids=all_asset_ids,
                size=payload.size, aspect_ratio=payload.aspect_ratio,
                requested_width=payload.requested_width, requested_height=payload.requested_height,
                quality=payload.quality, output_format=payload.output_format,
                metadata={
                    "workflow": "smart_image_variation", "output_project_id": project.id,
                    "listing_session_id": session.id, "listing_version_id": version.id,
                    "listing_version_number": version.version_number, "item_code": item_code,
                    "variation_type_code": plan.get("type_code"), "variation_type_name": plan.get("type_name"),
                    "variation_plan_code": plan.get("plan_code"), "variation_plan_name": plan.get("plan_name"),
                    "variation_version": version_number, "source_asset_id": payload.source_asset_id,
                },
            ))
    batch, jobs, created = await submit_batch(
        db, settings, organization_id=project.organization_id, user_id=principal.user.id,
        payload=JobBatchSubmitRequest(
            name=f"智能图片裂变 · Listing V{version.version_number}", workspace_type="listing",
            operation_code="listing.generate", capability="image_edit", model_code=model_code,
            idempotency_key=payload.idempotency_key, project_id=session.project_id,
            concurrency=min(payload.concurrency, len(batch_items)), items=batch_items,
        ),
    )
    snapshot = await build_input_asset_snapshot(
        db, organization_id=project.organization_id, product_asset_ids=product_asset_ids,
        reference_asset_ids=reference_asset_ids, template_asset_ids=[], primary_asset_id=session.primary_asset_id,
    )
    group = await create_group_for_batch(
        db, project=project, batch=batch, version=version, selected_image_types=list(requested),
        product_asset_ids=product_asset_ids, reference_asset_ids=reference_asset_ids, template_asset_ids=[],
        input_asset_snapshot=snapshot, user_id=principal.user.id,
        source_task_group_id=source_group.id if source_group else None,
    )
    group.group_name = f"智能图片裂变任务组 #{group.group_number}"
    for job in jobs:
        metadata = job.input_json.get("metadata")
        job.input_json = {
            **job.input_json,
            "metadata": {**(metadata if isinstance(metadata, dict) else {}), "listing_image_task_group_id": group.id},
        }
    project.last_batch_id = batch.id
    project.task_count = len(jobs)
    project.status = "generating"
    project.updated_by = principal.user.id
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=len(jobs), batch_id=batch.id))
    return OutputProjectGenerateResponse(
        project_id=project.id, batch_id=batch.id, task_group_id=group.id, group_number=group.group_number,
        status=batch.status, job_ids=[job.id for job in jobs], items=list(requested),
    )


@a_plus_router.post("", response_model=OutputProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_a_plus_project(payload: OutputProjectCreateRequest, db: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.submit"))) -> OutputProjectResponse:
    project = await _create_output_project(db, payload=payload, principal=principal, kind="a_plus")
    if not project.modules:
        version = await db.get(ListingVersion, project.listing_version_id)
        project.selected_template = "standard"
        project.modules = _default_a_plus_modules(version, "standard", None)
    await db.commit()
    return await _output_project_response(db, project, "a_plus")


@a_plus_router.get("/{project_id}", response_model=OutputProjectResponse)
async def get_a_plus_project(project_id: str, db: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.read"))) -> OutputProjectResponse:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="a_plus")
    response = await _output_project_response(db, project, "a_plus")
    await db.commit()
    return response


@a_plus_router.patch("/{project_id}", response_model=OutputProjectResponse)
async def update_a_plus_project(project_id: str, payload: OutputProjectUpdateRequest, db: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.submit"))) -> OutputProjectResponse:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="a_plus")
    session = await get_listing_session(db, organization_id=project.organization_id, session_id=project.session_id)
    _require_confirmed(session)
    if payload.expected_state_version is not None and payload.expected_state_version != project.state_version:
        raise AppError("aplus.state_version_conflict", "A+ 工作台草稿已被更新，请刷新后合并修改", 409,
                       {"expected": payload.expected_state_version, "actual": project.state_version})
    if payload.adopt_latest_listing: project.listing_version_id = session.current_listing_version_id
    if payload.selected_template is not None: project.selected_template = payload.selected_template
    if payload.prompt_config is not None: project.prompt_config = payload.prompt_config
    if payload.modules is not None: project.modules = payload.modules
    project.updated_by = principal.user.id
    project.state_version += 1
    project.last_saved_at = datetime.now(UTC)
    await db.commit()
    return await _output_project_response(db, project, "a_plus")


@a_plus_router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_a_plus_project(project_id: str, db: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.submit"))) -> None:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="a_plus")
    await db.delete(project)
    await db.commit()


@a_plus_router.post("/{project_id}/build-modules", response_model=APlusBuildModulesResponse)
async def build_a_plus_modules(project_id: str, payload: APlusBuildModulesRequest, db: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.submit"))) -> APlusBuildModulesResponse:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="a_plus")
    version = await db.get(ListingVersion, project.listing_version_id)
    project.selected_template = payload.template_code
    project.modules = _default_a_plus_modules(version, payload.template_code, payload.module_codes)
    project.updated_by = principal.user.id
    await db.commit()
    return APlusBuildModulesResponse(project_id=project.id, modules=project.modules)


@a_plus_router.post("/{project_id}/build-prompts", response_model=ProjectPromptBuildResponse)
async def build_a_plus_project_prompts(project_id: str, payload: ProjectPromptBuildRequest, db: AsyncSession = Depends(get_db_session), principal: Principal = Depends(require_permissions("jobs.submit"))) -> ProjectPromptBuildResponse:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="a_plus")
    version = await db.get(ListingVersion, project.listing_version_id)
    prompts = _a_plus_prompts(project, version, payload.selected_items, payload.prompt_overrides)
    project.prompt_config = {**dict(project.prompt_config or {}), "selected_items": list(prompts), "prompts": prompts}
    project.updated_by = principal.user.id
    await db.commit()
    return ProjectPromptBuildResponse(project_id=project.id, prompts=prompts)


async def _generate_output_project(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject | APlusProject,
    payload: OutputProjectGenerateRequest, principal: Principal, kind: str,
) -> OutputProjectGenerateResponse:
    session = await get_listing_session(db, organization_id=project.organization_id, session_id=project.session_id)
    _require_confirmed(session)
    version = await db.get(ListingVersion, project.listing_version_id)
    module_attribute_overrides = project.prompt_config.get("module_attribute_overrides")
    if not isinstance(module_attribute_overrides, dict):
        module_attribute_overrides = {}
    base_prompts = _snapshot_listing_prompts(
        version, payload.selected_items, {}, module_attribute_overrides,
    ) if kind == "listing_image" else _a_plus_prompts(project, version, payload.selected_items, {})
    prompts = await usable_project_prompts(
        db, organization_id=project.organization_id, project_type=kind, project_id=project.id,
        base_prompts=base_prompts, selected_items=list(base_prompts),
    )
    operation_code = "listing.generate" if kind == "listing_image" else "aplus.generate"
    workspace_type = "listing" if kind == "listing_image" else "aplus"
    model_code = payload.model_code or await resolve_bound_model_code(db, organization_id=project.organization_id, operation_code=operation_code, capability="image_edit")
    product_asset_ids = list(session.source_asset_ids or [])
    reference_asset_ids = [str(item) for item in (project.prompt_config.get("reference_asset_ids") or [])]
    template_asset_ids = [str(item) for item in (project.prompt_config.get("template_asset_ids") or [])]
    all_group_asset_ids = list(dict.fromkeys(product_asset_ids + reference_asset_ids + template_asset_ids))
    await _verify_assets(db, project.organization_id, all_group_asset_ids)
    per_item_references = project.prompt_config.get("item_reference_asset_ids")
    if not isinstance(per_item_references, dict):
        per_item_references = {}
    batch, jobs, created = await submit_batch(db, settings, organization_id=project.organization_id, user_id=principal.user.id, payload=JobBatchSubmitRequest(
        name=("Listing图片" if kind == "listing_image" else "A+图片") + f" · Listing V{version.version_number}",
        workspace_type=workspace_type, operation_code=operation_code, capability="image_edit", model_code=model_code,
        idempotency_key=payload.idempotency_key, project_id=session.project_id, concurrency=min(payload.concurrency, len(prompts)),
        items=[BatchJobItemRequest(
            client_item_id=f"{project.id}:{item}:v{version.version_number}", prompt=prompt,
            reference_asset_ids=list(dict.fromkeys(
                [str(asset_id) for asset_id in (per_item_references.get(item) or all_group_asset_ids)]
            )), size=payload.size, aspect_ratio=payload.aspect_ratio,
            requested_width=payload.requested_width, requested_height=payload.requested_height,
            quality=payload.quality, output_format=payload.output_format,
            metadata={"workflow": kind, "output_project_id": project.id, "listing_session_id": session.id,
                      "listing_version_id": version.id, "listing_version_number": version.version_number, "item_code": item},
        ) for item, prompt in prompts.items()],
    ))
    task_group = None
    if kind == "listing_image":
        snapshot = await build_input_asset_snapshot(
            db, organization_id=project.organization_id, product_asset_ids=product_asset_ids,
            reference_asset_ids=reference_asset_ids, template_asset_ids=template_asset_ids,
            primary_asset_id=session.primary_asset_id,
        )
        task_group = await create_group_for_batch(
            db, project=project, batch=batch, version=version, selected_image_types=list(prompts),
            product_asset_ids=product_asset_ids, reference_asset_ids=reference_asset_ids,
            template_asset_ids=template_asset_ids, input_asset_snapshot=snapshot,
            user_id=principal.user.id,
        )
        for job in jobs:
            metadata = job.input_json.get("metadata")
            job.input_json = {
                **job.input_json,
                "metadata": {**(metadata if isinstance(metadata, dict) else {}), "listing_image_task_group_id": task_group.id},
            }
    project.last_batch_id = batch.id
    project.task_count = len(jobs)
    project.status = "generating"
    project.prompt_config = {**dict(project.prompt_config or {}), "selected_items": list(prompts), "prompts": prompts}
    project.updated_by = principal.user.id
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=len(jobs), batch_id=batch.id))
    return OutputProjectGenerateResponse(
        project_id=project.id, batch_id=batch.id,
        task_group_id=task_group.id if task_group else None,
        group_number=task_group.group_number if task_group else None,
        status=batch.status, job_ids=[job.id for job in jobs], items=list(prompts),
    )


@listing_image_router.post("/{project_id}/generate", response_model=OutputProjectGenerateResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_listing_project(project_id: str, payload: OutputProjectGenerateRequest, db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings), principal: Principal = Depends(require_permissions("jobs.submit"))) -> OutputProjectGenerateResponse:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image")
    return await _generate_output_project(db, settings, project=project, payload=payload, principal=principal, kind="listing_image")


@a_plus_router.post("/{project_id}/generate", response_model=OutputProjectGenerateResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_a_plus_project(project_id: str, payload: OutputProjectGenerateRequest, db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings), principal: Principal = Depends(require_permissions("jobs.submit"))) -> OutputProjectGenerateResponse:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="a_plus")
    return await _generate_output_project(db, settings, project=project, payload=payload, principal=principal, kind="a_plus")


@listing_image_router.get("/{project_id}/task-groups", response_model=ListingImageTaskGroupPage)
async def list_listing_image_task_groups(
    project_id: str, group_status: str | None = Query(default=None, alias="status", max_length=30),
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> ListingImageTaskGroupPage:
    project = await _get_output_project(db, organization_id=_organization_id(principal), project_id=project_id, kind="listing_image")
    await ensure_legacy_groups(db, project=project)
    groups = list((await db.scalars(select(ListingImageTaskGroup).where(
        ListingImageTaskGroup.organization_id == project.organization_id,
        ListingImageTaskGroup.listing_image_project_id == project.id,
    ).order_by(ListingImageTaskGroup.group_number.desc()))).all())
    responses = [await task_group_response(db, storage, settings, group) for group in groups]
    if group_status:
        responses = [group for group in responses if group.status == group_status]
    await db.commit()
    return ListingImageTaskGroupPage(items=responses, total=len(responses))


async def _get_listing_task_group(db: AsyncSession, *, organization_id: str, group_id: str) -> ListingImageTaskGroup:
    group = await db.scalar(select(ListingImageTaskGroup).where(
        ListingImageTaskGroup.id == group_id, ListingImageTaskGroup.organization_id == organization_id,
    ))
    if group is None:
        raise AppError("listing_image.task_group_not_found", "任务组不存在或无权访问", 404)
    return group


@listing_image_task_group_router.get("/{group_id}", response_model=ListingImageTaskGroupResponse)
async def get_listing_image_task_group(
    group_id: str, db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> ListingImageTaskGroupResponse:
    group = await _get_listing_task_group(db, organization_id=_organization_id(principal), group_id=group_id)
    response = await task_group_response(db, storage, settings, group)
    await db.commit()
    return response


@listing_image_task_group_router.post("/{group_id}/cancel", response_model=ListingImageTaskGroupResponse)
async def cancel_listing_image_task_group(
    group_id: str, request: Request, db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.cancel")),
) -> ListingImageTaskGroupResponse:
    organization_id = _organization_id(principal)
    group = await _get_listing_task_group(db, organization_id=organization_id, group_id=group_id)
    jobs = list((await db.scalars(select(Job).where(Job.batch_id == group.job_batch_id))).all())
    for job in jobs:
        await cancel_job(db, organization_id=organization_id, job_id=job.id, user_id=principal.user.id)
    if group.job_batch_id:
        await refresh_batch_status(db, group.job_batch_id)
    group.status = "cancel_requested" if any(job.status != "cancelled" for job in jobs) else "cancelled"
    group.updated_by = principal.user.id
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=organization_id,
                  action="listing_image.task_group_cancel", resource_type="listing_image_task_group", resource_id=group.id)
    response = await task_group_response(db, storage, settings, group)
    await db.commit()
    return response


@listing_image_task_group_router.post("/{group_id}/retry-failed", response_model=ListingImageTaskGroupResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_failed_listing_image_task_group(
    group_id: str, payload: ListingImageTaskGroupRetryRequest, request: Request,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> ListingImageTaskGroupResponse:
    organization_id = _organization_id(principal)
    source_group = await _get_listing_task_group(db, organization_id=organization_id, group_id=group_id)
    project = await _get_output_project(db, organization_id=organization_id, project_id=source_group.listing_image_project_id, kind="listing_image")
    version = await db.get(ListingVersion, source_group.listing_version_id)
    source_batch = await db.get(JobBatch, source_group.job_batch_id) if source_group.job_batch_id else None
    source_jobs = list((await db.scalars(select(Job).where(
        Job.batch_id == source_group.job_batch_id, Job.status.in_(["failed", "cancelled"]),
    ).order_by(Job.created_at))).all())
    if not source_jobs or source_batch is None or version is None:
        raise AppError("listing_image.no_retryable_tasks", "当前任务组没有失败或已中止项目", 409)
    items = []
    for source_job in source_jobs:
        value = source_job.input_json
        metadata = value.get("metadata")
        items.append(BatchJobItemRequest(
            client_item_id=f"{source_job.client_item_id}:retry", prompt=str(value.get("prompt") or ""),
            reference_asset_ids=[str(item) for item in (value.get("reference_asset_ids") or [])],
            size=str(value.get("size") or "2048x2048"), aspect_ratio=str(value.get("aspect_ratio") or "1:1"),
            requested_width=int(value.get("requested_width") or 2048), requested_height=int(value.get("requested_height") or 2048),
            quality=str(value.get("quality") or "high"), output_format=str(value.get("output_format") or "png"),
            output_compression=value.get("output_compression"),
            metadata={**(metadata if isinstance(metadata, dict) else {}), "source_job_id": source_job.id},
        ))
    batch, jobs, created = await submit_batch(db, settings, organization_id=organization_id, user_id=principal.user.id, payload=JobBatchSubmitRequest(
        name=f"Listing图片 · 任务组 #{source_group.group_number} 失败项重试",
        workspace_type="listing", operation_code="listing.generate", capability="image_edit",
        model_code=source_batch.model_code or source_jobs[0].model_code,
        idempotency_key=payload.idempotency_key, project_id=source_jobs[0].project_id,
        concurrency=min(source_batch.concurrency, len(items)), items=items,
    ))
    group = await create_group_for_batch(
        db, project=project, batch=batch, version=version,
        selected_image_types=[str((job.input_json.get("metadata") or {}).get("item_code") or "") for job in source_jobs],
        product_asset_ids=list(source_group.product_image_asset_ids or []),
        reference_asset_ids=list(source_group.reference_asset_ids or []), template_asset_ids=list(source_group.template_asset_ids or []),
        input_asset_snapshot=dict(source_group.input_asset_snapshot or {}), user_id=principal.user.id,
        source_task_group_id=source_group.id,
    )
    for job in jobs:
        metadata = job.input_json.get("metadata")
        job.input_json = {**job.input_json, "metadata": {**(metadata if isinstance(metadata, dict) else {}), "listing_image_task_group_id": group.id}}
    add_audit_log(db, request=request, actor_user_id=principal.user.id, organization_id=organization_id,
                  action="listing_image.task_group_retry_failed", resource_type="listing_image_task_group", resource_id=group.id,
                  metadata={"source_task_group_id": source_group.id, "retry_count": len(jobs)})
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=len(jobs), batch_id=batch.id))
    return await task_group_response(db, storage, settings, group)
