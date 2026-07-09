"""rename node core version

Revision ID: f0b3c2d4e5a6
Revises: c8e71f2b9a64
Create Date: 2026-07-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f0b3c2d4e5a6'
down_revision = 'c8e71f2b9a64'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('nodes') as batch_op:
        batch_op.alter_column(
            'xray_version',
            new_column_name='core_version',
            existing_type=sa.String(length=32),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('nodes') as batch_op:
        batch_op.alter_column(
            'core_version',
            new_column_name='xray_version',
            existing_type=sa.String(length=32),
            nullable=True,
        )
