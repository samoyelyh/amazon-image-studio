"""Control-plane records only; image state remains in Job/JobBatch/Asset."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class AgentRun(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("conversation_id", "client_request_id", name="uq_agent_run_client_request"),
        Index("ix_agent_runs_owner_status", "organization_id", "user_id", "status"),
    )
    conversation_id: Mapped[str] = mapped_column(ForeignKey("hermes_conversations.id", ondelete="CASCADE"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_message_id: Mapped[str] = mapped_column(ForeignKey("hermes_messages.id", ondelete="CASCADE"))
    proposal_id: Mapped[str | None] = mapped_column(ForeignKey("hermes_proposals.id", ondelete="SET NULL"))
    client_request_id: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    graph_version: Mapped[str] = mapped_column(String(40), default="phase1-v1")
    status: Mapped[str] = mapped_column(String(40), default="planning")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    planner_mode: Mapped[str] = mapped_column(String(30), default="mock")
    selection_json: Mapped[dict] = mapped_column(JSON, default=dict)
    plan_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))


class AgentEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "agent_events"
    __table_args__ = (UniqueConstraint("run_id", "event_key", name="uq_agent_event_key"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    event_key: Mapped[str] = mapped_column(String(160))
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentJobLink(UuidPrimaryKeyMixin, Base):
    __tablename__ = "agent_job_links"
    __table_args__ = (UniqueConstraint("run_id", "job_id", name="uq_agent_job_link"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(30))
