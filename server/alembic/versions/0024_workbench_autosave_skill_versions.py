"""add workbench autosave versions and category skill versioning

Revision ID: 0024_workbench_skill_versions
Revises: 0023_prompt_optimizer
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "0024_workbench_skill_versions"
down_revision: str | None = "0023_prompt_optimizer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_ATTRIBUTE_SCHEMA = [
    {"code": "gender", "name": "适用性别", "type": "select", "required": False, "allowed_values": ["male", "female", "unisex"], "default": "", "operator_editable": True, "sort_order": 10},
    {"code": "age_group", "name": "适用年龄", "type": "text", "required": False, "default": "", "operator_editable": True, "sort_order": 20},
    {"code": "fit", "name": "版型", "type": "text", "required": False, "default": "", "operator_editable": True, "sort_order": 30},
    {"code": "jersey_style", "name": "球衣风格", "type": "text", "required": False, "default": "", "operator_editable": True, "sort_order": 40},
    {"code": "sleeve_type", "name": "袖型", "type": "text", "required": False, "default": "", "operator_editable": True, "sort_order": 50},
    {"code": "neck_type", "name": "领型", "type": "text", "required": False, "default": "", "operator_editable": True, "sort_order": 60},
    {"code": "main_color", "name": "主色", "type": "color", "required": False, "default": "", "operator_editable": True, "sort_order": 70},
    {"code": "secondary_color", "name": "辅色", "type": "color", "required": False, "default": "", "operator_editable": True, "sort_order": 80},
    {"code": "graphic_elements", "name": "图案元素", "type": "tags", "required": False, "default": [], "operator_editable": True, "sort_order": 90},
    {"code": "number_presence", "name": "是否有号码", "type": "boolean", "required": False, "default": False, "operator_editable": True, "sort_order": 100},
    {"code": "number_value", "name": "号码内容", "type": "text", "required": False, "default": "", "operator_editable": True, "sort_order": 110},
    {"code": "name_presence", "name": "是否有姓名", "type": "boolean", "required": False, "default": False, "operator_editable": True, "sort_order": 120},
    {"code": "name_value", "name": "姓名内容", "type": "text", "required": False, "default": "", "operator_editable": True, "sort_order": 130},
    {"code": "team_style", "name": "球队风格", "type": "text", "required": False, "default": "", "operator_editable": True, "sort_order": 140},
    {"code": "fabric_style", "name": "面料观感", "type": "text", "required": False, "default": "", "operator_editable": True, "sort_order": 150},
    {"code": "customizable", "name": "是否支持定制", "type": "boolean", "required": False, "default": False, "operator_editable": True, "sort_order": 160},
    {"code": "style_tags", "name": "风格标签", "type": "tags", "required": False, "default": [], "operator_editable": True, "sort_order": 170},
    {"code": "scene_tags", "name": "场景标签", "type": "tags", "required": False, "default": [], "operator_editable": True, "sort_order": 180},
    {"code": "target_audience", "name": "目标人群", "type": "text", "required": False, "default": "", "operator_editable": True, "sort_order": 190},
    {"code": "usage_scenarios", "name": "使用场景", "type": "tags", "required": False, "default": [], "operator_editable": True, "sort_order": 200},
]


def _json_value(value: object, fallback: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value if value is not None else fallback


def _image_types(skill_config: object, template_prompts: object, defaults: object) -> list[dict[str, object]]:
    skill_config = _json_value(skill_config, [])
    template_prompts = _json_value(template_prompts, {})
    defaults = _json_value(defaults, [])
    configured = skill_config if isinstance(skill_config, list) else []
    prompts = template_prompts if isinstance(template_prompts, dict) else {}
    default_codes = set(defaults if isinstance(defaults, list) else [])
    rows: list[dict[str, object]] = []
    for index, raw in enumerate(configured):
        if not isinstance(raw, dict) or not raw.get("code"):
            continue
        code = str(raw["code"])
        rows.append({
            **raw,
            "code": code,
            "enabled": bool(raw.get("enabled", True)),
            "default_selected": code in default_codes,
            "sort_order": int(raw.get("sort_order") or ((index + 1) * 10)),
            "prompt_template": str(prompts.get(code) or raw.get("prompt_template") or ""),
        })
    return rows


def upgrade() -> None:
    op.add_column("category_skills", sa.Column("description", sa.String(1000), nullable=True))
    op.add_column("category_skills", sa.Column("marketplace", sa.String(40), nullable=False, server_default="amazon_us"))
    op.add_column("category_skills", sa.Column("language", sa.String(40), nullable=False, server_default="en-US_zh-CN"))
    op.add_column("category_skills", sa.Column("status", sa.String(40), nullable=False, server_default="draft"))

    op.create_table(
        "category_skill_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("category_skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("analysis_config", sa.JSON(), nullable=False),
        sa.Column("listing_config", sa.JSON(), nullable=False),
        sa.Column("translation_config", sa.JSON(), nullable=False),
        sa.Column("image_prompt_config", sa.JSON(), nullable=False),
        sa.Column("a_plus_config", sa.JSON(), nullable=False),
        sa.Column("full_config_snapshot", sa.JSON(), nullable=False),
        sa.Column("change_summary", sa.String(1000), nullable=False, server_default=""),
        sa.Column("source_version_id", sa.String(36), sa.ForeignKey("category_skill_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("published_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("skill_id", "version_number", name="uq_category_skill_versions_number"),
    )
    op.create_index("ix_category_skill_versions_skill_status", "category_skill_versions", ["skill_id", "status"])
    op.add_column("category_skills", sa.Column("default_published_version_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_category_skills_default_published_version", "category_skills", "category_skill_versions",
        ["default_published_version_id"], ["id"], ondelete="SET NULL",
    )

    op.add_column("listing_generation_sessions", sa.Column("skill_version_id", sa.String(36), nullable=True))
    op.add_column("listing_generation_sessions", sa.Column("category_skill_snapshot", sa.JSON(), nullable=True))
    op.add_column("listing_generation_sessions", sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("listing_generation_sessions", sa.Column("current_step", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("listing_generation_sessions", sa.Column("last_saved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_listing_sessions_skill_version", "listing_generation_sessions", "category_skill_versions",
        ["skill_version_id"], ["id"], ondelete="SET NULL",
    )

    for table_name in ("listing_image_projects", "a_plus_projects", "image_prompt_items"):
        op.add_column(table_name, sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"))
        op.add_column(table_name, sa.Column("last_saved_at", sa.DateTime(timezone=True), nullable=True))

    bind = op.get_bind()
    skills = bind.execute(sa.text("SELECT * FROM category_skills ORDER BY category_id, version")).mappings().all()
    categories = {
        row["id"]: row for row in bind.execute(sa.text("SELECT * FROM product_categories")).mappings().all()
    }
    templates = {
        row["id"]: row for row in bind.execute(sa.text("SELECT * FROM category_image_templates")).mappings().all()
    }
    now = datetime.now(timezone.utc)
    version_by_skill: dict[str, tuple[str, dict[str, object]]] = {}
    for row in skills:
        category = categories.get(row["category_id"], {})
        template = templates.get(category.get("default_image_template_id"), {})
        analysis_config = {
            "system_prompt": "You are an Amazon US listing strategist and visual product analyst. Analyze only visible evidence and return valid JSON.",
            "task_prompt": row["analysis_prompt"],
            "attribute_schema": DEFAULT_ATTRIBUTE_SCHEMA,
            "output_format": "bilingual_listing_json",
        }
        listing_config = {
            "title": {"task_prompt": row["listing_title_prompt"], "target_language": "en-US", "max_characters": 200},
            "bullet_points": {"task_prompt": row["bullet_points_prompt"], "target_language": "en-US", "count": 5},
            "description": {"task_prompt": "Create a truthful Amazon product description from verified attributes."},
            "search_terms": {"task_prompt": "Create relevant backend search terms without trademarks or unsupported claims."},
            "selling_points": {"task_prompt": "Summarize only verified core selling points."},
            "customization_notes": {"task_prompt": "Describe customization only when supported by visible or supplied evidence."},
            "cautions": {"task_prompt": "State necessary product cautions without inventing specifications."},
        }
        translation_config = {
            "english_listing_rules": "Generate formal, truthful Amazon US English copy.",
            "chinese_explanation_rules": "Accurately explain the English meaning in natural Chinese for operators; add no new claims.",
            "zh_to_en_rules": "Treat Chinese edits as requirements and rewrite corresponding English copy without literal translation or invention.",
            "compliance_rules": "Keep Chinese and English fields paired one-to-one and preserve all verified facts.",
        }
        image_prompt_config = {
            "system_prompt": str(template.get("system_prompt") or ""),
            "category_prompt": row["image_prompt_template"],
            "prompt_rules": _json_value(row.get("prompt_rules"), {}),
            "image_types": _image_types(row.get("image_types_config"), template.get("image_type_prompts"), template.get("default_image_types")),
        }
        a_plus_config = {
            "system_prompt": row["a_plus_prompt"],
            "modules": [
                {"code": "brand_banner", "name": "品牌横幅", "enabled": True, "sort_order": 10, "copy_prompt": row["a_plus_prompt"], "image_prompt": "Create a cohesive e-commerce brand hero banner."},
                {"code": "key_benefits", "name": "产品卖点", "enabled": True, "sort_order": 20, "copy_prompt": row["a_plus_prompt"], "image_prompt": "Visualize verified product benefits."},
                {"code": "detail_story", "name": "细节展示", "enabled": True, "sort_order": 30, "copy_prompt": row["a_plus_prompt"], "image_prompt": "Show faithful product details."},
                {"code": "lifestyle", "name": "场景展示", "enabled": True, "sort_order": 40, "copy_prompt": row["a_plus_prompt"], "image_prompt": "Create a commercially attractive lifestyle scene."},
            ],
        }
        full = {
            "analysis_config": analysis_config, "listing_config": listing_config,
            "translation_config": translation_config, "image_prompt_config": image_prompt_config,
            "a_plus_config": a_plus_config,
        }
        version_id = str(uuid.uuid4())
        bind.execute(sa.text("""
            INSERT INTO category_skill_versions
            (id, skill_id, version_number, status, analysis_config, listing_config, translation_config,
             image_prompt_config, a_plus_config, full_config_snapshot, change_summary, source_version_id,
             published_by, published_at, created_by, created_at, updated_at)
            VALUES
            (:id, :skill_id, :version_number, 'published', :analysis_config, :listing_config, :translation_config,
             :image_prompt_config, :a_plus_config, :full_config_snapshot, :change_summary, NULL,
             NULL, :published_at, :created_by, :created_at, :updated_at)
        """).bindparams(
            sa.bindparam("analysis_config", type_=sa.JSON()),
            sa.bindparam("listing_config", type_=sa.JSON()),
            sa.bindparam("translation_config", type_=sa.JSON()),
            sa.bindparam("image_prompt_config", type_=sa.JSON()),
            sa.bindparam("a_plus_config", type_=sa.JSON()),
            sa.bindparam("full_config_snapshot", type_=sa.JSON()),
        ), {
            "id": version_id, "skill_id": row["id"], "version_number": int(row.get("version") or 1),
            "analysis_config": analysis_config, "listing_config": listing_config,
            "translation_config": translation_config, "image_prompt_config": image_prompt_config,
            "a_plus_config": a_plus_config, "full_config_snapshot": full,
            "change_summary": "Migrated from legacy category Skill configuration",
            "published_at": now, "created_by": row.get("created_by"), "created_at": row.get("created_at") or now,
            "updated_at": now,
        })
        bind.execute(sa.text("UPDATE category_skills SET default_published_version_id=:version_id, status='published' WHERE id=:skill_id"), {"version_id": version_id, "skill_id": row["id"]})
        snapshot = {
            "category_id": row["category_id"], "category_code": category.get("category_code"),
            "category_name": category.get("category_name"), "skill_id": row["id"],
            "skill_name": row["skill_name"], "skill_code": row["skill_code"],
            "skill_version_id": version_id, "skill_version": int(row.get("version") or 1),
            **full,
        }
        version_by_skill[row["id"]] = (version_id, snapshot)

    session_rows = bind.execute(sa.text("SELECT id, skill_id FROM listing_generation_sessions")).mappings().all()
    update_session = sa.text("""
        UPDATE listing_generation_sessions
        SET skill_version_id=:version_id, category_skill_snapshot=:snapshot, last_saved_at=updated_at
        WHERE id=:session_id
    """).bindparams(sa.bindparam("snapshot", type_=sa.JSON()))
    for row in session_rows:
        version_data = version_by_skill.get(row["skill_id"])
        if version_data:
            bind.execute(update_session, {"version_id": version_data[0], "snapshot": version_data[1], "session_id": row["id"]})


def downgrade() -> None:
    for table_name in ("image_prompt_items", "a_plus_projects", "listing_image_projects"):
        op.drop_column(table_name, "last_saved_at")
        op.drop_column(table_name, "state_version")
    op.drop_constraint("fk_listing_sessions_skill_version", "listing_generation_sessions", type_="foreignkey")
    op.drop_column("listing_generation_sessions", "last_saved_at")
    op.drop_column("listing_generation_sessions", "current_step")
    op.drop_column("listing_generation_sessions", "state_version")
    op.drop_column("listing_generation_sessions", "category_skill_snapshot")
    op.drop_column("listing_generation_sessions", "skill_version_id")
    op.drop_constraint("fk_category_skills_default_published_version", "category_skills", type_="foreignkey")
    op.drop_column("category_skills", "default_published_version_id")
    op.drop_index("ix_category_skill_versions_skill_status", table_name="category_skill_versions")
    op.drop_table("category_skill_versions")
    op.drop_column("category_skills", "status")
    op.drop_column("category_skills", "language")
    op.drop_column("category_skills", "marketplace")
    op.drop_column("category_skills", "description")
