"""add job attempt phase diagnostics

Revision ID: 0014_job_attempt_diagnostics
Revises: 0013_listing_output_transfer
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0014_job_attempt_diagnostics"
down_revision: str | None = "0013_listing_output_transfer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # MySQL DDL is non-transactional. Column guards make recovery safe if a
    # container was interrupted halfway through this migration.
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("job_attempts")}
    if "retry_after_seconds" not in existing:
        op.add_column("job_attempts", sa.Column("retry_after_seconds", sa.Integer(), nullable=True))
    if "provider_requested_at" not in existing:
        op.add_column("job_attempts", sa.Column("provider_requested_at", sa.DateTime(timezone=True), nullable=True))
    if "provider_responded_at" not in existing:
        op.add_column("job_attempts", sa.Column("provider_responded_at", sa.DateTime(timezone=True), nullable=True))
    if "phase_timings" not in existing:
        op.add_column("job_attempts", sa.Column("phase_timings", sa.JSON(), nullable=True))
        op.execute(sa.text("UPDATE job_attempts SET phase_timings = '{}' WHERE phase_timings IS NULL"))
        op.alter_column("job_attempts", "phase_timings", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("job_attempts")}
    for name in ("phase_timings", "provider_responded_at", "provider_requested_at", "retry_after_seconds"):
        if name in existing:
            op.drop_column("job_attempts", name)
