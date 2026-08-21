"""add phase 10 planning inputs and reference library

Revision ID: 0056_phase10_inputs
Revises: 0055_creative_presets
"""

from collections.abc import Sequence
from datetime import datetime, timezone
import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "0056_phase10_inputs"
down_revision: str | None = "0055_creative_presets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    model_columns = {item["name"] for item in inspector.get_columns("ai_model_presets")}
    for name, column in (
        ("source_type", sa.Column("source_type", sa.String(30), server_default="ADMIN_PRESET", nullable=False)),
        ("owner_user_id", sa.Column("owner_user_id", sa.String(36), nullable=True)),
        ("generation_parameters", sa.Column("generation_parameters", sa.JSON(), nullable=False, server_default=sa.text("('{}')"))),
    ):
        if name not in model_columns:
            op.add_column("ai_model_presets", column)
    foreign_keys = {item.get("name") for item in sa.inspect(op.get_bind()).get_foreign_keys("ai_model_presets")}
    if "fk_ai_model_presets_owner_user" not in foreign_keys:
        op.create_foreign_key("fk_ai_model_presets_owner_user", "ai_model_presets", "users", ["owner_user_id"], ["id"], ondelete="CASCADE")

    model_selection_unique = {item.get("name") for item in sa.inspect(op.get_bind()).get_unique_constraints("attachment_plan_model_selections")}
    if "uq_attachment_plan_model_slot" in model_selection_unique:
        op.drop_constraint("uq_attachment_plan_model_slot", "attachment_plan_model_selections", type_="unique")
    model_selection_indexes = {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes("attachment_plan_model_selections")}
    # Keep the legacy index: MySQL may be using it to satisfy the existing
    # workbench_plan_id foreign key. Add the scoped index below instead.
    selection_columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("attachment_plan_model_selections")}
    if "module_key" not in selection_columns:
        op.add_column("attachment_plan_model_selections", sa.Column("module_key", sa.String(60), server_default="__global__", nullable=False))
    if "selection_mode" not in selection_columns:
        op.add_column("attachment_plan_model_selections", sa.Column("selection_mode", sa.String(30), server_default="selected", nullable=False))
    op.alter_column("attachment_plan_model_selections", "model_preset_id", existing_type=sa.String(36), nullable=True)
    op.alter_column("attachment_plan_model_selections", "identity_version_id", existing_type=sa.String(36), nullable=True)
    if "uq_attachment_plan_model_scope_slot" not in {item.get("name") for item in sa.inspect(op.get_bind()).get_unique_constraints("attachment_plan_model_selections")}:
        op.create_unique_constraint("uq_attachment_plan_model_scope_slot", "attachment_plan_model_selections", ["workbench_plan_id", "module_key", "product_slot"])
    if "ix_attachment_plan_models_scope" not in {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes("attachment_plan_model_selections")}:
        op.create_index("ix_attachment_plan_models_scope", "attachment_plan_model_selections", ["workbench_plan_id", "module_key", "product_slot"])

    if not sa.inspect(op.get_bind()).has_table("attachment_reference_library_items"):
        op.create_table(
        "attachment_reference_library_items",
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000), server_default="", nullable=False),
        sa.Column("category_key", sa.String(100), nullable=True),
        sa.Column("module_key", sa.String(60), nullable=False),
        sa.Column("reference_role", sa.String(20), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("guidance", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("is_featured", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="100", nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        )
    if "ix_attachment_reference_library_browse" not in {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes("attachment_reference_library_items")}:
        op.create_index("ix_attachment_reference_library_browse", "attachment_reference_library_items", ["organization_id", "module_key", "is_active", "sort_order"])
    if not sa.inspect(op.get_bind()).has_table("attachment_reference_library_understandings"):
        op.create_table(
        "attachment_reference_library_understandings",
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("library_item_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), server_default="analyzing", nullable=False),
        sa.Column("structured_json", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("analysis_model", sa.String(120), nullable=True),
        sa.Column("analysis_model_config", sa.JSON(), nullable=False),
        sa.Column("analysis_prompt_version", sa.String(40), server_default="reference-library-v1", nullable=False),
        sa.Column("ai_job_id", sa.String(36), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["library_item_id"], ["attachment_reference_library_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ai_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("library_item_id", "version_number", name="uq_attachment_library_understanding_version"),
        )
    if "ix_attachment_library_understanding_item" not in {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes("attachment_reference_library_understandings")}:
        op.create_index("ix_attachment_library_understanding_item", "attachment_reference_library_understandings", ["organization_id", "library_item_id", "version_number"])

    module_reference_columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("attachment_module_references")}
    if "library_item_id" not in module_reference_columns:
        op.add_column("attachment_module_references", sa.Column("library_item_id", sa.String(36), nullable=True))
    if "keywords" not in module_reference_columns:
        op.add_column("attachment_module_references", sa.Column("keywords", sa.JSON(), nullable=False, server_default=sa.text("('[]')")))
    if "guidance" not in module_reference_columns:
        op.add_column("attachment_module_references", sa.Column("guidance", sa.Text(), nullable=False))
    if "fk_attachment_module_reference_library" not in {item.get("name") for item in sa.inspect(op.get_bind()).get_foreign_keys("attachment_module_references")}:
        op.create_foreign_key("fk_attachment_module_reference_library", "attachment_module_references", "attachment_reference_library_items", ["library_item_id"], ["id"], ondelete="SET NULL")

    understanding_columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("attachment_reference_understandings")}
    for name, column in (
        ("input_hash", sa.Column("input_hash", sa.String(64), server_default="", nullable=False)),
        ("analysis_task_type", sa.Column("analysis_task_type", sa.String(60), server_default="REFERENCE_ANALYSIS", nullable=False)),
        ("analysis_model_config", sa.Column("analysis_model_config", sa.JSON(), nullable=False, server_default=sa.text("('{}')"))),
        ("analysis_prompt_version", sa.Column("analysis_prompt_version", sa.String(40), server_default="attachment-reference-v2", nullable=False)),
        ("role_snapshot", sa.Column("role_snapshot", sa.JSON(), nullable=False, server_default=sa.text("('{}')"))),
        ("keywords_snapshot", sa.Column("keywords_snapshot", sa.JSON(), nullable=False, server_default=sa.text("('{}')"))),
        ("guidance_snapshot", sa.Column("guidance_snapshot", sa.JSON(), nullable=False, server_default=sa.text("('{}')"))),
    ):
        if name not in understanding_columns:
            op.add_column("attachment_reference_understandings", column)

    if not sa.inspect(op.get_bind()).has_table("attachment_product_identity_lock_versions"):
        op.create_table(
        "attachment_product_identity_lock_versions",
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("workbench_plan_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), server_default="analyzing", nullable=False),
        sa.Column("structured_json", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("source_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("ai_job_id", sa.String(36), nullable=True),
        sa.Column("ai_model", sa.String(120), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("corrected_by_user", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workbench_plan_id"], ["attachment_workbench_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ai_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("workbench_plan_id", "version_number", name="uq_attachment_product_lock_version"),
        )
    if "ix_attachment_product_lock_plan" not in {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes("attachment_product_identity_lock_versions")}:
        op.create_index("ix_attachment_product_lock_plan", "attachment_product_identity_lock_versions", ["organization_id", "workbench_plan_id", "version_number"])
    plan_columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("attachment_workbench_plans")}
    if "current_product_identity_lock_version_id" not in plan_columns:
        op.add_column("attachment_workbench_plans", sa.Column("current_product_identity_lock_version_id", sa.String(36), nullable=True))
    if "fk_attachment_plan_product_lock" not in {item.get("name") for item in sa.inspect(op.get_bind()).get_foreign_keys("attachment_workbench_plans")}:
        op.create_foreign_key("fk_attachment_plan_product_lock", "attachment_workbench_plans", "attachment_product_identity_lock_versions", ["current_product_identity_lock_version_id"], ["id"], ondelete="SET NULL")
    plan_version_columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("attachment_workbench_plan_versions")}
    if "reference_library_snapshot" not in plan_version_columns:
        op.add_column("attachment_workbench_plan_versions", sa.Column("reference_library_snapshot", sa.JSON(), nullable=False, server_default=sa.text("('[]')")))
    if "product_identity_lock_version_id" not in plan_version_columns:
        op.add_column("attachment_workbench_plan_versions", sa.Column("product_identity_lock_version_id", sa.String(36), nullable=True))
    if "fk_attachment_plan_version_product_lock" not in {item.get("name") for item in sa.inspect(op.get_bind()).get_foreign_keys("attachment_workbench_plan_versions")}:
        op.create_foreign_key("fk_attachment_plan_version_product_lock", "attachment_workbench_plan_versions", "attachment_product_identity_lock_versions", ["product_identity_lock_version_id"], ["id"], ondelete="SET NULL")

    _seed_phase10_ai_routing()


def _seed_phase10_ai_routing() -> None:
    """Seed the verified Mini route without duplicating providers or API keys."""
    connection = op.get_bind()
    now = datetime.now(timezone.utc)
    task_operations = (
        "listing.reference_analyze",
        "listing.reference_library_analyze",
        "listing.product_identity_extract",
        "listing.model_reference_analyze",
    )
    source_rows = connection.execute(sa.text("""
        SELECT DISTINCT
               p.id AS provider_id, p.code AS provider_code,
               m.config AS model_config,
               rp.id AS source_pool_id, rp.organization_id,
               rp.priority, rp.weight, rp.created_by, rp.updated_by
        FROM operation_resource_pools binding
        JOIN resource_pools rp ON rp.id = binding.resource_pool_id AND rp.enabled = 1
        JOIN models m ON m.id = rp.model_id AND m.enabled = 1
        JOIN providers p ON p.id = m.provider_id AND p.enabled = 1
        WHERE binding.operation_code = 'listing.plan'
          AND binding.required_capability = 'text_generation'
          AND binding.enabled = 1
    """)).mappings().all()

    for source in source_rows:
        model_id = connection.execute(sa.text("""
            SELECT id FROM models
            WHERE provider_id = :provider_id AND code = 'gpt-5.4-mini'
            LIMIT 1
        """), {"provider_id": source["provider_id"]}).scalar_one_or_none()
        if model_id is None:
            model_id = str(uuid4())
            model_config = source["model_config"] or {}
            if isinstance(model_config, str):
                try:
                    model_config = json.loads(model_config)
                except (TypeError, ValueError):
                    model_config = {}
            model_config = {**model_config, "phase10_seeded": True}
            connection.execute(sa.text("""
                INSERT INTO models (
                    id, provider_id, code, upstream_model, name, enabled, config,
                    created_by, updated_by, created_at, updated_at
                ) VALUES (
                    :id, :provider_id, 'gpt-5.4-mini', 'gpt-5.4-mini',
                    'GPT-5.4 Mini', 1, :config,
                    :created_by, :updated_by, :created_at, :updated_at
                )
            """), {
                "id": model_id,
                "provider_id": source["provider_id"],
                "config": json.dumps(model_config, ensure_ascii=False),
                "created_by": source["created_by"],
                "updated_by": source["updated_by"],
                "created_at": now,
                "updated_at": now,
            })

        for capability in ("text_generation", "vision_input"):
            exists = connection.execute(sa.text("""
                SELECT id FROM model_capabilities
                WHERE model_id = :model_id AND capability = :capability LIMIT 1
            """), {"model_id": model_id, "capability": capability}).scalar_one_or_none()
            if exists is None:
                connection.execute(sa.text("""
                    INSERT INTO model_capabilities (id, model_id, capability, created_by, created_at)
                    VALUES (:id, :model_id, :capability, :created_by, :created_at)
                """), {
                    "id": str(uuid4()), "model_id": model_id, "capability": capability,
                    "created_by": source["created_by"], "created_at": now,
                })

        pool_code = f"p10-{source['provider_code']}-mini"[:100]
        pool_id = connection.execute(sa.text("""
            SELECT id FROM resource_pools
            WHERE organization_id <=> :organization_id AND code = :pool_code
            LIMIT 1
        """), {
            "organization_id": source["organization_id"], "pool_code": pool_code,
        }).scalar_one_or_none()
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
                "code": pool_code, "name": f"{source['provider_code']} Phase 10 Mini",
                "priority": source["priority"], "weight": source["weight"],
                "created_by": source["created_by"], "updated_by": source["updated_by"],
                "created_at": now, "updated_at": now,
            })

        source_keys = connection.execute(sa.text("""
            SELECT api_key_id, enabled, priority, weight, created_by, updated_by
            FROM resource_pool_keys WHERE resource_pool_id = :source_pool_id
        """), {"source_pool_id": source["source_pool_id"]}).mappings().all()
        for key in source_keys:
            exists = connection.execute(sa.text("""
                SELECT id FROM resource_pool_keys
                WHERE resource_pool_id = :pool_id AND api_key_id = :api_key_id LIMIT 1
            """), {"pool_id": pool_id, "api_key_id": key["api_key_id"]}).scalar_one_or_none()
            if exists is None:
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

        for operation_code in task_operations:
            exists = connection.execute(sa.text("""
                SELECT id FROM operation_resource_pools
                WHERE organization_id <=> :organization_id
                  AND operation_code = :operation_code
                  AND resource_pool_id = :pool_id
                  AND required_capability = 'text_generation'
                LIMIT 1
            """), {
                "organization_id": source["organization_id"],
                "operation_code": operation_code,
                "pool_id": pool_id,
            }).scalar_one_or_none()
            if exists is None:
                connection.execute(sa.text("""
                    INSERT INTO operation_resource_pools (
                        id, organization_id, operation_code, resource_pool_id,
                        required_capability, enabled, priority,
                        created_by, updated_by, created_at, updated_at
                    ) VALUES (
                        :id, :organization_id, :operation_code, :pool_id,
                        'text_generation', 1, :priority,
                        :created_by, :updated_by, :created_at, :updated_at
                    )
                """), {
                    "id": str(uuid4()), "organization_id": source["organization_id"],
                    "operation_code": operation_code, "pool_id": pool_id,
                    "priority": source["priority"], "created_by": source["created_by"],
                    "updated_by": source["updated_by"], "created_at": now, "updated_at": now,
                })

    for operation_code in task_operations:
        connection.execute(sa.text("""
            INSERT INTO quota_rules (
                id, organization_id, operation_code, name, base_cost, model_multipliers,
                quality_multipliers, resolution_multipliers, resource_pool_multipliers,
                enabled, effective_from, effective_to, created_by, updated_by, created_at, updated_at
            )
            SELECT UUID(), source.organization_id, :operation_code, :name,
                   source.base_cost, source.model_multipliers, source.quality_multipliers,
                   source.resolution_multipliers, source.resource_pool_multipliers,
                   source.enabled, source.effective_from, source.effective_to,
                   source.created_by, source.updated_by, :now, :now
            FROM quota_rules source
            WHERE source.operation_code = 'listing.plan'
              AND NOT EXISTS (
                  SELECT 1 FROM quota_rules target
                  WHERE target.operation_code = :operation_code
                    AND target.organization_id <=> source.organization_id
                    AND target.effective_from = source.effective_from
              )
        """), {
            "operation_code": operation_code,
            "name": f"Phase 10 AI task: {operation_code}",
            "now": now,
        })


def downgrade() -> None:
    connection = op.get_bind()
    task_operations = (
        "listing.reference_analyze",
        "listing.reference_library_analyze",
        "listing.product_identity_extract",
        "listing.model_reference_analyze",
    )
    connection.execute(
        sa.text("DELETE FROM quota_rules WHERE operation_code IN :operation_codes")
        .bindparams(sa.bindparam("operation_codes", expanding=True)),
        {"operation_codes": task_operations},
    )
    connection.execute(
        sa.text("DELETE FROM operation_resource_pools WHERE operation_code IN :operation_codes")
        .bindparams(sa.bindparam("operation_codes", expanding=True)),
        {"operation_codes": task_operations},
    )
    connection.execute(sa.text("DELETE FROM resource_pools WHERE code LIKE 'p10-%-mini'"))
    connection.execute(sa.text("""
        DELETE FROM models
        WHERE code = 'gpt-5.4-mini'
          AND JSON_EXTRACT(config, '$.phase10_seeded') = true
    """))
    op.drop_constraint("fk_attachment_plan_version_product_lock", "attachment_workbench_plan_versions", type_="foreignkey")
    op.drop_column("attachment_workbench_plan_versions", "product_identity_lock_version_id")
    op.drop_column("attachment_workbench_plan_versions", "reference_library_snapshot")
    op.drop_constraint("fk_attachment_plan_product_lock", "attachment_workbench_plans", type_="foreignkey")
    op.drop_column("attachment_workbench_plans", "current_product_identity_lock_version_id")
    op.drop_index("ix_attachment_product_lock_plan", table_name="attachment_product_identity_lock_versions")
    op.drop_table("attachment_product_identity_lock_versions")
    for name in ("guidance_snapshot", "keywords_snapshot", "role_snapshot", "analysis_prompt_version", "analysis_model_config", "analysis_task_type", "input_hash"):
        op.drop_column("attachment_reference_understandings", name)
    op.drop_constraint("fk_attachment_module_reference_library", "attachment_module_references", type_="foreignkey")
    op.drop_column("attachment_module_references", "guidance")
    op.drop_column("attachment_module_references", "keywords")
    op.drop_column("attachment_module_references", "library_item_id")
    op.drop_index("ix_attachment_library_understanding_item", table_name="attachment_reference_library_understandings")
    op.drop_table("attachment_reference_library_understandings")
    op.drop_index("ix_attachment_reference_library_browse", table_name="attachment_reference_library_items")
    op.drop_table("attachment_reference_library_items")
    op.drop_constraint("uq_attachment_plan_model_scope_slot", "attachment_plan_model_selections", type_="unique")
    if "ix_attachment_plan_models_scope" in {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes("attachment_plan_model_selections")}:
        op.drop_index("ix_attachment_plan_models_scope", table_name="attachment_plan_model_selections")
    op.execute("DELETE FROM attachment_plan_model_selections WHERE model_preset_id IS NULL OR identity_version_id IS NULL")
    op.alter_column("attachment_plan_model_selections", "identity_version_id", existing_type=sa.String(36), nullable=False)
    op.alter_column("attachment_plan_model_selections", "model_preset_id", existing_type=sa.String(36), nullable=False)
    op.drop_column("attachment_plan_model_selections", "selection_mode")
    op.drop_column("attachment_plan_model_selections", "module_key")
    op.create_unique_constraint("uq_attachment_plan_model_slot", "attachment_plan_model_selections", ["workbench_plan_id", "product_slot"])
    if "ix_attachment_plan_models_plan" not in {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes("attachment_plan_model_selections")}:
        op.create_index("ix_attachment_plan_models_plan", "attachment_plan_model_selections", ["workbench_plan_id", "product_slot"])
    op.drop_constraint("fk_ai_model_presets_owner_user", "ai_model_presets", type_="foreignkey")
    op.drop_column("ai_model_presets", "generation_parameters")
    op.drop_column("ai_model_presets", "owner_user_id")
    op.drop_column("ai_model_presets", "source_type")
