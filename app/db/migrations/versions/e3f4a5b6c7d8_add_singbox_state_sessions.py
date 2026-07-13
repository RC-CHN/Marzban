"""add singbox link-state sessions

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
"""

import sqlalchemy as sa
from alembic import op


revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "singbox_node_state_sessions",
        sa.Column("node_id", sa.Integer(), primary_key=True),
        sa.Column("epoch", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("lease_token_hash", sa.String(64), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["singbox_nodes.id"]),
    )
    with op.batch_alter_table("singbox_ingress_services") as batch_op:
        batch_op.add_column(
            sa.Column("generation", sa.BigInteger(), server_default="1", nullable=False)
        )
    with op.batch_alter_table("singbox_adjacency_directions") as batch_op:
        batch_op.add_column(
            sa.Column("generation", sa.BigInteger(), server_default="1", nullable=False)
        )
    for table_name in ("singbox_ingress_observations", "singbox_link_state_observations"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(
                sa.Column("resource_generation", sa.BigInteger(), server_default="1", nullable=False)
            )
            batch_op.add_column(
                sa.Column("session_epoch", sa.BigInteger(), server_default="0", nullable=False)
            )
            batch_op.add_column(
                sa.Column("snapshot_sequence", sa.BigInteger(), server_default="0", nullable=False)
            )
        op.execute(
            sa.text(
                f"UPDATE {table_name} SET snapshot_sequence = sequence "
                "WHERE snapshot_sequence = 0"
            )
        )


def downgrade():
    for table_name in ("singbox_link_state_observations", "singbox_ingress_observations"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("snapshot_sequence")
            batch_op.drop_column("session_epoch")
            batch_op.drop_column("resource_generation")
    with op.batch_alter_table("singbox_adjacency_directions") as batch_op:
        batch_op.drop_column("generation")
    with op.batch_alter_table("singbox_ingress_services") as batch_op:
        batch_op.drop_column("generation")
    op.drop_table("singbox_node_state_sessions")
