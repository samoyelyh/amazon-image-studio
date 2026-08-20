from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class AttachmentMaterialSet(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachment_material_sets"
    __table_args__ = (
        Index("ix_attachment_material_sets_owner_updated", "organization_id", "owner_user_id", "updated_at"),
        Index("ix_attachment_material_sets_source_project", "organization_id", "source_project_id"),
        Index("ix_attachment_material_sets_category_status", "organization_id", "category_key", "status"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    category_key: Mapped[str] = mapped_column(String(100), nullable=False)
    category_name: Mapped[str] = mapped_column(String(160), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("listing_generation_sessions.id", ondelete="SET NULL"), nullable=True,
    )
    source_project_id: Mapped[str | None] = mapped_column(
        ForeignKey("listing_image_projects.id", ondelete="SET NULL"), nullable=True,
    )
    cover_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("attachment_material_set_versions.id", ondelete="SET NULL", use_alter=True), nullable=True,
    )
    selected_module_snapshot: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class AttachmentMaterialSetVersion(UuidPrimaryKeyMixin, Base):
    __tablename__ = "attachment_material_set_versions"
    __table_args__ = (
        UniqueConstraint("material_set_id", "version_number", name="uq_attachment_material_version_number"),
        Index("ix_attachment_material_version_hash", "material_set_id", "content_hash"),
        Index("ix_attachment_material_versions_org_set", "organization_id", "material_set_id", "version_number"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    material_set_id: Mapped[str] = mapped_column(
        ForeignKey("attachment_material_sets.id", ondelete="CASCADE"), nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_module_snapshot: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    module_count: Mapped[int] = mapped_column(Integer, nullable=False)
    target_module_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AttachmentMaterialItem(UuidPrimaryKeyMixin, Base):
    __tablename__ = "attachment_material_items"
    __table_args__ = (
        UniqueConstraint("material_version_id", "module_key", name="uq_attachment_material_item_module"),
        Index("ix_attachment_material_items_org_version", "organization_id", "material_version_id"),
        Index("ix_attachment_material_items_asset", "source_asset_id"),
        Index("ix_attachment_material_items_output", "source_output_id"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    material_version_id: Mapped[str] = mapped_column(
        ForeignKey("attachment_material_set_versions.id", ondelete="CASCADE"), nullable=False,
    )
    module_key: Mapped[str] = mapped_column(String(60), nullable=False)
    source_output_id: Mapped[str | None] = mapped_column(
        ForeignKey("generated_outputs.id", ondelete="RESTRICT"), nullable=True,
    )
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    source_task_group_id: Mapped[str | None] = mapped_column(
        ForeignKey("listing_image_task_groups.id", ondelete="SET NULL"), nullable=True,
    )
    source_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    plan_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("attachment_workbench_plan_versions.id", ondelete="SET NULL"), nullable=True,
    )
    prompt_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("attachment_workbench_plan_versions.id", ondelete="SET NULL"), nullable=True,
    )
    reference_understanding_id: Mapped[str | None] = mapped_column(
        ForeignKey("attachment_reference_understandings.id", ondelete="SET NULL"), nullable=True,
    )
    product_composition_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("attachment_product_composition_versions.id", ondelete="SET NULL"), nullable=True,
    )
    aspect_ratio: Mapped[str] = mapped_column(String(20), nullable=False)
    output_size: Mapped[str] = mapped_column(String(40), nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    product_mode: Mapped[str] = mapped_column(String(20), default="SINGLE", nullable=False)
    is_manual_revision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
