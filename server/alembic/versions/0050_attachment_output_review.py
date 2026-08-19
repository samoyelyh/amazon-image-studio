"""add attachment output review and final state

Revision ID: 0050_attachment_output_review
Revises: 0049_account_identity
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0050_attachment_output_review"
down_revision: str | None = "0049_account_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generated_outputs", sa.Column(
        "review_status", sa.String(30), nullable=False, server_default="pending_review",
    ))
    op.add_column("generated_outputs", sa.Column(
        "review_state_version", sa.Integer(), nullable=False, server_default="0",
    ))
    op.add_column("generated_outputs", sa.Column("reviewed_by", sa.String(36), nullable=True))
    op.add_column("generated_outputs", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("generated_outputs", sa.Column("discarded_by", sa.String(36), nullable=True))
    op.add_column("generated_outputs", sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_generated_outputs_reviewed_by", "generated_outputs", "users", ["reviewed_by"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_generated_outputs_discarded_by", "generated_outputs", "users", ["discarded_by"], ["id"], ondelete="SET NULL")
    op.create_index("ix_generated_outputs_review_status", "generated_outputs", ["organization_id", "review_status", "created_at"])
    op.create_index("ix_generated_outputs_discarded_at", "generated_outputs", ["organization_id", "discarded_at"])

    op.create_table(
        "attachment_module_result_states",
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("listing_image_project_id", sa.String(36), nullable=False),
        sa.Column("module_key", sa.String(60), nullable=False),
        sa.Column("current_final_output_id", sa.String(36), nullable=True),
        sa.Column("results_cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_image_project_id"], ["listing_image_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_final_output_id"], ["generated_outputs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_image_project_id", "module_key", name="uq_attachment_result_state_project_module"),
    )
    op.create_index(
        "ix_attachment_result_states_org_project", "attachment_module_result_states",
        ["organization_id", "listing_image_project_id"],
    )

    # All six state rows exist before any review command, so concurrent Final
    # changes serialize on a stable row instead of racing to insert it.
    bind = op.get_bind()
    module_keys = ("pure_white", "custom_process", "stadium_scene", "gift_scene", "detail_display", "casual_scene")
    projects = bind.execute(sa.text(
        "SELECT id, organization_id, created_by, updated_by FROM listing_image_projects"
    )).mappings().all()
    import uuid
    for project in projects:
        for module_key in module_keys:
            bind.execute(sa.text(
                "INSERT INTO attachment_module_result_states "
                "(id, organization_id, listing_image_project_id, module_key, state_version, created_by, updated_by, created_at, updated_at) "
                "VALUES (:id, :organization_id, :project_id, :module_key, 0, :created_by, :updated_by, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ), {
                "id": str(uuid.uuid4()), "organization_id": project["organization_id"],
                "project_id": project["id"], "module_key": module_key,
                "created_by": project["created_by"], "updated_by": project["updated_by"],
            })


def downgrade() -> None:
    op.drop_index("ix_attachment_result_states_org_project", table_name="attachment_module_result_states")
    op.drop_table("attachment_module_result_states")
    op.drop_index("ix_generated_outputs_discarded_at", table_name="generated_outputs")
    op.drop_index("ix_generated_outputs_review_status", table_name="generated_outputs")
    op.drop_constraint("fk_generated_outputs_discarded_by", "generated_outputs", type_="foreignkey")
    op.drop_constraint("fk_generated_outputs_reviewed_by", "generated_outputs", type_="foreignkey")
    op.drop_column("generated_outputs", "discarded_at")
    op.drop_column("generated_outputs", "discarded_by")
    op.drop_column("generated_outputs", "reviewed_at")
    op.drop_column("generated_outputs", "reviewed_by")
    op.drop_column("generated_outputs", "review_state_version")
    op.drop_column("generated_outputs", "review_status")
