"""add timestamp defaults to split listing workflow tables

Revision ID: 0022_listing_split_timestamps
Revises: 0021_split_listing_workspaces
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_listing_split_timestamps"
down_revision = "0021_split_listing_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("listing_versions", "listing_image_projects", "a_plus_projects"):
        op.alter_column(table_name, "created_at", existing_type=sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))
        op.alter_column(table_name, "updated_at", existing_type=sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def downgrade() -> None:
    for table_name in ("listing_versions", "listing_image_projects", "a_plus_projects"):
        op.alter_column(table_name, "created_at", existing_type=sa.DateTime(), nullable=False, server_default=None)
        op.alter_column(table_name, "updated_at", existing_type=sa.DateTime(), nullable=False, server_default=None)
