"""add per-combination detailed prompt analysis with Luna

Revision ID: 0034_batch_detailed_prompt
Revises: 0033_batch_prompt_types
"""

from collections.abc import Sequence
from datetime import datetime, timezone
import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "0034_batch_detailed_prompt"
down_revision: str | None = "0033_batch_prompt_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {item["name"] for item in inspector.get_columns("batch_tryon_template_prompts")}
    if "garment_id" not in columns:
        op.add_column("batch_tryon_template_prompts", sa.Column("garment_id", sa.String(120), nullable=True))
    if "client_item_id" not in columns:
        op.add_column("batch_tryon_template_prompts", sa.Column("client_item_id", sa.String(120), nullable=True))
    unique_names = {
        item.get("name") for item in sa.inspect(connection).get_unique_constraints("batch_tryon_template_prompts")
    }
    index_names = {
        item.get("name") for item in sa.inspect(connection).get_indexes("batch_tryon_template_prompts")
    }
    if "ix_batch_tryon_template_prompts_workflow_job" not in index_names:
        op.create_index(
            "ix_batch_tryon_template_prompts_workflow_job",
            "batch_tryon_template_prompts",
            ["workflow_job_id"],
        )
    if "uq_batch_tryon_template_prompt_workflow_template" in unique_names:
        op.drop_constraint(
            "uq_batch_tryon_template_prompt_workflow_template",
            "batch_tryon_template_prompts",
            type_="unique",
        )
    if "uq_batch_tryon_template_prompt_workflow_item" not in unique_names:
        op.create_unique_constraint(
            "uq_batch_tryon_template_prompt_workflow_item",
            "batch_tryon_template_prompts",
            ["workflow_job_id", "client_item_id"],
        )

    now = datetime.now(timezone.utc)
    source_rows = connection.execute(sa.text("""
        SELECT p.id AS provider_id, p.code AS provider_code,
               m.config AS model_config, rp.id AS source_pool_id,
               rp.organization_id, rp.code AS source_pool_code, rp.name AS source_pool_name,
               rp.priority, rp.weight, rp.created_by, rp.updated_by
        FROM providers p
        JOIN models m ON m.provider_id = p.id AND m.code = 'gpt-5.5' AND m.enabled = 1
        JOIN resource_pools rp ON rp.model_id = m.id AND rp.enabled = 1
        WHERE p.enabled = 1
    """)).mappings().all()

    for source in source_rows:
        model_id = connection.execute(sa.text("""
            SELECT id FROM models WHERE provider_id = :provider_id AND code = 'gpt-5.6-luna' LIMIT 1
        """), {"provider_id": source["provider_id"]}).scalar_one_or_none()
        if model_id is None:
            model_id = str(uuid4())
            model_config = source["model_config"]
            if isinstance(model_config, (dict, list)):
                model_config = json.dumps(model_config, ensure_ascii=False)
            connection.execute(sa.text("""
                INSERT INTO models (
                    id, provider_id, code, upstream_model, name, enabled, config,
                    created_by, updated_by, created_at, updated_at
                ) VALUES (
                    :id, :provider_id, 'gpt-5.6-luna', 'gpt-5.6-luna', 'GPT 5.6 Luna 精细视觉分析', 1, :config,
                    :created_by, :updated_by, :created_at, :updated_at
                )
            """), {
                "id": model_id,
                "provider_id": source["provider_id"],
                "config": model_config or "{}",
                "created_by": source["created_by"],
                "updated_by": source["updated_by"],
                "created_at": now,
                "updated_at": now,
            })
            for capability in ("text_generation", "vision_input"):
                connection.execute(sa.text("""
                    INSERT INTO model_capabilities (id, model_id, capability, created_by, created_at)
                    VALUES (:id, :model_id, :capability, :created_by, :created_at)
                """), {
                    "id": str(uuid4()), "model_id": model_id, "capability": capability,
                    "created_by": source["created_by"], "created_at": now,
                })

        pool_code = f"{source['source_pool_code']}-luna"[:100]
        pool_id = connection.execute(sa.text("""
            SELECT id FROM resource_pools
            WHERE model_id = :model_id AND code = :code
            ORDER BY created_at LIMIT 1
        """), {"model_id": model_id, "code": pool_code}).scalar_one_or_none()
        if pool_id is None:
            pool_id = str(uuid4())
            connection.execute(sa.text("""
                INSERT INTO resource_pools (
                    id, organization_id, model_id, code, name, enabled, priority, weight,
                    created_by, updated_by, created_at, updated_at
                ) VALUES (
                    :id, :organization_id, :model_id, :code, :name, 1, :priority, :weight,
                    :created_by, :updated_by, :created_at, :updated_at
                )
            """), {
                "id": pool_id, "organization_id": source["organization_id"], "model_id": model_id,
                "code": pool_code, "name": f"{source['source_pool_name']} · Luna 精细分析",
                "priority": source["priority"], "weight": source["weight"],
                "created_by": source["created_by"], "updated_by": source["updated_by"],
                "created_at": now, "updated_at": now,
            })
            source_keys = connection.execute(sa.text("""
                SELECT api_key_id, enabled, priority, weight, created_by, updated_by
                FROM resource_pool_keys WHERE resource_pool_id = :source_pool_id
            """), {"source_pool_id": source["source_pool_id"]}).mappings().all()
            for key in source_keys:
                connection.execute(sa.text("""
                    INSERT INTO resource_pool_keys (
                        id, resource_pool_id, api_key_id, enabled, priority, weight,
                        created_by, updated_by, created_at, updated_at
                    ) VALUES (
                        :id, :pool_id, :api_key_id, :enabled, :priority, :weight,
                        :created_by, :updated_by, :created_at, :updated_at
                    )
                """), {
                    "id": str(uuid4()), "pool_id": pool_id, "api_key_id": key["api_key_id"],
                    "enabled": key["enabled"], "priority": key["priority"], "weight": key["weight"],
                    "created_by": key["created_by"], "updated_by": key["updated_by"],
                    "created_at": now, "updated_at": now,
                })

        binding_exists = connection.execute(sa.text("""
            SELECT id FROM operation_resource_pools
            WHERE operation_code = 'batch_tryon.prompt_analyze_detailed'
              AND resource_pool_id = :pool_id AND required_capability = 'text_generation'
            LIMIT 1
        """), {"pool_id": pool_id}).scalar_one_or_none()
        if binding_exists is None:
            connection.execute(sa.text("""
                INSERT INTO operation_resource_pools (
                    id, organization_id, operation_code, resource_pool_id, required_capability,
                    enabled, priority, created_by, updated_by, created_at, updated_at
                ) VALUES (
                    :id, :organization_id, 'batch_tryon.prompt_analyze_detailed', :pool_id, 'text_generation',
                    1, :priority, :created_by, :updated_by, :created_at, :updated_at
                )
            """), {
                "id": str(uuid4()), "organization_id": source["organization_id"], "pool_id": pool_id,
                "priority": source["priority"], "created_by": source["created_by"],
                "updated_by": source["updated_by"], "created_at": now, "updated_at": now,
            })

    connection.execute(sa.text("""
        INSERT INTO quota_rules (
            id, organization_id, operation_code, name, base_cost, model_multipliers,
            quality_multipliers, resolution_multipliers, resource_pool_multipliers,
            enabled, effective_from, effective_to, created_by, updated_by, created_at, updated_at
        )
        SELECT UUID(), organization_id, 'batch_tryon.prompt_analyze_detailed',
               '批量套图逐图精细提示词分析', base_cost, model_multipliers,
               JSON_OBJECT('detailed', '1'), resolution_multipliers, resource_pool_multipliers,
               enabled, effective_from, effective_to, created_by, updated_by, :now, :now
        FROM quota_rules source
        WHERE source.operation_code = 'batch_tryon.prompt_analyze'
          AND NOT EXISTS (
              SELECT 1 FROM quota_rules target
              WHERE target.operation_code = 'batch_tryon.prompt_analyze_detailed'
                AND target.organization_id <=> source.organization_id
          )
    """), {"now": now})


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text(
        "DELETE FROM quota_rules WHERE operation_code = 'batch_tryon.prompt_analyze_detailed'"
    ))
    connection.execute(sa.text(
        "DELETE FROM operation_resource_pools WHERE operation_code = 'batch_tryon.prompt_analyze_detailed'"
    ))
    luna_model_ids = [row[0] for row in connection.execute(sa.text(
        "SELECT id FROM models WHERE code = 'gpt-5.6-luna' AND name = 'GPT 5.6 Luna 精细视觉分析'"
    )).all()]
    if luna_model_ids:
        connection.execute(sa.text(
            "DELETE FROM models WHERE code = 'gpt-5.6-luna' AND name = 'GPT 5.6 Luna 精细视觉分析'"
        ))
    op.drop_constraint(
        "uq_batch_tryon_template_prompt_workflow_item",
        "batch_tryon_template_prompts",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_batch_tryon_template_prompt_workflow_template",
        "batch_tryon_template_prompts",
        ["workflow_job_id", "template_id"],
    )
    op.drop_column("batch_tryon_template_prompts", "client_item_id")
    op.drop_column("batch_tryon_template_prompts", "garment_id")
