"""optimize job batch history lookup

Revision ID: 0046_job_batch_history
Revises: 0045_batch_tryon_workspaces
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0046_job_batch_history"
down_revision: str | None = "0045_batch_tryon_workspaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_job_batches_history_lookup",
        "job_batches",
        ["organization_id", "workspace_type", "operation_code", "project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_batches_history_lookup", table_name="job_batches")
