"""user password management and member creation idempotency

Revision ID: 0007_user_password_management
Revises: 0006_workbench_integration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007_user_password_management"
down_revision: str | None = "0006_workbench_integration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("temporary_password_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("created_by", sa.String(length=36), nullable=True))
    op.add_column("organization_members", sa.Column("creation_idempotency_key", sa.String(length=160), nullable=True))
    op.create_unique_constraint(
        "uq_org_member_creation_idempotency",
        "organization_members",
        ["organization_id", "creation_idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_org_member_creation_idempotency", "organization_members", type_="unique")
    op.drop_column("organization_members", "creation_idempotency_key")
    op.drop_column("users", "created_by")
    op.drop_column("users", "token_version")
    op.drop_column("users", "temporary_password_created_at")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "must_change_password")
