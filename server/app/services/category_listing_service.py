from __future__ import annotations

import json
import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.listing_workflow import (
    CategoryImageTemplate,
    CategorySkill,
    CategorySkillVersion,
    ListingGenerationSession,
    ListingVersion,
    ProductAnalysisResult,
    ProductCategory,
    PromptDebugConfig,
)
from app.services.category_skill_service import attach_runtime_version, runtime_config
from app.models.tasks import (
    ApiKey,
    Job,
    JobBatch,
    ModelCapability,
    OperationResourcePool,
    Provider,
    ProviderModel,
    ResourcePool,
    ResourcePoolKey,
)


def _localized_text(value: object) -> dict[str, str]:
    if isinstance(value, dict):
        return {"en": str(value.get("en") or "").strip(), "zh": str(value.get("zh") or "").strip()}
    if isinstance(value, list):
        return {"en": ", ".join(str(item).strip() for item in value if str(item).strip()), "zh": ""}
    return {"en": str(value or "").strip(), "zh": ""}


def _localized_terms(value: object) -> dict[str, list[str]]:
    def terms(raw: object) -> list[str]:
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        if isinstance(raw, str):
            cleaned = raw.strip().strip("[]")
            return [item.strip().strip("'\"") for item in re.split(r"[,，\n]", cleaned) if item.strip().strip("'\"")]
        return []
    if isinstance(value, dict):
        return {"en": terms(value.get("en")), "zh": terms(value.get("zh"))}
    if isinstance(value, (list, str)):
        return {"en": terms(value), "zh": []}
    return {"en": [], "zh": []}


def normalize_bilingual_listing_content(value: object) -> dict[str, object]:
    """Accept both legacy English-only content and the current bilingual structure."""
    raw = value if isinstance(value, dict) else {}
    bullets = raw.get("bullet_points") or raw.get("bullets") or []
    normalized_bullets: list[dict[str, str]] = []
    if isinstance(bullets, list):
        for index, item in enumerate(bullets[:5]):
            localized = _localized_text(item)
            item_id = str(item.get("id") or f"bullet-{index + 1}") if isinstance(item, dict) else f"bullet-{index + 1}"
            normalized_bullets.append({"id": item_id, **localized})
    content: dict[str, object] = {
        "title": _localized_text(raw.get("title")),
        "bullet_points": normalized_bullets,
        "description": _localized_text(raw.get("description") or raw.get("product_description")),
        "search_terms": _localized_terms(raw.get("search_terms") or raw.get("search_keywords")),
        "selling_points": _localized_text(raw.get("selling_points")),
        "usage_scenarios": _localized_text(raw.get("usage_scenarios") or raw.get("applicable_scenarios")),
        "customization_notes": _localized_text(raw.get("customization_notes")),
        "cautions": _localized_text(raw.get("cautions") or raw.get("notes")),
        "a_plus_copy": raw.get("a_plus_copy") or raw.get("aplus_copy") or {},
    }
    return content


def listing_english_text(content: dict[str, object], field: str) -> str:
    value = content.get(field)
    if isinstance(value, dict):
        return str(value.get("en") or "").strip()
    return str(value or "").strip()


def parse_json_object(text: str) -> dict[str, object]:
    value = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        value = fenced.group(1)
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise AppError("listing.analysis_invalid", "AI 分析结果不是有效 JSON，请重新分析", 422)
        try:
            payload = json.loads(value[start:end + 1])
        except json.JSONDecodeError as error:
            raise AppError("listing.analysis_invalid", "AI 分析结果不是有效 JSON，请重新分析", 422) from error
    if not isinstance(payload, dict):
        raise AppError("listing.analysis_invalid", "AI 分析结果必须是 JSON 对象", 422)
    return payload


def normalize_analysis_payload(
    payload: dict[str, object], attribute_schema: list[dict[str, object]] | None = None,
) -> tuple[dict[str, object], dict[str, object], str]:
    raw_attributes = payload.get("analysis") or payload.get("attributes") or {}
    if not isinstance(raw_attributes, dict):
        raw_attributes = {}
    fields = attribute_schema or []
    attributes = {
        str(field.get("code")): raw_attributes.get(str(field.get("code")), field.get("default", ""))
        for field in fields if isinstance(field, dict) and field.get("code")
    } if fields else dict(raw_attributes)
    listing_content = normalize_bilingual_listing_content(payload.get("listing_content") or {})
    user_prompt = str(payload.get("suggested_user_prompt") or "").strip()
    return attributes, listing_content, user_prompt


def build_analysis_segment(
    attributes: dict[str, object], attribute_schema: list[dict[str, object]] | None = None,
) -> str:
    labels = {
        str(field.get("code")): str(field.get("prompt_label") or field.get("name") or field.get("code"))
        for field in (attribute_schema or []) if isinstance(field, dict) and field.get("code")
    }
    keys = [str(field.get("code")) for field in (attribute_schema or []) if isinstance(field, dict) and field.get("code")]
    if not keys:
        keys = list(attributes)
    lines: list[str] = []
    for key in keys:
        value = attributes.get(key)
        if value in (None, "", [], {}):
            continue
        rendered = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
        lines.append(f"- {labels.get(key, key.replace('_', ' '))}: {rendered}")
    return "Verified product analysis:\n" + ("\n".join(lines) if lines else "- No reliable visual attributes were extracted; rely strictly on the reference images.")


def available_image_types(
    skill: CategorySkill, template: CategoryImageTemplate, snapshot: dict[str, object] | None = None,
) -> list[str]:
    if snapshot:
        image_config = snapshot.get("image_prompt_config")
        image_types = image_config.get("image_types") if isinstance(image_config, dict) else None
        if isinstance(image_types, list):
            return [
                str(item.get("code")) for item in sorted(
                    (item for item in image_types if isinstance(item, dict)), key=lambda item: int(item.get("sort_order") or 0),
                ) if item.get("code") and item.get("enabled", True) and item.get("default_selected", False)
            ] or [str(item.get("code")) for item in image_types if isinstance(item, dict) and item.get("code") and item.get("enabled", True)]
    config = runtime_config(skill)
    image_config = config.get("image_prompt_config")
    configured_types = image_config.get("image_types") if isinstance(image_config, dict) else None
    if isinstance(configured_types, list) and configured_types:
        return [
            str(item.get("code")) for item in sorted(
                (item for item in configured_types if isinstance(item, dict)), key=lambda item: int(item.get("sort_order") or 0),
            ) if item.get("code") and item.get("enabled", True) and item.get("default_selected", False)
        ] or [str(item.get("code")) for item in configured_types if isinstance(item, dict) and item.get("code") and item.get("enabled", True)]
    configured = {
        str(item.get("code"))
        for item in (skill.image_types_config or [])
        if isinstance(item, dict) and item.get("code")
    }
    defaults = [str(item) for item in (template.default_image_types or [])]
    return [item for item in defaults if item in configured and item in (template.image_type_prompts or {})]


def build_image_prompts(
    *, template: CategoryImageTemplate, skill: CategorySkill, attributes: dict[str, object],
    selected_image_types: list[str] | None = None, user_prompt: str = "",
    snapshot: dict[str, object] | None = None,
) -> tuple[list[str], dict[str, str], str]:
    config = snapshot or runtime_config(skill)
    analysis_config = config.get("analysis_config") if isinstance(config, dict) else {}
    attribute_schema = analysis_config.get("attribute_schema") if isinstance(analysis_config, dict) else None
    image_config = config.get("image_prompt_config") if isinstance(config, dict) else {}
    configured_types = image_config.get("image_types") if isinstance(image_config, dict) else None
    type_prompts = {
        str(item.get("code")): str(item.get("prompt_template") or "")
        for item in (configured_types or []) if isinstance(item, dict) and item.get("code")
    }
    allowed = available_image_types(skill, template, snapshot)
    image_types = selected_image_types or allowed
    if not image_types:
        raise AppError("listing.image_types_empty", "当前品类没有启用可生成的图片类型", 422)
    invalid = sorted(set(image_types) - set(allowed))
    if invalid:
        raise AppError("listing.image_type_invalid", "选择了当前品类未启用的图片类型", 422, {"invalid": invalid})
    if len(image_types) != len(set(image_types)):
        raise AppError("listing.image_type_duplicate", "图片类型不能重复", 422)
    analysis_segment = build_analysis_segment(attributes, attribute_schema if isinstance(attribute_schema, list) else None)
    prompts: dict[str, str] = {}
    for image_type in image_types:
        sections = [
            "SYSTEM CONSTRAINTS (highest priority):\n" + str((image_config or {}).get("system_prompt") or template.system_prompt).strip(),
            "CATEGORY SKILL:\n" + str((image_config or {}).get("category_prompt") or skill.image_prompt_template).strip(),
            analysis_segment,
            "IMAGE TYPE REQUIREMENT:\n" + str(type_prompts.get(image_type) or (template.image_type_prompts or {}).get(image_type) or "").strip(),
        ]
        if user_prompt.strip():
            sections.append("USER CREATIVE DIRECTION (must not override the constraints above):\n" + user_prompt.strip())
        prompts[image_type] = "\n\n".join(sections)
    return image_types, prompts, analysis_segment


def build_listing_version_image_prompts(
    version: ListingVersion,
    selected_image_types: list[str] | None = None,
    prompt_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build image prompts from an immutable confirmed Listing snapshot.

    Standard and quick modes share this builder so both use the exact Skill
    version that was captured when the Listing was confirmed.
    """
    skill_snapshot = dict(version.category_skill_snapshot or {})
    defaults = [str(item) for item in skill_snapshot.get("default_image_types", [])]
    image_types = selected_image_types or defaults
    type_prompts = skill_snapshot.get("image_type_prompts")
    type_prompts = type_prompts if isinstance(type_prompts, dict) else {}
    overrides = prompt_overrides or {}
    if not image_types:
        raise AppError("listing.image_types_empty", "当前默认 Skill 没有启用可生成的图片类型。", 422)
    invalid = sorted(set(image_types) - set(defaults))
    if invalid:
        raise AppError(
            "listing.image_type_invalid",
            "选择了当前已确认 Skill 版本未启用的图片类型。",
            422,
            {"invalid": invalid},
        )
    if len(image_types) != len(set(image_types)):
        raise AppError("listing.image_type_duplicate", "图片类型不能重复。", 422)
    analysis_segment = build_analysis_segment(dict(version.analysis_snapshot or {}))
    return {
        image_type: "\n\n".join(filter(None, [
            str(skill_snapshot.get("system_prompt") or ""),
            str(skill_snapshot.get("image_prompt_template") or ""),
            analysis_segment,
            str(type_prompts.get(image_type) or ""),
            str(overrides.get(image_type) or ""),
        ]))
        for image_type in image_types
    }


def build_category_analysis_prompts(category: ProductCategory, skill: CategorySkill) -> tuple[str, str]:
    config = runtime_config(skill)
    analysis_config = dict(config.get("analysis_config") or {})
    listing_config = dict(config.get("listing_config") or {})
    translation_config = dict(config.get("translation_config") or {})
    schema = analysis_config.get("attribute_schema") if isinstance(analysis_config.get("attribute_schema"), list) else []
    output_analysis = {
        str(field.get("code")): field.get("default", "")
        for field in schema if isinstance(field, dict) and field.get("code")
    }
    system_prompt = str(analysis_config.get("system_prompt") or (
        "You are an Amazon US listing strategist and visual product analyst. "
        "Analyze only visible evidence in the supplied product images. Do not invent licensing, team, player, "
        "material composition, measurements or performance claims. Return one valid JSON object only."
    ))
    user_prompt = f"""
Selected category (confirmed by the user): {category.category_name} ({category.category_code})

Category analysis rules:
{analysis_config.get("task_prompt") or skill.analysis_prompt}

Title rules:
{(listing_config.get("title") or {}).get("task_prompt") or skill.listing_title_prompt}

Bullet rules:
{(listing_config.get("bullet_points") or {}).get("task_prompt") or skill.bullet_points_prompt}

A+ rules:
{(config.get("a_plus_config") or {}).get("system_prompt") or skill.a_plus_prompt}

Return exactly this JSON shape:
{{
  "analysis": {{
    {json.dumps(output_analysis, ensure_ascii=False)[1:-1]}
  }},
  "listing_content": {{
    "title": {{"en": "Amazon-ready US English title", "zh": "自然准确的中文运营说明"}},
    "bullet_points": [
      {{"id": "bullet-1", "en": "US English bullet 1", "zh": "中文卖点说明1"}},
      {{"id": "bullet-2", "en": "US English bullet 2", "zh": "中文卖点说明2"}},
      {{"id": "bullet-3", "en": "US English bullet 3", "zh": "中文卖点说明3"}},
      {{"id": "bullet-4", "en": "US English bullet 4", "zh": "中文卖点说明4"}},
      {{"id": "bullet-5", "en": "US English bullet 5", "zh": "中文卖点说明5"}}
    ],
    "description": {{"en": "US English product description", "zh": "中文产品说明"}},
    "search_terms": {{"en": ["backend search terms"], "zh": ["中文关键词说明"]}},
    "selling_points": {{"en": "verified selling points", "zh": "核心卖点"}},
    "usage_scenarios": {{"en": "verified use scenarios", "zh": "适用场景"}},
    "customization_notes": {{"en": "truthful customization notes", "zh": "定制说明"}},
    "cautions": {{"en": "necessary cautions", "zh": "注意事项"}},
    "a_plus_copy": {{"headline": "", "body": "", "sections": []}}
  }},
  "suggested_user_prompt": "Optional English creative direction for the image set"
}}

English fields are formal Amazon US copy. Chinese fields naturally explain the exact same meaning for Chinese
operators; do not use stiff word-for-word translation. Keep each title, bullet and section paired one-to-one.

Configured bilingual rules:
{json.dumps(translation_config, ensure_ascii=False)}
""".strip()
    return system_prompt, user_prompt


def build_listing_content_optimization_prompts(
    *, direction: str, listing_content: dict[str, object], category_name: str,
    analysis: dict[str, object], skill: CategorySkill,
) -> tuple[str, str]:
    if direction == "en_to_zh":
        task = (
            "Keep every English field unchanged. Rewrite every paired Chinese field as a natural, accurate explanation "
            "for Chinese e-commerce operators. Preserve one-to-one bullet IDs and return the full bilingual JSON."
        )
    elif direction == "zh_to_en":
        task = (
            "Treat the Chinese fields as the operator's latest requirements. Rewrite only the corresponding English "
            "fields into truthful Amazon US listing copy. Do not translate literally, invent features, add unsupported "
            "claims, or overwrite unrelated bullets. Preserve bullet IDs and return the full bilingual JSON."
        )
    else:
        raise AppError("listing.optimization_direction_invalid", "Listing 优化方向无效", 422)
    config = runtime_config(skill)
    translation = dict(config.get("translation_config") or {})
    listing = dict(config.get("listing_config") or {})
    system_prompt = (
        "You are a bilingual Amazon US listing editor. Return one JSON object only, using the exact input structure. "
        "English is publishable copy; Chinese is an operator-facing explanation. Never invent product evidence."
    )
    user_prompt = (
        f"Product category: {category_name}\n\nVerified analysis:\n{json.dumps(analysis, ensure_ascii=False)}\n\n"
        f"Category title rules:\n{(listing.get('title') or {}).get('task_prompt') or skill.listing_title_prompt}\n\n"
        f"Category bullet rules:\n{(listing.get('bullet_points') or {}).get('task_prompt') or skill.bullet_points_prompt}\n\n"
        f"Configured bilingual rules:\n{json.dumps(translation, ensure_ascii=False)}\n\n"
        f"Editing task:\n{task}\n\nCurrent bilingual listing JSON:\n"
        f"{json.dumps(normalize_bilingual_listing_content(listing_content), ensure_ascii=False)}"
    )
    return system_prompt, user_prompt


def build_category_recommendation_prompts(categories: list[ProductCategory]) -> tuple[str, str]:
    choices = "\n".join(f"- {item.category_code}: {item.category_name} — {item.description or ''}" for item in categories)
    return (
        "You classify an uploaded product into a user-visible Amazon listing category. Return valid JSON only. "
        "The recommendation is advisory and the user will make the final selection.",
        f"Choose only from these active categories:\n{choices}\n\n"
        "Return {\"category_code\":\"...\",\"confidence\":0.0,\"reason\":\"short Chinese reason\"}. "
        "If no category is a reliable match, return an empty category_code and confidence 0.",
    )


async def category_bundle(
    db: AsyncSession, category_id: str, *, active_only: bool = True,
) -> tuple[ProductCategory, CategorySkill, CategoryImageTemplate]:
    category = await db.get(ProductCategory, category_id)
    if category is None or (active_only and not category.is_active):
        raise AppError("listing.category_not_found", "所选品类不存在或已停用", 404)
    skill = await db.get(CategorySkill, category.default_skill_id) if category.default_skill_id else None
    if skill is None or skill.category_id != category.id or (active_only and not skill.is_active):
        skill = await db.scalar(select(CategorySkill).where(
            CategorySkill.category_id == category.id,
            *([CategorySkill.is_active.is_(True)] if active_only else []),
        ).order_by(CategorySkill.version.desc()).limit(1))
    template = await db.get(CategoryImageTemplate, category.default_image_template_id) if category.default_image_template_id else None
    if template is None or template.category_id != category.id or (active_only and not template.is_active):
        template = await db.scalar(select(CategoryImageTemplate).where(
            CategoryImageTemplate.category_id == category.id,
            *([CategoryImageTemplate.is_active.is_(True)] if active_only else []),
        ).order_by(CategoryImageTemplate.version.desc()).limit(1))
    if skill is None:
        raise AppError("listing.category_skill_missing", "当前品类没有可用的默认 Skill", 422)
    if template is None:
        raise AppError("listing.category_template_missing", "当前品类没有可用的图片模板", 422)
    version = await db.get(CategorySkillVersion, skill.default_published_version_id) if skill.default_published_version_id else None
    if version is None:
        version = await db.scalar(select(CategorySkillVersion).where(
            CategorySkillVersion.skill_id == skill.id,
            CategorySkillVersion.status == "published",
        ).order_by(CategorySkillVersion.version_number.desc()).limit(1))
    attach_runtime_version(skill, version)
    return category, skill, template


async def quick_category_bundle(
    db: AsyncSession, category_id: str,
) -> tuple[ProductCategory, CategorySkill, CategoryImageTemplate, CategorySkillVersion]:
    """Resolve only the category's explicitly configured published default Skill."""
    category = await db.get(ProductCategory, category_id)
    if category is None or not category.is_active:
        raise AppError("listing.category_not_found", "所选品类不存在或已停用。", 404)
    skill = await db.get(CategorySkill, category.default_skill_id) if category.default_skill_id else None
    if skill is None or skill.category_id != category.id or not skill.is_active:
        raise AppError("listing.quick_default_skill_missing", "当前品类尚未配置默认Skill。", 422)
    version = await db.get(CategorySkillVersion, skill.default_published_version_id) if skill.default_published_version_id else None
    if version is None or version.skill_id != skill.id or version.status != "published":
        raise AppError("listing.quick_default_skill_missing", "当前品类尚未配置默认Skill。", 422)
    template = await db.get(CategoryImageTemplate, category.default_image_template_id) if category.default_image_template_id else None
    if template is None or template.category_id != category.id or not template.is_active:
        raise AppError("listing.category_template_missing", "当前品类尚未配置可用的图片模板。", 422)
    attach_runtime_version(skill, version)
    return category, skill, template, version


async def resolve_bound_model_code(
    db: AsyncSession, *, organization_id: str, operation_code: str, capability: str,
    additional_capabilities: set[str] | None = None,
) -> str:
    rows = (await db.execute(
        select(ProviderModel)
        .select_from(OperationResourcePool)
        .join(ResourcePool, OperationResourcePool.resource_pool_id == ResourcePool.id)
        .join(ProviderModel, ResourcePool.model_id == ProviderModel.id)
        .join(Provider, ProviderModel.provider_id == Provider.id)
        .join(ResourcePoolKey, ResourcePoolKey.resource_pool_id == ResourcePool.id)
        .join(ApiKey, ResourcePoolKey.api_key_id == ApiKey.id)
        .where(
            OperationResourcePool.operation_code == operation_code,
            OperationResourcePool.required_capability == capability,
            OperationResourcePool.enabled.is_(True), ResourcePool.enabled.is_(True),
            ProviderModel.enabled.is_(True), Provider.enabled.is_(True), ResourcePoolKey.enabled.is_(True),
            ApiKey.enabled.is_(True), ApiKey.status != "disabled",
            or_(OperationResourcePool.organization_id == organization_id, OperationResourcePool.organization_id.is_(None)),
            or_(ResourcePool.organization_id == organization_id, ResourcePool.organization_id.is_(None)),
            or_(ApiKey.organization_id == organization_id, ApiKey.organization_id.is_(None)),
        )
        .order_by(OperationResourcePool.organization_id.desc(), OperationResourcePool.priority, ResourcePool.priority)
    )).scalars().unique().all()
    required = {capability, *(additional_capabilities or set())}
    for model in rows:
        capabilities = set((await db.scalars(select(ModelCapability.capability).where(
            ModelCapability.model_id == model.id,
        ))).all())
        if required.issubset(capabilities):
            return model.code
    raise AppError(
        "resource_pool.operation_not_bound",
        "当前功能没有绑定具备所需能力的可用模型资源池，请联系管理员",
        422,
        {"operation_code": operation_code, "capability": capability, "required": sorted(required)},
    )


async def reconcile_listing_session(db: AsyncSession, listing_session: ListingGenerationSession) -> None:
    if listing_session.planning_job_id and not listing_session.analysis_result_id:
        job = await db.get(Job, listing_session.planning_job_id)
        if job and job.status == "failed":
            listing_session.status = "analysis_failed"
            listing_session.error_message = job.error_message or "AI 商品分析失败"
        elif job and job.status == "succeeded":
            metadata = (job.result_json or {}).get("metadata")
            text = str(metadata.get("text") or "") if isinstance(metadata, dict) else ""
            payload = parse_json_object(text)
            snapshot = listing_session.category_skill_snapshot or {}
            analysis_config = snapshot.get("analysis_config") if isinstance(snapshot, dict) else {}
            attribute_schema = analysis_config.get("attribute_schema") if isinstance(analysis_config, dict) else None
            attributes, listing_content, suggested_user_prompt = normalize_analysis_payload(
                payload, attribute_schema if isinstance(attribute_schema, list) else None,
            )
            analysis = ProductAnalysisResult(
                organization_id=listing_session.organization_id,
                category_id=listing_session.category_id,
                skill_id=listing_session.skill_id,
                source_asset_ids=list(listing_session.source_asset_ids),
                structured_attributes=attributes,
                listing_content=listing_content,
                raw_response=text,
                created_by=listing_session.created_by,
                updated_by=listing_session.updated_by,
            )
            db.add(analysis)
            await db.flush()
            _, skill, template = await category_bundle(db, listing_session.category_id)
            image_types, prompts, analysis_segment = build_image_prompts(
                template=template, skill=skill, attributes=attributes, user_prompt=suggested_user_prompt,
                snapshot=snapshot if isinstance(snapshot, dict) and snapshot else None,
            )
            prompt = PromptDebugConfig(
                organization_id=listing_session.organization_id,
                session_id=listing_session.id,
                category_id=listing_session.category_id,
                skill_id=listing_session.skill_id,
                system_prompt_snapshot=template.system_prompt,
                skill_prompt_snapshot=skill.image_prompt_template,
                analysis_prompt_segment=analysis_segment,
                user_prompt=suggested_user_prompt,
                final_prompt=prompts[image_types[0]],
                final_prompts=prompts,
                created_by=listing_session.created_by,
                updated_by=listing_session.updated_by,
            )
            db.add(prompt)
            listing_session.analysis_result_id = analysis.id
            listing_session.listing_content = listing_content
            listing_session.status = "generated"
            listing_session.error_message = None
    if listing_session.image_batch_id and listing_session.status != "confirmed":
        batch = await db.get(JobBatch, listing_session.image_batch_id)
        if batch:
            if batch.status in {"succeeded", "partially_succeeded", "failed", "cancelled"}:
                listing_session.status = "generated" if batch.status == "succeeded" else batch.status
            elif listing_session.analysis_result_id:
                listing_session.status = "generating"


async def get_listing_session(
    db: AsyncSession, *, organization_id: str, session_id: str,
) -> ListingGenerationSession:
    value = await db.scalar(select(ListingGenerationSession).where(
        ListingGenerationSession.id == session_id,
        ListingGenerationSession.organization_id == organization_id,
    ).with_for_update())
    if value is None:
        raise AppError("listing.session_not_found", "Listing 品类工作流会话不存在或无权访问", 404)
    await reconcile_listing_session(db, value)
    return value
