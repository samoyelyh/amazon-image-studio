"""add multi-module reference library and attachment output edit lineage

Revision ID: 0058_attachment_output_edits
Revises: 0057_attachment_dependencies
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0058_attachment_output_edits"
down_revision: str | None = "0057_attachment_dependencies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachment_reference_library_item_modules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("library_item_id", sa.String(length=36), nullable=False),
        sa.Column("module_key", sa.String(length=60), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["library_item_id"], ["attachment_reference_library_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("library_item_id", "module_key", name="uq_attachment_library_item_module"),
    )
    op.create_index("ix_attachment_library_module_browse", "attachment_reference_library_item_modules", ["organization_id", "module_key", "library_item_id"])
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, organization_id, module_key, created_by, created_at, updated_at FROM attachment_reference_library_items")).mappings()
    for row in rows:
        bind.execute(sa.text(
            "INSERT INTO attachment_reference_library_item_modules "
            "(id, organization_id, library_item_id, module_key, created_by, created_at, updated_at) "
            "VALUES (:id, :organization_id, :library_item_id, :module_key, :created_by, :created_at, :updated_at)"
        ), {"id": str(__import__("uuid").uuid4()), "organization_id": row["organization_id"], "library_item_id": row["id"],
            "module_key": row["module_key"], "created_by": row["created_by"], "created_at": row["created_at"], "updated_at": row["updated_at"]})

    op.create_table(
        "attachment_output_edit_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("listing_image_project_id", sa.String(length=36), nullable=False),
        sa.Column("module_key", sa.String(length=60), nullable=False),
        sa.Column("root_output_id", sa.String(length=36), nullable=False),
        sa.Column("parent_output_id", sa.String(length=36), nullable=False),
        sa.Column("result_output_id", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("batch_id", sa.String(length=36), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("edit_scope", sa.String(length=30), nullable=False, server_default="whole_image"),
        sa.Column("compiled_prompt", sa.Text(), nullable=False),
        sa.Column("explicit_overrides", sa.JSON(), nullable=False),
        sa.Column("override_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("product_identity_lock_version_id", sa.String(length=36), nullable=True),
        sa.Column("model_identity_snapshot", sa.JSON(), nullable=False),
        sa.Column("reference_snapshot", sa.JSON(), nullable=False),
        sa.Column("execution_snapshot", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_image_project_id"], ["listing_image_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["root_output_id"], ["generated_outputs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_output_id"], ["generated_outputs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["result_output_id"], ["generated_outputs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["batch_id"], ["job_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_identity_lock_version_id"], ["attachment_product_identity_lock_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_attachment_output_edit_job"),
    )
    op.create_index("ix_attachment_output_edits_project_root", "attachment_output_edit_revisions", ["organization_id", "listing_image_project_id", "root_output_id"])
    op.create_index("ix_attachment_output_edits_parent", "attachment_output_edit_revisions", ["organization_id", "parent_output_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_attachment_output_edits_parent", table_name="attachment_output_edit_revisions")
    op.drop_index("ix_attachment_output_edits_project_root", table_name="attachment_output_edit_revisions")
    op.drop_table("attachment_output_edit_revisions")
    op.drop_index("ix_attachment_library_module_browse", table_name="attachment_reference_library_item_modules")
    op.drop_table("attachment_reference_library_item_modules")
