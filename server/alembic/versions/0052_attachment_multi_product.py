"""add attachment multi-product composition

Revision ID: 0052_attachment_multi_product
Revises: 0051_attachment_creative
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0052_attachment_multi_product"
down_revision: str | None = "0051_attachment_creative"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    return any(item["name"] == column_name for item in sa.inspect(op.get_bind()).get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(item["name"] == index_name for item in sa.inspect(op.get_bind()).get_indexes(table_name))


def _foreign_key_exists(table_name: str, constraint_name: str) -> bool:
    return any(item["name"] == constraint_name for item in sa.inspect(op.get_bind()).get_foreign_keys(table_name))


def upgrade() -> None:
    if not _table_exists("attachment_product_compositions"):
        op.create_table(
            "attachment_product_compositions",
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("module_plan_id", sa.String(36), nullable=False),
            sa.Column("mode", sa.String(20), nullable=False, server_default="SINGLE"),
            sa.Column("current_version_number", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(36), nullable=False),
            sa.Column("updated_by", sa.String(36), nullable=False),
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["module_plan_id"], ["attachment_workbench_module_plans.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("module_plan_id", name="uq_attachment_product_composition_module"),
        )
        op.create_index(
            "ix_attachment_product_compositions_org_module", "attachment_product_compositions",
            ["organization_id", "module_plan_id"],
        )

    if not _table_exists("attachment_product_composition_items"):
        op.create_table(
            "attachment_product_composition_items",
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("composition_id", sa.String(36), nullable=False),
            sa.Column("product_role", sa.String(20), nullable=False),
            sa.Column("source_session_id", sa.String(36), nullable=False),
            sa.Column("source_project_id", sa.String(36), nullable=True),
            sa.Column("display_name_snapshot", sa.String(500), nullable=False, server_default=""),
            sa.Column("category_name_snapshot", sa.String(200), nullable=False, server_default=""),
            sa.Column("display_order", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(36), nullable=False),
            sa.Column("updated_by", sa.String(36), nullable=False),
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["composition_id"], ["attachment_product_compositions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_session_id"], ["listing_generation_sessions.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["source_project_id"], ["projects.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("composition_id", "source_session_id", name="uq_attachment_product_composition_session"),
            sa.UniqueConstraint(
                "composition_id", "product_role", "display_order",
                name="uq_attachment_product_composition_role_order",
            ),
        )
        op.create_index(
            "ix_attachment_product_composition_items_org_composition", "attachment_product_composition_items",
            ["organization_id", "composition_id", "display_order"],
        )

    if not _table_exists("attachment_product_composition_assets"):
        op.create_table(
            "attachment_product_composition_assets",
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("composition_item_id", sa.String(36), nullable=False),
            sa.Column("asset_id", sa.String(36), nullable=False),
            sa.Column("source_asset_id", sa.String(36), nullable=True),
            sa.Column("view_role", sa.String(20), nullable=False, server_default="front"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(36), nullable=False),
            sa.Column("updated_by", sa.String(36), nullable=False),
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["composition_item_id"], ["attachment_product_composition_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["source_asset_id"], ["assets.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "composition_item_id", "asset_id", "view_role",
                name="uq_attachment_product_composition_asset_role",
            ),
        )
        op.create_index(
            "ix_attachment_product_composition_assets_org_item", "attachment_product_composition_assets",
            ["organization_id", "composition_item_id", "sort_order"],
        )

    if not _table_exists("attachment_product_composition_versions"):
        op.create_table(
            "attachment_product_composition_versions",
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("composition_id", sa.String(36), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(36), nullable=False),
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["composition_id"], ["attachment_product_compositions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("composition_id", "version_number", name="uq_attachment_product_composition_version"),
        )
        op.create_index(
            "ix_attachment_product_composition_versions_org_composition", "attachment_product_composition_versions",
            ["organization_id", "composition_id", "version_number"],
        )

    plan_versions = "attachment_workbench_plan_versions"
    if not _column_exists(plan_versions, "product_composition_version_id"):
        op.add_column(plan_versions, sa.Column("product_composition_version_id", sa.String(36), nullable=True))
    if not _foreign_key_exists(plan_versions, "fk_attachment_plan_version_product_composition"):
        op.create_foreign_key(
            "fk_attachment_plan_version_product_composition", plan_versions,
            "attachment_product_composition_versions", ["product_composition_version_id"], ["id"], ondelete="SET NULL",
        )
    if not _index_exists(plan_versions, "ix_attachment_plan_versions_product_composition"):
        op.create_index(
            "ix_attachment_plan_versions_product_composition", plan_versions, ["product_composition_version_id"],
        )

    understandings = "attachment_reference_understandings"
    if not _column_exists(understandings, "product_composition_version_id"):
        op.add_column(understandings, sa.Column("product_composition_version_id", sa.String(36), nullable=True))
    if not _foreign_key_exists(understandings, "fk_attachment_understanding_product_composition"):
        op.create_foreign_key(
            "fk_attachment_understanding_product_composition", understandings,
            "attachment_product_composition_versions", ["product_composition_version_id"], ["id"], ondelete="SET NULL",
        )
    if not _index_exists(understandings, "ix_attachment_understandings_product_composition"):
        op.create_index(
            "ix_attachment_understandings_product_composition", understandings, ["product_composition_version_id"],
        )


def downgrade() -> None:
    understandings = "attachment_reference_understandings"
    if _index_exists(understandings, "ix_attachment_understandings_product_composition"):
        op.drop_index("ix_attachment_understandings_product_composition", table_name=understandings)
    if _foreign_key_exists(understandings, "fk_attachment_understanding_product_composition"):
        op.drop_constraint("fk_attachment_understanding_product_composition", understandings, type_="foreignkey")
    if _column_exists(understandings, "product_composition_version_id"):
        op.drop_column(understandings, "product_composition_version_id")

    plan_versions = "attachment_workbench_plan_versions"
    if _index_exists(plan_versions, "ix_attachment_plan_versions_product_composition"):
        op.drop_index("ix_attachment_plan_versions_product_composition", table_name=plan_versions)
    if _foreign_key_exists(plan_versions, "fk_attachment_plan_version_product_composition"):
        op.drop_constraint("fk_attachment_plan_version_product_composition", plan_versions, type_="foreignkey")
    if _column_exists(plan_versions, "product_composition_version_id"):
        op.drop_column(plan_versions, "product_composition_version_id")

    for table_name in (
        "attachment_product_composition_versions",
        "attachment_product_composition_assets",
        "attachment_product_composition_items",
        "attachment_product_compositions",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name)
