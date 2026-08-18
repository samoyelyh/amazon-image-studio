from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.listing_workflow import (
    CategorySkill,
    CategorySkillVersion,
    ImagePromptItem,
    ListingGenerationSession,
    ListingImageProject,
    ListingImageTaskGroup,
    ListingVersion,
    ProductCategory,
)
from app.schemas.tasks import BatchJobItemRequest, JobBatchSubmitRequest
from app.services.category_listing_service import build_analysis_segment, normalize_bilingual_listing_content, resolve_bound_model_code
from app.services.category_skill_service import version_config
from app.services.listing_image_task_group_service import build_input_asset_snapshot, create_group_for_batch
from app.services.task_service import submit_batch


UTC = timezone.utc
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
FREE_CATEGORY_CODE = "internal_free_image_variation"
FREE_SKILL_CODE = "internal_free_image_variation"
FREE_ITEM_CODE = "variation:free:main"
FREE_BASE_PROMPT = """Use all uploaded reference images as the visual source of truth.

Create one standalone, photorealistic e-commerce image that follows the operator's latest creative direction. Preserve the identity and all visually verified product details unless the operator explicitly asks to change them. Never invent unsupported product features, logos, text, numbers, graphics, materials, people, or claims. Keep visible text and symbols legible and accurate. Do not create a collage, contact sheet, split screen, or before-and-after layout. Return one complete image only."""


async def ensure_free_variation_foundation(
    db: AsyncSession, *, user_id: str,
) -> tuple[ProductCategory, CategorySkill]:
    """Create the hidden neutral context required by existing non-null task FKs.

    This is infrastructure only: it is inactive and never appears in the user
    category picker. Free mode prompts do not inherit category-specific rules.
    """
    category = await db.scalar(select(ProductCategory).where(ProductCategory.category_code == FREE_CATEGORY_CODE))
    if category is None:
        category = ProductCategory(
            category_code=FREE_CATEGORY_CODE,
            category_name="自由图片裂变",
            description="内部中性上下文，仅用于自由图片裂变任务复用现有Session和任务组。",
            is_active=False,
            sort_order=9999,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(category)
        await db.flush()
    skill = await db.scalar(select(CategorySkill).where(
        CategorySkill.category_id == category.id,
        CategorySkill.skill_code == FREE_SKILL_CODE,
    ))
    if skill is None:
        skill = CategorySkill(
            category_id=category.id,
            skill_name="自由裂变基础规则",
            skill_code=FREE_SKILL_CODE,
            is_active=False,
            version=1,
            analysis_prompt="",
            listing_title_prompt="",
            bullet_points_prompt="",
            a_plus_prompt="",
            image_prompt_template=FREE_BASE_PROMPT,
            image_types_config=[],
            prompt_rules={},
            status="internal",
            description="自由模式的中性保真约束，不向用户提供固定裂变流程。",
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(skill)
        await db.flush()
    return category, skill


def free_variation_snapshot(category: ProductCategory, skill: CategorySkill) -> dict[str, object]:
    return {
        "category_id": category.id,
        "category_code": category.category_code,
        "category_name": category.category_name,
        "skill_id": skill.id,
        "skill_name": skill.skill_name,
        "skill_code": skill.skill_code,
        "skill_version_id": None,
        "skill_version": 1,
        "system_prompt": FREE_BASE_PROMPT,
        "image_prompt_template": FREE_BASE_PROMPT,
        "default_image_types": [],
        "image_prompt_config": {
            "system_prompt": FREE_BASE_PROMPT,
            "category_prompt": "",
            "image_types": [],
        },
        "workflow_mode": "free_image_variation",
    }


async def create_free_variation_project(
    db: AsyncSession, *, organization_id: str, user_id: str,
    asset_ids: list[str], primary_asset_id: str,
) -> tuple[ListingGenerationSession, ListingVersion, ListingImageProject]:
    category, skill = await ensure_free_variation_foundation(db, user_id=user_id)
    snapshot = free_variation_snapshot(category, skill)
    now = datetime.now(UTC)
    listing = normalize_bilingual_listing_content({
        "title": {"en": "Free image variation", "zh": "自由图片裂变"},
        "bullet_points": [],
    })
    session = ListingGenerationSession(
        organization_id=organization_id,
        project_id=None,
        category_id=category.id,
        skill_id=skill.id,
        skill_version_id=None,
        category_skill_snapshot=snapshot,
        analysis_result_id=None,
        status="confirmed",
        source_asset_ids=list(asset_ids),
        primary_asset_id=primary_asset_id,
        listing_content=listing,
        confirmed_at=now,
        confirmed_by=user_id,
        current_step=4,
        last_saved_at=now,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(session)
    await db.flush()
    version = ListingVersion(
        organization_id=organization_id,
        session_id=session.id,
        version_number=1,
        source_listing_version_id=None,
        listing_snapshot=listing,
        analysis_snapshot={},
        category_skill_snapshot=snapshot,
        confirmed_at=now,
        confirmed_by=user_id,
        created_by=user_id,
    )
    db.add(version)
    await db.flush()
    session.current_listing_version_id = version.id
    project = ListingImageProject(
        organization_id=organization_id,
        session_id=session.id,
        listing_version_id=version.id,
        status="editing",
        selected_template=None,
        prompt_config={
            "free_variation": {
                "mode": "free",
                "asset_ids": list(asset_ids),
                "primary_asset_id": primary_asset_id,
                "chinese_prompt": "",
                "selected_category_id": None,
            }
        },
        task_count=0,
        generated_asset_ids=[],
        state_version=0,
        last_saved_at=now,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(project)
    await db.flush()
    return session, version, project


async def optional_skill_recommendations(
    db: AsyncSession, category_id: str | None,
) -> dict[str, object]:
    if not category_id:
        return {"available": False, "directions": [], "templates": []}
    category = await db.get(ProductCategory, category_id)
    if category is None or not category.is_active:
        return {"available": False, "directions": [], "templates": []}
    skill = await db.get(CategorySkill, category.default_skill_id) if category.default_skill_id else None
    if skill is None or not skill.is_active or skill.category_id != category.id:
        return {
            "available": False, "category_id": category.id, "category_name": category.category_name,
            "directions": [], "templates": [],
        }
    version = await db.get(CategorySkillVersion, skill.default_published_version_id) if skill.default_published_version_id else None
    if version is None or version.skill_id != skill.id or version.status != "published":
        return {
            "available": False, "category_id": category.id, "category_name": category.category_name,
            "directions": [], "templates": [],
        }
    config = version_config(version)
    image_config = config.get("image_prompt_config")
    image_config = image_config if isinstance(image_config, dict) else {}
    variation = image_config.get("variation_config")
    variation = variation if isinstance(variation, dict) and variation.get("enabled", True) else {}
    directions: list[dict[str, object]] = []
    templates: list[dict[str, str]] = []
    for variation_type in variation.get("types") or []:
        if not isinstance(variation_type, dict) or variation_type.get("enabled", True) is False:
            continue
        type_name = str(variation_type.get("name") or variation_type.get("code") or "裂变方向")
        plans = []
        for plan in variation_type.get("plans") or []:
            if not isinstance(plan, dict) or plan.get("enabled", True) is False:
                continue
            plan_name = str(plan.get("name") or plan.get("code") or "推荐方案")
            chinese = str(plan.get("chinese_instruction_default") or "").strip()
            if not chinese:
                chinese = f"保持参考图片中的主体和产品核心细节不变，按“{plan_name}”方向进行图片裂变"
            plans.append({"code": str(plan.get("code") or ""), "name": plan_name})
            templates.append({
                "id": f"skill:{variation_type.get('code')}:{plan.get('code')}",
                "name": f"{type_name} · {plan_name}",
                "text": chinese,
            })
        directions.append({
            "code": str(variation_type.get("code") or ""),
            "name": type_name,
            "preserve_elements": list(variation_type.get("preserve_elements") or []),
            "allowed_changes": list(variation_type.get("allowed_changes") or []),
            "plans": plans,
        })
    return {
        "available": True,
        "category_id": category.id,
        "category_name": category.category_name,
        "skill_id": skill.id,
        "skill_name": skill.skill_name,
        "skill_version_id": version.id,
        "skill_version_number": version.version_number,
        "directions": directions,
        "templates": templates,
        "prompt_context": {
            "category_prompt": str(image_config.get("category_prompt") or ""),
            "system_prompt": str(image_config.get("system_prompt") or ""),
            "directions": directions,
        },
    }


def build_free_variation_base_prompt(recommendation: dict[str, object]) -> str:
    sections = ["FREE VARIATION SYSTEM CONSTRAINTS (highest priority):\n" + FREE_BASE_PROMPT]
    if recommendation.get("available"):
        prompt_context = recommendation.get("prompt_context")
        prompt_context = prompt_context if isinstance(prompt_context, dict) else {}
        optional = "\n".join(filter(None, [
            str(prompt_context.get("system_prompt") or "").strip(),
            str(prompt_context.get("category_prompt") or "").strip(),
        ]))
        if optional:
            sections.append(
                "OPTIONAL CATEGORY/SKILL GUIDANCE (lower priority; use only when compatible with the operator's request):\n"
                + optional
            )
    sections.append(
        "The operator's Chinese instructions are the primary creative direction. Rewrite them into one complete, natural English image-editing prompt without mechanically appending a translation."
    )
    return "\n\n".join(sections)


async def build_and_save_free_variation_prompt(
    db: AsyncSession, *, project: ListingImageProject, session: ListingGenerationSession,
    chinese_prompt: str, selected_category_id: str | None,
    template_fragments: list[str], user_id: str,
) -> tuple[ImagePromptItem, dict[str, object]]:
    recommendation = await optional_skill_recommendations(db, selected_category_id)
    base_prompt = build_free_variation_base_prompt(recommendation)
    item = await db.scalar(select(ImagePromptItem).where(
        ImagePromptItem.organization_id == project.organization_id,
        ImagePromptItem.project_type == "listing_image",
        ImagePromptItem.project_id == project.id,
        ImagePromptItem.item_code == FREE_ITEM_CODE,
    ))
    now = datetime.now(UTC)
    if item is None:
        item = ImagePromptItem(
            organization_id=project.organization_id,
            project_type="listing_image",
            project_id=project.id,
            session_id=session.id,
            category_id=session.category_id,
            skill_id=session.skill_id,
            item_code=FREE_ITEM_CODE,
            image_type="variation.free",
            original_english_prompt=base_prompt,
            chinese_editing_instruction=chinese_prompt,
            optimized_english_prompt=base_prompt,
            status="needs_optimization",
            current_version_number=0,
            state_version=0,
            last_saved_at=now,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(item)
        await db.flush()
    else:
        changed = item.chinese_editing_instruction != chinese_prompt or item.original_english_prompt != base_prompt
        item.original_english_prompt = base_prompt
        item.chinese_editing_instruction = chinese_prompt
        item.updated_by = user_id
        item.last_saved_at = now
        item.error_message = None
        item.state_version += 1
        if changed:
            item.status = "needs_optimization"
    current = dict(project.prompt_config or {})
    free = dict(current.get("free_variation") or {})
    free.update({
        "mode": "free",
        "asset_ids": list(free.get("asset_ids") or session.source_asset_ids or []),
        "primary_asset_id": free.get("primary_asset_id") or session.primary_asset_id,
        "chinese_prompt": chinese_prompt,
        "selected_category_id": selected_category_id,
        "template_fragments": list(template_fragments),
        "skill_recommendation": {
            key: recommendation.get(key) for key in (
                "available", "category_id", "category_name", "skill_id", "skill_name",
                "skill_version_id", "skill_version_number",
            )
        },
    })
    project.prompt_config = {**current, "free_variation": free}
    project.updated_by = user_id
    project.state_version += 1
    project.last_saved_at = now
    return item, recommendation


def variation_config(snapshot: dict[str, object]) -> dict[str, object]:
    image_config = snapshot.get("image_prompt_config")
    raw = image_config.get("variation_config") if isinstance(image_config, dict) else None
    if not isinstance(raw, dict) or not raw.get("enabled", True):
        raise AppError(
            "listing_variation.not_configured",
            "当前品类暂未配置图片裂变方案，请联系管理员在Skill配置台中完成配置。",
            422,
        )
    types = raw.get("types")
    if not isinstance(types, list) or not any(isinstance(item, dict) and item.get("enabled", True) for item in types):
        raise AppError(
            "listing_variation.not_configured",
            "当前品类暂未配置图片裂变方案，请联系管理员在Skill配置台中完成配置。",
            422,
        )
    return raw


def enabled_variation_types(snapshot: dict[str, object]) -> list[dict[str, object]]:
    config = variation_config(snapshot)
    result: list[dict[str, object]] = []
    for item in config.get("types", []):
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        enabled_item = dict(item)
        enabled_item["plans"] = [
            dict(plan)
            for plan in item.get("plans") or []
            if isinstance(plan, dict) and plan.get("enabled", True)
        ]
        result.append(enabled_item)
    return result


def _type_index(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(item.get("code")): item for item in enabled_variation_types(snapshot) if item.get("code")}


def validate_variation_skill_config(config: dict[str, object]) -> list[str]:
    errors: list[str] = []
    variation = config.get("variation_config")
    if variation in (None, {}):
        return errors
    if not isinstance(variation, dict):
        return ["智能图片裂变配置必须是对象"]
    types = variation.get("types")
    if not isinstance(types, list):
        return ["智能图片裂变至少需要一个裂变类型"]
    type_codes: set[str] = set()
    for index, item in enumerate(types):
        if not isinstance(item, dict):
            errors.append(f"裂变类型 {index + 1} 必须是对象")
            continue
        code = str(item.get("code") or "")
        if not CODE_PATTERN.fullmatch(code):
            errors.append(f"裂变类型编码无效：{code or index + 1}")
        elif code in type_codes:
            errors.append(f"裂变类型编码重复：{code}")
        type_codes.add(code)
        if not str(item.get("prompt_rule") or "").strip():
            errors.append(f"裂变类型 {code or index + 1} 缺少独立提示词规则")
        if not isinstance(item.get("preserve_elements"), list) or not item.get("preserve_elements"):
            errors.append(f"裂变类型 {code or index + 1} 缺少必须保持元素")
        if not isinstance(item.get("allowed_changes"), list) or not item.get("allowed_changes"):
            errors.append(f"裂变类型 {code or index + 1} 缺少允许变化元素")
        plan_codes: set[str] = set()
        for plan_index, plan in enumerate(item.get("plans") or []):
            if not isinstance(plan, dict):
                errors.append(f"裂变类型 {code or index + 1} 的方案 {plan_index + 1} 必须是对象")
                continue
            plan_code = str(plan.get("code") or "")
            if not CODE_PATTERN.fullmatch(plan_code):
                errors.append(f"裂变方案编码无效：{plan_code or plan_index + 1}")
            elif plan_code in plan_codes:
                errors.append(f"裂变方案编码重复：{code}.{plan_code}")
            plan_codes.add(plan_code)
            if not str(plan.get("prompt_template") or "").strip():
                errors.append(f"裂变方案 {code}.{plan_code or plan_index + 1} 缺少英文提示词")
    return errors


def build_variation_prompt(
    version: ListingVersion, *, variation_type: dict[str, object], plan: dict[str, object], custom_plan: bool,
) -> str:
    snapshot = dict(version.category_skill_snapshot or {})
    image_config = snapshot.get("image_prompt_config")
    image_config = image_config if isinstance(image_config, dict) else {}
    listing = normalize_bilingual_listing_content(version.listing_snapshot or {})
    title = listing.get("title")
    title_en = str(title.get("en") or "") if isinstance(title, dict) else ""
    bullets = listing.get("bullet_points")
    bullet_text = "; ".join(
        str(item.get("en") or "").strip() for item in (bullets or []) if isinstance(item, dict) and item.get("en")
    )
    preserve = ", ".join(str(item) for item in variation_type.get("preserve_elements") or [])
    changes = ", ".join(str(item) for item in variation_type.get("allowed_changes") or [])
    plan_prompt = str(plan.get("prompt_template") or "").strip()
    if custom_plan and not plan_prompt:
        plan_prompt = "Create one distinct variation within this variation type. Follow the operator's optimized custom direction."
    sections = [
        "SYSTEM PRODUCT-FIDELITY CONSTRAINTS (highest priority):\n" + str(image_config.get("system_prompt") or snapshot.get("system_prompt") or "").strip(),
        "CATEGORY-SPECIFIC PRODUCT RULES:\n" + str(image_config.get("category_prompt") or snapshot.get("image_prompt_template") or "").strip(),
        build_analysis_segment(dict(version.analysis_snapshot or {})),
        "CONFIRMED LISTING EVIDENCE (do not invent claims):\n" + "\n".join(filter(None, [title_en, bullet_text])),
        f"VARIATION TYPE: {variation_type.get('name') or variation_type.get('code')}\n{str(variation_type.get('prompt_rule') or '').strip()}",
        f"MUST PRESERVE:\n{preserve}",
        f"ALLOWED TO CHANGE:\n{changes}",
        f"VARIATION PLAN: {plan.get('name') or plan.get('code')}\n{plan_prompt}",
        "Create a standalone e-commerce image. Keep all verified product identity and design details exact. Return no unsupported product feature or claim.",
    ]
    return "\n\n".join(section for section in sections if section and not section.endswith(":\n"))


async def build_and_save_variation_prompts(
    db: AsyncSession, *, project: ListingImageProject, version: ListingVersion,
    plans: list[dict[str, object]], user_id: str,
) -> list[dict[str, object]]:
    type_index = _type_index(dict(version.category_skill_snapshot or {}))
    current_config = dict(project.prompt_config or {})
    saved_plans = dict(current_config.get("variation_plans") or {})
    responses: list[dict[str, object]] = []
    for request_plan in plans:
        type_code = str(request_plan.get("type_code") or "")
        plan_code = str(request_plan.get("plan_code") or "")
        plan_key = str(request_plan.get("plan_key") or plan_code)
        custom = bool(request_plan.get("custom"))
        if type_code not in type_index:
            raise AppError("listing_variation.type_invalid", "选择了当前Skill不支持的裂变类型。", 422, {"type_code": type_code})
        if not CODE_PATTERN.fullmatch(plan_key):
            raise AppError("listing_variation.plan_key_invalid", "裂变方案标识无效。", 422)
        variation_type = type_index[type_code]
        configured = {
            str(item.get("code")): dict(item)
            for item in variation_type.get("plans") or []
            if isinstance(item, dict) and item.get("code") and item.get("enabled", True)
        }
        if custom:
            plan = {
                "code": plan_key,
                "name": str(request_plan.get("name") or "自定义方案").strip(),
                "prompt_template": "",
            }
        else:
            plan = configured.get(plan_code)
            if plan is None:
                raise AppError("listing_variation.plan_invalid", "选择了当前Skill不支持的裂变方案。", 422, {"plan_code": plan_code})
        item_code = f"variation:{type_code}:{plan_key}"
        if len(item_code) > 120:
            raise AppError("listing_variation.plan_key_invalid", "裂变方案标识过长。", 422)
        base_prompt = build_variation_prompt(version, variation_type=variation_type, plan=plan, custom_plan=custom)
        chinese = str(request_plan.get("chinese_instruction") or "").strip()
        item = await db.scalar(select(ImagePromptItem).where(
            ImagePromptItem.organization_id == project.organization_id,
            ImagePromptItem.project_type == "listing_image",
            ImagePromptItem.project_id == project.id,
            ImagePromptItem.item_code == item_code,
        ))
        if item is None:
            item = ImagePromptItem(
                organization_id=project.organization_id, project_type="listing_image", project_id=project.id,
                session_id=project.session_id, category_id=str(version.category_skill_snapshot.get("category_id") or "") or None,
                skill_id=str(version.category_skill_snapshot.get("skill_id") or "") or None,
                item_code=item_code, image_type=f"variation.{type_code}",
                original_english_prompt=base_prompt, chinese_editing_instruction=chinese,
                optimized_english_prompt=base_prompt,
                status="needs_optimization" if chinese or custom else "draft",
                current_version_number=0, state_version=0, last_saved_at=datetime.now(UTC),
                created_by=user_id, updated_by=user_id,
            )
            db.add(item)
            await db.flush()
        else:
            chinese_changed = item.chinese_editing_instruction != chinese
            item.original_english_prompt = base_prompt
            item.chinese_editing_instruction = chinese
            item.image_type = f"variation.{type_code}"
            item.updated_by = user_id
            item.last_saved_at = datetime.now(UTC)
            item.state_version += 1
            if chinese_changed or custom:
                item.status = "needs_optimization" if chinese or custom else "draft"
            elif item.status == "draft":
                item.optimized_english_prompt = base_prompt
        saved = {
            "item_code": item_code, "type_code": type_code,
            "type_name": str(variation_type.get("name") or type_code),
            "plan_code": str(plan.get("code") or plan_key), "plan_key": plan_key,
            "plan_name": str(plan.get("name") or plan_key), "custom": custom,
            "count": max(1, min(4, int(request_plan.get("count") or variation_type.get("default_count") or 1))),
            "recommended_aspect_ratio": str(variation_type.get("recommended_aspect_ratio") or "1:1"),
            "preserve_elements": list(variation_type.get("preserve_elements") or []),
            "allowed_changes": list(variation_type.get("allowed_changes") or []),
        }
        saved_plans[item_code] = saved
        responses.append({**saved, "base_prompt": base_prompt, "prompt_item_id": item.id, "prompt_status": item.status})
    project.prompt_config = {**current_config, "variation_plans": saved_plans}
    project.updated_by = user_id
    project.state_version += 1
    project.last_saved_at = datetime.now(UTC)
    return responses


async def create_quick_default_variation_group(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject, version: ListingVersion,
    workflow: ListingGenerationSession, user_id: str, planning_job_id: str,
) -> tuple[ListingImageTaskGroup | None, list[object], bool]:
    """Create the optional quick-mode variation group through existing JobBatch infrastructure."""
    config = variation_config(dict(version.category_skill_snapshot or {}))
    defaults = config.get("quick_defaults")
    defaults = defaults if isinstance(defaults, list) else []
    type_index = _type_index(dict(version.category_skill_snapshot or {}))
    drafts: list[dict[str, object]] = []
    for selection in defaults:
        if not isinstance(selection, dict):
            continue
        type_code = str(selection.get("type_code") or "")
        variation_type = type_index.get(type_code)
        if not variation_type:
            continue
        selected_codes = {str(item) for item in selection.get("plan_codes") or []}
        for plan in variation_type.get("plans") or []:
            if not isinstance(plan, dict) or plan.get("enabled", True) is False:
                continue
            code = str(plan.get("code") or "")
            if (selected_codes and code not in selected_codes) or (not selected_codes and not plan.get("default_selected")):
                continue
            drafts.append({
                "type_code": type_code, "plan_code": code, "plan_key": code,
                "name": str(plan.get("name") or code), "custom": False,
                "chinese_instruction": "", "count": max(1, min(4, int(selection.get("count") or 1))),
            })
    if not drafts:
        return None, [], False
    built = await build_and_save_variation_prompts(
        db, project=project, version=version, plans=drafts, user_id=user_id,
    )
    total = sum(int(item["count"]) for item in built)
    max_total = max(1, min(30, int(config.get("max_total_images") or 20)))
    if total > max_total:
        raise AppError("listing_variation.too_many_images", f"当前Skill快速裂变最多生成{max_total}张图片。", 422)
    model_code = await resolve_bound_model_code(
        db, organization_id=project.organization_id, operation_code="listing.generate", capability="image_edit",
    )
    items: list[BatchJobItemRequest] = []
    for item in built:
        for variation_version in range(1, int(item["count"]) + 1):
            items.append(BatchJobItemRequest(
                client_item_id=f"{item['item_code']}:{variation_version}:quick",
                prompt=str(item["base_prompt"]), reference_asset_ids=list(workflow.source_asset_ids or []),
                size="2048x2048", aspect_ratio=str(item["recommended_aspect_ratio"] or "1:1"),
                requested_width=2048, requested_height=2048, quality="high", output_format="png",
                metadata={
                    "workflow": "smart_image_variation", "quick_mode": True,
                    "output_project_id": project.id, "listing_session_id": workflow.id,
                    "listing_version_id": version.id, "listing_version_number": version.version_number,
                    "item_code": item["item_code"], "variation_type_code": item["type_code"],
                    "variation_type_name": item["type_name"], "variation_plan_code": item["plan_code"],
                    "variation_plan_name": item["plan_name"], "variation_version": variation_version,
                },
            ))
    batch, jobs, created = await submit_batch(
        db, settings, organization_id=project.organization_id, user_id=user_id,
        payload=JobBatchSubmitRequest(
            name=f"快速生成 · 智能图片裂变 · Listing V{version.version_number}", workspace_type="listing",
            operation_code="listing.generate", capability="image_edit", model_code=model_code,
            idempotency_key=f"quick-variations:{planning_job_id}", project_id=workflow.project_id,
            concurrency=min(3, len(items)), items=items,
        ),
    )
    snapshot = await build_input_asset_snapshot(
        db, organization_id=project.organization_id, product_asset_ids=list(workflow.source_asset_ids or []),
        reference_asset_ids=[], template_asset_ids=[], primary_asset_id=workflow.primary_asset_id,
    )
    group = await create_group_for_batch(
        db, project=project, batch=batch, version=version,
        selected_image_types=[str(item["item_code"]) for item in built],
        product_asset_ids=list(workflow.source_asset_ids or []), reference_asset_ids=[], template_asset_ids=[],
        input_asset_snapshot=snapshot, user_id=user_id,
    )
    group.group_name = f"快速生成 · 智能图片裂变 #{group.group_number}"
    for job in jobs:
        metadata = job.input_json.get("metadata")
        job.input_json = {
            **job.input_json,
            "metadata": {**(metadata if isinstance(metadata, dict) else {}), "listing_image_task_group_id": group.id},
        }
    return group, list(jobs), created
