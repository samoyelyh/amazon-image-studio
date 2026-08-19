"""add attachment workbench planning versions

Revision ID: 0047_attachment_planning
Revises: 0046_job_batch_history
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0047_attachment_planning"
down_revision: str | None = "0046_job_batch_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachment_workbench_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("listing_image_project_id", sa.String(36), sa.ForeignKey("listing_image_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("listing_generation_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("listing_version_id", sa.String(36), sa.ForeignKey("listing_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("skill_version_id", sa.String(36), sa.ForeignKey("category_skill_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("visual_direction_cn", sa.Text(), nullable=False),
        sa.Column("visual_direction_source", sa.String(40), nullable=False, server_default="none"),
        sa.Column("visual_direction_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planning_job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("planning_status", sa.String(30), nullable=False, server_default="idle"),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("listing_image_project_id", name="uq_attachment_workbench_plan_project"),
    )
    op.create_index("ix_attachment_workbench_plans_org_project", "attachment_workbench_plans", ["organization_id", "listing_image_project_id"])
    op.create_table(
        "attachment_workbench_module_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workbench_plan_id", sa.String(36), sa.ForeignKey("attachment_workbench_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_key", sa.String(60), nullable=False),
        sa.Column("plan_summary_cn", sa.Text(), nullable=False),
        sa.Column("prompt_cn", sa.Text(), nullable=False),
        sa.Column("operator_requirement_cn", sa.Text(), nullable=False),
        sa.Column("aspect_ratio", sa.String(20), nullable=False),
        sa.Column("source", sa.String(40), nullable=False, server_default="none"),
        sa.Column("current_version_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planning_job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workbench_plan_id", "module_key", name="uq_attachment_module_plan_key"),
    )
    op.create_index("ix_attachment_module_plans_org_plan", "attachment_workbench_module_plans", ["organization_id", "workbench_plan_id"])
    op.create_table(
        "attachment_workbench_plan_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workbench_plan_id", sa.String(36), sa.ForeignKey("attachment_workbench_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_plan_id", sa.String(36), sa.ForeignKey("attachment_workbench_module_plans.id", ondelete="CASCADE"), nullable=True),
        sa.Column("version_scope", sa.String(80), nullable=False),
        sa.Column("module_key", sa.String(60), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("visual_direction_cn", sa.Text(), nullable=True),
        sa.Column("plan_summary_cn", sa.Text(), nullable=True),
        sa.Column("prompt_cn", sa.Text(), nullable=True),
        sa.Column("operator_requirement_cn", sa.Text(), nullable=False),
        sa.Column("aspect_ratio", sa.String(20), nullable=True),
        sa.Column("selected_module_keys", sa.JSON(), nullable=False),
        sa.Column("skill_version_id", sa.String(36), sa.ForeignKey("category_skill_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_rule_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_version_id", sa.String(36), sa.ForeignKey("attachment_workbench_plan_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ai_job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ai_model", sa.String(120), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workbench_plan_id", "version_scope", "version_number", name="uq_attachment_plan_version_scope"),
    )
    op.create_index("ix_attachment_plan_versions_org_plan", "attachment_workbench_plan_versions", ["organization_id", "workbench_plan_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_attachment_plan_versions_org_plan", table_name="attachment_workbench_plan_versions")
    op.drop_table("attachment_workbench_plan_versions")
    op.drop_index("ix_attachment_module_plans_org_plan", table_name="attachment_workbench_module_plans")
    op.drop_table("attachment_workbench_module_plans")
    op.drop_index("ix_attachment_workbench_plans_org_project", table_name="attachment_workbench_plans")
    op.drop_table("attachment_workbench_plans")
