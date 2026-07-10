"""add singbox public subscription tokens

Revision ID: e91c9b5a2d7f
Revises: d4f3b2a1c9e8
Create Date: 2026-07-10 00:00:00.000000

"""
import secrets

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e91c9b5a2d7f'
down_revision = 'd4f3b2a1c9e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('singbox_user_credentials') as batch_op:
        batch_op.add_column(sa.Column('subscription_token', sa.String(length=96), nullable=True))
        batch_op.create_unique_constraint(
            'uq_singbox_user_credentials_subscription_token',
            ['subscription_token'],
        )

    credentials = sa.table(
        'singbox_user_credentials',
        sa.column('id', sa.Integer),
        sa.column('subscription_token', sa.String),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(credentials.c.id).where(credentials.c.subscription_token.is_(None))
    )
    for row in rows:
        connection.execute(
            credentials.update()
            .where(credentials.c.id == row.id)
            .values(subscription_token=secrets.token_urlsafe(32))
        )


def downgrade() -> None:
    with op.batch_alter_table('singbox_user_credentials') as batch_op:
        batch_op.drop_constraint(
            'uq_singbox_user_credentials_subscription_token',
            type_='unique',
        )
        batch_op.drop_column('subscription_token')
