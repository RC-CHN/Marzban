"""add singbox ingress health observations

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""

import sqlalchemy as sa
from alembic import op


revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "singbox_ingress_observations",
        sa.Column("ingress_service_id", sa.Integer(), primary_key=True),
        sa.Column("reporting_node_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("oper_state", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=True),
        sa.Column("hold_expires_at", sa.DateTime(), nullable=True),
        sa.Column("message", sa.String(1024), nullable=True),
        sa.ForeignKeyConstraint(["ingress_service_id"], ["singbox_ingress_services.id"]),
        sa.ForeignKeyConstraint(["reporting_node_id"], ["singbox_nodes.id"]),
    )


def downgrade():
    op.drop_table("singbox_ingress_observations")
