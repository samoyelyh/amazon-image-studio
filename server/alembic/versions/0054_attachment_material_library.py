"""add attachment personal material library

Revision ID: 0054_attachment_materials
Revises: 0053_attachment_timestamps
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0054_attachment_materials"
down_revision: str | None = "0053_attachment_timestamps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachment_material_sets",
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("category_key", sa.String(100), nullable=False),
        sa.Column("category_name", sa.String(160), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("source_session_id", sa.String(36), nullable=True),
        sa.Column("source_project_id", sa.String(36), nullable=True),
        sa.Column("cover_asset_id", sa.String(36), nullable=True),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("selected_module_snapshot", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_session_id"], ["listing_generation_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_project_id"], ["listing_image_projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cover_asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attachment_material_sets_owner_updated", "attachment_material_sets", ["organization_id", "owner_user_id", "updated_at"])
    op.create_index("ix_attachment_material_sets_source_project", "attachment_material_sets", ["organization_id", "source_project_id"])
    op.create_index("ix_attachment_material_sets_category_status", "attachment_material_sets", ["organization_id", "category_key", "status"])

    op.create_table(
        "attachment_material_set_versions",
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("material_set_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("selected_module_snapshot", sa.JSON(), nullable=False),
        sa.Column("module_count", sa.Integer(), nullable=False),
        sa.Column("target_module_count", sa.Integer(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["material_set_id"], ["attachment_material_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("material_set_id", "version_number", name="uq_attachment_material_version_number"),
    )
    op.create_index(
        "ix_attachment_material_version_hash",
        "attachment_material_set_versions",
        ["material_set_id", "content_hash"],
        unique=False,
    )
    op.create_index("ix_attachment_material_versions_org_set", "attachment_material_set_versions", ["organization_id", "material_set_id", "version_number"])

    op.create_table(
        "attachment_material_items",
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("material_version_id", sa.String(36), nullable=False),
        sa.Column("module_key", sa.String(60), nullable=False),
        sa.Column("source_output_id", sa.String(36), nullable=True),
        sa.Column("source_asset_id", sa.String(36), nullable=False),
        sa.Column("source_task_group_id", sa.String(36), nullable=True),
        sa.Column("source_job_id", sa.String(36), nullable=True),
        sa.Column("plan_version_id", sa.String(36), nullable=True),
        sa.Column("prompt_version_id", sa.String(36), nullable=True),
        sa.Column("reference_understanding_id", sa.String(36), nullable=True),
        sa.Column("product_composition_version_id", sa.String(36), nullable=True),
        sa.Column("aspect_ratio", sa.String(20), nullable=False),
        sa.Column("output_size", sa.String(40), nullable=False),
        sa.Column("generation_mode", sa.String(30), nullable=False),
        sa.Column("product_mode", sa.String(20), nullable=False),
        sa.Column("is_manual_revision", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["material_version_id"], ["attachment_material_set_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_output_id"], ["generated_outputs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_task_group_id"], ["listing_image_task_groups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plan_version_id"], ["attachment_workbench_plan_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["attachment_workbench_plan_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reference_understanding_id"], ["attachment_reference_understandings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_composition_version_id"], ["attachment_product_composition_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("material_version_id", "module_key", name="uq_attachment_material_item_module"),
    )
    op.create_index("ix_attachment_material_items_org_version", "attachment_material_items", ["organization_id", "material_version_id"])
    op.create_index("ix_attachment_material_items_asset", "attachment_material_items", ["source_asset_id"])
    op.create_index("ix_attachment_material_items_output", "attachment_material_items", ["source_output_id"])

    op.create_foreign_key(
        "fk_attachment_material_sets_current_version",
        "attachment_material_sets",
        "attachment_material_set_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_attachment_material_sets_current_version", "attachment_material_sets", type_="foreignkey")
    op.drop_table("attachment_material_items")
    op.drop_table("attachment_material_set_versions")
    op.drop_table("attachment_material_sets")
