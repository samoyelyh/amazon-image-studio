"""add generation resource diagnostics

Revision ID: 0018_resource_diagnostics
Revises: 0017_project_asset_labels
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0018_resource_diagnostics"
down_revision: str | None = "0017_project_asset_labels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("jobs")}
    if "technical_retry_count" not in columns:
        op.add_column(
            "jobs",
            sa.Column("technical_retry_count", sa.Integer(), nullable=False, server_default="0"),
        )
    if "next_dispatch_at" not in columns:
        op.add_column("jobs", sa.Column("next_dispatch_at", sa.DateTime(timezone=True), nullable=True))
    if "diagnostic_run_id" not in columns:
        op.add_column("jobs", sa.Column("diagnostic_run_id", sa.String(length=80), nullable=True))
    if "load_test_run_id" not in columns:
        op.add_column("jobs", sa.Column("load_test_run_id", sa.String(length=80), nullable=True))
    if "last_error_type" not in columns:
        op.add_column("jobs", sa.Column("last_error_type", sa.String(length=60), nullable=True))

    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("jobs")}
    if "ix_jobs_status_dispatch" not in indexes:
        op.create_index("ix_jobs_status_dispatch", "jobs", ["status", "next_dispatch_at"])
    if "ix_jobs_diagnostic_run_id" not in indexes:
        op.create_index("ix_jobs_diagnostic_run_id", "jobs", ["diagnostic_run_id"])
    if "ix_jobs_load_test_run_id" not in indexes:
        op.create_index("ix_jobs_load_test_run_id", "jobs", ["load_test_run_id"])

    if "job_status_events" not in inspector.get_table_names():
        op.create_table(
            "job_status_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("from_status", sa.String(length=30), nullable=True),
            sa.Column("to_status", sa.String(length=30), nullable=False),
            sa.Column("reason", sa.String(length=160), nullable=True),
            sa.Column("provider_id", sa.String(length=36), nullable=True),
            sa.Column("resource_pool_id", sa.String(length=36), nullable=True),
            sa.Column("api_key_id", sa.String(length=36), nullable=True),
            sa.Column("attempt_number", sa.Integer(), nullable=True),
            sa.Column("diagnostic_run_id", sa.String(length=80), nullable=True),
            sa.Column("load_test_run_id", sa.String(length=80), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["resource_pool_id"], ["resource_pools.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_job_status_events_job_created", "job_status_events", ["job_id", "created_at"])
        op.create_index(
            "ix_job_status_events_diagnostic_run",
            "job_status_events",
            ["diagnostic_run_id", "created_at"],
        )
        op.create_index(
            "ix_job_status_events_load_test_run",
            "job_status_events",
            ["load_test_run_id", "created_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "job_status_events" in inspector.get_table_names():
        op.drop_table("job_status_events")
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("jobs")}
    for name in ("ix_jobs_load_test_run_id", "ix_jobs_diagnostic_run_id", "ix_jobs_status_dispatch"):
        if name in indexes:
            op.drop_index(name, table_name="jobs")
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("jobs")}
    for name in (
        "last_error_type",
        "load_test_run_id",
        "diagnostic_run_id",
        "next_dispatch_at",
        "technical_retry_count",
    ):
        if name in columns:
            op.drop_column("jobs", name)
