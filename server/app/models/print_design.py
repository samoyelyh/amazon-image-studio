from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class PrintAssetGroup(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "print_asset_groups"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_print_asset_groups_org_code"),
        Index("ix_print_asset_groups_org_name", "organization_id", "name"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    product_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class PrintAssetLibraryItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "print_asset_library_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "asset_code", "version", name="uq_print_assets_org_code_version"),
        Index("ix_print_assets_org_group", "organization_id", "asset_group_id"),
        Index("ix_print_assets_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, unique=True)
    asset_group_id: Mapped[str | None] = mapped_column(ForeignKey("print_asset_groups.id", ondelete="SET NULL"), nullable=True)
    asset_code: Mapped[str] = mapped_column(String(120), nullable=False)
    asset_name: Mapped[str] = mapped_column(String(180), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(40), default="print", nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    default_position_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    allow_rotate: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_stretch: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    keep_ratio_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class ProductPrintMapping(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_print_mappings"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku", "asset_group_id", name="uq_product_print_mappings_org_sku_group"),
        Index("ix_product_print_mappings_org_sku", "organization_id", "sku"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    sku: Mapped[str] = mapped_column(String(160), nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    style_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    template_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    asset_group_id: Mapped[str] = mapped_column(ForeignKey("print_asset_groups.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
