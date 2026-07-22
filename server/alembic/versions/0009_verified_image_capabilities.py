"""verified image capabilities and multi-capability operation routes

Revision ID: 0009_verified_image_caps
Revises: 0008_provider_routing
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "0009_verified_image_caps"
down_revision: str | None = "0008_provider_routing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_operation_resource_pools_organization_id", "operation_resource_pools", type_="unique")
    op.create_unique_constraint(
        "uq_operation_resource_pool_capability", "operation_resource_pools",
        ["organization_id", "operation_code", "resource_pool_id", "required_capability"],
    )
    bind = op.get_bind()
    models = sa.table("models", sa.column("id", sa.String()), sa.column("code", sa.String()))
    capabilities = sa.table(
        "model_capabilities", sa.column("id", sa.String()), sa.column("model_id", sa.String()),
        sa.column("capability", sa.String()), sa.column("created_by", sa.String()),
        sa.column("created_at", sa.DateTime()),
    )
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
    model_id = bind.scalar(sa.select(models.c.id).where(models.c.code == "gpt-image-2").limit(1))
    now = datetime.now(timezone.utc)
    if model_id:
        existing_caps = set(bind.execute(sa.select(capabilities.c.capability).where(capabilities.c.model_id == model_id)).scalars())
        rows = [{"id": str(uuid4()), "model_id": model_id, "capability": capability, "created_by": None, "created_at": now}
                for capability in ["image_generation", "multi_image_reference"] if capability not in existing_caps]
        if rows:
            op.bulk_insert(capabilities, rows)
    pool_id = bind.scalar(sa.select(pools.c.id).where(pools.c.code == "aso8ty-image-edit").limit(1))
    if pool_id:
        existing_routes = set(bind.execute(sa.select(
            bindings.c.operation_code, bindings.c.resource_pool_id, bindings.c.required_capability,
        )).all())
        desired = [
            ("listing.generate", "image_generation"),
            ("aplus.generate", "image_generation"),
            ("batch_tryon.generate", "multi_image_reference"),
        ]
        rows = [{
            "id": str(uuid4()), "organization_id": None, "operation_code": operation_code,
            "resource_pool_id": pool_id, "required_capability": capability,
            "enabled": True, "priority": 100, "created_by": None, "updated_by": None,
            "created_at": now, "updated_at": now,
        } for operation_code, capability in desired if (operation_code, pool_id, capability) not in existing_routes]
        if rows:
            op.bulk_insert(bindings, rows)


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM operation_resource_pools WHERE resource_pool_id IN "
        "(SELECT id FROM resource_pools WHERE code = 'aso8ty-image-edit') "
        "AND required_capability IN ('image_generation', 'multi_image_reference')"
    ))
    op.execute(sa.text(
        "DELETE FROM model_capabilities WHERE model_id IN "
        "(SELECT id FROM models WHERE code = 'gpt-image-2') "
        "AND capability IN ('image_generation', 'multi_image_reference')"
    ))
    op.drop_constraint("uq_operation_resource_pool_capability", "operation_resource_pools", type_="unique")
    op.create_unique_constraint(
        "uq_operation_resource_pools_organization_id", "operation_resource_pools",
        ["organization_id", "operation_code", "resource_pool_id"],
    )
