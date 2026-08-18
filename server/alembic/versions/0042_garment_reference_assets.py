"""add non-destructive garment reference asset metadata

Revision ID: 0042_garment_references
Revises: 0041_update_custom_prompt
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0042_garment_references"
down_revision: str | None = "0041_update_custom_prompt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("assets")}
    if "source_asset_id" not in columns:
        op.add_column("assets", sa.Column("source_asset_id", sa.String(length=36), nullable=True))
        op.create_foreign_key(
            "fk_assets_source_asset_id_assets", "assets", "assets",
            ["source_asset_id"], ["id"], ondelete="RESTRICT",
        )
        op.create_index("ix_assets_source_asset_id", "assets", ["source_asset_id"])
    if "metadata" not in columns:
        op.add_column("assets", sa.Column("metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("assets")}
    if "metadata" in columns:
        op.drop_column("assets", "metadata")
    if "source_asset_id" in columns:
        op.drop_index("ix_assets_source_asset_id", table_name="assets")
        op.drop_constraint("fk_assets_source_asset_id_assets", "assets", type_="foreignkey")
        op.drop_column("assets", "source_asset_id")
