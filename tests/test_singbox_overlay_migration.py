import tempfile
import unittest
from pathlib import Path

import config as app_config
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


class SingBoxOverlayMigrationTestCase(unittest.TestCase):
    def test_v096_data_is_mapped_without_changing_legacy_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "migration.sqlite"
            database_url = f"sqlite:///{database_path}"
            alembic = Config("alembic.ini")
            original_url = app_config.SQLALCHEMY_DATABASE_URL
            app_config.SQLALCHEMY_DATABASE_URL = database_url
            try:
                command.upgrade(alembic, "b9d3e6f1a204")
                engine = sa.create_engine(database_url)
                self._seed_v096(engine)
                command.upgrade(alembic, "head")
                self._assert_overlay_data(engine)
                engine.dispose()
                command.downgrade(alembic, "b9d3e6f1a204")
                engine = sa.create_engine(database_url)
                self._assert_v096_schema_restored(engine)
                engine.dispose()
            finally:
                app_config.SQLALCHEMY_DATABASE_URL = original_url

    def _seed_v096(self, engine):
        metadata = sa.MetaData()
        metadata.reflect(engine)
        users = metadata.tables["users"]
        nodes = metadata.tables["singbox_nodes"]
        links = metadata.tables["singbox_node_links"]
        connections = metadata.tables["singbox_user_connections"]
        with engine.begin() as connection:
            user_id = connection.execute(
                users.insert().values(username="alice", status="active")
            ).inserted_primary_key[0]
            node_a_id = connection.execute(
                nodes.insert().values(
                    name="node-a",
                    public_host="192.0.2.10",
                    entry_enabled=True,
                    exit_enabled=True,
                    status="connected",
                    config_path="/etc/marzban-singbox/config.json",
                    public_ports={"anytls": 13003},
                    protocol_settings={"anytls": {"min_idle_session": 2}},
                )
            ).inserted_primary_key[0]
            node_b_id = connection.execute(
                nodes.insert().values(
                    name="node-b",
                    public_host="192.0.2.11",
                    entry_enabled=False,
                    exit_enabled=True,
                    status="connected",
                    config_path="/etc/marzban-singbox/config.json",
                )
            ).inserted_primary_key[0]
            connection.execute(
                links.insert(),
                [
                    {
                        "from_node_id": node_a_id,
                        "to_node_id": node_b_id,
                        "protocol": "anytls",
                        "auth_name": "link-a",
                        "password": "secret-a",
                    },
                    {
                        "from_node_id": node_b_id,
                        "to_node_id": node_a_id,
                        "protocol": "hysteria2",
                        "auth_name": "link-b",
                        "password": "secret-b",
                    },
                ],
            )
            connection.execute(
                connections.insert().values(
                    user_id=user_id,
                    entry_node_id=node_a_id,
                    exit_node_id=node_b_id,
                    protocol="anytls",
                    label="A via B",
                    auth_name="alice-a-b",
                    password="public-secret",
                )
            )

    def _assert_overlay_data(self, engine):
        metadata = sa.MetaData()
        metadata.reflect(engine)
        with engine.connect() as connection:
            addresses = connection.execute(
                sa.select(metadata.tables["singbox_node_addresses"])
            ).mappings().all()
            ingresses = connection.execute(
                sa.select(metadata.tables["singbox_ingress_services"])
            ).mappings().all()
            egresses = connection.execute(
                sa.select(metadata.tables["singbox_egress_services"])
            ).mappings().all()
            adjacencies = connection.execute(
                sa.select(metadata.tables["singbox_adjacencies"])
            ).mappings().all()
            directions = connection.execute(
                sa.select(metadata.tables["singbox_adjacency_directions"])
            ).mappings().all()
            ingress_observations = connection.execute(
                sa.select(metadata.tables["singbox_ingress_observations"])
            ).mappings().all()
            policies = connection.execute(
                sa.select(metadata.tables["singbox_routing_policies_v2"])
            ).mappings().all()
            migrated_connection = connection.execute(
                sa.select(metadata.tables["singbox_user_connections"])
            ).mappings().one()

        self.assertEqual({row.address for row in addresses}, {"192.0.2.10", "192.0.2.11"})
        self.assertEqual(len(ingresses), 7)
        anytls = next(row for row in ingresses if row.protocol == "anytls")
        self.assertEqual(anytls.listen_port, 13003)
        self.assertEqual(anytls.protocol_profile, {"min_idle_session": 2})
        self.assertEqual(len(egresses), 2)
        self.assertEqual(len(adjacencies), 1)
        self.assertEqual(len(directions), 2)
        self.assertEqual(ingress_observations, [])
        self.assertEqual({row.transport for row in directions}, {"anytls", "hysteria2"})
        self.assertEqual(len({(row.to_node_id, row.listen_port) for row in directions}), 2)
        self.assertTrue(all(row.listen_port >= 20000 for row in directions))
        self.assertEqual(policies[0].max_hops, 8)
        self.assertIsNotNone(migrated_connection.ingress_service_id)
        self.assertIsNotNone(migrated_connection.egress_service_id)
        self.assertEqual(migrated_connection.routing_policy_id, policies[0].id)
        self.assertEqual(migrated_connection.entry_node_id, anytls.node_id)
        self.assertEqual(migrated_connection.protocol, "anytls")
        connection_fks = {
            tuple(item["constrained_columns"])
            for item in sa.inspect(engine).get_foreign_keys("singbox_user_connections")
        }
        node_fks = {
            tuple(item["constrained_columns"])
            for item in sa.inspect(engine).get_foreign_keys("singbox_nodes")
        }
        self.assertTrue(
            {("ingress_service_id",), ("egress_service_id",), ("routing_policy_id",)}
            <= connection_fks
        )
        self.assertFalse(
            {("egress_service_id",), ("routing_policy_id",)} & node_fks
        )

    def _assert_v096_schema_restored(self, engine):
        inspector = sa.inspect(engine)
        self.assertNotIn("singbox_topology_revisions", inspector.get_table_names())
        self.assertNotIn("singbox_ingress_observations", inspector.get_table_names())
        connection_columns = {
            item["name"] for item in inspector.get_columns("singbox_user_connections")
        }
        self.assertFalse(
            {"ingress_service_id", "egress_service_id", "routing_policy_id"}
            & connection_columns
        )
        metadata = sa.MetaData()
        metadata.reflect(engine, only=["singbox_user_connections"])
        with engine.connect() as connection:
            restored = connection.execute(
                sa.select(metadata.tables["singbox_user_connections"])
            ).mappings().one()
        self.assertEqual(restored.label, "A via B")
        self.assertEqual(restored.protocol, "anytls")


if __name__ == "__main__":
    unittest.main()
