"""add persisted Listing image task groups

Revision ID: 0026_listing_image_groups
Revises: 0025_repair_skill_json
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0026_listing_image_groups"
down_revision: str | None = "0025_repair_skill_json"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listing_image_task_groups",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("listing_image_project_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("listing_version_id", sa.String(length=36), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("category_skill_version_id", sa.String(length=36), nullable=True),
        sa.Column("job_batch_id", sa.String(length=36), nullable=True),
        sa.Column("source_task_group_id", sa.String(length=36), nullable=True),
        sa.Column("group_number", sa.Integer(), nullable=False),
        sa.Column("group_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("product_image_asset_ids", sa.JSON(), nullable=False),
        sa.Column("reference_asset_ids", sa.JSON(), nullable=False),
        sa.Column("template_asset_ids", sa.JSON(), nullable=False),
        sa.Column("input_asset_snapshot", sa.JSON(), nullable=False),
        sa.Column("selected_image_types", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("updated_by", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_image_project_id"], ["listing_image_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["listing_generation_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_version_id"], ["listing_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["category_id"], ["product_categories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["category_skill_version_id"], ["category_skill_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_batch_id"], ["job_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_task_group_id"], ["listing_image_task_groups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_image_project_id", "group_number", name="uq_listing_image_task_groups_number"),
        sa.UniqueConstraint("job_batch_id", name="uq_listing_image_task_groups_batch"),
    )
    op.create_index("ix_listing_image_task_groups_org_project", "listing_image_task_groups", ["organization_id", "listing_image_project_id", "created_at"])
    op.create_index("ix_listing_image_task_groups_org_status", "listing_image_task_groups", ["organization_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_listing_image_task_groups_org_status", table_name="listing_image_task_groups")
    op.drop_index("ix_listing_image_task_groups_org_project", table_name="listing_image_task_groups")
    op.drop_table("listing_image_task_groups")
