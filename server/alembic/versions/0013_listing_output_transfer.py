"""listing output transfer idempotency

Revision ID: 0013_listing_output_transfer
Revises: 0012_batch_review
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0013_listing_output_transfer"
down_revision: str | None = "0012_batch_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listing_output_transfers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("listing_output_id", sa.String(36), sa.ForeignKey("generated_outputs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_asset_id", sa.String(36), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("template_replaced", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_project", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_listing_transfer_org_idempotency"),
    )
    op.create_index(
        "ix_listing_transfer_org_output",
        "listing_output_transfers",
        ["organization_id", "listing_output_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_listing_transfer_org_output", table_name="listing_output_transfers")
    op.drop_table("listing_output_transfers")
