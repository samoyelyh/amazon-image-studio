"""Repair timestamp defaults for the first local 0064 deployment."""
from alembic import op
import sqlalchemy as sa
revision='0065_dsh_switch_defaults'
down_revision='0064_dsh_controller'
branch_labels=None
depends_on=None
def upgrade():
    for name in ['created_at','updated_at']:
        op.alter_column('agent_controller_settings',name,existing_type=sa.DateTime(timezone=True),existing_nullable=False,server_default=sa.func.now())
def downgrade():
    # 0064 now defines the same defaults. Keep them during application rollback.
    pass
