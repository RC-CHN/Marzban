"""add singbox public tls controls

Revision ID: 9d6c3f4a7b21
Revises: 6b6d8f0f8e10
Create Date: 2026-07-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9d6c3f4a7b21'
down_revision = '6b6d8f0f8e10'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'singbox_nodes',
        sa.Column('public_tls_mode', sa.String(length=32), server_default='system-ca', nullable=False),
    )
    op.add_column(
        'singbox_nodes',
        sa.Column('public_tls_ca_cert_path', sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('singbox_nodes', 'public_tls_ca_cert_path')
    op.drop_column('singbox_nodes', 'public_tls_mode')
