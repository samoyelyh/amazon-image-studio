"""add stable template id for batch try-on bulk actions

Revision ID: 0019_batch_tryon_bulk_actions
Revises: 0018_resource_diagnostics
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0019_batch_tryon_bulk_actions"
down_revision: str | None = "0018_resource_diagnostics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]
        for column in inspector.get_columns("batch_tryon_review_items")
    }
    if "template_id" not in columns:
        op.add_column(
            "batch_tryon_review_items",
            sa.Column("template_id", sa.String(length=120), nullable=True),
        )
    version_columns = {
        column["name"]
        for column in inspector.get_columns("batch_try_on_versions")
    }
    if "created_by" not in version_columns:
        op.add_column(
            "batch_try_on_versions",
            sa.Column("created_by", sa.String(length=36), nullable=True),
        )
        op.create_foreign_key(
            "fk_batch_try_on_versions_created_by_users",
            "batch_try_on_versions",
            "users",
            ["created_by"],
            ["id"],
            ondelete="SET NULL",
        )
    indexes = {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("batch_tryon_review_items")
    }
    if "ix_batch_tryon_review_batch_template" not in indexes:
        op.create_index(
            "ix_batch_tryon_review_batch_template",
            "batch_tryon_review_items",
            ["batch_id", "template_id"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    version_columns = {
        column["name"]
        for column in inspector.get_columns("batch_try_on_versions")
    }
    if "created_by" in version_columns:
        op.drop_constraint(
            "fk_batch_try_on_versions_created_by_users",
            "batch_try_on_versions",
            type_="foreignkey",
        )
        op.drop_column("batch_try_on_versions", "created_by")
    indexes = {
        index["name"]
        for index in inspector.get_indexes("batch_tryon_review_items")
    }
    if "ix_batch_tryon_review_batch_template" in indexes:
        op.drop_index(
            "ix_batch_tryon_review_batch_template",
            table_name="batch_tryon_review_items",
        )
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("batch_tryon_review_items")
    }
    if "template_id" in columns:
        op.drop_column("batch_tryon_review_items", "template_id")
