"""add persistent batch try-on workspace batches

Revision ID: 0045_batch_tryon_workspaces
Revises: 0044_print_design_library
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0045_batch_tryon_workspaces"
down_revision: str | None = "0044_print_design_library"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job_batches", sa.Column("parent_batch_id", sa.String(36), nullable=True))
    op.add_column("job_batches", sa.Column("batch_kind", sa.String(30), nullable=False, server_default="production"))
    op.add_column("job_batches", sa.Column("workspace_hidden", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("job_batches", sa.Column("workspace_config", sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE job_batches SET workspace_config = '{}' WHERE workspace_config IS NULL"))
    op.alter_column("job_batches", "workspace_config", existing_type=sa.JSON(), nullable=False)
    op.create_foreign_key(
        "fk_job_batches_parent_batch_id", "job_batches", "job_batches", ["parent_batch_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "ix_job_batches_workspace_tabs", "job_batches",
        ["organization_id", "project_id", "batch_kind", "workspace_hidden", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_batches_workspace_tabs", table_name="job_batches")
    op.drop_constraint("fk_job_batches_parent_batch_id", "job_batches", type_="foreignkey")
    op.drop_column("job_batches", "workspace_config")
    op.drop_column("job_batches", "workspace_hidden")
    op.drop_column("job_batches", "batch_kind")
    op.drop_column("job_batches", "parent_batch_id")
