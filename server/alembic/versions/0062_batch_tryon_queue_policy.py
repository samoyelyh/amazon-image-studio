"""Organization batch queue retention settings; task and asset tables unchanged."""
from alembic import op
import sqlalchemy as sa

revision = "0062_batch_queue_policy"
down_revision = "0061_edit_timestamp_defaults"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("batch_tryon_queue_policies",
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("age_basis", sa.String(30), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_summary", sa.JSON(), nullable=False),
        sa.Column("pending_storage_keys", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("batch_tryon_queue_policies")
