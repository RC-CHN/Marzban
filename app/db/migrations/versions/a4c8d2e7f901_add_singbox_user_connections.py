"""add singbox user connections

Revision ID: a4c8d2e7f901
Revises: e91c9b5a2d7f
"""

from __future__ import annotations

import secrets

import sqlalchemy as sa
from alembic import op


revision = "a4c8d2e7f901"
down_revision = "e91c9b5a2d7f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "singbox_user_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entry_node_id", sa.Integer(), nullable=False),
        sa.Column("exit_node_id", sa.Integer(), nullable=True),
        sa.Column("protocol", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("auth_name", sa.String(length=128), nullable=False),
        sa.Column("password", sa.String(length=256), nullable=False),
        sa.Column("vmess_uuid", sa.String(length=36), nullable=True),
        sa.Column("vless_uuid", sa.String(length=36), nullable=True),
        sa.Column("tuic_uuid", sa.String(length=36), nullable=True),
        sa.Column("shadowsocks_password", sa.String(length=256), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="100", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["entry_node_id"], ["singbox_nodes.id"]),
        sa.ForeignKeyConstraint(["exit_node_id"], ["singbox_nodes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("auth_name", name="uq_singbox_user_connections_auth_name"),
    )
    op.create_index(
        "ix_singbox_user_connections_user_id",
        "singbox_user_connections",
        ["user_id"],
    )
    _migrate_legacy_connections()


def _migrate_legacy_connections():
    bind = op.get_bind()
    metadata = sa.MetaData()
    credentials = sa.Table("singbox_user_credentials", metadata, autoload_with=bind)
    users = sa.Table("users", metadata, autoload_with=bind)
    nodes = sa.Table("singbox_nodes", metadata, autoload_with=bind)
    policies = sa.Table("singbox_route_policies", metadata, autoload_with=bind)
    connections = sa.Table("singbox_user_connections", metadata, autoload_with=bind)

    entry_nodes = bind.execute(
        sa.select(nodes.c.id, nodes.c.name).where(nodes.c.entry_enabled.is_(True))
    ).mappings().all()
    node_names = {
        row.id: row.name for row in bind.execute(sa.select(nodes.c.id, nodes.c.name)).mappings()
    }
    for credential in bind.execute(
        sa.select(credentials, users.c.username)
        .select_from(credentials.join(users, credentials.c.user_id == users.c.id))
    ).mappings():
        user_policies = bind.execute(
            sa.select(policies.c.entry_node_id, policies.c.exit_node_id).where(
                policies.c.user_id == credential.user_id,
                policies.c.enabled.is_(True),
            )
        ).mappings().all()
        routes = user_policies or [
            {"entry_node_id": node.id, "exit_node_id": credential.exit_node_id}
            for node in entry_nodes
        ]
        for route in routes:
            entry_name = node_names.get(route["entry_node_id"], "entry")
            exit_name = node_names.get(route["exit_node_id"], "Direct")
            for index, protocol in enumerate(credential.enabled_protocols or []):
                bind.execute(
                    connections.insert().values(
                        user_id=credential.user_id,
                        entry_node_id=route["entry_node_id"],
                        exit_node_id=route["exit_node_id"],
                        protocol=protocol,
                        label=f"{entry_name} -> {exit_name} / {protocol}",
                        auth_name=f"u{credential.user_id}-{protocol}-{secrets.token_hex(5)}",
                        password=credential.password,
                        vmess_uuid=credential.vmess_uuid,
                        vless_uuid=credential.vless_uuid,
                        tuic_uuid=credential.tuic_uuid,
                        shadowsocks_password=credential.shadowsocks_password,
                        enabled=True,
                        sort_order=100 + index,
                    )
                )


def downgrade():
    op.drop_index("ix_singbox_user_connections_user_id", table_name="singbox_user_connections")
    op.drop_table("singbox_user_connections")
