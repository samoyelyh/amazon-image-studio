"""add material extraction operation binding and billing rule

Revision ID: 0029_material_extract
Revises: 0028_football_variations
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "0029_material_extract"
down_revision: str | None = "0028_football_variations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    now = datetime.now(timezone.utc)
    bindings = sa.table(
        "operation_resource_pools",
        sa.column("id", sa.String()),
        sa.column("organization_id", sa.String()),
        sa.column("operation_code", sa.String()),
        sa.column("resource_pool_id", sa.String()),
        sa.column("required_capability", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("priority", sa.Integer()),
        sa.column("created_by", sa.String()),
        sa.column("updated_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    source_rows = connection.execute(sa.select(
        bindings.c.organization_id,
        bindings.c.resource_pool_id,
        bindings.c.enabled,
        bindings.c.priority,
        bindings.c.created_by,
        bindings.c.updated_by,
    ).where(
        bindings.c.operation_code == "listing.generate",
        bindings.c.required_capability == "image_edit",
    )).all()
    existing = {
        (row.organization_id, row.resource_pool_id)
        for row in connection.execute(sa.select(
            bindings.c.organization_id, bindings.c.resource_pool_id,
        ).where(
            bindings.c.operation_code == "asset.extract",
            bindings.c.required_capability == "image_edit",
        )).all()
    }
    rows = [{
        "id": str(uuid4()),
        "organization_id": row.organization_id,
        "operation_code": "asset.extract",
        "resource_pool_id": row.resource_pool_id,
        "required_capability": "image_edit",
        "enabled": row.enabled,
        "priority": row.priority,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": now,
        "updated_at": now,
    } for row in source_rows if (row.organization_id, row.resource_pool_id) not in existing]
    if rows:
        op.bulk_insert(bindings, rows)

    quota_rules = sa.table(
        "quota_rules",
        sa.column("id", sa.String()),
        sa.column("organization_id", sa.String()),
        sa.column("operation_code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("base_cost", sa.BigInteger()),
        sa.column("model_multipliers", sa.JSON()),
        sa.column("quality_multipliers", sa.JSON()),
        sa.column("resolution_multipliers", sa.JSON()),
        sa.column("resource_pool_multipliers", sa.JSON()),
        sa.column("enabled", sa.Boolean()),
        sa.column("effective_from", sa.DateTime(timezone=True)),
        sa.column("effective_to", sa.DateTime(timezone=True)),
        sa.column("created_by", sa.String()),
        sa.column("updated_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    effective_from = datetime(2020, 1, 1, tzinfo=timezone.utc)
    has_rule = connection.execute(sa.select(quota_rules.c.id).where(
        quota_rules.c.organization_id.is_(None),
        quota_rules.c.operation_code == "asset.extract",
        quota_rules.c.effective_from == effective_from,
    )).first()
    if not has_rule:
        op.bulk_insert(quota_rules, [{
            "id": str(uuid4()),
            "organization_id": None,
            "operation_code": "asset.extract",
            "name": "素材提取",
            "base_cost": 10,
            "model_multipliers": {},
            "quality_multipliers": {"standard": "1", "high": "1.5"},
            "resolution_multipliers": {"1024": "1", "2048": "2"},
            "resource_pool_multipliers": {"platform": "1", "personal": "0"},
            "enabled": True,
            "effective_from": effective_from,
            "effective_to": None,
            "created_by": None,
            "updated_by": None,
            "created_at": now,
            "updated_at": now,
        }])


def downgrade() -> None:
    op.execute("DELETE FROM operation_resource_pools WHERE operation_code = 'asset.extract'")
    op.execute("DELETE FROM quota_rules WHERE operation_code = 'asset.extract'")

