"""add singbox enrollment tokens

Revision ID: c8e71f2b9a64
Revises: 9d6c3f4a7b21
Create Date: 2026-07-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8e71f2b9a64'
down_revision = '9d6c3f4a7b21'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'singbox_enrollment_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['node_id'], ['singbox_nodes.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )


def downgrade() -> None:
    op.drop_table('singbox_enrollment_tokens')
