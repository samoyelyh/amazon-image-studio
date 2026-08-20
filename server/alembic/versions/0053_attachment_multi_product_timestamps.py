"""add defaults for attachment multi-product timestamps

Revision ID: 0053_attachment_timestamps
Revises: 0052_attachment_multi_product
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0053_attachment_timestamps"
down_revision: str | None = "0052_attachment_multi_product"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES = (
    "attachment_product_compositions",
    "attachment_product_composition_items",
    "attachment_product_composition_assets",
    "attachment_product_composition_versions",
)


def upgrade() -> None:
    for table_name in TABLES:
        op.alter_column(
            table_name,
            "created_at",
            existing_type=sa.DateTime(),
            existing_nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        op.alter_column(
            table_name,
            "updated_at",
            existing_type=sa.DateTime(),
            existing_nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )


def downgrade() -> None:
    for table_name in reversed(TABLES):
        op.alter_column(
            table_name,
            "updated_at",
            existing_type=sa.DateTime(),
            existing_nullable=False,
            server_default=None,
        )
        op.alter_column(
            table_name,
            "created_at",
            existing_type=sa.DateTime(),
            existing_nullable=False,
            server_default=None,
        )
