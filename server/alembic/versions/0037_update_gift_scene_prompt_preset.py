"""update the system gift-scene batch try-on prompt preset

Revision ID: 0037_update_gift_scene_prompt
Revises: 0036_update_pure_white_prompt
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.prompts.batch_tryon_prompt_templates import GIFT_SCENE_ANALYSIS_PROMPT


revision: str = "0037_update_gift_scene_prompt"
down_revision: str | None = "0036_update_pure_white_prompt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    prompt_presets = sa.table(
        "batch_tryon_prompt_presets",
        sa.column("scope", sa.String(length=20)),
        sa.column("template_type", sa.String(length=60)),
        sa.column("analysis_prompt_template", sa.Text()),
    )
    op.execute(
        prompt_presets.update()
        .where(
            prompt_presets.c.scope == "system",
            prompt_presets.c.template_type == "gift_scene",
        )
        .values(analysis_prompt_template=GIFT_SCENE_ANALYSIS_PROMPT)
    )


def downgrade() -> None:
    # Historical jobs preserve their exact prompt snapshots, so preset content
    # is not rewritten during a schema rollback.
    pass
