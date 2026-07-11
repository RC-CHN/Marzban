"""add singbox protocol profiles

Revision ID: b9d3e6f1a204
Revises: a4c8d2e7f901
"""

import sqlalchemy as sa
from alembic import op


revision = "b9d3e6f1a204"
down_revision = "a4c8d2e7f901"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("singbox_nodes") as batch_op:
        batch_op.add_column(sa.Column("protocol_settings", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("singbox_nodes") as batch_op:
        batch_op.drop_column("protocol_settings")
