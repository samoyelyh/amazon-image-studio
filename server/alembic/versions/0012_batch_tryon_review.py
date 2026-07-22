"""add batch try-on review items and immutable versions

Revision ID: 0012_batch_review
Revises: 0011_job_duration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0012_batch_review"
down_revision: str | None = "0011_job_duration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batch_tryon_review_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("job_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_item_id", sa.String(120), nullable=False),
        sa.Column("garment_asset_id", sa.String(36), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model_asset_id", sa.String(36), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("approved_version_id", sa.String(36), nullable=True),
        sa.Column("review_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("regeneration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("batch_id", "client_item_id", name="uq_batch_tryon_review_batch_client"),
    )
    op.create_index("ix_batch_tryon_review_org_batch", "batch_tryon_review_items", ["organization_id", "batch_id"])
    op.create_index("ix_batch_tryon_review_org_status", "batch_tryon_review_items", ["organization_id", "review_status"])

    op.create_table(
        "batch_try_on_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.String(36), sa.ForeignKey("batch_tryon_review_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(36), sa.ForeignKey("batch_try_on_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("generated_asset_id", sa.String(36), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prompt_snapshot", sa.Text(), nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("retry_mode", sa.String(30), nullable=False, server_default="initial"),
        sa.Column("generation_status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("review_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("item_id", "version_number", name="uq_batch_try_on_version_number"),
        sa.UniqueConstraint("task_id", name="uq_batch_try_on_version_task"),
    )
    op.create_index("ix_batch_try_on_versions_org_item", "batch_try_on_versions", ["organization_id", "item_id", "version_number"])


def downgrade() -> None:
    op.drop_index("ix_batch_try_on_versions_org_item", table_name="batch_try_on_versions")
    op.drop_table("batch_try_on_versions")
    op.drop_index("ix_batch_tryon_review_org_status", table_name="batch_tryon_review_items")
    op.drop_index("ix_batch_tryon_review_org_batch", table_name="batch_tryon_review_items")
    op.drop_table("batch_tryon_review_items")
