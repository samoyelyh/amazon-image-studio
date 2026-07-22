"""provider operation routing and safe job diagnostics

Revision ID: 0008_provider_routing
Revises: 0007_user_password_management
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "0008_provider_routing"
down_revision: str | None = "0007_user_password_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("operation_resource_pools"):
        columns = {item["name"] for item in inspector.get_columns("job_attempts")}
        missing = {
            "model_id": sa.Column("model_id", sa.String(length=36), nullable=True),
            "worker_name": sa.Column("worker_name", sa.String(length=160), nullable=True),
            "normalized_base_url": sa.Column("normalized_base_url", sa.String(length=500), nullable=True),
            "upstream_request_id": sa.Column("upstream_request_id", sa.String(length=200), nullable=True),
        }
        for name, column in missing.items():
            if name not in columns:
                op.add_column("job_attempts", column)
        foreign_keys = {item.get("name") for item in sa.inspect(bind).get_foreign_keys("job_attempts")}
        if "fk_job_attempts_model_id" not in foreign_keys:
            op.create_foreign_key("fk_job_attempts_model_id", "job_attempts", "models", ["model_id"], ["id"], ondelete="SET NULL")
        _seed_bindings()
        return
    op.create_table(
        "operation_resource_pools",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("operation_code", sa.String(length=120), nullable=False),
        sa.Column("resource_pool_id", sa.String(length=36), nullable=False),
        sa.Column("required_capability", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_pool_id"], ["resource_pools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "operation_code", "resource_pool_id"),
    )
    op.create_index(
        "ix_operation_resource_pools_lookup", "operation_resource_pools",
        ["organization_id", "operation_code", "enabled", "priority"], unique=False,
    )
    op.add_column("job_attempts", sa.Column("model_id", sa.String(length=36), nullable=True))
    op.add_column("job_attempts", sa.Column("worker_name", sa.String(length=160), nullable=True))
    op.add_column("job_attempts", sa.Column("normalized_base_url", sa.String(length=500), nullable=True))
    op.add_column("job_attempts", sa.Column("upstream_request_id", sa.String(length=200), nullable=True))
    op.create_foreign_key("fk_job_attempts_model_id", "job_attempts", "models", ["model_id"], ["id"], ondelete="SET NULL")

    _seed_bindings()


def _seed_bindings() -> None:
    pools = sa.table("resource_pools", sa.column("id", sa.String()), sa.column("code", sa.String()))
    bindings = sa.table(
        "operation_resource_pools",
        sa.column("id", sa.String()), sa.column("organization_id", sa.String()),
        sa.column("operation_code", sa.String()), sa.column("resource_pool_id", sa.String()),
        sa.column("required_capability", sa.String()), sa.column("enabled", sa.Boolean()),
        sa.column("priority", sa.Integer()), sa.column("created_by", sa.String()),
        sa.column("updated_by", sa.String()), sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    pool_ids = dict(op.get_bind().execute(sa.select(pools.c.code, pools.c.id).where(
        pools.c.code.in_(["aso8ty-text-default", "aso8ty-image-edit"])
    )).all())
    desired = [
        ("listing.plan", "aso8ty-text-default", "text_generation"),
        ("aplus.plan", "aso8ty-text-default", "text_generation"),
        ("listing.generate", "aso8ty-image-edit", "image_edit"),
        ("aplus.generate", "aso8ty-image-edit", "image_edit"),
        ("batch_tryon.generate", "aso8ty-image-edit", "image_edit"),
    ]
    now = datetime.now(timezone.utc)
    existing = set(op.get_bind().execute(sa.select(
        bindings.c.operation_code, bindings.c.resource_pool_id, bindings.c.required_capability,
    )).all())
    rows = [{
        "id": str(uuid4()), "organization_id": None, "operation_code": operation_code,
        "resource_pool_id": pool_ids[pool_code], "required_capability": capability,
        "enabled": True, "priority": 100, "created_by": None, "updated_by": None,
        "created_at": now, "updated_at": now,
    } for operation_code, pool_code, capability in desired
        if pool_code in pool_ids and (operation_code, pool_ids[pool_code], capability) not in existing]
    if rows:
        op.bulk_insert(bindings, rows)


def downgrade() -> None:
    op.drop_constraint("fk_job_attempts_model_id", "job_attempts", type_="foreignkey")
    op.drop_column("job_attempts", "upstream_request_id")
    op.drop_column("job_attempts", "normalized_base_url")
    op.drop_column("job_attempts", "worker_name")
    op.drop_column("job_attempts", "model_id")
    op.drop_index("ix_operation_resource_pools_lookup", table_name="operation_resource_pools")
    op.drop_table("operation_resource_pools")
