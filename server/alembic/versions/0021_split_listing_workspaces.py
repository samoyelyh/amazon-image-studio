"""split category listing workflow into confirmed versions and isolated output projects

Revision ID: 0021_split_listing_workspaces
Revises: 0020_category_listing_workflow
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_split_listing_workspaces"
down_revision = "0020_category_listing_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("listing_generation_sessions", sa.Column("current_listing_version_id", sa.String(36), nullable=True))
    op.add_column("listing_generation_sessions", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("listing_generation_sessions", sa.Column("confirmed_by", sa.String(36), nullable=True))
    op.create_foreign_key("fk_listing_sessions_confirmed_by", "listing_generation_sessions", "users", ["confirmed_by"], ["id"], ondelete="SET NULL")

    op.create_table(
        "listing_versions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_listing_version_id", sa.String(36), nullable=True),
        sa.Column("listing_snapshot", sa.JSON(), nullable=False),
        sa.Column("analysis_snapshot", sa.JSON(), nullable=False),
        sa.Column("category_skill_snapshot", sa.JSON(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_by", sa.String(36), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["listing_generation_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_listing_version_id"], ["listing_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "version_number", name="uq_listing_versions_session_number"),
    )
    op.create_index("ix_listing_versions_org_session", "listing_versions", ["organization_id", "session_id"])
    op.create_foreign_key("fk_listing_sessions_current_version", "listing_generation_sessions", "listing_versions", ["current_listing_version_id"], ["id"], ondelete="SET NULL")

    for table_name, index_name in (
        ("listing_image_projects", "ix_listing_image_projects_org_status"),
        ("a_plus_projects", "ix_a_plus_projects_org_status"),
    ):
        columns = [
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("session_id", sa.String(36), nullable=False),
            sa.Column("listing_version_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("selected_template", sa.String(120), nullable=True),
        ]
        if table_name == "a_plus_projects":
            columns.append(sa.Column("modules", sa.JSON(), nullable=False))
        columns.extend([
            sa.Column("prompt_config", sa.JSON(), nullable=False),
            sa.Column("task_count", sa.Integer(), nullable=False),
            sa.Column("generated_asset_ids", sa.JSON(), nullable=False),
            sa.Column("last_batch_id", sa.String(36), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=False),
            sa.Column("updated_by", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["session_id"], ["listing_generation_sessions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["listing_version_id"], ["listing_versions.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["last_batch_id"], ["job_batches.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("session_id", name=f"uq_{table_name}_session"),
        ])
        op.create_table(table_name, *columns)
        op.create_index(index_name, table_name, ["organization_id", "status"])

    op.execute("UPDATE listing_generation_sessions SET status = 'generated' WHERE status = 'ready'")


def downgrade() -> None:
    op.drop_table("a_plus_projects")
    op.drop_table("listing_image_projects")
    op.drop_constraint("fk_listing_sessions_current_version", "listing_generation_sessions", type_="foreignkey")
    op.drop_table("listing_versions")
    op.drop_constraint("fk_listing_sessions_confirmed_by", "listing_generation_sessions", type_="foreignkey")
    op.drop_column("listing_generation_sessions", "confirmed_by")
    op.drop_column("listing_generation_sessions", "confirmed_at")
    op.drop_column("listing_generation_sessions", "current_listing_version_id")
