from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin


class BatchTryOnQueuePolicy(TimestampMixin, Base):
    """Organization retention rule and durable, retryable object-deletion outbox."""
    __tablename__ = "batch_tryon_queue_policies"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    age_basis: Mapped[str] = mapped_column(String(30), default="last_activity", nullable=False)
    action: Mapped[str] = mapped_column(String(30), default="delete", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    pending_storage_keys: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
