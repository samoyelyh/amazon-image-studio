"""add batch garment style profiles and analysis operation

Revision ID: 0030_batch_style_profiles
Revises: 0029_material_extract
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "0030_batch_style_profiles"
down_revision: str | None = "0029_material_extract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batch_garment_style_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("source_sample_asset_id", sa.String(length=36), nullable=False),
        sa.Column("profile_key", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("structure_json", sa.JSON(), nullable=False),
        sa.Column("view_rules_json", sa.JSON(), nullable=False),
        sa.Column("preservation_rules_json", sa.JSON(), nullable=False),
        sa.Column("covered_garment_asset_ids_json", sa.JSON(), nullable=False),
        sa.Column("first_sample_observation_json", sa.JSON(), nullable=True),
        sa.Column("analysis_model", sa.String(length=120), nullable=True),
        sa.Column("analysis_version", sa.String(length=80), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["job_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_sample_asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "profile_key", name="uq_batch_garment_style_profile_key"),
    )
    op.create_index(
        "ix_batch_garment_style_profiles_org_batch",
        "batch_garment_style_profiles",
        ["organization_id", "batch_id"],
        unique=False,
    )

    connection = op.get_bind()
    now = datetime.now(timezone.utc)
    bindings = sa.table(
        "operation_resource_pools",
        sa.column("id", sa.String()), sa.column("organization_id", sa.String()),
        sa.column("operation_code", sa.String()), sa.column("resource_pool_id", sa.String()),
        sa.column("required_capability", sa.String()), sa.column("enabled", sa.Boolean()),
        sa.column("priority", sa.Integer()), sa.column("created_by", sa.String()),
        sa.column("updated_by", sa.String()), sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    source_rows = connection.execute(sa.select(
        bindings.c.organization_id, bindings.c.resource_pool_id, bindings.c.enabled,
        bindings.c.priority, bindings.c.created_by, bindings.c.updated_by,
    ).where(
        bindings.c.operation_code == "listing.plan",
        bindings.c.required_capability == "text_generation",
    )).all()
    existing = {
        (row.organization_id, row.resource_pool_id)
        for row in connection.execute(sa.select(
            bindings.c.organization_id, bindings.c.resource_pool_id,
        ).where(
            bindings.c.operation_code == "batch_tryon.style_analyze",
            bindings.c.required_capability == "text_generation",
        )).all()
    }
    rows = [{
        "id": str(uuid4()), "organization_id": row.organization_id,
        "operation_code": "batch_tryon.style_analyze", "resource_pool_id": row.resource_pool_id,
        "required_capability": "text_generation", "enabled": row.enabled, "priority": row.priority,
        "created_by": row.created_by, "updated_by": row.updated_by, "created_at": now, "updated_at": now,
    } for row in source_rows if (row.organization_id, row.resource_pool_id) not in existing]
    if rows:
        op.bulk_insert(bindings, rows)

    quota_rules = sa.table(
        "quota_rules",
        sa.column("id", sa.String()), sa.column("organization_id", sa.String()),
        sa.column("operation_code", sa.String()), sa.column("name", sa.String()),
        sa.column("base_cost", sa.BigInteger()), sa.column("model_multipliers", sa.JSON()),
        sa.column("quality_multipliers", sa.JSON()), sa.column("resolution_multipliers", sa.JSON()),
        sa.column("resource_pool_multipliers", sa.JSON()), sa.column("enabled", sa.Boolean()),
        sa.column("effective_from", sa.DateTime(timezone=True)), sa.column("effective_to", sa.DateTime(timezone=True)),
        sa.column("created_by", sa.String()), sa.column("updated_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    effective_from = datetime(2020, 1, 1, tzinfo=timezone.utc)
    if not connection.execute(sa.select(quota_rules.c.id).where(
        quota_rules.c.organization_id.is_(None),
        quota_rules.c.operation_code == "batch_tryon.style_analyze",
        quota_rules.c.effective_from == effective_from,
    )).first():
        op.bulk_insert(quota_rules, [{
            "id": str(uuid4()), "organization_id": None,
            "operation_code": "batch_tryon.style_analyze", "name": "批量套图款式分析",
            "base_cost": 1, "model_multipliers": {}, "quality_multipliers": {"standard": "1"},
            "resolution_multipliers": {"text": "1"},
            "resource_pool_multipliers": {"platform": "1", "personal": "0"},
            "enabled": True, "effective_from": effective_from, "effective_to": None,
            "created_by": None, "updated_by": None, "created_at": now, "updated_at": now,
        }])


def downgrade() -> None:
    op.execute("DELETE FROM operation_resource_pools WHERE operation_code = 'batch_tryon.style_analyze'")
    op.execute("DELETE FROM quota_rules WHERE operation_code = 'batch_tryon.style_analyze'")
    op.drop_index("ix_batch_garment_style_profiles_org_batch", table_name="batch_garment_style_profiles")
    op.drop_table("batch_garment_style_profiles")
