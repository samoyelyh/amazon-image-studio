"""add optional font reference snapshot to batch try-on prompts

Revision ID: 0035_batch_font_reference
Revises: 0034_batch_detailed_prompt
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0035_batch_font_reference"
down_revision: str | None = "0034_batch_detailed_prompt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("batch_tryon_template_prompts")}
    if "font_reference_asset_id" not in columns:
        op.add_column(
            "batch_tryon_template_prompts",
            sa.Column("font_reference_asset_id", sa.String(length=36), nullable=True),
        )
        op.create_foreign_key(
            "fk_batch_tryon_template_prompts_font_reference_asset_id_assets",
            "batch_tryon_template_prompts",
            "assets",
            ["font_reference_asset_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("batch_tryon_template_prompts")}
    if "font_reference_asset_id" in columns:
        op.drop_constraint(
            "fk_batch_tryon_template_prompts_font_reference_asset_id_assets",
            "batch_tryon_template_prompts",
            type_="foreignkey",
        )
        op.drop_column("batch_tryon_template_prompts", "font_reference_asset_id")
