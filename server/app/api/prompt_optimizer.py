from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.listing_workflow import (
    APlusProject, ImagePromptItem, ImagePromptVersion, ListingGenerationSession,
    ListingImageProject, ListingVersion, ProductCategory,
)
from app.schemas.listing_workflow import (
    ImagePromptItemResponse, ImagePromptItemUpsertRequest, ImagePromptOptimizeRequest,
    ImagePromptVersionResponse, OptimizeAllImagePromptsRequest, OptimizeAllImagePromptsResponse,
)
from app.schemas.tasks import JobSubmitRequest
from app.security.principal import Principal, require_permissions
from app.services.category_listing_service import resolve_bound_model_code
from app.services.prompt_optimizer_service import (
    build_image_prompt_optimizer_input, reconcile_prompt_item,
)
from app.services.task_service import dispatch_jobs, due_jobs, submit_job


router = APIRouter(prefix="/prompt-optimizer", tags=["prompt-optimizer"])
UTC = timezone.utc


def _organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队", 409)
    return principal.organization.id


async def _project_context(
    db: AsyncSession, *, organization_id: str, project_type: str, project_id: str,
) -> tuple[ListingImageProject | APlusProject, ListingGenerationSession, ListingVersion, ProductCategory]:
    model = ListingImageProject if project_type == "listing_image" else APlusProject
    project = await db.scalar(select(model).where(model.id == project_id, model.organization_id == organization_id))
    if project is None:
        raise AppError("prompt_optimizer.project_not_found", "图片项目不存在或无权访问", 404)
    session = await db.get(ListingGenerationSession, project.session_id)
    version = await db.get(ListingVersion, project.listing_version_id)
    category = await db.get(ProductCategory, session.category_id) if session else None
    if session is None or version is None or category is None:
        raise AppError("prompt_optimizer.project_context_missing", "图片项目缺少Listing上下文", 409)
    return project, session, version, category


def _response(item: ImagePromptItem) -> ImagePromptItemResponse:
    return ImagePromptItemResponse(
        id=item.id, project_type=item.project_type, project_id=item.project_id, session_id=item.session_id,
        prompt_item_id=item.item_code, image_type=item.image_type,
        original_english_prompt=item.original_english_prompt,
        chinese_editing_instruction=item.chinese_editing_instruction,
        optimized_english_prompt=item.optimized_english_prompt, status=item.status,
        current_version_number=item.current_version_number, optimizer_job_id=item.optimizer_job_id,
        optimizer_model=item.optimizer_model, optimized_at=item.optimized_at, error_message=item.error_message,
        state_version=item.state_version, last_saved_at=item.last_saved_at,
    )


async def _upsert(
    db: AsyncSession, *, organization_id: str, user_id: str, payload: ImagePromptItemUpsertRequest,
) -> ImagePromptItem:
    _, session, _, _ = await _project_context(
        db, organization_id=organization_id, project_type=payload.project_type, project_id=payload.project_id,
    )
    if session.id != payload.session_id or session.category_id != payload.category_id:
        raise AppError("prompt_optimizer.context_mismatch", "提示词与当前项目上下文不一致", 422)
    item = await db.scalar(select(ImagePromptItem).where(
        ImagePromptItem.organization_id == organization_id,
        ImagePromptItem.project_type == payload.project_type,
        ImagePromptItem.project_id == payload.project_id,
        ImagePromptItem.item_code == payload.prompt_item_id,
    ))
    if item is None:
        item = ImagePromptItem(
            organization_id=organization_id, project_type=payload.project_type, project_id=payload.project_id,
            session_id=payload.session_id, category_id=payload.category_id, skill_id=session.skill_id,
            item_code=payload.prompt_item_id, image_type=payload.image_type,
            original_english_prompt=payload.original_english_prompt,
            chinese_editing_instruction=payload.chinese_editing_instruction,
            optimized_english_prompt=payload.optimized_english_prompt or payload.original_english_prompt,
            status="manually_edited" if payload.manual_edit else ("needs_optimization" if payload.chinese_editing_instruction.strip() else "draft"),
            current_version_number=0, created_by=user_id, updated_by=user_id,
            state_version=0, last_saved_at=datetime.now(UTC),
        )
        db.add(item)
        await db.flush()
        return item
    if payload.expected_state_version is not None and payload.expected_state_version != item.state_version:
        raise AppError(
            "prompt_optimizer.state_version_conflict", "该提示词已被更新，请刷新后合并修改", 409,
            {"expected": payload.expected_state_version, "actual": item.state_version},
        )
    chinese_changed = item.chinese_editing_instruction != payload.chinese_editing_instruction
    item.original_english_prompt = payload.original_english_prompt
    item.image_type = payload.image_type
    item.chinese_editing_instruction = payload.chinese_editing_instruction
    item.updated_by = user_id
    item.error_message = None
    if payload.manual_edit and payload.optimized_english_prompt:
        item.optimized_english_prompt = payload.optimized_english_prompt
        item.status = "manually_edited"
    elif chinese_changed:
        item.status = "needs_optimization" if payload.chinese_editing_instruction.strip() else "draft"
        if not payload.chinese_editing_instruction.strip():
            item.optimized_english_prompt = item.original_english_prompt
    elif item.status == "draft":
        item.optimized_english_prompt = item.original_english_prompt
    item.state_version += 1
    item.last_saved_at = datetime.now(UTC)
    return item


async def _start_optimization(
    db: AsyncSession, settings: Settings, *, organization_id: str, user_id: str,
    payload: ImagePromptOptimizeRequest,
) -> tuple[ImagePromptItem, bool]:
    project, session, version, category = await _project_context(
        db, organization_id=organization_id, project_type=payload.project_type, project_id=payload.project_id,
    )
    item = await _upsert(db, organization_id=organization_id, user_id=user_id, payload=payload)
    free_context = (project.prompt_config or {}).get("free_variation") if isinstance(project, ListingImageProject) else None
    free_context = free_context if isinstance(free_context, dict) else {}
    recommendation = free_context.get("skill_recommendation")
    recommendation = recommendation if isinstance(recommendation, dict) else {}
    is_free_variation = payload.image_type == "variation.free"
    free_asset_ids = [str(value) for value in (free_context.get("asset_ids") or session.source_asset_ids or [])]
    system_prompt, user_prompt = build_image_prompt_optimizer_input(
        category_name=(str(recommendation.get("category_name") or "自由图片裂变") if is_free_variation else category.category_name),
        image_type=payload.image_type,
        product_analysis=dict(version.analysis_snapshot or {}),
        category_skill_rules=(
            {"mode": "optional_recommendation", **recommendation}
            if is_free_variation else version.category_skill_snapshot
        ),
        original_english_prompt=item.original_english_prompt,
        chinese_editing_instruction=item.chinese_editing_instruction,
    )
    workspace = "listing" if payload.project_type == "listing_image" else "aplus"
    operation = "listing.plan" if workspace == "listing" else "aplus.plan"
    model_code = await resolve_bound_model_code(
        db, organization_id=organization_id, operation_code=operation, capability="text_generation",
    )
    job, created = await submit_job(db, settings, organization_id=organization_id, user_id=user_id, payload=JobSubmitRequest(
        operation_code=operation, workspace_type=workspace, queue_name="planning_queue",
        capability="text_generation", model_code=model_code, idempotency_key=payload.idempotency_key,
        project_id=session.project_id,
        input={"system_prompt": system_prompt, "user_prompt": user_prompt, "temperature": 0.2,
               "reference_asset_ids": free_asset_ids if is_free_variation else [],
               "metadata": {"workflow": "image_prompt_optimizer", "prompt_item_id": item.id,
                            "variation_mode": "free" if is_free_variation else None}},
        billing_factors={"quality": "standard", "resolution": "text"}, client_item_id=item.item_code,
    ))
    item.optimizer_job_id = job.id
    item.optimizer_model = model_code
    item.status = "optimizing" if job.status != "succeeded" else "optimizing"
    item.error_message = None
    item.updated_by = user_id
    return item, created


@router.put("/project-items", response_model=ImagePromptItemResponse)
async def save_prompt_item(
    payload: ImagePromptItemUpsertRequest, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> ImagePromptItemResponse:
    item = await _upsert(db, organization_id=_organization_id(principal), user_id=principal.user.id, payload=payload)
    await db.commit()
    return _response(item)


@router.post("/optimize-image-prompt", response_model=ImagePromptItemResponse, status_code=status.HTTP_202_ACCEPTED)
async def optimize_image_prompt(
    payload: ImagePromptOptimizeRequest, db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), principal: Principal = Depends(require_permissions("jobs.submit")),
) -> ImagePromptItemResponse:
    item, created = await _start_optimization(
        db, settings, organization_id=_organization_id(principal), user_id=principal.user.id, payload=payload,
    )
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return _response(item)


@router.get("/items/{item_id}", response_model=ImagePromptItemResponse)
async def get_prompt_item(
    item_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> ImagePromptItemResponse:
    item = await db.scalar(select(ImagePromptItem).where(
        ImagePromptItem.id == item_id, ImagePromptItem.organization_id == _organization_id(principal),
    ))
    if item is None:
        raise AppError("prompt_optimizer.item_not_found", "提示词记录不存在或无权访问", 404)
    await reconcile_prompt_item(db, item)
    await db.commit()
    return _response(item)


@router.get("/projects/{project_type}/{project_id}/items", response_model=list[ImagePromptItemResponse])
async def list_prompt_items(
    project_type: str, project_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[ImagePromptItemResponse]:
    organization_id = _organization_id(principal)
    if project_type not in {"listing_image", "a_plus"}:
        raise AppError("prompt_optimizer.project_type_invalid", "提示词项目类型无效", 422)
    await _project_context(db, organization_id=organization_id, project_type=project_type, project_id=project_id)
    rows = list((await db.scalars(select(ImagePromptItem).where(
        ImagePromptItem.organization_id == organization_id,
        ImagePromptItem.project_type == project_type,
        ImagePromptItem.project_id == project_id,
    ).order_by(ImagePromptItem.created_at))).all())
    for item in rows:
        await reconcile_prompt_item(db, item)
    await db.commit()
    return [_response(item) for item in rows]


@router.get("/items/{item_id}/versions", response_model=list[ImagePromptVersionResponse])
async def list_prompt_versions(
    item_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[ImagePromptVersionResponse]:
    item = await db.scalar(select(ImagePromptItem).where(
        ImagePromptItem.id == item_id, ImagePromptItem.organization_id == _organization_id(principal),
    ))
    if item is None:
        raise AppError("prompt_optimizer.item_not_found", "提示词记录不存在或无权访问", 404)
    rows = list((await db.scalars(select(ImagePromptVersion).where(
        ImagePromptVersion.prompt_item_id == item.id,
    ).order_by(ImagePromptVersion.version_number.desc()))).all())
    return [ImagePromptVersionResponse(
        id=row.id, version_number=row.version_number,
        original_english_prompt=row.original_english_prompt,
        chinese_editing_instruction=row.chinese_editing_instruction,
        optimized_english_prompt=row.optimized_english_prompt,
        optimizer_model=row.optimizer_model, optimized_at=row.optimized_at,
    ) for row in rows]


@router.post("/items/{item_id}/restore-previous", response_model=ImagePromptItemResponse)
async def restore_previous_prompt(
    item_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> ImagePromptItemResponse:
    item = await db.scalar(select(ImagePromptItem).where(
        ImagePromptItem.id == item_id, ImagePromptItem.organization_id == _organization_id(principal),
    ))
    if item is None:
        raise AppError("prompt_optimizer.item_not_found", "提示词记录不存在或无权访问", 404)
    target = await db.scalar(select(ImagePromptVersion).where(
        ImagePromptVersion.prompt_item_id == item.id,
        ImagePromptVersion.version_number < item.current_version_number,
    ).order_by(ImagePromptVersion.version_number.desc()).limit(1))
    if target:
        item.optimized_english_prompt = target.optimized_english_prompt
        item.chinese_editing_instruction = target.chinese_editing_instruction
        item.current_version_number = target.version_number
        item.status = "optimized"
    else:
        item.optimized_english_prompt = item.original_english_prompt
        item.chinese_editing_instruction = ""
        item.current_version_number = 0
        item.status = "draft"
    item.updated_by = principal.user.id
    item.error_message = None
    item.state_version += 1
    item.last_saved_at = datetime.now(UTC)
    await db.commit()
    return _response(item)


@router.post("/items/{item_id}/restore-skill-default", response_model=ImagePromptItemResponse)
async def restore_skill_default_prompt(
    item_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> ImagePromptItemResponse:
    item = await db.scalar(select(ImagePromptItem).where(
        ImagePromptItem.id == item_id, ImagePromptItem.organization_id == _organization_id(principal),
    ))
    if item is None:
        raise AppError("prompt_optimizer.item_not_found", "提示词记录不存在或无权访问", 404)
    item.chinese_editing_instruction = ""
    item.optimized_english_prompt = item.original_english_prompt
    item.status = "draft"
    item.error_message = None
    item.updated_by = principal.user.id
    item.state_version += 1
    item.last_saved_at = datetime.now(UTC)
    await db.commit()
    return _response(item)


@router.post("/optimize-all", response_model=OptimizeAllImagePromptsResponse, status_code=status.HTTP_202_ACCEPTED)
async def optimize_all_prompts(
    payload: OptimizeAllImagePromptsRequest, db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), principal: Principal = Depends(require_permissions("jobs.submit")),
) -> OptimizeAllImagePromptsResponse:
    organization_id = _organization_id(principal)
    _, session, _, _ = await _project_context(db, organization_id=organization_id, project_type=payload.project_type, project_id=payload.project_id)
    rows = list((await db.scalars(select(ImagePromptItem).where(
        ImagePromptItem.organization_id == organization_id,
        ImagePromptItem.project_type == payload.project_type,
        ImagePromptItem.project_id == payload.project_id,
        ImagePromptItem.status == "needs_optimization",
    ))).all())
    created_count = 0
    for index, row in enumerate(rows):
        request = ImagePromptOptimizeRequest(
            project_type=payload.project_type, project_id=payload.project_id, session_id=session.id,
            prompt_item_id=row.item_code, category_id=session.category_id, image_type=row.image_type,
            original_english_prompt=row.original_english_prompt,
            chinese_editing_instruction=row.chinese_editing_instruction,
            idempotency_key=f"{payload.idempotency_key}:{index + 1}",
        )
        _, created = await _start_optimization(
            db, settings, organization_id=organization_id, user_id=principal.user.id, payload=request,
        )
        created_count += int(created)
    await db.commit()
    if created_count:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=created_count))
    return OptimizeAllImagePromptsResponse(project_id=payload.project_id, items=[_response(item) for item in rows])
