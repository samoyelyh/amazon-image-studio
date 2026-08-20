"""add creative attachment generation lineage

Revision ID: 0051_attachment_creative
Revises: 0050_attachment_output_review
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0051_attachment_creative"
down_revision: str | None = "0050_attachment_output_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(item["name"] == column_name for item in inspector.get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(item["name"] == index_name for item in inspector.get_indexes(table_name))


def _foreign_key_exists(table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(item["name"] == constraint_name for item in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    module_table = "attachment_workbench_module_plans"
    version_table = "attachment_workbench_plan_versions"
    if not _column_exists(module_table, "derived_from_output_id"):
        op.add_column(module_table, sa.Column("derived_from_output_id", sa.String(36), nullable=True))
    if not _foreign_key_exists(module_table, "fk_attachment_module_plan_derived_output"):
        op.create_foreign_key(
            "fk_attachment_module_plan_derived_output", module_table, "generated_outputs",
            ["derived_from_output_id"], ["id"], ondelete="SET NULL",
        )
    if not _index_exists(module_table, "ix_attachment_module_plans_derived_output"):
        op.create_index("ix_attachment_module_plans_derived_output", module_table, ["derived_from_output_id"])

    if not _column_exists(version_table, "generation_mode"):
        op.add_column(version_table, sa.Column(
            "generation_mode", sa.String(20), nullable=False, server_default="standard",
        ))
    if not _column_exists(version_table, "creative_direction_index"):
        op.add_column(version_table, sa.Column("creative_direction_index", sa.Integer(), nullable=True))
    if not _column_exists(version_table, "derived_from_output_id"):
        op.add_column(version_table, sa.Column("derived_from_output_id", sa.String(36), nullable=True))
    if not _foreign_key_exists(version_table, "fk_attachment_plan_version_derived_output"):
        op.create_foreign_key(
            "fk_attachment_plan_version_derived_output", version_table, "generated_outputs",
            ["derived_from_output_id"], ["id"], ondelete="SET NULL",
        )
    if not _index_exists(version_table, "ix_attachment_plan_versions_creative"):
        op.create_index(
            "ix_attachment_plan_versions_creative", version_table,
            ["organization_id", "module_plan_id", "generation_mode", "created_at"],
        )
    if not _index_exists(version_table, "ix_attachment_plan_versions_derived_output"):
        op.create_index("ix_attachment_plan_versions_derived_output", version_table, ["derived_from_output_id"])


def downgrade() -> None:
    module_table = "attachment_workbench_module_plans"
    version_table = "attachment_workbench_plan_versions"
    if _index_exists(version_table, "ix_attachment_plan_versions_derived_output"):
        op.drop_index("ix_attachment_plan_versions_derived_output", table_name=version_table)
    if _index_exists(version_table, "ix_attachment_plan_versions_creative"):
        op.drop_index("ix_attachment_plan_versions_creative", table_name=version_table)
    if _foreign_key_exists(version_table, "fk_attachment_plan_version_derived_output"):
        op.drop_constraint("fk_attachment_plan_version_derived_output", version_table, type_="foreignkey")
    if _column_exists(version_table, "derived_from_output_id"):
        op.drop_column(version_table, "derived_from_output_id")
    if _column_exists(version_table, "creative_direction_index"):
        op.drop_column(version_table, "creative_direction_index")
    if _column_exists(version_table, "generation_mode"):
        op.drop_column(version_table, "generation_mode")

    if _index_exists(module_table, "ix_attachment_module_plans_derived_output"):
        op.drop_index("ix_attachment_module_plans_derived_output", table_name=module_table)
    if _foreign_key_exists(module_table, "fk_attachment_module_plan_derived_output"):
        op.drop_constraint("fk_attachment_module_plan_derived_output", module_table, type_="foreignkey")
    if _column_exists(module_table, "derived_from_output_id"):
        op.drop_column(module_table, "derived_from_output_id")
