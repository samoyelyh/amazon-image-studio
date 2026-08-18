"""add print design asset library

Revision ID: 0044_print_design_library
Revises: 0043_batch_region_replace
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0044_print_design_library"
down_revision: str | None = "0043_batch_region_replace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "print_asset_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("product_type", sa.String(100), nullable=True),
        sa.Column("remark", sa.String(500), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_print_asset_groups_org_code"),
    )
    op.create_index("ix_print_asset_groups_org_name", "print_asset_groups", ["organization_id", "name"])
    op.create_table(
        "print_asset_library_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("asset_group_id", sa.String(36), sa.ForeignKey("print_asset_groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("asset_code", sa.String(120), nullable=False),
        sa.Column("asset_name", sa.String(180), nullable=False),
        sa.Column("asset_type", sa.String(40), nullable=False, server_default="print"),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("default_position_json", sa.JSON(), nullable=True),
        sa.Column("allow_rotate", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_stretch", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("keep_ratio_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "asset_code", "version", name="uq_print_assets_org_code_version"),
    )
    op.create_index("ix_print_assets_org_group", "print_asset_library_items", ["organization_id", "asset_group_id"])
    op.create_index("ix_print_assets_org_status", "print_asset_library_items", ["organization_id", "status"])
    op.create_table(
        "product_print_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku", sa.String(160), nullable=False),
        sa.Column("product_code", sa.String(160), nullable=True),
        sa.Column("style_code", sa.String(160), nullable=True),
        sa.Column("template_code", sa.String(160), nullable=True),
        sa.Column("asset_group_id", sa.String(36), sa.ForeignKey("print_asset_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "sku", "asset_group_id", name="uq_product_print_mappings_org_sku_group"),
    )
    op.create_index("ix_product_print_mappings_org_sku", "product_print_mappings", ["organization_id", "sku"])
    connection = op.get_bind()
    for operation_code in ("print_design.replace", "print_design.blend"):
        connection.execute(sa.text("""
            INSERT INTO operation_resource_pools (
                id, organization_id, operation_code, resource_pool_id, required_capability,
                enabled, priority, created_by, updated_by, created_at, updated_at
            )
            SELECT UUID(), source.organization_id, :operation_code, source.resource_pool_id, 'mask_edit',
                   source.enabled, source.priority, source.created_by, source.updated_by,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM operation_resource_pools source
            WHERE source.operation_code = 'batch_tryon.region_replace'
              AND source.required_capability = 'mask_edit'
              AND NOT EXISTS (
                  SELECT 1 FROM operation_resource_pools target
                  WHERE target.operation_code = :operation_code
                    AND target.resource_pool_id = source.resource_pool_id
                    AND target.required_capability = 'mask_edit'
                    AND target.organization_id <=> source.organization_id
              )
        """), {"operation_code": operation_code})
        connection.execute(sa.text("""
            INSERT INTO quota_rules (
                id, organization_id, operation_code, name, base_cost, model_multipliers,
                quality_multipliers, resolution_multipliers, resource_pool_multipliers,
                enabled, effective_from, effective_to, created_by, updated_by, created_at, updated_at
            )
            SELECT UUID(), source.organization_id, :operation_code, :name, source.base_cost,
                   source.model_multipliers, source.quality_multipliers, source.resolution_multipliers,
                   source.resource_pool_multipliers, source.enabled, source.effective_from,
                   source.effective_to, source.created_by, source.updated_by,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM quota_rules source
            WHERE source.operation_code = 'batch_tryon.region_replace'
              AND NOT EXISTS (
                  SELECT 1 FROM quota_rules target
                  WHERE target.operation_code = :operation_code
                    AND target.organization_id <=> source.organization_id
              )
        """), {"operation_code": operation_code, "name": "印花局部替换" if operation_code.endswith("replace") else "印花边缘融合"})


def downgrade() -> None:
    op.execute("DELETE FROM quota_rules WHERE operation_code IN ('print_design.replace', 'print_design.blend')")
    op.execute("DELETE FROM operation_resource_pools WHERE operation_code IN ('print_design.replace', 'print_design.blend')")
    op.drop_table("product_print_mappings")
    op.drop_table("print_asset_library_items")
    op.drop_table("print_asset_groups")
