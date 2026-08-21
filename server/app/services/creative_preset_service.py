from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.attachment_planning import AttachmentWorkbenchModulePlan, AttachmentWorkbenchPlan
from app.models.creative_presets import (
    AIModelIdentityVersion,
    AIModelPreset,
    AIModelPresetReference,
    AttachmentPlanModelSelection,
    ThemePreset,
    ThemePresetVersion,
    VisualPreset,
    VisualPresetVersion,
)


UTC = timezone.utc
MODEL_SUPPORTED_MODULES = frozenset({"stadium_scene", "gift_scene", "casual_scene"})


async def visible_visual_presets(
    db: AsyncSession, *, organization_id: str, include_inactive: bool = False,
) -> list[tuple[VisualPreset, VisualPresetVersion]]:
    statement = select(VisualPreset, VisualPresetVersion).join(
        VisualPresetVersion, VisualPresetVersion.id == VisualPreset.current_version_id,
    ).where(or_(VisualPreset.organization_id.is_(None), VisualPreset.organization_id == organization_id))
    if not include_inactive:
        statement = statement.where(VisualPreset.is_active.is_(True))
    rows = list((await db.execute(statement.order_by(VisualPreset.sort_order, VisualPreset.name))).all())
    scoped = {preset.code for preset, _ in rows if preset.organization_id == organization_id}
    return [(preset, version) for preset, version in rows if preset.organization_id == organization_id or preset.code not in scoped]


async def visible_theme_presets(
    db: AsyncSession, *, organization_id: str, include_inactive: bool = False,
) -> list[tuple[ThemePreset, ThemePresetVersion]]:
    statement = select(ThemePreset, ThemePresetVersion).join(
        ThemePresetVersion, ThemePresetVersion.id == ThemePreset.current_version_id,
    ).where(or_(ThemePreset.organization_id.is_(None), ThemePreset.organization_id == organization_id))
    if not include_inactive:
        statement = statement.where(ThemePreset.is_active.is_(True))
    rows = list((await db.execute(statement.order_by(ThemePreset.sort_order, ThemePreset.name))).all())
    scoped = {preset.code for preset, _ in rows if preset.organization_id == organization_id}
    return [(preset, version) for preset, version in rows if preset.organization_id == organization_id or preset.code not in scoped]


async def visible_model_presets(
    db: AsyncSession, *, organization_id: str, published_only: bool = True, user_id: str | None = None,
) -> list[AIModelPreset]:
    statement = select(AIModelPreset).where(
        or_(AIModelPreset.organization_id.is_(None), AIModelPreset.organization_id == organization_id),
        AIModelPreset.is_active.is_(True),
    )
    if published_only:
        statement = statement.join(
            AIModelIdentityVersion,
            AIModelIdentityVersion.id == AIModelPreset.current_identity_version_id,
        ).where(
            AIModelIdentityVersion.organization_id == organization_id,
            or_(
                (AIModelPreset.is_published.is_(True)) & (AIModelPreset.status == "PUBLISHED") & (AIModelIdentityVersion.status == "PUBLISHED"),
                (AIModelPreset.owner_user_id == user_id) & (AIModelPreset.source_type == "USER_GENERATED") & (AIModelIdentityVersion.status == "PERSONAL_READY"),
            ) if user_id else (
                (AIModelPreset.is_published.is_(True)) & (AIModelPreset.status == "PUBLISHED") & (AIModelIdentityVersion.status == "PUBLISHED")
            ),
        )
    rows = list((await db.scalars(statement.order_by(AIModelPreset.sort_order, AIModelPreset.display_name))).all())
    scoped = {item.code for item in rows if item.organization_id == organization_id}
    return [item for item in rows if item.organization_id == organization_id or item.code not in scoped]


async def default_visual_preset(
    db: AsyncSession, *, organization_id: str,
) -> tuple[VisualPreset, VisualPresetVersion]:
    rows = await visible_visual_presets(db, organization_id=organization_id)
    if not rows:
        # Test databases and fresh developer databases may be created directly
        # from SQLAlchemy metadata instead of Alembic. Use the same deterministic
        # IDs as migration 0055 so this idempotent fallback cannot create a
        # second system default after the migration seed exists.
        preset_id = str(uuid5(NAMESPACE_URL, "amazon-image-studio:phase9:visual:amazon_conversion"))
        version_id = str(uuid5(NAMESPACE_URL, "amazon-image-studio:phase9:visual-version:amazon_conversion"))
        preset = await db.get(VisualPreset, preset_id)
        version = await db.get(VisualPresetVersion, version_id)
        if preset is None:
            preset = VisualPreset(
                id=preset_id, organization_id=None, code="amazon_conversion", name="亚马逊高转化电商",
                short_description="商品突出 · 卖点清晰", category_scope=[], recommended_modules=[],
                recommended_model_tags=["commercial", "sports"], tags=["conversion", "commerce"],
                current_version_id=None, sort_order=10, is_active=True, is_default=True,
            )
            db.add(preset)
            await db.flush()
        if version is None:
            version = VisualPresetVersion(
                id=version_id, preset_id=preset.id, version_number=1,
                full_prompt_template=(
                    "你正在为 Amazon Listing 策划一整套商品附图。采用亚马逊高转化电商方向："
                    "商品始终是第一视觉主体；商品颜色、结构、Logo、文字、号码、印花及定制内容严格依据PRODUCT。"
                    "人物和环境只辅助传达卖点，不得抢夺焦点或修改商品。输出统一视觉方向、模块方案和可执行中文Prompt。"
                ),
                change_summary="系统默认兜底", created_by=None, created_at=datetime.now(UTC),
            )
            db.add(version)
            await db.flush()
        preset.current_version_id = version.id
        rows = [(preset, version)]
    return next((item for item in rows if item[0].is_default), rows[0])


async def ensure_plan_creative_context(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan,
) -> None:
    if plan.visual_preset_id and plan.visual_preset_version_id:
        return
    preset, version = await default_visual_preset(db, organization_id=plan.organization_id)
    plan.visual_preset_id = preset.id
    plan.visual_preset_version_id = version.id
    plan.model_selection_mode = plan.model_selection_mode or "recommended"
    plan.creative_context_version = max(1, int(plan.creative_context_version or 0))


async def _active_visual(
    db: AsyncSession, *, organization_id: str, preset_id: str,
) -> tuple[VisualPreset, VisualPresetVersion]:
    row = (await db.execute(select(VisualPreset, VisualPresetVersion).join(
        VisualPresetVersion, VisualPresetVersion.id == VisualPreset.current_version_id,
    ).where(
        VisualPreset.id == preset_id,
        or_(VisualPreset.organization_id.is_(None), VisualPreset.organization_id == organization_id),
        VisualPreset.is_active.is_(True),
    ))).first()
    if row is None:
        raise AppError("creative_preset.visual_invalid", "选择的整套视觉模板不存在或已停用", 422)
    return row[0], row[1]


async def _active_theme(
    db: AsyncSession, *, organization_id: str, preset_id: str | None,
) -> tuple[ThemePreset, ThemePresetVersion] | None:
    if not preset_id:
        return None
    row = (await db.execute(select(ThemePreset, ThemePresetVersion).join(
        ThemePresetVersion, ThemePresetVersion.id == ThemePreset.current_version_id,
    ).where(
        ThemePreset.id == preset_id,
        or_(ThemePreset.organization_id.is_(None), ThemePreset.organization_id == organization_id),
        ThemePreset.is_active.is_(True),
    ))).first()
    if row is None:
        raise AppError("creative_preset.theme_invalid", "选择的主题模板不存在或已停用", 422)
    return row[0], row[1]


async def _identity_with_model(
    db: AsyncSession, *, organization_id: str, identity_id: str, user_id: str | None = None,
) -> tuple[AIModelIdentityVersion, AIModelPreset]:
    row = (await db.execute(select(AIModelIdentityVersion, AIModelPreset).join(
        AIModelPreset, AIModelPreset.id == AIModelIdentityVersion.model_preset_id,
    ).where(
        AIModelIdentityVersion.id == identity_id,
        AIModelPreset.current_identity_version_id == AIModelIdentityVersion.id,
        AIModelPreset.is_active.is_(True),
        or_(
            (AIModelPreset.is_published.is_(True)) & (AIModelPreset.status == "PUBLISHED") & (AIModelIdentityVersion.status == "PUBLISHED"),
            (AIModelPreset.owner_user_id == user_id) & (AIModelPreset.source_type.in_(["USER_TEMPORARY", "USER_GENERATED"])) & (AIModelIdentityVersion.status == "PERSONAL_READY"),
        ) if user_id else (
            (AIModelPreset.is_published.is_(True)) & (AIModelPreset.status == "PUBLISHED") & (AIModelIdentityVersion.status == "PUBLISHED")
        ),
        AIModelIdentityVersion.organization_id == organization_id,
        or_(AIModelPreset.organization_id.is_(None), AIModelPreset.organization_id == organization_id),
    ))).first()
    if row is None:
        raise AppError("creative_preset.model_invalid", "选择的AI模特不存在、未发布或已停用", 422)
    return row[0], row[1]


async def recommend_models(
    db: AsyncSession, *, organization_id: str, visual: VisualPreset,
    theme: ThemePreset | None, count: int,
) -> list[tuple[AIModelIdentityVersion, AIModelPreset]]:
    candidates = await visible_model_presets(db, organization_id=organization_id, published_only=True)
    desired = set(visual.recommended_model_tags or []) | set(theme.tags or [] if theme else [])
    ranked = sorted(
        candidates,
        key=lambda item: (-len(desired & set(item.tags or [])), item.sort_order, item.display_name),
    )
    result: list[tuple[AIModelIdentityVersion, AIModelPreset]] = []
    seen: set[str] = set()
    for model in ranked:
        if not model.current_identity_version_id or model.current_identity_version_id in seen:
            continue
        identity = await db.get(AIModelIdentityVersion, model.current_identity_version_id)
        if identity is None or identity.status != "PUBLISHED":
            continue
        seen.add(identity.id)
        result.append((identity, model))
        if len(result) >= count:
            break
    return result


async def selected_models(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan, module_key: str = "__global__",
) -> list[tuple[AttachmentPlanModelSelection, AIModelIdentityVersion, AIModelPreset]]:
    rows = list((await db.execute(select(
        AttachmentPlanModelSelection, AIModelIdentityVersion, AIModelPreset,
    ).join(
        AIModelIdentityVersion, AIModelIdentityVersion.id == AttachmentPlanModelSelection.identity_version_id,
    ).join(
        AIModelPreset, AIModelPreset.id == AttachmentPlanModelSelection.model_preset_id,
    ).where(
        AttachmentPlanModelSelection.workbench_plan_id == plan.id,
        AttachmentPlanModelSelection.organization_id == plan.organization_id,
        AttachmentPlanModelSelection.module_key == module_key,
        AttachmentPlanModelSelection.identity_version_id.is_not(None),
    ).order_by(AttachmentPlanModelSelection.product_slot))).all())
    return [(row[0], row[1], row[2]) for row in rows]


async def set_plan_creative_context(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan, modules: list[AttachmentWorkbenchModulePlan],
    visual_preset_id: str, theme_preset_id: str | None, model_selection_mode: str,
    selected_model_identity_version_ids: list[str], expected_version: int, user_id: str,
) -> None:
    if plan.creative_context_version != expected_version:
        raise AppError("creative_context.version_conflict", "创意设置已在其他页面更新，请刷新后重试", 409)
    visual, visual_version = await _active_visual(db, organization_id=plan.organization_id, preset_id=visual_preset_id)
    theme_row = await _active_theme(db, organization_id=plan.organization_id, preset_id=theme_preset_id)
    theme, theme_version = theme_row if theme_row else (None, None)
    model_rows: list[tuple[AIModelIdentityVersion, AIModelPreset]] = []
    if model_selection_mode == "selected":
        model_rows = [await _identity_with_model(
            db, organization_id=plan.organization_id, identity_id=identity_id, user_id=user_id,
        ) for identity_id in selected_model_identity_version_ids]
    elif model_selection_mode == "recommended":
        model_rows = await recommend_models(
            db, organization_id=plan.organization_id, visual=visual, theme=theme, count=3,
        )
    elif model_selection_mode != "none":
        raise AppError("creative_context.model_mode_invalid", "模特选择方式无效", 422)

    old_model_ids = [row[1].id for row in await selected_models(db, plan=plan)]
    new_model_ids = [identity.id for identity, _ in model_rows]
    visual_changed = plan.visual_preset_version_id != visual_version.id
    theme_changed = plan.theme_preset_version_id != (theme_version.id if theme_version else None)
    model_changed = plan.model_selection_mode != model_selection_mode or old_model_ids != new_model_ids
    if not (visual_changed or theme_changed or model_changed):
        return

    await db.execute(delete(AttachmentPlanModelSelection).where(
        AttachmentPlanModelSelection.workbench_plan_id == plan.id,
        AttachmentPlanModelSelection.module_key == "__global__",
    ))
    for slot, (identity, model) in enumerate(model_rows, 1):
        db.add(AttachmentPlanModelSelection(
            organization_id=plan.organization_id, workbench_plan_id=plan.id,
            module_key="__global__", product_slot=slot, selection_mode=model_selection_mode,
            model_preset_id=model.id, identity_version_id=identity.id,
            source=model_selection_mode, created_by=user_id, updated_by=user_id,
        ))
    plan.visual_preset_id = visual.id
    plan.visual_preset_version_id = visual_version.id
    plan.theme_preset_id = theme.id if theme else None
    plan.theme_preset_version_id = theme_version.id if theme_version else None
    plan.model_selection_mode = model_selection_mode
    plan.creative_context_version += 1
    plan.updated_by = user_id
    plan.last_saved_at = datetime.now(UTC)
    if plan.visual_direction_version > 0:
        plan.planning_status = "stale"
    for module in modules:
        if visual_changed or theme_changed or (model_changed and module.module_key in MODEL_SUPPORTED_MODULES):
            if module.current_version_number > 0:
                module.status = "stale"
            module.updated_by = user_id


async def set_module_model_context(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan, module: AttachmentWorkbenchModulePlan,
    selection_mode: str, selected_model_identity_version_ids: list[str], user_id: str,
) -> None:
    """Persist one module override without mutating the global model default."""
    if module.module_key not in MODEL_SUPPORTED_MODULES:
        raise AppError("creative_context.module_model_unsupported", "当前模块不支持AI模特", 422)
    if selection_mode not in {"inherit", "recommended", "selected", "none"}:
        raise AppError("creative_context.model_mode_invalid", "模特选择方式无效", 422)
    model_rows: list[tuple[AIModelIdentityVersion, AIModelPreset]] = []
    if selection_mode == "selected":
        if not selected_model_identity_version_ids:
            raise AppError("creative_context.model_required", "请选择至少一个AI模特", 422)
        model_rows = [await _identity_with_model(
            db, organization_id=plan.organization_id, identity_id=identity_id, user_id=user_id,
        ) for identity_id in selected_model_identity_version_ids]
    elif selection_mode == "recommended":
        visual = await db.get(VisualPreset, plan.visual_preset_id)
        theme = await db.get(ThemePreset, plan.theme_preset_id) if plan.theme_preset_id else None
        if visual is None:
            raise AppError("creative_preset.visual_missing", "请先选择整套视觉模板", 409)
        model_rows = await recommend_models(
            db, organization_id=plan.organization_id, visual=visual, theme=theme, count=max(1, len(selected_model_identity_version_ids) or 1),
        )
    await db.execute(delete(AttachmentPlanModelSelection).where(
        AttachmentPlanModelSelection.workbench_plan_id == plan.id,
        AttachmentPlanModelSelection.module_key == module.module_key,
    ))
    if selection_mode != "inherit":
        if model_rows:
            for slot, (identity, model) in enumerate(model_rows, 1):
                db.add(AttachmentPlanModelSelection(
                    organization_id=plan.organization_id, workbench_plan_id=plan.id,
                    module_key=module.module_key, product_slot=slot, selection_mode=selection_mode,
                    model_preset_id=model.id, identity_version_id=identity.id,
                    source=selection_mode, created_by=user_id, updated_by=user_id,
                ))
        else:
            db.add(AttachmentPlanModelSelection(
                organization_id=plan.organization_id, workbench_plan_id=plan.id,
                module_key=module.module_key, product_slot=-1, selection_mode=selection_mode,
                model_preset_id=None, identity_version_id=None,
                source=selection_mode, created_by=user_id, updated_by=user_id,
            ))
    if module.current_version_number > 0:
        module.status = "stale"
    module.state_version += 1
    module.updated_by = user_id
    module.last_saved_at = datetime.now(UTC)


async def module_model_context_snapshot(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan, module_key: str,
) -> dict[str, object]:
    marker = await db.scalar(select(AttachmentPlanModelSelection).where(
        AttachmentPlanModelSelection.workbench_plan_id == plan.id,
        AttachmentPlanModelSelection.module_key == module_key,
    ).order_by(AttachmentPlanModelSelection.product_slot))
    inherited = marker is None
    effective_key = "__global__" if inherited else module_key
    mode = plan.model_selection_mode if inherited else marker.selection_mode
    rows = await selected_models(db, plan=plan, module_key=effective_key)
    models = await _model_snapshot_rows(db, rows)
    return {
        "module_key": module_key,
        "selection_mode": "inherit" if inherited else mode,
        "effective_selection_mode": mode,
        "inherited": inherited,
        "selected_models": models,
    }


async def _model_snapshot_rows(
    db: AsyncSession,
    rows: list[tuple[AttachmentPlanModelSelection, AIModelIdentityVersion, AIModelPreset]],
) -> list[dict[str, object]]:
    models: list[dict[str, object]] = []
    for selection, identity, model in rows:
        references = list((await db.scalars(select(AIModelPresetReference).where(
            AIModelPresetReference.identity_version_id == identity.id,
        ).order_by(AIModelPresetReference.sort_order))).all())
        models.append({
            "product_slot": selection.product_slot, "source": selection.source,
            "model_preset_id": model.id, "model_code": model.code, "model_name": model.display_name,
            "identity_version_id": identity.id, "identity_version_number": identity.version_number,
            "identity_asset_id": identity.identity_asset_id,
            "identity_prompt_snapshot": identity.identity_prompt_snapshot,
            "reference_assets": [{"role": item.reference_role, "asset_id": item.asset_id, "sort_order": item.sort_order} for item in references],
        })
    return models


async def creative_context_snapshot(
    db: AsyncSession, *, plan: AttachmentWorkbenchPlan,
) -> dict[str, object]:
    await ensure_plan_creative_context(db, plan=plan)
    visual = await db.get(VisualPreset, plan.visual_preset_id)
    visual_version = await db.get(VisualPresetVersion, plan.visual_preset_version_id)
    if visual is None or visual_version is None:
        raise AppError("creative_preset.visual_missing", "当前项目的整套视觉模板已不存在", 409)
    theme = await db.get(ThemePreset, plan.theme_preset_id) if plan.theme_preset_id else None
    theme_version = await db.get(ThemePresetVersion, plan.theme_preset_version_id) if plan.theme_preset_version_id else None
    model_rows = await selected_models(db, plan=plan)
    models = await _model_snapshot_rows(db, model_rows)
    return {
        "visual_preset_id": visual.id,
        "visual_preset_code": visual.code,
        "visual_preset_name": visual.name,
        "visual_preset_version_id": visual_version.id,
        "visual_preset_version_number": visual_version.version_number,
        "visual_preset_prompt": visual_version.full_prompt_template,
        "theme_preset_id": theme.id if theme else None,
        "theme_preset_code": theme.code if theme else None,
        "theme_preset_name": theme.name if theme else None,
        "theme_preset_version_id": theme_version.id if theme_version else None,
        "theme_preset_version_number": theme_version.version_number if theme_version else None,
        "theme_prompt": theme_version.full_prompt_template if theme_version else "",
        "model_selection_mode": plan.model_selection_mode,
        "selected_models": models,
        "creative_context_version": plan.creative_context_version,
    }


async def next_version_number(db: AsyncSession, *, version_model: type, preset_id: str) -> int:
    value = await db.scalar(select(func.max(version_model.version_number)).where(version_model.preset_id == preset_id))
    return int(value or 0) + 1
