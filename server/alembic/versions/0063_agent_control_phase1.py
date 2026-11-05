"""Opt-in LangGraph control plane. Existing image task tables unchanged."""
from alembic import op
import sqlalchemy as sa

revision = "0063_agent_control"
down_revision = "0062_batch_queue_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("hermes_conversations", sa.Column("controller_type", sa.String(20), nullable=False, server_default="hermes"))
    op.add_column("hermes_conversations", sa.Column("context_project_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_hermes_context_project", "hermes_conversations", "projects", ["context_project_id"], ["id"], ondelete="CASCADE")
    for table in ("hermes_conversations", "hermes_proposals", "hermes_tool_audits"):
        op.alter_column(table, "listing_image_project_id", existing_type=sa.String(36), nullable=True)
    op.create_table("agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("hermes_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_message_id", sa.String(36), sa.ForeignKey("hermes_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("proposal_id", sa.String(36), sa.ForeignKey("hermes_proposals.id", ondelete="SET NULL")),
        sa.Column("client_request_id", sa.String(80), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("graph_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("planner_mode", sa.String(30), nullable=False),
        sa.Column("selection_json", sa.JSON(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("conversation_id", "client_request_id", name="uq_agent_run_client_request"))
    op.create_index("ix_agent_runs_owner_status", "agent_runs", ["organization_id", "user_id", "status"])
    op.create_table("agent_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "event_key", name="uq_agent_event_key"))
    op.create_table("agent_job_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.UniqueConstraint("run_id", "job_id", name="uq_agent_job_link"))


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT COUNT(*) FROM hermes_conversations WHERE controller_type='langgraph'")) or connection.scalar(sa.text("SELECT COUNT(*) FROM agent_runs")):
        raise RuntimeError("Export and explicitly remove Agent conversations before downgrade; no data will be discarded automatically.")
    op.drop_table("agent_job_links")
    op.drop_table("agent_events")
    op.drop_table("agent_runs")
    for table in ("hermes_conversations", "hermes_proposals", "hermes_tool_audits"):
        op.alter_column(table, "listing_image_project_id", existing_type=sa.String(36), nullable=False)
    op.drop_constraint("fk_hermes_context_project", "hermes_conversations", type_="foreignkey")
    op.drop_column("hermes_conversations", "context_project_id")
    op.drop_column("hermes_conversations", "controller_type")
