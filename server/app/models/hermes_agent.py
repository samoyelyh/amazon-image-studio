from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class HermesConversation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "hermes_conversations"
    __table_args__ = (Index("ix_hermes_conversations_user_project", "organization_id", "user_id", "listing_image_project_id", "updated_at"),)

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_image_project_id: Mapped[str] = mapped_column(ForeignKey("listing_image_projects.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(160), default="Hermes 智能助理", nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="suggest", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    external_session_id: Mapped[str | None] = mapped_column(String(160), nullable=True)


class HermesMessage(UuidPrimaryKeyMixin, Base):
    __tablename__ = "hermes_messages"
    __table_args__ = (Index("ix_hermes_messages_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[str] = mapped_column(ForeignKey("hermes_conversations.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    external_response_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HermesProposal(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "hermes_proposals"
    __table_args__ = (Index("ix_hermes_proposals_conversation_status", "conversation_id", "status", "created_at"),)

    conversation_id: Mapped[str] = mapped_column(ForeignKey("hermes_conversations.id", ondelete="CASCADE"), nullable=False)
    source_message_id: Mapped[str] = mapped_column(ForeignKey("hermes_messages.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_image_project_id: Mapped[str] = mapped_column(ForeignKey("listing_image_projects.id", ondelete="CASCADE"), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    actions_json: Mapped[list[dict[str, object]]] = mapped_column("actions", JSON, default=list, nullable=False)
    expected_state_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    result_json: Mapped[dict[str, object]] = mapped_column("result", JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HermesToolAudit(UuidPrimaryKeyMixin, Base):
    __tablename__ = "hermes_tool_audits"
    __table_args__ = (Index("ix_hermes_tool_audits_project_created", "organization_id", "listing_image_project_id", "created_at"),)

    conversation_id: Mapped[str] = mapped_column(ForeignKey("hermes_conversations.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[str | None] = mapped_column(ForeignKey("hermes_proposals.id", ondelete="SET NULL"), nullable=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_image_project_id: Mapped[str] = mapped_column(ForeignKey("listing_image_projects.id", ondelete="CASCADE"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    arguments_json: Mapped[dict[str, object]] = mapped_column("arguments", JSON, default=dict, nullable=False)
    result_json: Mapped[dict[str, object]] = mapped_column("result", JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
