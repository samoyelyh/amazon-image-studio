from __future__ import annotations

from datetime import datetime
from enum import Enum
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class QuotaTransactionType(str, Enum):
    GRANT = "grant"
    RECHARGE = "recharge"
    RESERVE = "reserve"
    CONSUME = "consume"
    RELEASE = "release"
    REFUND = "refund"
    ADJUST = "adjust"
    EXPIRE = "expire"


class QuotaReservationStatus(str, Enum):
    RESERVED = "reserved"
    CONSUMED = "consumed"
    PARTIALLY_CONSUMED = "partially_consumed"
    RELEASED = "released"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    EXPIRED = "expired"


class QuotaAccount(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quota_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id"),
        CheckConstraint("balance >= 0", name="quota_account_balance_nonnegative"),
        CheckConstraint("reserved_balance >= 0", name="quota_account_reserved_nonnegative"),
        CheckConstraint("reserved_balance <= balance", name="quota_account_reserved_within_balance"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reserved_balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class QuotaRule(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quota_rules"
    __table_args__ = (
        Index("ix_quota_rules_operation_effective", "operation_code", "enabled", "effective_from"),
        UniqueConstraint("organization_id", "operation_code", "effective_from"),
        CheckConstraint("base_cost >= 0", name="quota_rule_base_cost_nonnegative"),
    )

    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    operation_code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    base_cost: Mapped[int] = mapped_column(BigInteger, nullable=False)
    model_multipliers: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    quality_multipliers: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    resolution_multipliers: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    resource_pool_multipliers: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class QuotaPackage(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quota_packages"
    __table_args__ = (
        CheckConstraint("quota_amount > 0", name="quota_package_amount_positive"),
        CheckConstraint("price >= 0", name="quota_package_price_nonnegative"),
    )

    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    quota_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)
    valid_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class QuotaReservation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quota_reservations"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key"),
        Index("ix_quota_reservations_org_status_expires", "organization_id", "status", "expires_at"),
        CheckConstraint("quantity > 0", name="quota_reservation_quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="quota_reservation_unit_cost_nonnegative"),
        CheckConstraint("reserved_amount >= 0", name="quota_reservation_reserved_nonnegative"),
        CheckConstraint("consumed_amount >= 0", name="quota_reservation_consumed_nonnegative"),
        CheckConstraint("released_amount >= 0", name="quota_reservation_released_nonnegative"),
        CheckConstraint("refunded_amount >= 0", name="quota_reservation_refunded_nonnegative"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("quota_accounts.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("quota_rules.id", ondelete="SET NULL"), nullable=True)
    operation_code: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_cost: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    consumed_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    released_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    refunded_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=QuotaReservationStatus.RESERVED.value, nullable=False)
    factors_json: Mapped[dict[str, object]] = mapped_column("factors", JSON, default=dict, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    settlement_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    account: Mapped[QuotaAccount] = relationship(lazy="selectin")


class QuotaTransaction(UuidPrimaryKeyMixin, Base):
    __tablename__ = "quota_transactions"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key"),
        Index("ix_quota_transactions_org_created", "organization_id", "created_at"),
        Index("ix_quota_transactions_reservation", "reservation_id", "created_at"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("quota_accounts.id", ondelete="CASCADE"), nullable=False)
    reservation_id: Mapped[str | None] = mapped_column(ForeignKey("quota_reservations.id", ondelete="SET NULL"), nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operation_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column("metadata", JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
