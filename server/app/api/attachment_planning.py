from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.attachment_planning import (
    AttachmentModuleReference,
    AttachmentProductComposition,
    AttachmentProductCompositionAsset,
    AttachmentProductCompositionItem,
    AttachmentProductReferenceGroup,
    AttachmentProductReferenceItem,
    AttachmentWorkbenchModulePlan,
    AttachmentWorkbenchPlan,
)
from app.models.content import Asset
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject, ListingVersion
from app.schemas.attachment_planning import (
    AttachmentModulePlanRequest,
    AttachmentModulePlanResponse,
    AttachmentModulePlanUpdate,
    AttachmentPlanningResponse,
    AttachmentPlanVersionResponse,
    AttachmentSkillSourceResponse,
    AttachmentSuitePlanRequest,
    AttachmentVisualDirectionUpdate,
    AttachmentModuleReferenceResponse,
    AttachmentModuleReferenceStateResponse,
    AttachmentProductReferenceItemResponse,
    AttachmentProductReferenceRequest,
    AttachmentReferenceAnalyzeRequest,
    AttachmentReferenceCreateRequest,
    AttachmentReferenceSlotDefinitionResponse,
    AttachmentReferenceStateResponse,
    AttachmentReferenceUnderstandingResponse,
    AttachmentGenerationSelectionRequest,
    AttachmentGenerationRequest,
    AttachmentGenerationModulePreviewResponse,
    AttachmentGenerationPreviewResponse,
    AttachmentGenerationResponse,
    AttachmentCreativeDirectionResponse,
    AttachmentCreativePlanningRequest,
    AttachmentCreativePlanningResponse,
    AttachmentAdoptDirectionRequest,
    AttachmentModuleKeysRequest,
    AttachmentProductCompositionAssetResponse,
    AttachmentProductCompositionItemResponse,
    AttachmentProductCompositionResponse,
    AttachmentProductModeUpdate,
    AttachmentSecondaryProductRequest,
    AttachmentOutputReviewRequest,
    AttachmentOutputStateResponse,
    AttachmentResultStateResponse,
    AttachmentRetryJobRequest,
)
from app.schemas.listing_workflow import ListingImageTaskGroupResponse
from app.security.principal import Principal, require_permissions
from app.services.attachment_planning_service import (
    STANDARD_MODULE_CODES,
    add_module_version,
    add_suite_version,
    attachment_module_rule,
    get_or_create_attachment_plan,
    list_attachment_versions,
    reconcile_attachment_planning,
    start_module_planning,
    start_suite_planning,
)
from app.services.task_service import dispatch_jobs, due_jobs
from app.services.asset_service import signed_asset_response
from app.services.attachment_reference_service import (
    add_module_reference,
    ensure_product_reference_group,
    latest_reference_understanding,
    list_module_references,
    reconcile_reference_understandings,
    remove_module_reference,
    replace_product_reference,
    slot_definitions,
    start_reference_analysis,
)
from app.services.storage_service import StorageService, get_storage_service
from app.services.attachment_generation_service import (
    AttachmentGenerationPreview,
    build_attachment_generation_preview,
    create_attachment_generation,
)
from app.services.attachment_result_service import (
    adopt_attachment_creative_direction,
    clear_attachment_final,
    discard_attachment_results,
    ensure_attachment_result_states,
    reset_attachment_module,
    result_state_response,
    retry_attachment_job,
    review_attachment_output,
    set_attachment_final,
)
from app.services.attachment_creative_service import (
    creative_planning_response,
    start_creative_planning,
)
from app.services.attachment_product_composition_service import (
    add_secondary_product,
    current_composition_version,
    ensure_product_composition,
    get_product_composition,
    remove_secondary_product,
    replace_secondary_product,
    set_product_mode,
)
from app.services.audit_service import add_audit_log
from app.services.listing_image_task_group_service import task_group_response


router = APIRouter(prefix="/attachment-workbench", tags=["attachment-workbench"])
UTC = timezone.utc


def _organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队", 409)
    return principal.organization.id


async def _context(
    db: AsyncSession, *, organization_id: str, project_id: str, user_id: str,
) -> tuple[ListingImageProject, ListingGenerationSession, ListingVersion, AttachmentWorkbenchPlan, list[AttachmentWorkbenchModulePlan]]:
    project = await db.scalar(select(ListingImageProject).where(
        ListingImageProject.id == project_id,
        ListingImageProject.organization_id == organization_id,
    ))
    if project is None:
        raise AppError("attachment_planning.project_not_found", "附图项目不存在或无权访问", 404)
    session = await db.scalar(select(ListingGenerationSession).where(
        ListingGenerationSession.id == project.session_id,
        ListingGenerationSession.organization_id == organization_id,
    ))
    version = await db.scalar(select(ListingVersion).where(
        ListingVersion.id == project.listing_version_id,
        ListingVersion.organization_id == organization_id,
    ))
    if session is None or version is None or not session.confirmed_at:
        raise AppError("attachment_planning.context_missing", "附图项目缺少已确认的Listing上下文", 409)
    plan, modules = await get_or_create_attachment_plan(
        db, project=project, session=session, version=version, user_id=user_id,
    )
    _, product_references = await ensure_product_reference_group(
        db, plan=plan, session=session, user_id=user_id,
    )
    for module in modules:
        await ensure_product_composition(
            db, module=module, session=session,
            product_references=product_references, user_id=user_id,
        )
    await ensure_attachment_result_states(
        db, project=project, module_keys=list(STANDARD_MODULE_CODES), user_id=user_id,
    )
    return project, session, version, plan, modules


def _can_view_rules(principal: Principal) -> bool:
    return principal.is_platform_admin or "organization_admin" in principal.role_codes


def _response(
    *, project: ListingImageProject, version: ListingVersion, plan: AttachmentWorkbenchPlan,
    modules: list[AttachmentWorkbenchModulePlan], principal: Principal,
) -> AttachmentPlanningResponse:
    snapshot = dict(version.category_skill_snapshot or {})
    can_view = _can_view_rules(principal)
    module_names = {
        "pure_white": "纯白底图", "custom_process": "定制流程图", "stadium_scene": "观赛场景图",
        "gift_scene": "礼品场景图", "detail_display": "细节展示图", "casual_scene": "休闲场景图",
    }
    return AttachmentPlanningResponse(
        id=plan.id, project_id=project.id, session_id=plan.session_id,
        visual_direction_cn=plan.visual_direction_cn,
        visual_direction_source=plan.visual_direction_source,
        visual_direction_version=plan.visual_direction_version,
        planning_status=plan.planning_status, planning_job_id=plan.planning_job_id,
        error_message=plan.error_message, state_version=plan.state_version,
        last_saved_at=plan.last_saved_at,
        modules=[AttachmentModulePlanResponse(
            id=item.id, module_key=item.module_key, module_name=module_names.get(item.module_key, item.module_key),
            plan_summary_cn=item.plan_summary_cn, prompt_cn=item.prompt_cn,
            operator_requirement_cn=item.operator_requirement_cn, aspect_ratio=item.aspect_ratio,
            source=item.source,
            supports_creative=bool(attachment_module_rule(snapshot, item.module_key).get("supports_creative")),
            supports_multi_product=bool(
                attachment_module_rule(snapshot, item.module_key).get("supports_multi_product")
            ),
            derived_from_output_id=item.derived_from_output_id,
            current_version_number=item.current_version_number,
            status=item.status, planning_job_id=item.planning_job_id, error_message=item.error_message,
            reference_context_dirty=item.reference_context_dirty,
            reference_state_version=item.reference_state_version,
            reference_analysis_job_id=item.reference_analysis_job_id,
            state_version=item.state_version, last_saved_at=item.last_saved_at,
            skill_source=AttachmentSkillSourceResponse(
                skill_name=str(snapshot.get("skill_name") or ""),
                skill_version_id=plan.skill_version_id,
                skill_version_number=int(snapshot.get("skill_version") or 0) or None,
                can_view_rules=can_view,
                module_rule=attachment_module_rule(snapshot, item.module_key) if can_view else None,
            ),
        ) for item in modules],
    )


async def _load_and_reconcile(
    db: AsyncSession, *, project_id: str, principal: Principal,
) -> tuple[ListingImageProject, ListingGenerationSession, ListingVersion, AttachmentWorkbenchPlan, list[AttachmentWorkbenchModulePlan]]:
    context = await _context(
        db, organization_id=_organization_id(principal), project_id=project_id, user_id=principal.user.id,
    )
    project, _, version, plan, modules = context
    await reconcile_reference_understandings(db, plan=plan, modules=modules)
    await reconcile_attachment_planning(db, plan=plan, modules=modules, version=version)
    await db.commit()
    return project, context[1], version, plan, modules


async def _reference_response(
    db: AsyncSession, storage: StorageService, settings: Settings, *,
    plan: AttachmentWorkbenchPlan, modules: list[AttachmentWorkbenchModulePlan],
) -> AttachmentReferenceStateResponse:
    group = await db.scalar(select(AttachmentProductReferenceGroup).where(
        AttachmentProductReferenceGroup.workbench_plan_id == plan.id,
        AttachmentProductReferenceGroup.organization_id == plan.organization_id,
    ))
    if group is None:
        raise AppError("attachment_reference.group_missing", "商品参考组尚未初始化", 409)
    all_product_items = list((await db.scalars(select(AttachmentProductReferenceItem).where(
        AttachmentProductReferenceItem.product_group_id == group.id,
    ).order_by(AttachmentProductReferenceItem.sort_order, AttachmentProductReferenceItem.created_at))).all())
    product_items: list[AttachmentProductReferenceItem] = []
    for role in ("front", "back", "detail"):
        matching = [item for item in all_product_items if item.view_role == role]
        overrides = [item for item in matching if item.source == "override"]
        product_items.extend(overrides or [item for item in matching if item.source == "session"])
    references_by_module = {
        module.id: await list_module_references(db, module.id) for module in modules
    }
    asset_ids = {item.asset_id for item in product_items}
    asset_ids.update(item.asset_id for rows in references_by_module.values() for item in rows)
    assets = list((await db.scalars(select(Asset).where(
        Asset.organization_id == plan.organization_id,
        Asset.id.in_(asset_ids) if asset_ids else Asset.id == "",
        Asset.deleted_at.is_(None),
    ))).all())
    signed = {item.id: await signed_asset_response(item, storage, settings) for item in assets}
    module_states: list[AttachmentModuleReferenceStateResponse] = []
    for module in modules:
        understanding = await latest_reference_understanding(db, module.id)
        module_states.append(AttachmentModuleReferenceStateResponse(
            module_key=module.module_key,
            slot_definitions=[AttachmentReferenceSlotDefinitionResponse(**item) for item in slot_definitions(module.module_key)],
            references=[AttachmentModuleReferenceResponse(
                id=item.id, slot_type=item.slot_type, asset=signed[item.asset_id],
                sort_order=item.sort_order, metadata=dict(item.metadata_json or {}),
            ) for item in references_by_module[module.id] if item.asset_id in signed],
            reference_context_dirty=module.reference_context_dirty,
            reference_state_version=module.reference_state_version,
            reference_analysis_job_id=module.reference_analysis_job_id,
            understanding=AttachmentReferenceUnderstandingResponse(
                id=understanding.id, version_number=understanding.version_number,
                status=understanding.status, structured=dict(understanding.structured_json or {}),
                source_snapshot=dict(understanding.source_snapshot_json or {}),
                ai_job_id=understanding.ai_job_id, ai_model=understanding.ai_model,
                error_message=understanding.error_message, created_at=understanding.created_at,
            ) if understanding else None,
        ))
    return AttachmentReferenceStateResponse(
        product_group_id=group.id, product_state_version=group.state_version,
        product_references=[AttachmentProductReferenceItemResponse(
            id=item.id, asset=signed[item.asset_id], source_asset_id=item.source_asset_id,
            view_role=item.view_role, sort_order=item.sort_order, source=item.source,
            transform_metadata=dict(item.transform_metadata or {}),
        ) for item in product_items if item.asset_id in signed],
        modules=module_states,
    )


async def _product_composition_responses(
    db: AsyncSession, storage: StorageService, settings: Settings, *,
    modules: list[AttachmentWorkbenchModulePlan],
) -> list[AttachmentProductCompositionResponse]:
    module_ids = [item.id for item in modules]
    compositions = list((await db.scalars(select(AttachmentProductComposition).where(
        AttachmentProductComposition.module_plan_id.in_(module_ids),
    ))).all()) if module_ids else []
    composition_by_module = {item.module_plan_id: item for item in compositions}
    composition_ids = [item.id for item in compositions]
    items = list((await db.scalars(select(AttachmentProductCompositionItem).where(
        AttachmentProductCompositionItem.composition_id.in_(composition_ids),
    ).order_by(
        AttachmentProductCompositionItem.display_order,
        AttachmentProductCompositionItem.created_at,
    ))).all()) if composition_ids else []
    item_ids = [item.id for item in items]
    composition_assets = list((await db.scalars(select(AttachmentProductCompositionAsset).where(
        AttachmentProductCompositionAsset.composition_item_id.in_(item_ids),
    ).order_by(
        AttachmentProductCompositionAsset.sort_order,
        AttachmentProductCompositionAsset.created_at,
    ))).all()) if item_ids else []
    asset_ids = {item.asset_id for item in composition_assets}
    assets = list((await db.scalars(select(Asset).where(
        Asset.id.in_(asset_ids) if asset_ids else Asset.id == "",
        Asset.deleted_at.is_(None),
    ))).all())
    signed = {item.id: await signed_asset_response(item, storage, settings) for item in assets}
    assets_by_item: dict[str, list[AttachmentProductCompositionAsset]] = {}
    for item in composition_assets:
        assets_by_item.setdefault(item.composition_item_id, []).append(item)
    items_by_composition: dict[str, list[AttachmentProductCompositionItem]] = {}
    for item in items:
        items_by_composition.setdefault(item.composition_id, []).append(item)

    responses: list[AttachmentProductCompositionResponse] = []
    for module in modules:
        composition = composition_by_module.get(module.id)
        if composition is None:
            continue
        current_version = await current_composition_version(db, composition)
        responses.append(AttachmentProductCompositionResponse(
            id=composition.id,
            module_key=module.module_key,
            mode=composition.mode,
            current_version_id=current_version.id,
            current_version_number=current_version.version_number,
            state_version=composition.state_version,
            products=[AttachmentProductCompositionItemResponse(
                id=item.id,
                product_role=item.product_role,
                source_session_id=item.source_session_id,
                source_project_id=item.source_project_id,
                display_name=item.display_name_snapshot,
                category_name=item.category_name_snapshot,
                display_order=item.display_order,
                assets=[AttachmentProductCompositionAssetResponse(
                    id=reference.id,
                    asset=signed[reference.asset_id],
                    source_asset_id=reference.source_asset_id,
                    view_role=reference.view_role,
                    sort_order=reference.sort_order,
                ) for reference in assets_by_item.get(item.id, []) if reference.asset_id in signed],
            ) for item in items_by_composition.get(composition.id, [])],
        ))
    return responses


def _generation_preview_response(
    project: ListingImageProject, preview: AttachmentGenerationPreview,
) -> AttachmentGenerationPreviewResponse:
    return AttachmentGenerationPreviewResponse(
        project_id=project.id, model_code=preview.model_code,
        total_images=preview.total_images, snapshot_signature=preview.snapshot_signature,
        modules=[AttachmentGenerationModulePreviewResponse(
            module_key=item.module_key, module_name=item.module_name,
            aspect_ratio=item.aspect_ratio, image_count=item.image_count,
            generation_mode=item.generation_mode,
            delivery_width=item.width, delivery_height=item.height,
            plan_version_id=item.plan_version.id,
            plan_version_number=item.plan_version.version_number,
            prompt_version_id=item.plan_version.id,
            prompt_version_number=item.plan_version.version_number,
            reference_understanding_id=item.understanding.id,
            reference_understanding_version=item.understanding.version_number,
            reference_count=sum(len(values) for values in item.grouped_references.values()),
            directions=[AttachmentCreativeDirectionResponse(
                plan_version_id=direction.plan_version.id,
                module_key=item.module_key,
                direction_index=direction.creative_direction_index or direction.slot_index,
                plan_summary_cn=str(direction.plan_version.plan_summary_cn or ""),
                prompt_cn=str(direction.plan_version.prompt_cn or ""),
                aspect_ratio=item.aspect_ratio,
            ) for direction in item.directions] if item.generation_mode == "creative" else [],
        ) for item in preview.modules],
    )


@router.get("/projects/{project_id}/planning", response_model=AttachmentPlanningResponse)
async def get_planning(
    project_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> AttachmentPlanningResponse:
    project, _, version, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


@router.get("/projects/{project_id}/references", response_model=AttachmentReferenceStateResponse)
async def get_references(
    project_id: str, db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> AttachmentReferenceStateResponse:
    _, _, _, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    return await _reference_response(db, storage, settings, plan=plan, modules=modules)


@router.get(
    "/projects/{project_id}/product-compositions",
    response_model=list[AttachmentProductCompositionResponse],
)
async def get_product_compositions(
    project_id: str,
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[AttachmentProductCompositionResponse]:
    _, _, _, _, modules = await _load_and_reconcile(
        db, project_id=project_id, principal=principal,
    )
    return await _product_composition_responses(db, storage, settings, modules=modules)


async def _changed_product_composition_response(
    db: AsyncSession, storage: StorageService, settings: Settings, *,
    module_key: str, modules: list[AttachmentWorkbenchModulePlan],
) -> AttachmentProductCompositionResponse:
    rows = await _product_composition_responses(db, storage, settings, modules=modules)
    response = next((item for item in rows if item.module_key == module_key), None)
    if response is None:
        raise AppError("attachment_composition.missing", "商品组合尚未初始化，请刷新后重试", 409)
    return response


@router.patch(
    "/projects/{project_id}/modules/{module_key}/product-composition",
    response_model=AttachmentProductCompositionResponse,
)
async def update_product_composition_mode(
    project_id: str, module_key: str, payload: AttachmentProductModeUpdate,
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentProductCompositionResponse:
    _, _, version, _, modules = await _load_and_reconcile(
        db, project_id=project_id, principal=principal,
    )
    module = next((item for item in modules if item.module_key == module_key), None)
    if module is None:
        raise AppError("attachment_composition.module_invalid", "选择了不支持的附图模块", 422)
    rule = attachment_module_rule(dict(version.category_skill_snapshot or {}), module_key)
    await set_product_mode(
        db, module=module, mode=payload.mode,
        expected_state_version=payload.expected_state_version,
        user_id=principal.user.id,
        supports_multi_product=bool(rule.get("supports_multi_product")),
    )
    await db.commit()
    return await _changed_product_composition_response(
        db, storage, settings, module_key=module_key, modules=modules,
    )


@router.post(
    "/projects/{project_id}/modules/{module_key}/product-composition/products",
    response_model=AttachmentProductCompositionResponse,
)
async def add_product_composition_item(
    project_id: str, module_key: str, payload: AttachmentSecondaryProductRequest,
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentProductCompositionResponse:
    _, _, version, _, modules = await _load_and_reconcile(
        db, project_id=project_id, principal=principal,
    )
    module = next((item for item in modules if item.module_key == module_key), None)
    if module is None:
        raise AppError("attachment_composition.module_invalid", "选择了不支持的附图模块", 422)
    if not attachment_module_rule(dict(version.category_skill_snapshot or {}), module_key).get("supports_multi_product"):
        raise AppError("attachment_composition.mode_unsupported", "当前模块不支持多件商品", 422)
    await add_secondary_product(
        db, module=module, source_session_id=payload.source_session_id,
        expected_state_version=payload.expected_state_version, user_id=principal.user.id,
    )
    await db.commit()
    return await _changed_product_composition_response(
        db, storage, settings, module_key=module_key, modules=modules,
    )


@router.put(
    "/projects/{project_id}/modules/{module_key}/product-composition/products/{item_id}",
    response_model=AttachmentProductCompositionResponse,
)
async def replace_product_composition_item(
    project_id: str, module_key: str, item_id: str, payload: AttachmentSecondaryProductRequest,
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentProductCompositionResponse:
    _, _, _, _, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    module = next((item for item in modules if item.module_key == module_key), None)
    if module is None:
        raise AppError("attachment_composition.module_invalid", "选择了不支持的附图模块", 422)
    await replace_secondary_product(
        db, module=module, item_id=item_id, source_session_id=payload.source_session_id,
        expected_state_version=payload.expected_state_version, user_id=principal.user.id,
    )
    await db.commit()
    return await _changed_product_composition_response(
        db, storage, settings, module_key=module_key, modules=modules,
    )


@router.delete(
    "/projects/{project_id}/modules/{module_key}/product-composition/products/{item_id}",
    response_model=AttachmentProductCompositionResponse,
)
async def delete_product_composition_item(
    project_id: str, module_key: str, item_id: str,
    expected_state_version: int = Query(ge=0),
    db: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentProductCompositionResponse:
    _, _, _, _, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    module = next((item for item in modules if item.module_key == module_key), None)
    if module is None:
        raise AppError("attachment_composition.module_invalid", "选择了不支持的附图模块", 422)
    await remove_secondary_product(
        db, module=module, item_id=item_id,
        expected_state_version=expected_state_version, user_id=principal.user.id,
    )
    await db.commit()
    return await _changed_product_composition_response(
        db, storage, settings, module_key=module_key, modules=modules,
    )


@router.post("/projects/{project_id}/generation-preview", response_model=AttachmentGenerationPreviewResponse)
async def preview_generation(
    project_id: str, payload: AttachmentGenerationSelectionRequest,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentGenerationPreviewResponse:
    project, listing_session, version, plan, modules = await _load_and_reconcile(
        db, project_id=project_id, principal=principal,
    )
    preview = await build_attachment_generation_preview(
        db, project=project, session=listing_session, version=version, plan=plan,
        modules=modules, selected_module_keys=payload.selected_module_keys,
        creative_planning_job_id=payload.creative_planning_job_id,
    )
    return _generation_preview_response(project, preview)


@router.post(
    "/projects/{project_id}/generate", response_model=AttachmentGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_attachments(
    project_id: str, payload: AttachmentGenerationRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentGenerationResponse:
    project, listing_session, version, plan, modules = await _load_and_reconcile(
        db, project_id=project_id, principal=principal,
    )
    preview, batch, jobs, group, created = await create_attachment_generation(
        db, settings, project=project, session=listing_session, version=version,
        plan=plan, modules=modules, selected_module_keys=payload.selected_module_keys,
        snapshot_signature=payload.snapshot_signature, idempotency_key=payload.idempotency_key,
        user_id=principal.user.id, creative_planning_job_id=payload.creative_planning_job_id,
    )
    await db.commit()
    if created:
        await dispatch_jobs(
            db,
            await due_jobs(db, settings, limit=preview.total_images, batch_id=batch.id),
        )
    return AttachmentGenerationResponse(
        project_id=project.id, batch_id=batch.id, task_group_id=group.id,
        group_number=group.group_number, status=batch.status,
        job_ids=[item.id for item in jobs],
        module_keys=[item.module_key for item in preview.modules],
        total_images=preview.total_images, created=created,
    )


@router.post(
    "/projects/{project_id}/creative-plans",
    response_model=AttachmentCreativePlanningResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_creative_plan(
    project_id: str, payload: AttachmentCreativePlanningRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentCreativePlanningResponse:
    project, listing_session, version, plan, modules = await _load_and_reconcile(
        db, project_id=project_id, principal=principal,
    )
    job, created = await start_creative_planning(
        db, settings, project=project, session=listing_session, version=version, plan=plan,
        modules=modules, selected_module_keys=payload.selected_module_keys,
        idempotency_key=payload.idempotency_key, user_id=principal.user.id,
    )
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return AttachmentCreativePlanningResponse(
        project_id=project.id, planning_job_id=job.id,
        status="running" if job.status in {"running", "dispatching"} else "queued",
        created=created,
    )


@router.get(
    "/projects/{project_id}/creative-plans/{planning_job_id}",
    response_model=AttachmentCreativePlanningResponse,
)
async def get_creative_plan(
    project_id: str, planning_job_id: str,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> AttachmentCreativePlanningResponse:
    project, _, _, plan, modules = await _load_and_reconcile(
        db, project_id=project_id, principal=principal,
    )
    response = await creative_planning_response(
        db, project=project, plan=plan, modules=modules, planning_job_id=planning_job_id,
    )
    await db.commit()
    return response


@router.post("/projects/{project_id}/modules/{module_key}/references", response_model=AttachmentReferenceStateResponse)
async def create_reference(
    project_id: str, module_key: str, payload: AttachmentReferenceCreateRequest,
    db: AsyncSession = Depends(get_db_session), storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentReferenceStateResponse:
    _, _, _, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    module = next((item for item in modules if item.module_key == module_key), None)
    if module is None:
        raise AppError("attachment_reference.module_invalid", "选择了不支持的附图模块", 422)
    await add_module_reference(
        db, module=module, slot_type=payload.slot_type, asset_id=payload.asset_id,
        metadata=payload.metadata, user_id=principal.user.id,
    )
    await db.commit()
    return await _reference_response(db, storage, settings, plan=plan, modules=modules)


@router.delete("/projects/{project_id}/modules/{module_key}/references/{reference_id}", response_model=AttachmentReferenceStateResponse)
async def delete_reference(
    project_id: str, module_key: str, reference_id: str,
    db: AsyncSession = Depends(get_db_session), storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentReferenceStateResponse:
    _, _, _, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    module = next((item for item in modules if item.module_key == module_key), None)
    if module is None:
        raise AppError("attachment_reference.module_invalid", "选择了不支持的附图模块", 422)
    await remove_module_reference(db, module=module, reference_id=reference_id)
    await db.commit()
    return await _reference_response(db, storage, settings, plan=plan, modules=modules)


@router.put("/projects/{project_id}/product-references/{view_role}", response_model=AttachmentReferenceStateResponse)
async def put_product_reference(
    project_id: str, view_role: str, payload: AttachmentProductReferenceRequest,
    db: AsyncSession = Depends(get_db_session), storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentReferenceStateResponse:
    _, session, _, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    if view_role != payload.view_role:
        raise AppError("attachment_reference.product_role_mismatch", "商品参考角色不一致", 422)
    group, _ = await ensure_product_reference_group(db, plan=plan, session=session, user_id=principal.user.id)
    await replace_product_reference(
        db, group=group, asset_id=payload.asset_id, source_asset_id=payload.source_asset_id,
        view_role=payload.view_role, transform_metadata=payload.transform_metadata,
        user_id=principal.user.id,
    )
    await db.commit()
    return await _reference_response(db, storage, settings, plan=plan, modules=modules)


@router.post(
    "/projects/{project_id}/modules/{module_key}/references/analyze",
    response_model=AttachmentReferenceStateResponse, status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_references(
    project_id: str, module_key: str, payload: AttachmentReferenceAnalyzeRequest,
    db: AsyncSession = Depends(get_db_session), storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentReferenceStateResponse:
    project, _, _, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    module = next((item for item in modules if item.module_key == module_key), None)
    if module is None:
        raise AppError("attachment_reference.module_invalid", "选择了不支持的附图模块", 422)
    job, _, created = await start_reference_analysis(
        db, settings, project=project, plan=plan, module=module,
        idempotency_key=payload.idempotency_key, user_id=principal.user.id,
    )
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return await _reference_response(db, storage, settings, plan=plan, modules=modules)


@router.post("/projects/{project_id}/plan", response_model=AttachmentPlanningResponse, status_code=status.HTTP_202_ACCEPTED)
async def plan_suite(
    project_id: str, payload: AttachmentSuitePlanRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    project, session, version, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    job, created = await start_suite_planning(
        db, settings, project=project, session=session, version=version, plan=plan, module_rows=modules,
        modules=payload.modules, visual_direction_cn=payload.visual_direction_cn,
        idempotency_key=payload.idempotency_key, user_id=principal.user.id,
    )
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


async def _start_one(
    *, project_id: str, module_key: str, payload: AttachmentModulePlanRequest, action: str,
    db: AsyncSession, settings: Settings, principal: Principal,
) -> AttachmentPlanningResponse:
    if module_key not in STANDARD_MODULE_CODES:
        raise AppError("attachment_planning.module_invalid", "选择了不支持的附图模块", 422)
    project, session, version, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    if not plan.visual_direction_cn.strip():
        raise AppError("attachment_planning.visual_direction_required", "请先完成整套AI策划，再单独调整模块", 409)
    indexed = {item.module_key: item for item in modules}
    module = indexed[module_key]
    if action == "optimize_prompt" and (not module.plan_summary_cn.strip() or not module.prompt_cn.strip()):
        raise AppError("attachment_planning.module_prompt_required", "当前模块尚未完成策划，不能只优化Prompt", 409)
    job, created = await start_module_planning(
        db, settings, project=project, session=session, version=version, plan=plan, module=module,
        action=action, aspect_ratio=payload.aspect_ratio,
        operator_requirement_cn=payload.operator_requirement_cn,
        idempotency_key=payload.idempotency_key, user_id=principal.user.id,
    )
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1))
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


@router.post("/projects/{project_id}/modules/{module_key}/replan", response_model=AttachmentPlanningResponse, status_code=status.HTTP_202_ACCEPTED)
async def replan_module(
    project_id: str, module_key: str, payload: AttachmentModulePlanRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    return await _start_one(
        project_id=project_id, module_key=module_key, payload=payload, action="module_replan",
        db=db, settings=settings, principal=principal,
    )


@router.post("/projects/{project_id}/modules/{module_key}/optimize-prompt", response_model=AttachmentPlanningResponse, status_code=status.HTTP_202_ACCEPTED)
async def optimize_module_prompt(
    project_id: str, module_key: str, payload: AttachmentModulePlanRequest,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    return await _start_one(
        project_id=project_id, module_key=module_key, payload=payload, action="optimize_prompt",
        db=db, settings=settings, principal=principal,
    )


@router.patch("/projects/{project_id}/visual-direction", response_model=AttachmentPlanningResponse)
async def update_visual_direction(
    project_id: str, payload: AttachmentVisualDirectionUpdate,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    project, _, version, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    if payload.expected_state_version != plan.state_version:
        raise AppError(
            "attachment_planning.state_version_conflict", "整套视觉方向已被更新，请刷新后合并修改", 409,
            {"expected": payload.expected_state_version, "actual": plan.state_version},
        )
    value = payload.visual_direction_cn.strip()
    if value != plan.visual_direction_cn:
        await add_suite_version(
            db, plan=plan, action="manual_edit", selected=[], user_id=principal.user.id,
            visual_direction_cn=value,
        )
        plan.state_version += 1
        plan.updated_by = principal.user.id
        plan.last_saved_at = datetime.now(UTC)
        if plan.planning_status != "planning":
            plan.planning_status = "ready" if value else "idle"
        plan.error_message = None
    await db.commit()
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


@router.patch("/projects/{project_id}/modules/{module_key}", response_model=AttachmentPlanningResponse)
async def update_module(
    project_id: str, module_key: str, payload: AttachmentModulePlanUpdate,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    project, _, version, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    indexed = {item.module_key: item for item in modules}
    module = indexed.get(module_key)
    if module is None:
        raise AppError("attachment_planning.module_invalid", "选择了不支持的附图模块", 422)
    if payload.expected_state_version != module.state_version:
        raise AppError(
            "attachment_planning.state_version_conflict", "该模块已被更新，请刷新后合并修改", 409,
            {"expected": payload.expected_state_version, "actual": module.state_version, "module_key": module_key},
        )
    next_plan = module.plan_summary_cn if payload.plan_summary_cn is None else payload.plan_summary_cn.strip()
    next_prompt = module.prompt_cn if payload.prompt_cn is None else payload.prompt_cn.strip()
    next_requirement = module.operator_requirement_cn if payload.operator_requirement_cn is None else payload.operator_requirement_cn.strip()
    next_ratio = module.aspect_ratio if payload.aspect_ratio is None else payload.aspect_ratio
    if next_ratio not in {"1:1", "4:5", "3:4"}:
        raise AppError("attachment_planning.aspect_ratio_invalid", "图片比例无效", 422)
    changed = (next_plan, next_prompt, next_requirement, next_ratio) != (
        module.plan_summary_cn, module.prompt_cn, module.operator_requirement_cn, module.aspect_ratio,
    )
    if changed:
        module.operator_requirement_cn = next_requirement
        module.aspect_ratio = next_ratio
        composition = await get_product_composition(db, module=module)
        composition_version = await current_composition_version(db, composition)
        await add_module_version(
            db, plan=plan, module=module, action="manual_edit", user_id=principal.user.id,
            rule_snapshot=attachment_module_rule(dict(version.category_skill_snapshot or {}), module_key),
            plan_summary_cn=next_plan, prompt_cn=next_prompt,
            product_composition_version_id=composition_version.id,
        )
        module.state_version += 1
        module.updated_by = principal.user.id
        module.last_saved_at = datetime.now(UTC)
        if module.status != "planning":
            module.status = "ready" if next_prompt else "draft"
        module.error_message = None
    await db.commit()
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


@router.get("/projects/{project_id}/versions", response_model=list[AttachmentPlanVersionResponse])
async def list_versions(
    project_id: str, module_key: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[AttachmentPlanVersionResponse]:
    _, _, _, plan, _ = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    if module_key is not None and module_key not in STANDARD_MODULE_CODES:
        raise AppError("attachment_planning.module_invalid", "选择了不支持的附图模块", 422)
    rows = await list_attachment_versions(
        db, organization_id=_organization_id(principal), plan_id=plan.id, module_key=module_key,
    )
    return [AttachmentPlanVersionResponse.model_validate(row, from_attributes=True) for row in rows]


@router.get("/projects/{project_id}/results", response_model=AttachmentResultStateResponse)
async def get_result_state(
    project_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> AttachmentResultStateResponse:
    project, _, _, _, _ = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    response = await result_state_response(db, project=project, user_id=principal.user.id)
    await db.commit()
    return response


@router.post(
    "/projects/{project_id}/outputs/{output_id}/review", response_model=AttachmentOutputStateResponse,
)
async def review_output(
    project_id: str, output_id: str, payload: AttachmentOutputReviewRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentOutputStateResponse:
    project, _, _, _, _ = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    response = await review_attachment_output(
        db, project=project, output_id=output_id, status=payload.status,
        expected_review_state_version=payload.expected_review_state_version,
        clear_final_if_rejected=payload.clear_final_if_rejected, user_id=principal.user.id,
    )
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=project.organization_id,
        action=f"attachment_result.{payload.status}", resource_type="generated_output", resource_id=output_id,
        metadata={"project_id": project.id, "module_key": response.module_key},
    )
    await db.commit()
    return response


@router.post(
    "/projects/{project_id}/outputs/{output_id}/adopt-direction",
    response_model=AttachmentPlanningResponse,
)
async def adopt_creative_direction(
    project_id: str, output_id: str, payload: AttachmentAdoptDirectionRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    project, _, version, plan, modules = await _load_and_reconcile(
        db, project_id=project_id, principal=principal,
    )
    module = await adopt_attachment_creative_direction(
        db, project=project, plan=plan, version=version, modules=modules,
        output_id=output_id, expected_state_version=payload.expected_state_version,
        user_id=principal.user.id,
    )
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=project.organization_id,
        action="attachment_result.adopt_creative_direction",
        resource_type="generated_output", resource_id=output_id,
        metadata={"project_id": project.id, "module_key": module.module_key, "plan_version": module.current_version_number},
    )
    await db.commit()
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


@router.post(
    "/projects/{project_id}/outputs/{output_id}/final", response_model=AttachmentOutputStateResponse,
)
async def set_final_output(
    project_id: str, output_id: str, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentOutputStateResponse:
    project, _, _, _, _ = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    response = await set_attachment_final(db, project=project, output_id=output_id, user_id=principal.user.id)
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=project.organization_id,
        action="attachment_result.set_final", resource_type="generated_output", resource_id=output_id,
        metadata={"project_id": project.id, "module_key": response.module_key},
    )
    await db.commit()
    return response


@router.delete("/projects/{project_id}/modules/{module_key}/final", response_model=AttachmentResultStateResponse)
async def clear_final_output(
    project_id: str, module_key: str, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentResultStateResponse:
    project, _, _, _, _ = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    if module_key not in STANDARD_MODULE_CODES:
        raise AppError("attachment_result.module_invalid", "选择了不支持的附图模块", 422)
    await clear_attachment_final(db, project=project, module_key=module_key, user_id=principal.user.id)
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=project.organization_id,
        action="attachment_result.clear_final", resource_type="listing_image_project", resource_id=project.id,
        metadata={"module_key": module_key},
    )
    response = await result_state_response(db, project=project, user_id=principal.user.id)
    await db.commit()
    return response


@router.post("/projects/{project_id}/discard-results", response_model=AttachmentResultStateResponse)
async def discard_results(
    project_id: str, payload: AttachmentModuleKeysRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentResultStateResponse:
    project, _, _, _, _ = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    changed = await discard_attachment_results(
        db, project=project, module_keys=payload.module_keys, user_id=principal.user.id,
    )
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=project.organization_id,
        action="attachment_result.discard", resource_type="listing_image_project", resource_id=project.id,
        metadata={"module_keys": payload.module_keys, "discarded_outputs": changed},
    )
    response = await result_state_response(db, project=project, user_id=principal.user.id)
    await db.commit()
    return response


@router.post("/projects/{project_id}/modules/{module_key}/reset", response_model=AttachmentPlanningResponse)
async def reset_module(
    project_id: str, module_key: str, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> AttachmentPlanningResponse:
    project, _, version, plan, modules = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    module = next((item for item in modules if item.module_key == module_key), None)
    if module is None:
        raise AppError("attachment_result.module_invalid", "选择了不支持的附图模块", 422)
    await reset_attachment_module(db, project=project, plan=plan, module=module, user_id=principal.user.id)
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=project.organization_id,
        action="attachment_result.reset_module", resource_type="listing_image_project", resource_id=project.id,
        metadata={"module_key": module_key},
    )
    await db.commit()
    return _response(project=project, version=version, plan=plan, modules=modules, principal=principal)


@router.post(
    "/projects/{project_id}/jobs/{job_id}/retry", response_model=ListingImageTaskGroupResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_failed_slot(
    project_id: str, job_id: str, payload: AttachmentRetryJobRequest, request: Request,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> ListingImageTaskGroupResponse:
    project, _, _, _, _ = await _load_and_reconcile(db, project_id=project_id, principal=principal)
    batch, jobs, group, created = await retry_attachment_job(
        db, settings, project=project, source_job_id=job_id,
        idempotency_key=payload.idempotency_key, user_id=principal.user.id,
    )
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=project.organization_id,
        action="attachment_result.retry_slot", resource_type="job", resource_id=job_id,
        metadata={"retry_group_id": group.id},
    )
    await db.commit()
    if created:
        await dispatch_jobs(db, await due_jobs(db, settings, limit=1, batch_id=batch.id))
    return await task_group_response(db, storage, settings, group)
