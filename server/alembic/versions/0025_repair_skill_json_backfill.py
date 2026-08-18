"""repair legacy JSON backfill for category skill versions

Revision ID: 0025_repair_skill_json
Revises: 0024_workbench_skill_versions
"""

from __future__ import annotations

from collections.abc import Sequence
import json

from alembic import op
import sqlalchemy as sa


revision: str = "0025_repair_skill_json"
down_revision: str | None = "0024_workbench_skill_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _decode(value: object, fallback: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value if value is not None else fallback


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("""
        SELECT v.id AS version_id, v.skill_id, v.version_number,
               v.analysis_config, v.listing_config, v.translation_config, v.a_plus_config,
               s.skill_name, s.skill_code, s.analysis_prompt, s.listing_title_prompt,
               s.bullet_points_prompt, s.a_plus_prompt, s.image_prompt_template,
               s.image_types_config, s.prompt_rules, s.marketplace, s.language,
               c.id AS category_id, c.category_code, c.category_name,
               t.id AS template_id, t.template_name, t.system_prompt,
               t.image_type_prompts, t.default_image_types
        FROM category_skill_versions v
        JOIN category_skills s ON s.id = v.skill_id
        JOIN product_categories c ON c.id = s.category_id
        LEFT JOIN category_image_templates t ON t.id = c.default_image_template_id
    """)).mappings().all()
    update_version = sa.text("""
        UPDATE category_skill_versions
        SET image_prompt_config=:image_config, full_config_snapshot=:full_config
        WHERE id=:version_id
    """).bindparams(
        sa.bindparam("image_config", type_=sa.JSON()),
        sa.bindparam("full_config", type_=sa.JSON()),
    )
    update_session = sa.text("""
        UPDATE listing_generation_sessions
        SET category_skill_snapshot=:snapshot
        WHERE skill_version_id=:version_id
    """).bindparams(sa.bindparam("snapshot", type_=sa.JSON()))
    for row in rows:
        configured = _decode(row.get("image_types_config"), [])
        prompts = _decode(row.get("image_type_prompts"), {})
        defaults = _decode(row.get("default_image_types"), [])
        default_codes = set(defaults if isinstance(defaults, list) else [])
        image_types: list[dict[str, object]] = []
        for index, raw in enumerate(configured if isinstance(configured, list) else []):
            if not isinstance(raw, dict) or not raw.get("code"):
                continue
            code = str(raw["code"])
            image_types.append({
                **raw, "code": code, "enabled": bool(raw.get("enabled", True)),
                "default_selected": code in default_codes,
                "sort_order": int(raw.get("sort_order") or ((index + 1) * 10)),
                "prompt_template": str((prompts if isinstance(prompts, dict) else {}).get(code) or raw.get("prompt_template") or ""),
            })
        image_config = {
            "system_prompt": str(row.get("system_prompt") or ""),
            "category_prompt": row["image_prompt_template"],
            "prompt_rules": _decode(row.get("prompt_rules"), {}),
            "image_types": image_types,
        }
        full = {
            "analysis_config": _decode(row["analysis_config"], {}),
            "listing_config": _decode(row["listing_config"], {}),
            "translation_config": _decode(row["translation_config"], {}),
            "image_prompt_config": image_config,
            "a_plus_config": _decode(row["a_plus_config"], {}),
        }
        bind.execute(update_version, {"image_config": image_config, "full_config": full, "version_id": row["version_id"]})
        snapshot = {
            "category_id": row["category_id"], "category_code": row["category_code"], "category_name": row["category_name"],
            "skill_id": row["skill_id"], "skill_name": row["skill_name"], "skill_code": row["skill_code"],
            "skill_version_id": row["version_id"], "skill_version": int(row["version_number"]),
            "marketplace": row["marketplace"], "language": row["language"], **full,
            "analysis_prompt": row["analysis_prompt"], "listing_title_prompt": row["listing_title_prompt"],
            "bullet_points_prompt": row["bullet_points_prompt"], "a_plus_prompt": row["a_plus_prompt"],
            "image_prompt_template": row["image_prompt_template"],
            "prompt_rules": _decode(row.get("prompt_rules"), {}),
            "image_template_id": row.get("template_id"), "image_template_name": row.get("template_name"),
            "system_prompt": str(row.get("system_prompt") or ""),
            "image_type_prompts": prompts if isinstance(prompts, dict) else {},
            "default_image_types": defaults if isinstance(defaults, list) else [],
        }
        bind.execute(update_session, {"snapshot": snapshot, "version_id": row["version_id"]})


def downgrade() -> None:
    # This migration only repairs values produced by 0024; schema is unchanged.
    pass
