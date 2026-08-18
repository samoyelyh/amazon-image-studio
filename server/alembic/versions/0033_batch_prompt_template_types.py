"""seed additional batch try-on prompt template types

Revision ID: 0033_batch_prompt_types
Revises: 0032_batch_prompt_templates
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

from app.prompts.batch_tryon_prompt_templates import SYSTEM_PROMPT_PRESETS


revision: str = "0033_batch_prompt_types"
down_revision: str | None = "0032_batch_prompt_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ADDITIONAL_TYPES = {
    "gift_scene", "stadium_scene", "detail_display", "casual_scene", "custom_process",
}


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    presets = sa.table(
        "batch_tryon_prompt_presets",
        sa.column("id", sa.String()),
        sa.column("organization_id", sa.String()),
        sa.column("owner_user_id", sa.String()),
        sa.column("scope", sa.String()),
        sa.column("template_type", sa.String()),
        sa.column("label", sa.String()),
        sa.column("analysis_prompt_template", sa.Text()),
        sa.column("enabled", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_system_preset", sa.Boolean()),
        sa.column("created_by", sa.String()),
        sa.column("updated_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(presets, [
        {
            "id": str(uuid4()),
            "organization_id": None,
            "owner_user_id": None,
            "scope": "system",
            "template_type": template_type,
            "label": label,
            "analysis_prompt_template": analysis_prompt,
            "enabled": True,
            "sort_order": sort_order,
            "is_system_preset": True,
            "created_by": None,
            "updated_by": None,
            "created_at": now,
            "updated_at": now,
        }
        for template_type, label, analysis_prompt, sort_order in SYSTEM_PROMPT_PRESETS
        if template_type in ADDITIONAL_TYPES
    ])


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM batch_tryon_prompt_presets "
        "WHERE scope = 'system' AND is_system_preset = 1 "
        "AND template_type IN ('gift_scene', 'stadium_scene', 'detail_display', 'casual_scene', 'custom_process')"
    ))
