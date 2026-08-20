from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class VisualPreset(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "visual_presets"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_visual_presets_scope_code"),
        Index("ix_visual_presets_active_order", "organization_id", "is_active", "sort_order"),
    )

    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    short_description: Mapped[str] = mapped_column(String(500), nullable=False)
    category_scope: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    recommended_modules: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    recommended_model_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("visual_preset_versions.id", ondelete="SET NULL", use_alter=True), nullable=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class VisualPresetVersion(UuidPrimaryKeyMixin, Base):
    __tablename__ = "visual_preset_versions"
    __table_args__ = (
        UniqueConstraint("preset_id", "version_number", name="uq_visual_preset_version_number"),
        Index("ix_visual_preset_versions_preset", "preset_id", "version_number"),
    )

    preset_id: Mapped[str] = mapped_column(ForeignKey("visual_presets.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    full_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    change_summary: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ThemePreset(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "theme_presets"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_theme_presets_scope_code"),
        Index("ix_theme_presets_active_order", "organization_id", "is_active", "sort_order"),
    )

    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    short_description: Mapped[str] = mapped_column(String(500), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("theme_preset_versions.id", ondelete="SET NULL", use_alter=True), nullable=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ThemePresetVersion(UuidPrimaryKeyMixin, Base):
    __tablename__ = "theme_preset_versions"
    __table_args__ = (UniqueConstraint("preset_id", "version_number", name="uq_theme_preset_version_number"),)

    preset_id: Mapped[str] = mapped_column(ForeignKey("theme_presets.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    full_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    change_summary: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIModelPreset(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_model_presets"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_ai_model_presets_scope_code"),
        Index("ix_ai_model_presets_status_order", "organization_id", "status", "sort_order"),
    )

    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    gender_presentation: Mapped[str] = mapped_column(String(40), nullable=False)
    age_range: Mapped[str] = mapped_column(String(60), nullable=False)
    body_type: Mapped[str] = mapped_column(String(120), nullable=False)
    short_description: Mapped[str] = mapped_column(String(500), nullable=False)
    identity_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    generation_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_constraints: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recommended_visual_presets: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    recommended_modules: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    cover_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True)
    current_identity_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_model_identity_versions.id", ondelete="SET NULL", use_alter=True), nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class AIModelIdentityVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_model_identity_versions"
    __table_args__ = (
        UniqueConstraint("model_preset_id", "version_number", name="uq_ai_model_identity_version_number"),
        Index("ix_ai_model_identity_versions_preset", "model_preset_id", "version_number"),
    )

    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    model_preset_id: Mapped[str] = mapped_column(ForeignKey("ai_model_presets.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    identity_prompt_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    identity_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True)
    identity_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    reference_batch_id: Mapped[str | None] = mapped_column(ForeignKey("job_batches.id", ondelete="SET NULL"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class AIModelPresetReference(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_model_preset_references"
    __table_args__ = (
        UniqueConstraint("identity_version_id", "reference_role", name="uq_ai_model_reference_role"),
        Index("ix_ai_model_references_asset", "asset_id"),
    )

    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    model_preset_id: Mapped[str] = mapped_column(ForeignKey("ai_model_presets.id", ondelete="CASCADE"), nullable=False)
    identity_version_id: Mapped[str] = mapped_column(ForeignKey("ai_model_identity_versions.id", ondelete="CASCADE"), nullable=False)
    reference_role: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    source_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class AttachmentPlanModelSelection(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachment_plan_model_selections"
    __table_args__ = (
        UniqueConstraint("workbench_plan_id", "product_slot", name="uq_attachment_plan_model_slot"),
        Index("ix_attachment_plan_models_plan", "workbench_plan_id", "product_slot"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    workbench_plan_id: Mapped[str] = mapped_column(ForeignKey("attachment_workbench_plans.id", ondelete="CASCADE"), nullable=False)
    product_slot: Mapped[int] = mapped_column(Integer, nullable=False)
    model_preset_id: Mapped[str] = mapped_column(ForeignKey("ai_model_presets.id", ondelete="RESTRICT"), nullable=False)
    identity_version_id: Mapped[str] = mapped_column(ForeignKey("ai_model_identity_versions.id", ondelete="RESTRICT"), nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="recommended", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
