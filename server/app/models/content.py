from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class ProjectType(str, Enum):
    LISTING = "listing"
    BATCH_TRYON = "batch_tryon"
    APLUS = "aplus"


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    ARCHIVED = "archived"


class AssetCategory(str, Enum):
    PRODUCT_REFERENCE = "product_reference"
    MODEL_TEMPLATE = "model_template"
    GARMENT = "garment"
    STYLE_REFERENCE = "style_reference"
    LISTING_OUTPUT = "listing_output"
    BATCH_TRYON_OUTPUT = "batch_tryon_output"
    APLUS_OUTPUT = "aplus_output"
    TEMPORARY = "temporary"


class Project(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_organization_type_updated", "organization_id", "project_type", "updated_at"),
        Index("ix_projects_organization_status", "organization_id", "status", "deleted_at"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ProjectStatus.DRAFT.value, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    versions: Mapped[list[ProjectVersion]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )
    asset_links: Mapped[list[ProjectAsset]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )


class ProjectVersion(UuidPrimaryKeyMixin, Base):
    __tablename__ = "project_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_number"),
        Index("ix_project_versions_organization_project", "organization_id", "project_id", "version_number"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    project: Mapped[Project] = relationship(back_populates="versions")


class Asset(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_organization_category_created", "organization_id", "category", "created_at"),
        Index("ix_assets_organization_hash", "organization_id", "sha256"),
        Index("ix_assets_organization_deleted", "organization_id", "deleted_at"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(700), unique=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project_links: Mapped[list[ProjectAsset]] = relationship(back_populates="asset", lazy="selectin")


class ProjectAsset(UuidPrimaryKeyMixin, Base):
    __tablename__ = "project_assets"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", "role"),
        Index("ix_project_assets_organization_project", "organization_id", "project_id", "sort_order"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[str] = mapped_column(String(60), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    project: Mapped[Project] = relationship(back_populates="asset_links")
    asset: Mapped[Asset] = relationship(back_populates="project_links", lazy="selectin")


class GeneratedOutput(UuidPrimaryKeyMixin, Base):
    __tablename__ = "generated_outputs"
    __table_args__ = (
        Index("ix_generated_outputs_organization_project", "organization_id", "project_id", "created_at"),
        Index("ix_generated_outputs_organization_created", "organization_id", "created_at"),
        Index("ix_generated_outputs_job", "job_id", "sequence_number"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    project_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_versions.id", ondelete="SET NULL"), nullable=True
    )
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("job_batches.id", ondelete="SET NULL"), nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_type: Mapped[str] = mapped_column(String(60), nullable=False)
    module_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column("metadata", JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ListingOutputTransfer(UuidPrimaryKeyMixin, Base):
    __tablename__ = "listing_output_transfers"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_listing_transfer_org_idempotency"),
        Index("ix_listing_transfer_org_output", "organization_id", "listing_output_id", "created_at"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    listing_output_id: Mapped[str] = mapped_column(ForeignKey("generated_outputs.id", ondelete="RESTRICT"), nullable=False)
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    target_project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    template_replaced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_project: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
