"""add category-driven listing workflow

Revision ID: 0020_category_listing_workflow
Revises: 0019_batch_tryon_bulk_actions
"""

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision: str = "0020_category_listing_workflow"
down_revision: str | None = "0019_batch_tryon_bulk_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FOOTBALL_CATEGORY_ID = "00000000-0000-0000-0000-00000000f001"
FOOTBALL_SKILL_ID = "00000000-0000-0000-0000-00000000f101"
FOOTBALL_TEMPLATE_ID = "00000000-0000-0000-0000-00000000f201"


def upgrade() -> None:
    op.create_table(
        "product_categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("category_code", sa.String(100), nullable=False),
        sa.Column("category_name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("default_skill_id", sa.String(36), nullable=True),
        sa.Column("default_listing_template_id", sa.String(36), nullable=True),
        sa.Column("default_image_template_id", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("category_code", name="uq_product_categories_code"),
    )
    op.create_index("ix_product_categories_active_sort", "product_categories", ["is_active", "sort_order"])

    op.create_table(
        "category_skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("product_categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_name", sa.String(160), nullable=False),
        sa.Column("skill_code", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("analysis_prompt", sa.Text(), nullable=False),
        sa.Column("listing_title_prompt", sa.Text(), nullable=False),
        sa.Column("bullet_points_prompt", sa.Text(), nullable=False),
        sa.Column("a_plus_prompt", sa.Text(), nullable=False),
        sa.Column("image_prompt_template", sa.Text(), nullable=False),
        sa.Column("image_types_config", sa.JSON(), nullable=False),
        sa.Column("prompt_rules", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("category_id", "skill_code", "version", name="uq_category_skills_version"),
    )
    op.create_index("ix_category_skills_category_active", "category_skills", ["category_id", "is_active"])

    op.create_table(
        "category_image_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("product_categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_name", sa.String(160), nullable=False),
        sa.Column("template_code", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("image_type_prompts", sa.JSON(), nullable=False),
        sa.Column("default_image_types", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("category_id", "template_code", "version", name="uq_category_image_templates_version"),
    )
    op.create_index("ix_category_image_templates_category_active", "category_image_templates", ["category_id", "is_active"])
    op.create_foreign_key(
        "fk_product_categories_default_skill", "product_categories", "category_skills",
        ["default_skill_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_product_categories_default_image_template", "product_categories", "category_image_templates",
        ["default_image_template_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "product_analysis_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("category_skills.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_asset_ids", sa.JSON(), nullable=False),
        sa.Column("structured_attributes", sa.JSON(), nullable=False),
        sa.Column("listing_content", sa.JSON(), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_product_analysis_org_created", "product_analysis_results", ["organization_id", "created_at"])

    op.create_table(
        "listing_generation_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("category_skills.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("analysis_result_id", sa.String(36), sa.ForeignKey("product_analysis_results.id", ondelete="SET NULL"), nullable=True),
        sa.Column("planning_job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("image_batch_id", sa.String(36), sa.ForeignKey("job_batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="analyzing"),
        sa.Column("source_asset_ids", sa.JSON(), nullable=False),
        sa.Column("primary_asset_id", sa.String(36), sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("listing_content", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_listing_sessions_org_created", "listing_generation_sessions", ["organization_id", "created_at"])
    op.create_index("ix_listing_sessions_org_status", "listing_generation_sessions", ["organization_id", "status"])

    op.create_table(
        "prompt_debug_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("listing_generation_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("category_skills.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("system_prompt_snapshot", sa.Text(), nullable=False),
        sa.Column("skill_prompt_snapshot", sa.Text(), nullable=False),
        sa.Column("analysis_prompt_segment", sa.Text(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("final_prompt", sa.Text(), nullable=False),
        sa.Column("final_prompts", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", name="uq_prompt_debug_session"),
    )
    op.create_index("ix_prompt_debug_org_session", "prompt_debug_configs", ["organization_id", "session_id"])

    now = datetime.now(timezone.utc)
    category_table = sa.table(
        "product_categories",
        sa.column("id", sa.String), sa.column("category_code", sa.String), sa.column("category_name", sa.String),
        sa.column("description", sa.String), sa.column("is_active", sa.Boolean), sa.column("sort_order", sa.Integer),
        sa.column("default_skill_id", sa.String), sa.column("default_image_template_id", sa.String),
        sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(category_table, [{
        "id": FOOTBALL_CATEGORY_ID, "category_code": "football_jersey", "category_name": "橄榄球衣",
        "description": "美式橄榄球球衣、球迷服与比赛日运动上衣 Listing 工作流。",
        "is_active": True, "sort_order": 10, "default_skill_id": None,
        "default_image_template_id": None, "created_at": now, "updated_at": now,
    }])
    image_types = [
        {"code": "main", "name": "主图"}, {"code": "model", "name": "模特图"},
        {"code": "detail", "name": "细节图"}, {"code": "selling_point", "name": "卖点图"},
        {"code": "scene", "name": "场景图"}, {"code": "size_chart", "name": "尺寸图"},
        {"code": "customization", "name": "定制说明图"},
    ]
    skill_table = sa.table(
        "category_skills",
        sa.column("id", sa.String), sa.column("category_id", sa.String), sa.column("skill_name", sa.String),
        sa.column("skill_code", sa.String), sa.column("is_active", sa.Boolean), sa.column("version", sa.Integer),
        sa.column("analysis_prompt", sa.Text), sa.column("listing_title_prompt", sa.Text),
        sa.column("bullet_points_prompt", sa.Text), sa.column("a_plus_prompt", sa.Text),
        sa.column("image_prompt_template", sa.Text), sa.column("image_types_config", sa.JSON),
        sa.column("prompt_rules", sa.JSON), sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(skill_table, [{
        "id": FOOTBALL_SKILL_ID, "category_id": FOOTBALL_CATEGORY_ID,
        "skill_name": "橄榄球衣 Listing 基础 Skill", "skill_code": "football_jersey_listing", "is_active": True,
        "version": 1,
        "analysis_prompt": "Analyze the uploaded American football jersey images. Extract gender, fit, sleeve_type, neck_type, main_color, secondary_color, graphic_elements, number_presence, name_presence, fabric_style, style_tags and scene_tags. Do not invent details that are not visible.",
        "listing_title_prompt": "Create a concise US English Amazon title for an American football jersey using only verified attributes. Avoid unsupported team, league, player, fabric or licensing claims.",
        "bullet_points_prompt": "Create exactly five US English bullets covering jersey design, fit, visible graphic details, use occasions and care/customization cautions without unsupported claims.",
        "a_plus_prompt": "Create concise A+ copy for an American football jersey with a sportswear tone, clear section headings and no unverifiable performance or licensing claims.",
        "image_prompt_template": "Emphasize authentic American football jersey styling, athletic energy, team-uniform proportions and faithful number/name graphics. Model images should use a natural Western sportswear look. Scene images may use a football field or game-day atmosphere. Detail images should highlight neckline, cuffs, print and fabric appearance.",
        "image_types_config": image_types,
        "prompt_rules": {"preserve_text": True, "preserve_numbers": True, "preserve_colors": True, "marketplace": "amazon_us"},
        "created_at": now, "updated_at": now,
    }])
    template_table = sa.table(
        "category_image_templates",
        sa.column("id", sa.String), sa.column("category_id", sa.String), sa.column("template_name", sa.String),
        sa.column("template_code", sa.String), sa.column("version", sa.Integer), sa.column("is_active", sa.Boolean),
        sa.column("system_prompt", sa.Text), sa.column("image_type_prompts", sa.JSON),
        sa.column("default_image_types", sa.JSON), sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(template_table, [{
        "id": FOOTBALL_TEMPLATE_ID, "category_id": FOOTBALL_CATEGORY_ID,
        "template_name": "橄榄球衣七图 Listing 模板", "template_code": "football_jersey_7_images",
        "version": 1, "is_active": True,
        "system_prompt": "Preserve the uploaded garment exactly. Do not alter or hallucinate text, numbers, names, graphics, stripes, colors, neckline, sleeves, hem or silhouette. Create a clean, commercially usable Amazon listing image with the garment as the clear subject. Avoid unrelated products, misleading accessories, watermarks, logos not present in the reference, and unverifiable claims.",
        "image_type_prompts": {
            "main": "MAIN IMAGE: isolated product-only presentation on pure white background, centered, full garment visible, no model, no props, no text overlay.",
            "model": "MODEL IMAGE: realistic sportswear model wearing the exact jersey, natural athletic stance, full front design readable, clean commercial lighting.",
            "detail": "DETAIL IMAGE: premium close-up composition emphasizing neckline, sleeve finish, print edges and fabric texture while preserving every visible graphic.",
            "selling_point": "SELLING POINT IMAGE: structured e-commerce infographic composition with clear visual callouts; do not invent technical specifications.",
            "scene": "SCENE IMAGE: authentic American football or game-day lifestyle atmosphere with the exact jersey remaining dominant and readable.",
            "size_chart": "SIZE IMAGE: clean size-guide layout using editable placeholder zones; do not invent numeric measurements not provided by the user.",
            "customization": "CUSTOMIZATION IMAGE: explain visible name/number customization areas with neutral placeholders; do not add unprovided personal names or numbers.",
        },
        "default_image_types": ["main", "model", "detail", "selling_point", "scene", "size_chart", "customization"],
        "created_at": now, "updated_at": now,
    }])
    op.execute(sa.update(category_table).where(category_table.c.id == FOOTBALL_CATEGORY_ID).values(
        default_skill_id=FOOTBALL_SKILL_ID, default_image_template_id=FOOTBALL_TEMPLATE_ID,
    ))


def downgrade() -> None:
    op.drop_index("ix_prompt_debug_org_session", table_name="prompt_debug_configs")
    op.drop_table("prompt_debug_configs")
    op.drop_index("ix_listing_sessions_org_status", table_name="listing_generation_sessions")
    op.drop_index("ix_listing_sessions_org_created", table_name="listing_generation_sessions")
    op.drop_table("listing_generation_sessions")
    op.drop_index("ix_product_analysis_org_created", table_name="product_analysis_results")
    op.drop_table("product_analysis_results")
    op.drop_constraint("fk_product_categories_default_image_template", "product_categories", type_="foreignkey")
    op.drop_constraint("fk_product_categories_default_skill", "product_categories", type_="foreignkey")
    op.drop_index("ix_category_image_templates_category_active", table_name="category_image_templates")
    op.drop_table("category_image_templates")
    op.drop_index("ix_category_skills_category_active", table_name="category_skills")
    op.drop_table("category_skills")
    op.drop_index("ix_product_categories_active_sort", table_name="product_categories")
    op.drop_table("product_categories")
