"""add durable attachment planning dependency intent

Revision ID: 0057_attachment_dependencies
Revises: 0056_phase10_inputs
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0057_attachment_dependencies"
down_revision: str | None = "0056_phase10_inputs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("attachment_workbench_plans")}
    if "pending_planning_json" not in columns:
        op.add_column(
            "attachment_workbench_plans",
            sa.Column("pending_planning_json", sa.JSON(), nullable=False, server_default=sa.text("('{}')")),
        )


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("attachment_workbench_plans")}
    if "pending_planning_json" in columns:
        op.drop_column("attachment_workbench_plans", "pending_planning_json")
