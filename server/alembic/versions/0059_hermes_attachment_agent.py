"""add Hermes attachment workbench conversations and audited proposals

Revision ID: 0059_hermes_attachment_agent
Revises: 0058_attachment_output_edits
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0059_hermes_attachment_agent"
down_revision: str | None = "0058_attachment_output_edits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hermes_conversations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("listing_image_project_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(160), nullable=False, server_default="Hermes 智能助理"),
        sa.Column("mode", sa.String(20), nullable=False, server_default="suggest"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("external_session_id", sa.String(160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_image_project_id"], ["listing_image_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hermes_conversations_user_project", "hermes_conversations", ["organization_id", "user_id", "listing_image_project_id", "updated_at"])
    op.create_table(
        "hermes_messages",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("external_response_id", sa.String(160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["hermes_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hermes_messages_conversation_created", "hermes_messages", ["conversation_id", "created_at"])
    op.create_table(
        "hermes_proposals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("source_message_id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("listing_image_project_id", sa.String(36), nullable=False),
        sa.Column("summary", sa.String(1000), nullable=False),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("expected_state_signature", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["hermes_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["hermes_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_image_project_id"], ["listing_image_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hermes_proposals_conversation_status", "hermes_proposals", ["conversation_id", "status", "created_at"])
    op.create_table(
        "hermes_tool_audits",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("proposal_id", sa.String(36), nullable=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("listing_image_project_id", sa.String(36), nullable=False),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["hermes_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["hermes_proposals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_image_project_id"], ["listing_image_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hermes_tool_audits_project_created", "hermes_tool_audits", ["organization_id", "listing_image_project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_hermes_tool_audits_project_created", table_name="hermes_tool_audits")
    op.drop_table("hermes_tool_audits")
    op.drop_index("ix_hermes_proposals_conversation_status", table_name="hermes_proposals")
    op.drop_table("hermes_proposals")
    op.drop_index("ix_hermes_messages_conversation_created", table_name="hermes_messages")
    op.drop_table("hermes_messages")
    op.drop_index("ix_hermes_conversations_user_project", table_name="hermes_conversations")
    op.drop_table("hermes_conversations")
