"""Add recoverable workbench batches and generated-output job links.

Revision ID: 0006_workbench_integration
Revises: 0005_tasks_resource_pool
Create Date: 2026-07-17
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006_workbench_integration"
down_revision: str | None = "0005_tasks_resource_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job_batches", sa.Column("name", sa.String(160), nullable=True))
    op.add_column("job_batches", sa.Column("model_code", sa.String(120), nullable=True))
    op.add_column("job_batches", sa.Column("capability", sa.String(80), nullable=True))
    op.add_column("job_batches", sa.Column("idempotency_key", sa.String(200), nullable=True))
    op.add_column("job_batches", sa.Column("request_hash", sa.String(64), nullable=True))
    op.add_column("job_batches", sa.Column("concurrency", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("job_batches", sa.Column("error_message", sa.String(1000), nullable=True))
    op.add_column("job_batches", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_batches", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_job_batches_org_idempotency", "job_batches", ["organization_id", "idempotency_key"])

    op.add_column("jobs", sa.Column("client_item_id", sa.String(120), nullable=True))
    op.create_index("ix_jobs_batch_client_item", "jobs", ["batch_id", "client_item_id"])

    op.alter_column("generated_outputs", "project_id", existing_type=sa.String(36), nullable=True)
    op.add_column("generated_outputs", sa.Column("job_id", sa.String(36), nullable=True))
    op.add_column("generated_outputs", sa.Column("batch_id", sa.String(36), nullable=True))
    op.add_column("generated_outputs", sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="0"))
    op.create_foreign_key("fk_generated_outputs_job_id_jobs", "generated_outputs", "jobs", ["job_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_generated_outputs_batch_id_job_batches", "generated_outputs", "job_batches", ["batch_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_generated_outputs_organization_created", "generated_outputs", ["organization_id", "created_at"])
    op.create_index("ix_generated_outputs_job", "generated_outputs", ["job_id", "sequence_number"])


def downgrade() -> None:
    op.drop_index("ix_generated_outputs_job", table_name="generated_outputs")
    op.drop_index("ix_generated_outputs_organization_created", table_name="generated_outputs")
    op.drop_constraint("fk_generated_outputs_batch_id_job_batches", "generated_outputs", type_="foreignkey")
    op.drop_constraint("fk_generated_outputs_job_id_jobs", "generated_outputs", type_="foreignkey")
    op.drop_column("generated_outputs", "sequence_number")
    op.drop_column("generated_outputs", "batch_id")
    op.drop_column("generated_outputs", "job_id")
    op.alter_column("generated_outputs", "project_id", existing_type=sa.String(36), nullable=False)
    op.drop_index("ix_jobs_batch_client_item", table_name="jobs")
    op.drop_column("jobs", "client_item_id")
    op.drop_constraint("uq_job_batches_org_idempotency", "job_batches", type_="unique")
    for column in ["finished_at", "started_at", "error_message", "concurrency", "request_hash", "idempotency_key", "capability", "model_code", "name"]:
        op.drop_column("job_batches", column)
