"""add batch try-on filename snapshots

Revision ID: 0015_batch_tryon_filenames
Revises: 0014_job_attempt_diagnostics
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0015_batch_tryon_filenames"
down_revision: str | None = "0014_job_attempt_diagnostics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    item_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("batch_tryon_review_items")
    }
    if "source_filename" not in item_columns:
        op.add_column(
            "batch_tryon_review_items",
            sa.Column("source_filename", sa.String(length=255), nullable=True),
        )

    version_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("batch_try_on_versions")
    }
    for name, column_type in (
        ("source_filename", sa.String(length=255)),
        ("display_filename", sa.String(length=255)),
        ("download_filename", sa.String(length=255)),
        ("output_format", sa.String(length=16)),
    ):
        if name not in version_columns:
            op.add_column("batch_try_on_versions", sa.Column(name, column_type, nullable=True))

    op.execute(sa.text(
        """
        UPDATE batch_tryon_review_items
        SET source_filename = (
            SELECT assets.filename FROM assets
            WHERE assets.id = batch_tryon_review_items.garment_asset_id
        )
        WHERE source_filename IS NULL
        """
    ))
    op.execute(sa.text(
        """
        UPDATE batch_try_on_versions
        SET source_filename = (
            SELECT batch_tryon_review_items.source_filename
            FROM batch_tryon_review_items
            WHERE batch_tryon_review_items.id = batch_try_on_versions.item_id
        )
        WHERE source_filename IS NULL
        """
    ))


def downgrade() -> None:
    version_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("batch_try_on_versions")
    }
    for name in ("output_format", "download_filename", "display_filename", "source_filename"):
        if name in version_columns:
            op.drop_column("batch_try_on_versions", name)
    item_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("batch_tryon_review_items")
    }
    if "source_filename" in item_columns:
        op.drop_column("batch_tryon_review_items", "source_filename")
