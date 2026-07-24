"""add batch try-on matrix and admin concurrency snapshots

Revision ID: 0016_batch_tryon_matrix
Revises: 0015_batch_tryon_filenames
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0016_batch_tryon_matrix"
down_revision: str | None = "0015_batch_tryon_filenames"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    batch_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("job_batches")
    }
    if "admin_test_mode" not in batch_columns:
        op.add_column(
            "job_batches",
            sa.Column("admin_test_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    item_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("batch_tryon_review_items")
    }
    for name, column_type in (
        ("template_name", sa.String(length=255)),
        ("preset_summary", sa.String(length=1000)),
        ("preset_codes", sa.JSON()),
    ):
        if name not in item_columns:
            op.add_column("batch_tryon_review_items", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    item_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("batch_tryon_review_items")
    }
    for name in ("preset_codes", "preset_summary", "template_name"):
        if name in item_columns:
            op.drop_column("batch_tryon_review_items", name)
    batch_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("job_batches")
    }
    if "admin_test_mode" in batch_columns:
        op.drop_column("job_batches", "admin_test_mode")
