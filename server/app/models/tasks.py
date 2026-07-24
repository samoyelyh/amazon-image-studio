from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class ProviderType(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    NEW_API = "new_api"
    CUSTOM = "custom"


class ApiKeyStatus(str, Enum):
    ACTIVE = "active"
    COOLING = "cooling"
    DISABLED = "disabled"


class JobStatus(str, Enum):
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    RETRY_WAITING = "retry_waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchStatus(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Provider(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "providers"

    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_json: Mapped[dict[str, object]] = mapped_column("config", JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ProviderModel(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "models"
    __table_args__ = (UniqueConstraint("provider_id", "code"),)

    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    upstream_model: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_json: Mapped[dict[str, object]] = mapped_column("config", JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    provider: Mapped[Provider] = relationship(lazy="selectin")
    capabilities: Mapped[list[ModelCapability]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class ModelCapability(UuidPrimaryKeyMixin, Base):
    __tablename__ = "model_capabilities"
    __table_args__ = (UniqueConstraint("model_id", "capability"),)

    model_id: Mapped[str] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), nullable=False)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ResourcePool(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resource_pools"
    __table_args__ = (
        UniqueConstraint("organization_id", "code"),
        Index("ix_resource_pools_model_enabled", "model_id", "enabled", "priority"),
    )

    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    model: Mapped[ProviderModel] = relationship(lazy="selectin")


class OperationResourcePool(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operation_resource_pools"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "operation_code", "resource_pool_id", "required_capability",
            name="uq_operation_resource_pool_capability",
        ),
        Index("ix_operation_resource_pools_lookup", "organization_id", "operation_code", "enabled", "priority"),
    )

    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    operation_code: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_pool_id: Mapped[str] = mapped_column(ForeignKey("resource_pools.id", ondelete="CASCADE"), nullable=False)
    required_capability: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    resource_pool: Mapped[ResourcePool] = relationship(lazy="selectin")


class ApiKey(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_provider_status", "provider_id", "enabled", "status"),)

    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    secret_suffix: Mapped[str] = mapped_column(String(8), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=ApiKeyStatus.ACTIVE.value, nullable=False)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining_balance: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ResourcePoolKey(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resource_pool_keys"
    __table_args__ = (UniqueConstraint("resource_pool_id", "api_key_id"),)

    resource_pool_id: Mapped[str] = mapped_column(ForeignKey("resource_pools.id", ondelete="CASCADE"), nullable=False)
    api_key_id: Mapped[str] = mapped_column(ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class JobBatch(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "job_batches"
    __table_args__ = (
        Index("ix_job_batches_org_status_created", "organization_id", "status", "created_at"),
        Index("uq_job_batches_org_idempotency", "organization_id", "idempotency_key", unique=True),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    workspace_type: Mapped[str] = mapped_column(String(40), nullable=False)
    operation_code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    capability: Mapped[str | None] = mapped_column(String(80), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    concurrency: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    admin_test_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=BatchStatus.DRAFT.value, nullable=False)
    total_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancelled_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class Job(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key"),
        Index("ix_jobs_org_status_created", "organization_id", "status", "created_at"),
        Index("ix_jobs_status_retry", "status", "next_retry_at"),
        Index("ix_jobs_batch_client_item", "batch_id", "client_item_id"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("job_batches.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    quota_reservation_id: Mapped[str] = mapped_column(ForeignKey("quota_reservations.id", ondelete="RESTRICT"), nullable=False)
    operation_code: Mapped[str] = mapped_column(String(120), nullable=False)
    workspace_type: Mapped[str] = mapped_column(String(40), nullable=False)
    queue_name: Mapped[str] = mapped_column(String(60), nullable=False)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    model_code: Mapped[str] = mapped_column(String(120), nullable=False)
    client_item_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=JobStatus.QUEUED.value, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_json: Mapped[dict[str, object]] = mapped_column("input", JSON, nullable=False)
    result_json: Mapped[dict[str, object] | None] = mapped_column("result", JSON, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    selected_pool_id: Mapped[str | None] = mapped_column(ForeignKey("resource_pools.id", ondelete="SET NULL"), nullable=True)
    selected_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generation_duration_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class BatchTryOnReviewItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "batch_tryon_review_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "client_item_id", name="uq_batch_tryon_review_batch_client"),
        Index("ix_batch_tryon_review_org_batch", "organization_id", "batch_id"),
        Index("ix_batch_tryon_review_org_status", "organization_id", "review_status"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[str] = mapped_column(ForeignKey("job_batches.id", ondelete="CASCADE"), nullable=False)
    client_item_id: Mapped[str] = mapped_column(String(120), nullable=False)
    garment_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    model_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    template_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preset_summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    preset_codes: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    review_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    regeneration_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class BatchTryOnVersion(UuidPrimaryKeyMixin, Base):
    __tablename__ = "batch_try_on_versions"
    __table_args__ = (
        UniqueConstraint("item_id", "version_number", name="uq_batch_try_on_version_number"),
        UniqueConstraint("task_id", name="uq_batch_try_on_version_task"),
        Index("ix_batch_try_on_versions_org_item", "organization_id", "item_id", "version_number"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[str] = mapped_column(ForeignKey("batch_tryon_review_items.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("batch_try_on_versions.id", ondelete="SET NULL"), nullable=True)
    generated_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    download_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    prompt_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_mode: Mapped[str] = mapped_column(String(30), default="initial", nullable=False)
    generation_status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobAttempt(UuidPrimaryKeyMixin, Base):
    __tablename__ = "job_attempts"
    __table_args__ = (UniqueConstraint("job_id", "attempt_number"), Index("ix_job_attempts_org_job", "organization_id", "job_id"))

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("providers.id", ondelete="SET NULL"), nullable=True)
    resource_pool_id: Mapped[str | None] = mapped_column(ForeignKey("resource_pools.id", ondelete="SET NULL"), nullable=True)
    api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)
    model_id: Mapped[str | None] = mapped_column(ForeignKey("models.id", ondelete="SET NULL"), nullable=True)
    worker_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    normalized_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    upstream_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phase_timings_json: Mapped[dict[str, object]] = mapped_column("phase_timings", JSON, default=dict, nullable=False)


class ApiKeyUsageStat(UuidPrimaryKeyMixin, Base):
    __tablename__ = "api_key_usage_stats"
    __table_args__ = (Index("ix_api_key_usage_key_created", "api_key_id", "created_at"),)

    api_key_id: Mapped[str] = mapped_column(ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
