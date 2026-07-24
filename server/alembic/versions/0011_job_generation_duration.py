"""persist provider generation duration

Revision ID: 0011_job_duration
Revises: 0010_verified_vision
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0011_job_duration"
down_revision: str | None = "0010_verified_vision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("generation_duration_ms", sa.BigInteger(), nullable=False, server_default="0"))
    op.execute(sa.text(
        "UPDATE jobs SET generation_duration_ms = GREATEST(0, "
        "TIMESTAMPDIFF(MICROSECOND, started_at, finished_at) DIV 1000) "
        "WHERE started_at IS NOT NULL AND finished_at IS NOT NULL"
    ))
    bind = op.get_bind()
    models = sa.table("models", sa.column("id", sa.String()), sa.column("code", sa.String()), sa.column("config", sa.JSON()))
    row = bind.execute(sa.select(models.c.id, models.c.config).where(models.c.code == "gpt-image-2").limit(1)).first()
    if row:
        config = dict(row.config or {})
        config.update({
            "edits_endpoint": "/images/edits",
            "edit_body_fields": ["model", "prompt", "aspect_ratio"],
            "edit_dimension_mode": "aspect_ratio",
            "edit_aspect_ratio_field": "aspect_ratio",
            "supported_edit_aspect_ratios": ["1:1", "3:4"],
            "verified_edit_output_sizes": {"1:1": "1254x1254", "3:4": "1024x1536"},
        })
        bind.execute(sa.update(models).where(models.c.id == row.id).values(config=config))


def downgrade() -> None:
    bind = op.get_bind()
    models = sa.table("models", sa.column("id", sa.String()), sa.column("code", sa.String()), sa.column("config", sa.JSON()))
    row = bind.execute(sa.select(models.c.id, models.c.config).where(models.c.code == "gpt-image-2").limit(1)).first()
    if row:
        config = dict(row.config or {})
        for key in (
            "edit_dimension_mode", "edit_aspect_ratio_field", "supported_edit_aspect_ratios",
            "verified_edit_output_sizes",
        ):
            config.pop(key, None)
        config["edit_body_fields"] = ["model", "prompt"]
        bind.execute(sa.update(models).where(models.c.id == row.id).values(config=config))
    op.drop_column("jobs", "generation_duration_ms")
