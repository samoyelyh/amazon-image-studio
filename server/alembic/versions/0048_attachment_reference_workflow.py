"""add attachment reference workflow

Revision ID: 0048_attachment_references
Revises: 0047_attachment_planning
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0048_attachment_references"
down_revision: str | None = "0047_attachment_planning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attachment_workbench_module_plans", sa.Column("reference_context_dirty", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("attachment_workbench_module_plans", sa.Column("reference_state_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("attachment_workbench_module_plans", sa.Column("reference_analysis_job_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_attachment_module_reference_analysis_job", "attachment_workbench_module_plans", "jobs",
        ["reference_analysis_job_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "attachment_product_reference_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workbench_plan_id", sa.String(36), sa.ForeignKey("attachment_workbench_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workbench_plan_id", name="uq_attachment_product_group_plan"),
    )
    op.create_index("ix_attachment_product_groups_org_plan", "attachment_product_reference_groups", ["organization_id", "workbench_plan_id"])

    op.create_table(
        "attachment_product_reference_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_group_id", sa.String(36), sa.ForeignKey("attachment_product_reference_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_asset_id", sa.String(36), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("view_role", sa.String(20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(30), nullable=False, server_default="session"),
        sa.Column("transform_metadata", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("product_group_id", "asset_id", "view_role", name="uq_attachment_product_item_role"),
    )
    op.create_index("ix_attachment_product_items_org_group", "attachment_product_reference_items", ["organization_id", "product_group_id", "sort_order"])

    op.create_table(
        "attachment_module_references",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_plan_id", sa.String(36), sa.ForeignKey("attachment_workbench_module_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slot_type", sa.String(20), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("module_plan_id", "slot_type", "asset_id", name="uq_attachment_module_reference_asset"),
    )
    op.create_index("ix_attachment_module_refs_org_module", "attachment_module_references", ["organization_id", "module_plan_id", "slot_type", "sort_order"])

    op.create_table(
        "attachment_reference_understandings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_plan_id", sa.String(36), sa.ForeignKey("attachment_workbench_module_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="analyzing"),
        sa.Column("structured_json", sa.JSON(), nullable=False),
        sa.Column("source_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("ai_job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ai_model", sa.String(120), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("module_plan_id", "version_number", name="uq_attachment_understanding_version"),
    )
    op.create_index("ix_attachment_understandings_org_module", "attachment_reference_understandings", ["organization_id", "module_plan_id", "version_number"])

    op.add_column("attachment_workbench_plan_versions", sa.Column("reference_understanding_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_attachment_plan_version_understanding", "attachment_workbench_plan_versions",
        "attachment_reference_understandings", ["reference_understanding_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_attachment_plan_version_understanding", "attachment_workbench_plan_versions", type_="foreignkey")
    op.drop_column("attachment_workbench_plan_versions", "reference_understanding_id")
    op.drop_index("ix_attachment_understandings_org_module", table_name="attachment_reference_understandings")
    op.drop_table("attachment_reference_understandings")
    op.drop_index("ix_attachment_module_refs_org_module", table_name="attachment_module_references")
    op.drop_table("attachment_module_references")
    op.drop_index("ix_attachment_product_items_org_group", table_name="attachment_product_reference_items")
    op.drop_table("attachment_product_reference_items")
    op.drop_index("ix_attachment_product_groups_org_plan", table_name="attachment_product_reference_groups")
    op.drop_table("attachment_product_reference_groups")
    op.drop_constraint("fk_attachment_module_reference_analysis_job", "attachment_workbench_module_plans", type_="foreignkey")
    op.drop_column("attachment_workbench_module_plans", "reference_analysis_job_id")
    op.drop_column("attachment_workbench_module_plans", "reference_state_version")
    op.drop_column("attachment_workbench_module_plans", "reference_context_dirty")
