"""update the system pure-white batch try-on prompt preset

Revision ID: 0036_update_pure_white_prompt
Revises: 0035_batch_font_reference
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.prompts.batch_tryon_prompt_templates import PURE_WHITE_ANALYSIS_PROMPT


revision: str = "0036_update_pure_white_prompt"
down_revision: str | None = "0035_batch_font_reference"
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
            prompt_presets.c.template_type == "pure_white",
        )
        .values(analysis_prompt_template=PURE_WHITE_ANALYSIS_PROMPT)
    )


def downgrade() -> None:
    # System preset content is intentionally not rolled back because historical
    # jobs already preserve the exact prompt snapshot that they used.
    pass
