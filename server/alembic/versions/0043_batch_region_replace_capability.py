"""enable verified batch region replacement capability

Revision ID: 0043_batch_region_replace
Revises: 0042_garment_references
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0043_batch_region_replace"
down_revision: str | None = "0042_garment_references"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    models = connection.execute(sa.text(
        """
        SELECT DISTINCT m.id
        FROM models m
        JOIN providers p ON p.id = m.provider_id
        JOIN resource_pools rp ON rp.model_id = m.id
        JOIN operation_resource_pools orb ON orb.resource_pool_id = rp.id
        WHERE orb.operation_code = 'batch_tryon.generate'
          AND orb.required_capability IN ('image_edit', 'multi_image_reference')
          AND p.code IN ('aso8ty-openai', 'aso8ty-openai-channel-2')
          AND m.enabled = 1 AND rp.enabled = 1 AND orb.enabled = 1
        """
    )).fetchall()
    for (model_id,) in models:
        existing = connection.execute(sa.text(
            "SELECT id FROM model_capabilities WHERE model_id = :model_id AND capability = 'mask_edit' LIMIT 1"
        ), {"model_id": model_id}).scalar()
        if not existing:
            connection.execute(sa.text(
                "INSERT INTO model_capabilities (id, model_id, capability, created_at) VALUES (UUID(), :model_id, 'mask_edit', CURRENT_TIMESTAMP)"
            ), {"model_id": model_id})

    bindings = connection.execute(sa.text(
        """
        SELECT id, organization_id, resource_pool_id, priority
        FROM operation_resource_pools
        WHERE operation_code = 'batch_tryon.generate'
          AND required_capability IN ('image_edit', 'multi_image_reference')
          AND enabled = 1
        """
    )).mappings().all()
    seen: set[tuple[object, object]] = set()
    for binding in bindings:
        key = (binding["organization_id"], binding["resource_pool_id"])
        if key in seen:
            continue
        seen.add(key)
        if binding["organization_id"] is None:
            existing = connection.execute(sa.text(
                """SELECT id FROM operation_resource_pools
                WHERE organization_id IS NULL AND operation_code = 'batch_tryon.region_replace'
                  AND resource_pool_id = :pool_id AND required_capability = 'mask_edit' LIMIT 1"""
            ), {"pool_id": binding["resource_pool_id"]}).scalar()
        else:
            existing = connection.execute(sa.text(
                """SELECT id FROM operation_resource_pools
                WHERE organization_id = :organization_id AND operation_code = 'batch_tryon.region_replace'
                  AND resource_pool_id = :pool_id AND required_capability = 'mask_edit' LIMIT 1"""
            ), {"organization_id": binding["organization_id"], "pool_id": binding["resource_pool_id"]}).scalar()
        if not existing:
            connection.execute(sa.text(
                """INSERT INTO operation_resource_pools
                (id, organization_id, operation_code, resource_pool_id, required_capability, enabled, priority, created_at, updated_at)
                VALUES (UUID(), :organization_id, 'batch_tryon.region_replace', :pool_id, 'mask_edit', 1, :priority, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
            ), {
                "organization_id": binding["organization_id"],
                "pool_id": binding["resource_pool_id"],
                "priority": binding["priority"],
            })


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text(
        "DELETE FROM operation_resource_pools WHERE operation_code = 'batch_tryon.region_replace' AND required_capability = 'mask_edit'"
    ))
    connection.execute(sa.text(
        "DELETE FROM model_capabilities WHERE capability = 'mask_edit'"
    ))
