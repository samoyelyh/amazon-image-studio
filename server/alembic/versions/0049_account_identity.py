"""replace email identity with globally unique managed accounts

Revision ID: 0049_account_identity
Revises: 0048_attachment_references
"""

from collections.abc import Sequence
import re

from alembic import op
import sqlalchemy as sa


revision: str = "0049_account_identity"
down_revision: str | None = "0048_attachment_references"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _account_stem(email: str | None) -> str:
    local = (email or "").split("@", 1)[0].strip().lower()
    stem = re.sub(r"[^a-z0-9_-]+", "-", local).strip("-_")
    if len(stem) < 3:
        stem = "user"
    return stem[:32]


def _unique_account(stem: str, used: set[str]) -> str:
    candidate = stem
    suffix = 2
    while candidate.casefold() in used:
        tail = str(suffix)
        candidate = f"{stem[:32 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def _drop_email_keys(table_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints(table_name):
        if constraint.get("column_names") == ["email"] and constraint.get("name"):
            op.drop_constraint(constraint["name"], table_name, type_="unique")
    inspector = sa.inspect(op.get_bind())
    for index in inspector.get_indexes(table_name):
        if index.get("column_names") == ["email"] and index.get("name"):
            op.drop_index(index["name"], table_name=table_name)


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("users", sa.Column("account", sa.String(32), nullable=True))
    op.add_column("login_audits", sa.Column("account", sa.String(32), nullable=True))

    rows = bind.execute(
        sa.text("SELECT id, email FROM users ORDER BY created_at ASC, id ASC")
    ).mappings().all()
    used: set[str] = set()
    for row in rows:
        account = _unique_account(_account_stem(row["email"]), used)
        bind.execute(
            sa.text("UPDATE users SET account = :account WHERE id = :user_id"),
            {"account": account, "user_id": row["id"]},
        )

    bind.execute(sa.text(
        "UPDATE login_audits "
        "SET account = (SELECT users.account FROM users WHERE users.id = login_audits.user_id) "
        "WHERE user_id IS NOT NULL"
    ))
    bind.execute(sa.text(
        "UPDATE users SET must_change_password = 0, temporary_password_created_at = NULL"
    ))

    op.alter_column("users", "account", existing_type=sa.String(32), nullable=False)
    op.create_unique_constraint("uq_users_account", "users", ["account"])
    _drop_email_keys("users")
    op.drop_column("login_audits", "email")
    op.drop_column("users", "email")


def downgrade() -> None:
    # The original addresses are intentionally not retained or recreated.
    op.add_column("users", sa.Column("email", sa.String(320), nullable=True))
    op.add_column("login_audits", sa.Column("email", sa.String(320), nullable=True))
    op.drop_constraint("uq_users_account", "users", type_="unique")
    op.drop_column("login_audits", "account")
    op.drop_column("users", "account")
