"""Add database defaults for batch garment style profile timestamps.

Revision ID: 0031_batch_style_ts_defaults
Revises: 0030_batch_style_profiles
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0031_batch_style_ts_defaults"
down_revision: str | None = "0030_batch_style_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "batch_garment_style_profiles",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "batch_garment_style_profiles",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def downgrade() -> None:
    op.alter_column(
        "batch_garment_style_profiles",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "batch_garment_style_profiles",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=None,
    )
