"""add project asset labels and default marker

Revision ID: 0017_project_asset_labels
Revises: 0016_batch_tryon_matrix
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0017_project_asset_labels"
down_revision: str | None = "0016_batch_tryon_matrix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("project_assets")
    }
    if "display_name" not in columns:
        op.add_column("project_assets", sa.Column("display_name", sa.String(length=255), nullable=True))
    if "is_default" not in columns:
        op.add_column(
            "project_assets",
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("project_assets")
    }
    if "is_default" in columns:
        op.drop_column("project_assets", "is_default")
    if "display_name" in columns:
        op.drop_column("project_assets", "display_name")
