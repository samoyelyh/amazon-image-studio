"""Add transactional quota accounts, rules, reservations, packages, and ledger.

Revision ID: 0004_quota_and_billing
Revises: 0003_assets_and_projects
Create Date: 2026-07-17
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004_quota_and_billing"
down_revision: str | None = "0003_assets_and_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "quota_packages",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("quota_amount", sa.BigInteger(), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("valid_days", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        *timestamps(),
        sa.CheckConstraint("quota_amount > 0", name="ck_quota_packages_quota_package_amount_positive"),
        sa.CheckConstraint("price >= 0", name="ck_quota_packages_quota_package_price_nonnegative"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "quota_rules",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=True),
        sa.Column("operation_code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("base_cost", sa.BigInteger(), nullable=False),
        sa.Column("model_multipliers", sa.JSON(), nullable=False),
        sa.Column("quality_multipliers", sa.JSON(), nullable=False),
        sa.Column("resolution_multipliers", sa.JSON(), nullable=False),
        sa.Column("resource_pool_multipliers", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        *timestamps(),
        sa.CheckConstraint("base_cost >= 0", name="ck_quota_rules_quota_rule_base_cost_nonnegative"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "operation_code", "effective_from"),
    )
    op.create_index("ix_quota_rules_operation_effective", "quota_rules", ["operation_code", "enabled", "effective_from"])

    op.create_table(
        "quota_accounts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved_balance", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        *timestamps(),
        sa.CheckConstraint("balance >= 0", name="ck_quota_accounts_quota_account_balance_nonnegative"),
        sa.CheckConstraint("reserved_balance >= 0", name="ck_quota_accounts_quota_account_reserved_nonnegative"),
        sa.CheckConstraint("reserved_balance <= balance", name="ck_quota_accounts_quota_account_reserved_within_balance"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
    )

    op.create_table(
        "quota_reservations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("rule_id", sa.String(36), nullable=True),
        sa.Column("operation_code", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("actual_quantity", sa.Integer(), nullable=True),
        sa.Column("unit_cost", sa.BigInteger(), nullable=False),
        sa.Column("reserved_amount", sa.BigInteger(), nullable=False),
        sa.Column("consumed_amount", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("released_amount", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("refunded_amount", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="reserved"),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("reference_type", sa.String(80), nullable=True),
        sa.Column("reference_id", sa.String(100), nullable=True),
        sa.Column("settlement_idempotency_key", sa.String(200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        *timestamps(),
        sa.CheckConstraint("quantity > 0", name="ck_quota_reservations_quota_reservation_quantity_positive"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_quota_reservations_quota_reservation_unit_cost_nonnegative"),
        sa.CheckConstraint("reserved_amount >= 0", name="ck_quota_reservations_quota_reservation_reserved_nonnegative"),
        sa.CheckConstraint("consumed_amount >= 0", name="ck_quota_reservations_quota_reservation_consumed_nonnegative"),
        sa.CheckConstraint("released_amount >= 0", name="ck_quota_reservations_quota_reservation_released_nonnegative"),
        sa.CheckConstraint("refunded_amount >= 0", name="ck_quota_reservations_quota_reservation_refunded_nonnegative"),
        sa.ForeignKeyConstraint(["account_id"], ["quota_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["quota_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key"),
    )
    op.create_index("ix_quota_reservations_org_status_expires", "quota_reservations", ["organization_id", "status", "expires_at"])

    op.create_table(
        "quota_transactions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("reservation_id", sa.String(36), nullable=True),
        sa.Column("transaction_type", sa.String(30), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("balance_delta", sa.BigInteger(), nullable=False),
        sa.Column("reserved_delta", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("reserved_after", sa.BigInteger(), nullable=False),
        sa.Column("operation_code", sa.String(120), nullable=True),
        sa.Column("idempotency_key", sa.String(220), nullable=False),
        sa.Column("reference_type", sa.String(80), nullable=True),
        sa.Column("reference_id", sa.String(100), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["quota_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reservation_id"], ["quota_reservations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key"),
    )
    op.create_index("ix_quota_transactions_org_created", "quota_transactions", ["organization_id", "created_at"])
    op.create_index("ix_quota_transactions_reservation", "quota_transactions", ["reservation_id", "created_at"])


def downgrade() -> None:
    op.drop_table("quota_transactions")
    op.drop_table("quota_reservations")
    op.drop_table("quota_accounts")
    op.drop_table("quota_rules")
    op.drop_table("quota_packages")
