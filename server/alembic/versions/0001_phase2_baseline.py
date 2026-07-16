"""Create the Phase 2 infrastructure baseline.

Revision ID: 0001_phase2_baseline
Revises:
Create Date: 2026-07-16
"""
from typing import Sequence


revision: str = "0001_phase2_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Business tables intentionally start in Phase 3. Applying this revision
    # creates Alembic's version table and proves the migration pipeline.
    pass


def downgrade() -> None:
    pass
