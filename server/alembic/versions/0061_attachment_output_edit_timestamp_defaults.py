"""add database defaults for attachment output edit timestamps

Revision ID: 0061_edit_timestamp_defaults
Revises: 0060_hermes_timestamp_defaults
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0061_edit_timestamp_defaults"
down_revision: str | None = "0060_hermes_timestamp_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "attachment_output_edit_revisions",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "attachment_output_edit_revisions",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def downgrade() -> None:
    op.alter_column(
        "attachment_output_edit_revisions",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=None,
    )
    op.alter_column(
        "attachment_output_edit_revisions",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=None,
    )
