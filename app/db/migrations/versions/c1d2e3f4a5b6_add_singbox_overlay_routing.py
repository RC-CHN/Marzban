"""add singbox overlay routing model

Revision ID: c1d2e3f4a5b6
Revises: b9d3e6f1a204
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import secrets

import sqlalchemy as sa
from alembic import op


revision = "c1d2e3f4a5b6"
down_revision = "b9d3e6f1a204"
branch_labels = None
depends_on = None

PROTOCOL_PORTS = {
    "hysteria2": 11001,
    "tuic": 11002,
    "anytls": 11003,
    "vmess": 11004,
    "vless": 11005,
    "trojan": 11006,
    "shadowsocks": 11007,
}


def upgrade():
    _create_service_tables()
    _create_adjacency_tables()
    _create_revision_tables()
    with op.batch_alter_table("singbox_user_connections") as batch_op:
        batch_op.add_column(sa.Column("ingress_service_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("egress_service_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("routing_policy_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_singbox_connections_ingress_service",
            "singbox_ingress_services",
            ["ingress_service_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_singbox_connections_egress_service",
            "singbox_egress_services",
            ["egress_service_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_singbox_connections_routing_policy",
            "singbox_routing_policies_v2",
            ["routing_policy_id"],
            ["id"],
        )
    with op.batch_alter_table("singbox_nodes") as batch_op:
        batch_op.add_column(sa.Column("capabilities", sa.JSON(), nullable=True))
    _migrate_v096_data()


def _create_service_tables():
    op.create_table(
        "singbox_node_addresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(256), nullable=False),
        sa.Column("kind", sa.String(32), server_default="public", nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["node_id"], ["singbox_nodes.id"]),
        sa.UniqueConstraint("node_id", "address"),
    )
    op.create_index("ix_singbox_node_addresses_node_id", "singbox_node_addresses", ["node_id"])
    op.create_table(
        "singbox_ingress_services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("advertised_address_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("listen_port", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("tls_mode", sa.String(32), server_default="system-ca", nullable=False),
        sa.Column("tls_profile", sa.JSON(), nullable=True),
        sa.Column("protocol_profile", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["node_id"], ["singbox_nodes.id"]),
        sa.ForeignKeyConstraint(["advertised_address_id"], ["singbox_node_addresses.id"]),
        sa.UniqueConstraint("node_id", "protocol", "listen_port"),
    )
    op.create_index("ix_singbox_ingress_services_node_id", "singbox_ingress_services", ["node_id"])
    op.create_table(
        "singbox_egress_services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), server_default="direct", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["node_id"], ["singbox_nodes.id"]),
        sa.UniqueConstraint("node_id", "kind", "name"),
    )
    op.create_index("ix_singbox_egress_services_node_id", "singbox_egress_services", ["node_id"])
    op.create_table(
        "singbox_routing_policies_v2",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("metric_mode", sa.String(32), server_default="admin_only", nullable=False),
        sa.Column("max_hops", sa.Integer(), server_default="8", nullable=False),
        sa.Column("allow_degraded", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("failover", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("required_node_ids", sa.JSON(), nullable=True),
        sa.Column("avoided_node_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )


def _create_adjacency_tables():
    op.create_table(
        "singbox_adjacencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_a_id", sa.Integer(), nullable=False),
        sa.Column("node_b_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["node_a_id"], ["singbox_nodes.id"]),
        sa.ForeignKeyConstraint(["node_b_id"], ["singbox_nodes.id"]),
        sa.UniqueConstraint("node_a_id", "node_b_id"),
    )
    op.create_table(
        "singbox_adjacency_directions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("adjacency_id", sa.Integer(), nullable=False),
        sa.Column("from_node_id", sa.Integer(), nullable=False),
        sa.Column("to_node_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("transport", sa.String(32), server_default="anytls", nullable=False),
        sa.Column("listen_port", sa.Integer(), nullable=False),
        sa.Column("admin_cost", sa.Integer(), server_default="100", nullable=False),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("credential_generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("probe_auth_name", sa.String(128), nullable=False, unique=True),
        sa.Column("probe_password", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["adjacency_id"], ["singbox_adjacencies.id"]),
        sa.ForeignKeyConstraint(["from_node_id"], ["singbox_nodes.id"]),
        sa.ForeignKeyConstraint(["to_node_id"], ["singbox_nodes.id"]),
        sa.UniqueConstraint("adjacency_id", "from_node_id", "to_node_id"),
    )
    op.create_index(
        "ix_singbox_adjacency_directions_adjacency_id",
        "singbox_adjacency_directions",
        ["adjacency_id"],
    )
    op.create_table(
        "singbox_link_state_observations",
        sa.Column("adjacency_direction_id", sa.Integer(), primary_key=True),
        sa.Column("reporting_node_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("oper_state", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("rtt_ms", sa.Float(), nullable=True),
        sa.Column("loss_ppm", sa.Integer(), nullable=True),
        sa.Column("bandwidth_mbps", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=True),
        sa.Column("hold_expires_at", sa.DateTime(), nullable=True),
        sa.Column("message", sa.String(1024), nullable=True),
        sa.ForeignKeyConstraint(["adjacency_direction_id"], ["singbox_adjacency_directions.id"]),
        sa.ForeignKeyConstraint(["reporting_node_id"], ["singbox_nodes.id"]),
    )


def _create_revision_tables():
    op.create_table(
        "singbox_topology_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.Integer(), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "singbox_route_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.Integer(), nullable=False, unique=True),
        sa.Column("topology_revision_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("drain_until", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["topology_revision_id"], ["singbox_topology_revisions.id"]),
    )
    op.create_table(
        "singbox_computed_paths",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("route_revision_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("total_cost", sa.Integer(), nullable=True),
        sa.Column("hop_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(1024), nullable=True),
        sa.ForeignKeyConstraint(["route_revision_id"], ["singbox_route_revisions.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["singbox_user_connections.id"]),
        sa.UniqueConstraint("route_revision_id", "connection_id"),
    )
    op.create_index("ix_singbox_computed_paths_route_revision_id", "singbox_computed_paths", ["route_revision_id"])
    op.create_index("ix_singbox_computed_paths_connection_id", "singbox_computed_paths", ["connection_id"])
    op.create_table(
        "singbox_route_hop_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("route_revision_id", sa.Integer(), nullable=False),
        sa.Column("egress_service_id", sa.Integer(), nullable=False),
        sa.Column("routing_policy_id", sa.Integer(), nullable=False),
        sa.Column("adjacency_direction_id", sa.Integer(), nullable=False),
        sa.Column("auth_name", sa.String(128), nullable=False, unique=True),
        sa.Column("password", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["route_revision_id"], ["singbox_route_revisions.id"]),
        sa.ForeignKeyConstraint(["egress_service_id"], ["singbox_egress_services.id"]),
        sa.ForeignKeyConstraint(["routing_policy_id"], ["singbox_routing_policies_v2.id"]),
        sa.ForeignKeyConstraint(["adjacency_direction_id"], ["singbox_adjacency_directions.id"]),
        sa.UniqueConstraint(
            "route_revision_id",
            "egress_service_id",
            "routing_policy_id",
            "adjacency_direction_id",
        ),
    )
    op.create_index(
        "ix_singbox_route_hop_credentials_route_id",
        "singbox_route_hop_credentials",
        ["route_revision_id"],
    )
    op.create_table(
        "singbox_computed_path_hops",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("computed_path_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("adjacency_direction_id", sa.Integer(), nullable=False),
        sa.Column("from_node_id", sa.Integer(), nullable=False),
        sa.Column("to_node_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["computed_path_id"], ["singbox_computed_paths.id"]),
        sa.ForeignKeyConstraint(["adjacency_direction_id"], ["singbox_adjacency_directions.id"]),
        sa.ForeignKeyConstraint(["from_node_id"], ["singbox_nodes.id"]),
        sa.ForeignKeyConstraint(["to_node_id"], ["singbox_nodes.id"]),
        sa.UniqueConstraint("computed_path_id", "position"),
    )
    op.create_index("ix_singbox_computed_path_hops_path_id", "singbox_computed_path_hops", ["computed_path_id"])
    op.create_table(
        "singbox_node_route_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("route_revision_id", sa.Integer(), nullable=False),
        sa.Column("desired_hash", sa.String(64), nullable=True),
        sa.Column("applied_hash", sa.String(64), nullable=True),
        sa.Column("state", sa.String(32), server_default="pending", nullable=False),
        sa.Column("message", sa.String(1024), nullable=True),
        sa.Column("updated_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["node_id"], ["singbox_nodes.id"]),
        sa.ForeignKeyConstraint(["route_revision_id"], ["singbox_route_revisions.id"]),
        sa.UniqueConstraint("node_id", "route_revision_id"),
    )
    op.create_index("ix_singbox_node_route_revisions_node_id", "singbox_node_route_revisions", ["node_id"])
    op.create_index("ix_singbox_node_route_revisions_route_id", "singbox_node_route_revisions", ["route_revision_id"])


def _migrate_v096_data():
    bind = op.get_bind()
    metadata = sa.MetaData()
    nodes = sa.Table("singbox_nodes", metadata, autoload_with=bind)
    links = sa.Table("singbox_node_links", metadata, autoload_with=bind)
    connections = sa.Table("singbox_user_connections", metadata, autoload_with=bind)
    addresses = sa.Table("singbox_node_addresses", metadata, autoload_with=bind)
    ingresses = sa.Table("singbox_ingress_services", metadata, autoload_with=bind)
    egresses = sa.Table("singbox_egress_services", metadata, autoload_with=bind)
    policies = sa.Table("singbox_routing_policies_v2", metadata, autoload_with=bind)
    adjacencies = sa.Table("singbox_adjacencies", metadata, autoload_with=bind)
    directions = sa.Table("singbox_adjacency_directions", metadata, autoload_with=bind)
    now = datetime.utcnow()

    default_policy_id = bind.execute(
        policies.insert().values(
            name="Default",
            metric_mode="admin_only",
            max_hops=8,
            allow_degraded=False,
            failover=True,
            required_node_ids=[],
            avoided_node_ids=[],
            created_at=now,
            updated_at=now,
        )
    ).inserted_primary_key[0]

    node_rows = bind.execute(sa.select(nodes)).mappings().all()
    node_names = {row.id: row.name for row in node_rows}
    ingress_ids = {}
    egress_ids = {}
    reserved_ports = defaultdict(set)
    for node in node_rows:
        address_id = bind.execute(
            addresses.insert().values(
                node_id=node.id,
                address=node.public_host,
                kind="public",
                is_primary=True,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        ).inserted_primary_key[0]
        public_ports = node.public_ports or {}
        protocol_settings = node.protocol_settings or {}
        if node.entry_enabled:
            for protocol, default_port in PROTOCOL_PORTS.items():
                port = int(public_ports.get(protocol, default_port))
                reserved_ports[node.id].add(port)
                ingress_id = bind.execute(
                    ingresses.insert().values(
                        node_id=node.id,
                        advertised_address_id=address_id,
                        name=f"{node.name} / {protocol}",
                        protocol=protocol,
                        listen_port=port,
                        enabled=True,
                        tls_mode=node.public_tls_mode or "system-ca",
                        tls_profile={
                            "cert_path": node.public_tls_cert_path,
                            "key_path": node.public_tls_key_path,
                            "ca_cert_path": node.public_tls_ca_cert_path,
                        },
                        protocol_profile=protocol_settings.get(protocol, {}),
                        created_at=now,
                        updated_at=now,
                    )
                ).inserted_primary_key[0]
                ingress_ids[(node.id, protocol)] = ingress_id
        egress_id = bind.execute(
            egresses.insert().values(
                node_id=node.id,
                name=f"Direct @ {node.name}",
                kind="direct",
                enabled=bool(node.exit_enabled),
                settings={},
                created_at=now,
                updated_at=now,
            )
        ).inserted_primary_key[0]
        egress_ids[node.id] = egress_id

    adjacency_ids = {}
    next_port = defaultdict(lambda: 20000)
    for link in bind.execute(sa.select(links).order_by(links.c.id)).mappings():
        pair = tuple(sorted((link.from_node_id, link.to_node_id)))
        adjacency_id = adjacency_ids.get(pair)
        if adjacency_id is None:
            adjacency_id = bind.execute(
                adjacencies.insert().values(
                    node_a_id=pair[0],
                    node_b_id=pair[1],
                    name=f"{node_names[pair[0]]} <-> {node_names[pair[1]]}",
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
            ).inserted_primary_key[0]
            adjacency_ids[pair] = adjacency_id
        port = next_port[link.to_node_id]
        while port in reserved_ports[link.to_node_id]:
            port += 1
        next_port[link.to_node_id] = port + 1
        reserved_ports[link.to_node_id].add(port)
        bind.execute(
            directions.insert().values(
                adjacency_id=adjacency_id,
                from_node_id=link.from_node_id,
                to_node_id=link.to_node_id,
                enabled=bool(link.enabled),
                transport=link.protocol,
                listen_port=port,
                admin_cost=100,
                settings={},
                credential_generation=1,
                probe_auth_name=f"probe-{secrets.token_hex(12)}",
                probe_password=secrets.token_urlsafe(32),
                created_at=now,
                updated_at=now,
            )
        )

    for connection in bind.execute(sa.select(connections)).mappings():
        egress_node_id = connection.exit_node_id or connection.entry_node_id
        bind.execute(
            connections.update()
            .where(connections.c.id == connection.id)
            .values(
                ingress_service_id=ingress_ids.get((connection.entry_node_id, connection.protocol)),
                egress_service_id=egress_ids.get(egress_node_id),
                routing_policy_id=default_policy_id,
            )
        )


def downgrade():
    with op.batch_alter_table("singbox_nodes") as batch_op:
        batch_op.drop_column("capabilities")
    with op.batch_alter_table("singbox_user_connections") as batch_op:
        batch_op.drop_constraint("fk_singbox_connections_routing_policy", type_="foreignkey")
        batch_op.drop_constraint("fk_singbox_connections_egress_service", type_="foreignkey")
        batch_op.drop_constraint("fk_singbox_connections_ingress_service", type_="foreignkey")
        batch_op.drop_column("routing_policy_id")
        batch_op.drop_column("egress_service_id")
        batch_op.drop_column("ingress_service_id")
    op.drop_index("ix_singbox_node_route_revisions_route_id", table_name="singbox_node_route_revisions")
    op.drop_index("ix_singbox_node_route_revisions_node_id", table_name="singbox_node_route_revisions")
    op.drop_table("singbox_node_route_revisions")
    op.drop_index("ix_singbox_computed_path_hops_path_id", table_name="singbox_computed_path_hops")
    op.drop_table("singbox_computed_path_hops")
    op.drop_index("ix_singbox_computed_paths_connection_id", table_name="singbox_computed_paths")
    op.drop_index("ix_singbox_computed_paths_route_revision_id", table_name="singbox_computed_paths")
    op.drop_table("singbox_computed_paths")
    op.drop_index(
        "ix_singbox_route_hop_credentials_route_id",
        table_name="singbox_route_hop_credentials",
    )
    op.drop_table("singbox_route_hop_credentials")
    op.drop_table("singbox_route_revisions")
    op.drop_table("singbox_topology_revisions")
    op.drop_table("singbox_link_state_observations")
    op.drop_index(
        "ix_singbox_adjacency_directions_adjacency_id",
        table_name="singbox_adjacency_directions",
    )
    op.drop_table("singbox_adjacency_directions")
    op.drop_table("singbox_adjacencies")
    op.drop_table("singbox_routing_policies_v2")
    op.drop_index("ix_singbox_egress_services_node_id", table_name="singbox_egress_services")
    op.drop_table("singbox_egress_services")
    op.drop_index("ix_singbox_ingress_services_node_id", table_name="singbox_ingress_services")
    op.drop_table("singbox_ingress_services")
    op.drop_index("ix_singbox_node_addresses_node_id", table_name="singbox_node_addresses")
    op.drop_table("singbox_node_addresses")
