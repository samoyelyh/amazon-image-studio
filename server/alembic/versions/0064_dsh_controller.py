"""Additive controller switch. Existing conversations/jobs/outputs remain intact."""
from alembic import op
import sqlalchemy as sa
revision='0064_dsh_controller'
down_revision='0063_agent_control'
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('agent_controller_settings',sa.Column('id',sa.String(36),primary_key=True),sa.Column('controller',sa.String(20),nullable=False),sa.Column('updated_by',sa.String(36)),sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
def downgrade():op.drop_table('agent_controller_settings')
