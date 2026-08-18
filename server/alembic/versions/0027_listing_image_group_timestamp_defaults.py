"""add timestamp defaults to listing image task groups

Revision ID: 0027_listing_group_timestamps
Revises: 0026_listing_image_groups
"""

from alembic import op
import sqlalchemy as sa


revision = "0027_listing_group_timestamps"
down_revision = "0026_listing_image_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "listing_image_task_groups",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "listing_image_task_groups",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def downgrade() -> None:
    op.alter_column(
        "listing_image_task_groups",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=None,
    )
    op.alter_column(
        "listing_image_task_groups",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=None,
    )
