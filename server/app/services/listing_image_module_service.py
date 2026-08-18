from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core.errors import AppError


COMMON_PRODUCT_TRUTH_CONSTRAINTS = """PRODUCT TRUTH CONSTRAINTS (highest priority):
The supplied product reference images are the highest-priority source for product appearance.
Do not redesign the product. Do not change its colors, structure, silhouette, collar, sleeves, cuffs, shoulders, logos, numbers, text, typography, graphics, prints, patterns, seams, or panel construction.
Creative freedom is allowed only for the scene, environment, model, lighting, composition, atmosphere, and props, subject to the module rules.
If confirmed Listing information visibly conflicts with the reference images, flag the conflict instead of deciding or inventing a resolution.
Never add unsupported performance, material, licensing, certification, waterproof, UV protection, moisture-wicking, quick-dry, antibacterial, high-stretch, professional-grade, official-team, league, or event claims.
Do not introduce any brand, team, league, event logo, or other intellectual-property element that is not supplied in the product references."""


STANDARD_LISTING_IMAGE_MODULES: tuple[dict[str, Any], ...] = (
    {
        "code": "pure_white", "name": "纯白底图", "sort_order": 10,
        "objective": "清晰、准确、完整展示商品本身，真实性优先。",
        "high_weight_fields": ["product_name", "product_category", "main_color", "secondary_color", "collar_type", "sleeve_type", "cuff_design", "shoulder_design", "hem_design", "front_design", "back_design", "logo", "graphic", "pattern", "custom_fields"],
        "low_weight_fields": ["gift_scenarios", "usage_scenarios"],
        "recommended_aspect_ratio": "1:1",
        "recommendation_strategy": "pure_white",
        "prompt_template": """Create a professional Amazon product presentation on a pure #FFFFFF background. Show only the exact product, centered, fully visible, naturally proportioned, and occupying the main image area. Use clean commercial lighting and a restrained natural shadow. Clearly render only verified fabric texture, seams, collar, cuffs, shoulder construction, print, and other visible details. Do not add a model, props, decorative elements, accessories, text overlays, or background color.""",
    },
    {
        "code": "custom_process", "name": "定制流程图", "sort_order": 20,
        "objective": "解释当前商品真实支持的定制字段与完成流程。",
        "high_weight_fields": ["product_name", "customizable", "custom_fields", "custom_name", "custom_number", "custom_shoulder_number", "custom_sleeve_number", "custom_text"],
        "low_weight_fields": ["gift_scenarios"],
        "recommended_aspect_ratio": "1:1",
        "recommendation_strategy": "custom_process",
        "prompt_template": """Create a clear modern four-step product customization infographic: 1) Choose Your Style, 2) Enter Your Custom Information, 3) Preview Your Product, 4) Complete Your Order. The only verified customizable fields are: {custom_fields}. Show only these fields and never add unsupported name, back-number, shoulder-number, sleeve-number, or custom-text controls. Use the exact product reference in the product display and keep all displayed custom values typographically consistent.""",
    },
    {
        "code": "stadium_scene", "name": "观赛场景图", "sort_order": 30,
        "objective": "展示比赛日、球场、球迷和观赛环境中的使用价值。",
        "high_weight_fields": ["product_name", "sport_type", "target_customer", "usage_scenarios", "main_color", "style", "custom_fields"],
        "low_weight_fields": ["gift_scenarios"],
        "recommended_aspect_ratio": "4:5",
        "recommendation_strategy": "stadium_scene",
        "prompt_template": """Create a premium game-day spectator advertising image set in {sport_scene}. Models may watch, celebrate, or support a team naturally. The environment, crowd, seating, flags, lighting, and camera distance may be designed creatively, but the exact supplied product must remain dominant and readable. Do not force text overlays such as TEAM SPIRIT or GAME DAY and do not introduce real team or league branding.""",
    },
    {
        "code": "gift_scene", "name": "礼品场景图", "sort_order": 40,
        "objective": "表达商品作为个性化礼物的仪式感与送礼价值。",
        "high_weight_fields": ["product_name", "gender", "age_group", "customizable", "gift_scenarios", "sport_type", "target_customer", "custom_fields"],
        "low_weight_fields": ["usage_scenarios"],
        "recommended_aspect_ratio": "4:5",
        "recommendation_strategy": "gift_scene",
        "prompt_template": """Create a premium personalized sports-gift scene for these selected occasions: {recommendations}. Use tasteful gift boxes, wrapping paper, ribbon, cards, warm lights, and restrained sport-related props. Communicate personalization and commemorative value only when supported by the verified customization fields ({custom_fields}). Never add unsupported customization capabilities.""",
    },
    {
        "code": "detail_display", "name": "细节展示图", "sort_order": 50,
        "objective": "从真实结构与Listing卖点中选择3–5个最有购买决策价值的细节。",
        "high_weight_fields": ["product_name", "product_features", "material", "fabric_texture", "collar_type", "sleeve_type", "cuff_design", "shoulder_design", "hem_design", "logo", "graphic", "pattern", "custom_fields"],
        "low_weight_fields": ["gift_scenarios", "usage_scenarios"],
        "recommended_aspect_ratio": "1:1",
        "recommendation_strategy": "detail_display",
        "prompt_template": """Create a professional Amazon detail-display image with 3–5 truthful close-ups. Prioritize these verified detail directions: {recommendations}. Every close-up must come from the actual product references. Do not invent fabric technology, breathability, stitching, perforation, logos, graphics, or functional benefits. Keep all details consistent with the full product.""",
    },
    {
        "code": "casual_scene", "name": "休闲场景图", "sort_order": 60,
        "objective": "展示日常穿搭、社交与生活方式，不与体育场观赛场景重复。",
        "high_weight_fields": ["product_name", "gender", "age_group", "style", "target_customer", "usage_scenarios", "main_color"],
        "low_weight_fields": ["gift_scenarios"],
        "recommended_aspect_ratio": "4:5",
        "recommendation_strategy": "casual_scene",
        "prompt_template": """Create a natural premium casual lifestyle image for the verified target customer. Recommended non-stadium settings: {recommendations}. Show authentic daily wear, social use, and relaxed styling without a stiff studio pose. The setting may be creative but must not overpower the exact product, and it must not duplicate a stadium game-day scene.""",
    },
)

STANDARD_MODULE_CODES = tuple(item["code"] for item in STANDARD_LISTING_IMAGE_MODULES)

FIELD_LABELS = {
    "asin": "ASIN", "sku": "SKU", "product_category": "产品分类", "sport_type": "运动类型",
    "product_name": "产品名称", "brand": "品牌", "gender": "适用性别", "age_group": "年龄段",
    "main_color": "主色", "secondary_color": "辅色", "style": "风格", "material": "材质",
    "fabric_texture": "面料纹理", "breathability": "透气性", "collar_type": "领型",
    "sleeve_type": "袖型", "sleeve_length": "袖长", "cuff_design": "袖口设计",
    "shoulder_design": "肩部设计", "hem_design": "下摆设计", "fit_type": "版型",
    "front_design": "正面设计", "back_design": "背面设计", "sleeve_design": "袖部设计",
    "logo": "Logo", "graphic": "图案", "pattern": "印花/纹样", "customizable": "支持定制",
    "custom_fields": "定制字段", "custom_name": "定制姓名", "custom_number": "定制号码",
    "custom_shoulder_number": "肩部号码", "custom_sleeve_number": "袖部号码", "custom_text": "定制文字",
    "target_customer": "目标人群", "usage_scenarios": "使用场景", "gift_scenarios": "礼品场景",
    "product_features": "产品卖点",
}


def _localized(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("en") or value.get("zh") or "").strip()
    return ""


def _list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("；", ";").replace("，", ",").split(",") if item.strip()]
    return []


def _first(source: dict[str, object], *keys: str, default: object = "") -> object:
    for key in keys:
        value = source.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _listing_text(listing: dict[str, object], key: str) -> str:
    return _localized(listing.get(key))


def normalize_listing_product_profile(
    analysis: dict[str, object], listing: dict[str, object], skill_snapshot: dict[str, object],
) -> dict[str, object]:
    """Normalize old and new category schemas without changing stored product data."""
    title = _listing_text(listing, "title")
    category_name = str(skill_snapshot.get("category_name") or "")
    category_code = str(skill_snapshot.get("category_code") or "")
    sport_type = _first(analysis, "sport_type", default=("American Football" if "football" in category_code else ""))
    custom_fields = _list(analysis.get("custom_fields"))
    if not custom_fields:
        if analysis.get("name_presence") or analysis.get("custom_name"):
            custom_fields.append("Player Name")
        if analysis.get("number_presence") or analysis.get("custom_number"):
            custom_fields.append("Back Number")
        if analysis.get("shoulder_number_presence") or analysis.get("custom_shoulder_number"):
            custom_fields.append("Shoulder Number")
        if analysis.get("sleeve_number_presence") or analysis.get("custom_sleeve_number"):
            custom_fields.append("Sleeve Number")
    customizable = bool(analysis.get("customizable") or custom_fields or _listing_text(listing, "customization_notes"))
    usage = _list(_first(analysis, "usage_scenarios", "scene_tags"))
    gift = _list(analysis.get("gift_scenarios"))
    if not gift and customizable:
        gift = ["Birthday", "Christmas", "Game Day Gift", "Team Gift"]
    bullets = listing.get("bullet_points")
    bullet_text = [_localized(item) for item in bullets] if isinstance(bullets, list) else []
    product_features = _list(analysis.get("product_features"))
    if not product_features:
        product_features = [item for item in [_listing_text(listing, "selling_points"), *bullet_text] if item]
    graphic_elements = _list(_first(analysis, "graphic", "graphic_elements"))
    profile: dict[str, object] = {
        "asin": _first(analysis, "asin"), "sku": _first(analysis, "sku"),
        "product_category": _first(analysis, "product_category", "jersey_style", default=category_name),
        "sport_type": sport_type, "product_name": _first(analysis, "product_name", default=title),
        "brand": _first(analysis, "brand", "brand_name"), "gender": _first(analysis, "gender"),
        "age_group": _first(analysis, "age_group"), "main_color": _first(analysis, "main_color"),
        "secondary_color": _first(analysis, "secondary_color"), "style": _first(analysis, "style", "jersey_style", "style_tags"),
        "material": _first(analysis, "material", "fabric_style"),
        "fabric_texture": _first(analysis, "fabric_texture", "fabric_style"),
        "breathability": _first(analysis, "breathability"), "collar_type": _first(analysis, "collar_type", "neck_type"),
        "sleeve_type": _first(analysis, "sleeve_type"), "sleeve_length": _first(analysis, "sleeve_length"),
        "cuff_design": _first(analysis, "cuff_design"), "shoulder_design": _first(analysis, "shoulder_design"),
        "hem_design": _first(analysis, "hem_design"), "fit_type": _first(analysis, "fit_type", "fit"),
        "front_design": _first(analysis, "front_design", default=graphic_elements),
        "back_design": _first(analysis, "back_design"), "sleeve_design": _first(analysis, "sleeve_design"),
        "logo": _first(analysis, "logo"), "graphic": graphic_elements, "pattern": _first(analysis, "pattern", "graphic_elements"),
        "customizable": customizable, "custom_fields": custom_fields,
        "custom_name": _first(analysis, "custom_name", "name_value"),
        "custom_number": _first(analysis, "custom_number", "number_value"),
        "custom_shoulder_number": _first(analysis, "custom_shoulder_number"),
        "custom_sleeve_number": _first(analysis, "custom_sleeve_number"), "custom_text": _first(analysis, "custom_text"),
        "target_customer": _first(analysis, "target_customer", "target_audience"),
        "usage_scenarios": usage or _list(_listing_text(listing, "usage_scenarios")),
        "gift_scenarios": gift, "product_features": product_features,
        "marketplace": skill_snapshot.get("marketplace") or "amazon_us",
        "information_conflicts": _list(_first(analysis, "information_conflicts", "conflicts")),
    }
    return profile


def _render(value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{key}: {_render(item)}" for key, item in value.items())
    return str(value or "").strip()


def _stadium_for_sport(sport: str) -> str:
    lowered = sport.lower()
    if "american" in lowered or "football" in lowered:
        return "an American football stadium or stadium seating area"
    if "soccer" in lowered:
        return "a soccer stadium"
    if "baseball" in lowered:
        return "a baseball stadium"
    if "basketball" in lowered:
        return "a basketball arena"
    return "a venue that accurately matches the verified sport type"


def _detail_recommendations(profile: dict[str, object]) -> list[str]:
    candidates = [
        ("fabric_texture", "面料纹理"), ("collar_type", "领口结构"), ("shoulder_design", "肩部结构"),
        ("cuff_design", "袖口设计"), ("sleeve_type", "袖型"), ("graphic", "图案与印花"),
        ("custom_fields", "定制印花区域"), ("hem_design", "下摆结构"), ("material", "材质观感"),
    ]
    selected = [label for key, label in candidates if profile.get(key) not in (None, "", [], {})]
    return selected[:5] or ["产品整体结构", "参考图中清晰可见的真实局部"]


def _recommendations(module: dict[str, object], profile: dict[str, object]) -> list[str]:
    configured = _list(module.get("recommendations"))
    if configured:
        return configured
    strategy = str(module.get("recommendation_strategy") or "")
    if strategy == "pure_white":
        return ["纯白 #FFFFFF 背景", "商品居中完整展示", "商业摄影灯光与自然阴影"]
    if strategy == "custom_process":
        fields = _list(profile.get("custom_fields"))
        return ["Choose Your Style", "Enter Your Custom Information", "Preview Your Product", "Complete Your Order", *fields]
    if strategy == "stadium_scene":
        return [_stadium_for_sport(str(profile.get("sport_type") or "")), "Game Day观赛氛围", "产品清晰可见"]
    if strategy == "gift_scene":
        return _list(profile.get("gift_scenarios")) or ["Birthday", "Christmas", "Game Day Gift"]
    if strategy == "detail_display":
        return _detail_recommendations(profile)
    if strategy == "casual_scene":
        return ["城市街头", "朋友聚会", "周末出行", "咖啡店或休闲酒吧", "校园或户外休闲"]
    return []


class _PromptContext(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def _module_prompt(
    code: str, profile: dict[str, object], recommendations: list[str], module: dict[str, object],
) -> str:
    high_fields = [str(value) for value in module.get("high_weight_fields", [])]
    low_fields = [str(value) for value in module.get("low_weight_fields", [])]
    high_facts = "\n".join(
        f"- {FIELD_LABELS.get(key, key)}: {_render(profile.get(key))}"
        for key in high_fields if profile.get(key) not in (None, "", [], {})
    ) or "- No additional verified high-priority text attributes; rely on the supplied product images."
    low_facts = "\n".join(
        f"- {FIELD_LABELS.get(key, key)}: {_render(profile.get(key))}"
        for key in low_fields if profile.get(key) not in (None, "", [], {})
    ) or "- None."
    custom_fields = _render(profile.get("custom_fields")) or "No verified customization fields"
    context = _PromptContext(
        {key: _render(value) for key, value in profile.items()},
        custom_fields=custom_fields,
        recommendations=", ".join(recommendations),
        sport_scene=_stadium_for_sport(str(profile.get("sport_type") or "")),
    )
    template = str(module.get("prompt_template") or "Create a truthful Amazon secondary image for the selected module.")
    instruction = template.format_map(context)
    additional_constraints = _list(module.get("additional_constraints"))
    if additional_constraints:
        instruction += "\nAdditional module constraints:\n- " + "\n- ".join(additional_constraints)
    conflict_text = _render(profile.get("information_conflicts"))
    conflict = f"\n\nPRODUCT INFORMATION CONFLICTS TO FLAG: {conflict_text}" if conflict_text else ""
    return (
        f"MODULE: {module.get('name')}\n"
        f"MODULE OBJECTIVE: {module.get('objective')}\n\n"
        f"HIGH-PRIORITY VERIFIED PRODUCT FIELDS:\n{high_facts}\n\n"
        f"LOW-WEIGHT CREATIVE CONTEXT:\n{low_facts}\n\n"
        f"MODULE CREATIVE REQUIREMENT:\n{instruction}{conflict}\n\n"
        f"{COMMON_PRODUCT_TRUTH_CONSTRAINTS}"
    )


def build_listing_image_modules(
    *, analysis_snapshot: dict[str, object], listing_snapshot: dict[str, object],
    skill_snapshot: dict[str, object], selected_codes: list[str] | None = None,
    attribute_overrides: dict[str, dict[str, object]] | None = None,
    prompt_overrides: dict[str, str] | None = None,
) -> tuple[list[dict[str, object]], dict[str, str]]:
    configured = deepcopy(STANDARD_LISTING_IMAGE_MODULES)
    image_config = skill_snapshot.get("image_prompt_config")
    image_config = image_config if isinstance(image_config, dict) else {}
    custom_modules = image_config.get("listing_image_modules")
    custom_index = {
        str(item.get("code")): item for item in (custom_modules or [])
        if isinstance(item, dict) and item.get("code") in STANDARD_MODULE_CODES
    }
    modules = [{**item, **dict(custom_index.get(str(item["code"])) or {})} for item in configured]
    selected = selected_codes or list(STANDARD_MODULE_CODES)
    invalid = sorted(set(selected) - set(STANDARD_MODULE_CODES))
    if invalid:
        raise AppError("listing.image_module_invalid", "选择了不支持的Listing副图模块。", 422, {"invalid": invalid})
    if len(selected) != len(set(selected)):
        raise AppError("listing.image_type_duplicate", "图片模块不能重复。", 422)
    base_profile = normalize_listing_product_profile(analysis_snapshot, listing_snapshot, skill_snapshot)
    attribute_overrides = attribute_overrides or {}
    prompt_overrides = prompt_overrides or {}
    specs: list[dict[str, object]] = []
    prompts: dict[str, str] = {}
    for module in sorted(modules, key=lambda item: int(item.get("sort_order") or 0)):
        code = str(module["code"])
        profile = {**base_profile, **dict(attribute_overrides.get(code) or {})}
        recommendations = _recommendations(module, profile)
        high_fields = [str(value) for value in module.get("high_weight_fields", [])]
        low_fields = [str(value) for value in module.get("low_weight_fields", [])]
        used = [{
            "code": field, "label": FIELD_LABELS.get(field, field), "value": profile.get(field, ""),
            "weight": "high" if field in high_fields else "low",
            "source": "module_override" if field in (attribute_overrides.get(code) or {}) else "product_profile",
        } for field in dict.fromkeys(high_fields + low_fields)]
        available = not (code == "custom_process" and not bool(profile.get("customizable")))
        reason = "" if available else "当前商品没有已确认的可定制字段，不能生成定制流程图。"
        prompt = _module_prompt(code, profile, recommendations, module)
        if str(prompt_overrides.get(code) or "").strip():
            prompt += "\n\nOPERATOR CREATIVE OVERRIDE (cannot override product truth constraints):\n" + str(prompt_overrides[code]).strip()
        specs.append({**module, "available": available, "unavailable_reason": reason, "used_attributes": used,
                      "recommendations": recommendations, "prompt": prompt, "reference_role": "product_reference"})
        if code in selected:
            if not available:
                raise AppError("listing.image_module_unavailable", reason, 422, {"module": code})
            prompts[code] = prompt
    if not prompts:
        raise AppError("listing.image_types_empty", "请至少选择一个Listing副图模块。", 422)
    return specs, prompts
