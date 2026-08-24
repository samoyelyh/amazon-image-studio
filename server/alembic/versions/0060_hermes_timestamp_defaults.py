"""add database defaults for Hermes timestamps

Revision ID: 0060_hermes_timestamp_defaults
Revises: 0059_hermes_attachment_agent
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0060_hermes_timestamp_defaults"
down_revision: str | None = "0059_hermes_attachment_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _default(table: str, column: str, *, nullable: bool = False) -> None:
    op.alter_column(
        table,
        column,
        existing_type=sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _drop_default(table: str, column: str, *, nullable: bool = False) -> None:
    op.alter_column(
        table,
        column,
        existing_type=sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=None,
    )


def upgrade() -> None:
    _default("hermes_conversations", "created_at")
    _default("hermes_conversations", "updated_at")
    _default("hermes_messages", "created_at")
    _default("hermes_proposals", "created_at")
    _default("hermes_proposals", "updated_at")
    _default("hermes_tool_audits", "created_at")


def downgrade() -> None:
    _drop_default("hermes_tool_audits", "created_at")
    _drop_default("hermes_proposals", "updated_at")
    _drop_default("hermes_proposals", "created_at")
    _drop_default("hermes_messages", "created_at")
    _drop_default("hermes_conversations", "updated_at")
    _drop_default("hermes_conversations", "created_at")
