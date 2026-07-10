"""add singbox node sync tokens

Revision ID: d4f3b2a1c9e8
Revises: f0b3c2d4e5a6
Create Date: 2026-07-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4f3b2a1c9e8'
down_revision = 'f0b3c2d4e5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('singbox_nodes') as batch_op:
        batch_op.add_column(sa.Column('sync_token_hash', sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint('uq_singbox_nodes_sync_token_hash', ['sync_token_hash'])


def downgrade() -> None:
    with op.batch_alter_table('singbox_nodes') as batch_op:
        batch_op.drop_constraint('uq_singbox_nodes_sync_token_hash', type_='unique')
        batch_op.drop_column('sync_token_hash')
