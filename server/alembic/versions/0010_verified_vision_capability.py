"""verified vision input capability

Revision ID: 0010_verified_vision
Revises: 0009_verified_image_caps
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "0010_verified_vision"
down_revision: str | None = "0009_verified_image_caps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    models = sa.table("models", sa.column("id", sa.String()), sa.column("code", sa.String()))
    capabilities = sa.table(
        "model_capabilities", sa.column("id", sa.String()), sa.column("model_id", sa.String()),
        sa.column("capability", sa.String()), sa.column("created_by", sa.String()),
        sa.column("created_at", sa.DateTime()),
    )
    model_id = bind.scalar(sa.select(models.c.id).where(models.c.code == "gpt-5.5").limit(1))
    if model_id and not bind.scalar(sa.select(capabilities.c.id).where(
        capabilities.c.model_id == model_id, capabilities.c.capability == "vision_input",
    ).limit(1)):
        op.bulk_insert(capabilities, [{
            "id": str(uuid4()), "model_id": model_id, "capability": "vision_input",
            "created_by": None, "created_at": datetime.now(timezone.utc),
        }])


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM model_capabilities WHERE model_id IN "
        "(SELECT id FROM models WHERE code = 'gpt-5.5') AND capability = 'vision_input'"
    ))
