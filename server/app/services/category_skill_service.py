from __future__ import annotations

import copy
import re
from typing import Any

from app.models.listing_workflow import CategoryImageTemplate, CategorySkill, CategorySkillVersion, ProductCategory


ALLOWED_ATTRIBUTE_TYPES = {
    "text", "textarea", "boolean", "select", "multiselect", "number", "color", "tags", "json",
}
ALLOWED_TEMPLATE_ROOTS = {"product_analysis", "category", "marketplace", "brand_name"}
VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)*)\s*}}")


def complete_config(
    *, analysis_config: dict[str, object], listing_config: dict[str, object],
    translation_config: dict[str, object], image_prompt_config: dict[str, object],
    a_plus_config: dict[str, object],
) -> dict[str, object]:
    return {
        "analysis_config": copy.deepcopy(analysis_config),
        "listing_config": copy.deepcopy(listing_config),
        "translation_config": copy.deepcopy(translation_config),
        "image_prompt_config": copy.deepcopy(image_prompt_config),
        "a_plus_config": copy.deepcopy(a_plus_config),
    }


def version_config(version: CategorySkillVersion) -> dict[str, object]:
    return complete_config(
        analysis_config=dict(version.analysis_config or {}),
        listing_config=dict(version.listing_config or {}),
        translation_config=dict(version.translation_config or {}),
        image_prompt_config=dict(version.image_prompt_config or {}),
        a_plus_config=dict(version.a_plus_config or {}),
    )


def attach_runtime_version(skill: CategorySkill, version: CategorySkillVersion | None) -> None:
    if version is None:
        return
    skill._runtime_skill_version_id = version.id
    skill._runtime_skill_version_number = version.version_number
    skill._runtime_skill_config = version_config(version)


def runtime_config(skill: CategorySkill) -> dict[str, object]:
    configured = getattr(skill, "_runtime_skill_config", None)
    if isinstance(configured, dict):
        return configured
    return {
        "analysis_config": {"task_prompt": skill.analysis_prompt, "attribute_schema": []},
        "listing_config": {
            "title": {"task_prompt": skill.listing_title_prompt},
            "bullet_points": {"task_prompt": skill.bullet_points_prompt},
        },
        "translation_config": {},
        "image_prompt_config": {
            "category_prompt": skill.image_prompt_template,
            "prompt_rules": dict(skill.prompt_rules or {}),
            "image_types": list(skill.image_types_config or []),
        },
        "a_plus_config": {"system_prompt": skill.a_plus_prompt, "modules": []},
    }


def build_skill_snapshot(
    category: ProductCategory, skill: CategorySkill, template: CategoryImageTemplate,
    version: CategorySkillVersion | None = None,
) -> dict[str, object]:
    config = version_config(version) if version else runtime_config(skill)
    image_config = dict(config.get("image_prompt_config") or {})
    image_config.setdefault("system_prompt", template.system_prompt)
    if not image_config.get("image_types"):
        defaults = set(template.default_image_types or [])
        image_config["image_types"] = [
            {
                **dict(item), "enabled": True, "default_selected": str(item.get("code")) in defaults,
                "prompt_template": str((template.image_type_prompts or {}).get(str(item.get("code"))) or ""),
            }
            for item in (skill.image_types_config or []) if isinstance(item, dict) and item.get("code")
        ]
    config["image_prompt_config"] = image_config
    return {
        "category_id": category.id, "category_code": category.category_code, "category_name": category.category_name,
        "skill_id": skill.id, "skill_name": skill.skill_name, "skill_code": skill.skill_code,
        "skill_version_id": version.id if version else getattr(skill, "_runtime_skill_version_id", None),
        "skill_version": version.version_number if version else getattr(skill, "_runtime_skill_version_number", skill.version),
        "marketplace": skill.marketplace, "language": skill.language,
        **copy.deepcopy(config),
        # Compatibility fields used by existing confirmed Listing versions.
        "analysis_prompt": str((config.get("analysis_config") or {}).get("task_prompt") or skill.analysis_prompt),
        "listing_title_prompt": str(((config.get("listing_config") or {}).get("title") or {}).get("task_prompt") or skill.listing_title_prompt),
        "bullet_points_prompt": str(((config.get("listing_config") or {}).get("bullet_points") or {}).get("task_prompt") or skill.bullet_points_prompt),
        "a_plus_prompt": str((config.get("a_plus_config") or {}).get("system_prompt") or skill.a_plus_prompt),
        "image_prompt_template": str(image_config.get("category_prompt") or skill.image_prompt_template),
        "prompt_rules": dict(image_config.get("prompt_rules") or skill.prompt_rules or {}),
        "image_template_id": template.id, "image_template_name": template.template_name,
        "system_prompt": str(image_config.get("system_prompt") or template.system_prompt),
        "image_type_prompts": {
            str(item.get("code")): str(item.get("prompt_template") or "")
            for item in image_config.get("image_types", []) if isinstance(item, dict) and item.get("code")
        },
        "default_image_types": [
            str(item.get("code")) for item in image_config.get("image_types", [])
            if isinstance(item, dict) and item.get("code") and item.get("enabled", True) and item.get("default_selected", False)
        ] or list(template.default_image_types or []),
    }


def _all_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_all_strings(item))
        return values
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_all_strings(item))
        return values
    return []


def validate_skill_configuration(config: dict[str, object]) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    analysis = config.get("analysis_config")
    listing = config.get("listing_config")
    translation = config.get("translation_config")
    image = config.get("image_prompt_config")
    a_plus = config.get("a_plus_config")
    if not isinstance(analysis, dict):
        errors.append("商品分析配置必须是 JSON 对象")
        analysis = {}
    schema = analysis.get("attribute_schema")
    if not isinstance(schema, list) or not schema:
        errors.append("商品分析至少需要一个属性字段")
        schema = []
    codes: set[str] = set()
    for index, field in enumerate(schema):
        if not isinstance(field, dict):
            errors.append(f"属性字段 {index + 1} 必须是对象")
            continue
        code = str(field.get("code") or "").strip()
        field_type = str(field.get("type") or "text")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", code):
            errors.append(f"属性字段编码无效：{code or index + 1}")
        elif code in codes:
            errors.append(f"属性字段编码重复：{code}")
        codes.add(code)
        if field_type not in ALLOWED_ATTRIBUTE_TYPES:
            errors.append(f"属性 {code or index + 1} 的类型不支持：{field_type}")
        if field_type in {"select", "multiselect"} and not isinstance(field.get("allowed_values"), list):
            errors.append(f"属性 {code or index + 1} 必须配置允许值")
    if not isinstance(listing, dict) or not isinstance(listing.get("title"), dict) or not isinstance(listing.get("bullet_points"), dict):
        errors.append("Listing 配置必须包含标题和五点描述规则")
    if not isinstance(translation, dict) or not str(translation.get("english_listing_rules") or "").strip() or not str(translation.get("chinese_explanation_rules") or "").strip():
        errors.append("中英文规则不完整")
    image_types = image.get("image_types") if isinstance(image, dict) else None
    if not isinstance(image_types, list) or not any(isinstance(item, dict) and item.get("enabled", True) for item in image_types):
        errors.append("至少需要一个启用的图片类型")
    if isinstance(image, dict):
        # Imported lazily to keep the core Skill module independent from the
        # Listing orchestration services used by the prompt builder.
        from app.services.smart_image_variation_service import validate_variation_skill_config
        errors.extend(validate_variation_skill_config(image))
    if not isinstance(a_plus, dict):
        errors.append("A+ 配置必须是 JSON 对象")

    variables = sorted({match for text in _all_strings(config) for match in VARIABLE_PATTERN.findall(text)})
    for variable in variables:
        root, *parts = variable.split(".")
        if root not in ALLOWED_TEMPLATE_ROOTS:
            errors.append(f"未定义的模板变量：{variable}")
        elif root == "product_analysis" and (not parts or parts[0] not in codes):
            errors.append(f"模板变量引用了不存在的分析字段：{variable}")
    if len(schema) > 80:
        warnings.append("分析字段超过 80 个，可能增加模型解析失败率")
    return errors, warnings, variables


def draft_preview(config: dict[str, object], sample_analysis: dict[str, object], product_information: str) -> dict[str, Any]:
    analysis = dict(config.get("analysis_config") or {})
    schema = analysis.get("attribute_schema") if isinstance(analysis.get("attribute_schema"), list) else []
    structured = {
        str(field.get("code")): sample_analysis.get(str(field.get("code")), field.get("default", ""))
        for field in schema if isinstance(field, dict) and field.get("code")
    }
    listing = dict(config.get("listing_config") or {})
    image = dict(config.get("image_prompt_config") or {})
    system_prompt = str(analysis.get("system_prompt") or "")
    user_prompt = "\n\n".join(filter(None, [str(analysis.get("task_prompt") or ""), product_information.strip()]))
    image_prompts = {
        str(item.get("code")): "\n\n".join(filter(None, [
            str(image.get("system_prompt") or ""), str(image.get("category_prompt") or ""),
            str(item.get("prompt_template") or ""), product_information.strip(),
        ]))
        for item in image.get("image_types", [])
        if isinstance(item, dict) and item.get("code") and item.get("enabled", True)
    }
    bilingual = {
        "title": {"en": str((listing.get("title") or {}).get("task_prompt") or ""), "zh": "测试预览：发布前请使用真实图片运行模型测试"},
        "bullet_points": [], "description": {"en": "", "zh": ""},
    }
    return {
        "system_prompt": system_prompt, "user_prompt": user_prompt,
        "structured_analysis_preview": structured, "bilingual_listing_preview": bilingual,
        "image_prompts": image_prompts,
    }
