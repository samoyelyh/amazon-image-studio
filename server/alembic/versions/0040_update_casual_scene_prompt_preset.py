"""update the system casual-scene batch try-on prompt preset

Revision ID: 0040_update_casual_prompt
Revises: 0039_update_detail_prompt
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.prompts.batch_tryon_prompt_templates import CASUAL_SCENE_ANALYSIS_PROMPT


revision: str = "0040_update_casual_prompt"
down_revision: str | None = "0039_update_detail_prompt"
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
            prompt_presets.c.template_type == "casual_scene",
        )
        .values(analysis_prompt_template=CASUAL_SCENE_ANALYSIS_PROMPT)
    )


def downgrade() -> None:
    # Historical jobs preserve their exact prompt snapshots.
    pass
