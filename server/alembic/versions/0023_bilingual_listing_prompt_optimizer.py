"""add bilingual listing image prompt optimizer

Revision ID: 0023_prompt_optimizer
Revises: 0022_listing_split_timestamps
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_prompt_optimizer"
down_revision = "0022_listing_split_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_prompt_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_type", sa.String(40), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("listing_generation_sessions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("category_skills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("item_code", sa.String(120), nullable=False),
        sa.Column("image_type", sa.String(120), nullable=False),
        sa.Column("original_english_prompt", sa.Text(), nullable=False),
        sa.Column("chinese_editing_instruction", sa.Text(), nullable=False),
        sa.Column("optimized_english_prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("current_version_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("optimizer_job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("optimizer_model", sa.String(120), nullable=True),
        sa.Column("optimized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("organization_id", "project_type", "project_id", "item_code", name="uq_image_prompt_items_project_code"),
    )
    op.create_index("ix_image_prompt_items_project", "image_prompt_items", ["organization_id", "project_type", "project_id"])
    op.create_index("ix_image_prompt_items_status", "image_prompt_items", ["organization_id", "status"])
    op.create_table(
        "image_prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_item_id", sa.String(36), sa.ForeignKey("image_prompt_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("original_english_prompt", sa.Text(), nullable=False),
        sa.Column("chinese_editing_instruction", sa.Text(), nullable=False),
        sa.Column("optimized_english_prompt", sa.Text(), nullable=False),
        sa.Column("optimizer_model", sa.String(120), nullable=True),
        sa.Column("optimizer_job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("optimized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("optimized_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("prompt_item_id", "version_number", name="uq_image_prompt_versions_item_number"),
        sa.UniqueConstraint("optimizer_job_id", name="uq_image_prompt_versions_optimizer_job"),
    )
    op.create_index("ix_image_prompt_versions_item", "image_prompt_versions", ["prompt_item_id", "version_number"])


def downgrade() -> None:
    op.drop_table("image_prompt_versions")
    op.drop_table("image_prompt_items")
