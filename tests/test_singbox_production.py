import base64
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.singbox import production
from app.db.base import Base
from app.db.models import SingBoxIngressService, SingBoxNode, SingBoxUserCredential, User
from app.models.singbox import SingBoxConnectionWrite
from app.models.user import UserStatus


class SingBoxProductionTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _user(self, username: str = "user1", status: UserStatus = UserStatus.active) -> User:
        user = User(username=username, status=status, data_limit=0, expire=0)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def test_ensure_user_credentials_creates_public_subscription_token(self):
        user = self._user()

        credential = production.ensure_user_credentials(self.db, user)

        self.assertTrue(credential.subscription_token)
        self.assertGreater(len(credential.subscription_token), 32)
        found = production.get_user_credential_by_subscription_token(
            self.db,
            credential.subscription_token,
        )
        self.assertIsNotNone(found)
        self.assertEqual(found.user.username, "user1")

    def test_public_subscription_token_lookup_requires_active_user(self):
        user = self._user(status=UserStatus.disabled)
        credential = production.ensure_user_credentials(self.db, user)

        found = production.get_user_credential_by_subscription_token(
            self.db,
            credential.subscription_token,
        )

        self.assertIsNone(found)

    def test_ensure_user_credentials_backfills_missing_subscription_token(self):
        user = self._user()
        credential = SingBoxUserCredential(
            user_id=user.id,
            subscription_token=None,
            password="password",
            vmess_uuid="11111111-1111-4111-8111-111111111111",
            vless_uuid="22222222-2222-4222-8222-222222222222",
            tuic_uuid="33333333-3333-4333-8333-333333333333",
            shadowsocks_password="shadowsocks-password",
            enabled_protocols=["hysteria2", "tuic"],
        )
        self.db.add(credential)
        self.db.commit()

        credential = production.ensure_user_credentials(self.db, user)

        self.assertTrue(credential.subscription_token)

    def test_connections_support_same_entry_protocol_with_different_exits(self):
        user = self._user()
        nodes = [
            SingBoxNode(name="entry", public_host="entry.example", entry_enabled=True, exit_enabled=True),
            SingBoxNode(name="exit-a", public_host="exit-a.example", entry_enabled=False, exit_enabled=True),
            SingBoxNode(name="exit-b", public_host="exit-b.example", entry_enabled=False, exit_enabled=True),
        ]
        self.db.add_all(nodes)
        self.db.commit()

        connections = production.replace_user_connections(
            self.db,
            user,
            [
                SingBoxConnectionWrite(
                    label="Entry direct",
                    protocol="hysteria2",
                    entry_node_id=nodes[0].id,
                    exit_node_id=None,
                    sort_order=10,
                ),
                SingBoxConnectionWrite(
                    label="Entry via A",
                    protocol="hysteria2",
                    entry_node_id=nodes[0].id,
                    exit_node_id=nodes[1].id,
                    sort_order=20,
                ),
                SingBoxConnectionWrite(
                    label="Entry via B",
                    protocol="hysteria2",
                    entry_node_id=nodes[0].id,
                    exit_node_id=nodes[2].id,
                    sort_order=30,
                ),
            ],
        )

        self.assertEqual(len(connections), 3)
        self.assertEqual(len({connection.auth_name for connection in connections}), 3)
        self.assertEqual(len({connection.password for connection in connections}), 3)

        builder = production.build_builder(self.db)
        entry_users = builder.build_node_config("entry")["inbounds"][0]["users"]
        self.assertEqual(len(entry_users), 3)
        self.assertEqual(builder.build_node_config("exit-a")["inbounds"][0]["users"], [])
        policies = [policy for policy in builder.route_policies if policy.entry_node == "entry"]
        self.assertEqual({policy.exit_node for policy in policies}, {None, "exit-a", "exit-b"})
        self.assertTrue(all(policy.protocol == "hysteria2" for policy in policies))

        subscription = production.build_user_subscription(self.db, user, config_format="sing-box")
        selector = subscription["outbounds"][0]
        self.assertEqual(selector["outbounds"], [f"connection-{connection.id}" for connection in connections])
        clash = production.build_user_subscription(self.db, user, config_format="clash")
        self.assertIn('name: "Entry via A"', clash)
        v2rayn = base64.b64decode(
            production.build_user_subscription(self.db, user, config_format="v2rayn")
        ).decode()
        self.assertIn("#Entry%20via%20B", v2rayn)

    def test_replace_connections_allows_duplicate_route_with_distinct_credentials(self):
        user = self._user()
        entry = SingBoxNode(name="entry", public_host="entry.example", entry_enabled=True)
        self.db.add(entry)
        self.db.commit()

        payload = SingBoxConnectionWrite(protocol="vless", entry_node_id=entry.id)
        connections = production.replace_user_connections(self.db, user, [payload, payload])

        self.assertEqual(len(connections), 2)
        self.assertNotEqual(connections[0].auth_name, connections[1].auth_name)
        self.assertNotEqual(connections[0].vless_uuid, connections[1].vless_uuid)

    def test_connection_can_select_custom_ingress_service_port_and_profile(self):
        user = self._user()
        node = SingBoxNode(name="entry", public_host="entry.example", entry_enabled=True)
        self.db.add(node)
        self.db.commit()
        defaults = production.ensure_node_overlay_services(self.db, node)
        address = defaults["address"]
        custom = SingBoxIngressService(
            node_id=node.id,
            advertised_address_id=address.id,
            name="AnyTLS alternate",
            protocol="anytls",
            listen_port=15443,
            enabled=True,
            tls_mode="ip-insecure",
            protocol_profile={"min_idle_session": 7},
        )
        self.db.add(custom)
        self.db.commit()

        connection = production.replace_user_connections(
            self.db,
            user,
            [SingBoxConnectionWrite(ingress_service_id=custom.id)],
        )[0]

        self.assertEqual(connection.protocol, "anytls")
        self.assertEqual(connection.ingress_service_id, custom.id)
        config, _ = production.build_node_config(self.db, node.id)
        inbound = next(item for item in config["inbounds"] if item["tag"] == f"public-ingress-{custom.id}")
        self.assertEqual(inbound["listen_port"], 15443)
        self.assertEqual([item["name"] for item in inbound["users"]], [connection.auth_name])
        subscription = production.build_user_subscription(self.db, user, config_format="sing-box")
        outbound = next(item for item in subscription["outbounds"] if item["tag"] == f"connection-{connection.id}")
        self.assertEqual(outbound["server_port"], 15443)
        self.assertEqual(outbound["min_idle_session"], 7)

    def test_delete_node_rejects_referenced_connection(self):
        user = self._user()
        node = SingBoxNode(name="entry", public_host="entry.example", entry_enabled=True)
        self.db.add(node)
        self.db.commit()
        production.replace_user_connections(
            self.db,
            user,
            [SingBoxConnectionWrite(protocol="vless", entry_node_id=node.id)],
        )

        with self.assertRaisesRegex(ValueError, "1 connection"):
            production.delete_node(self.db, node)

        self.assertIsNotNone(production.get_node(self.db, node.id))

    def test_delete_unused_node(self):
        node = SingBoxNode(name="unused", public_host="unused.example")
        self.db.add(node)
        self.db.commit()
        node_id = node.id

        production.delete_node(self.db, node)

        self.assertIsNone(production.get_node(self.db, node_id))

    def test_legacy_policy_creates_default_connections_once(self):
        user = self._user()
        entry = SingBoxNode(name="entry", public_host="entry.example", entry_enabled=True)
        exit_node = SingBoxNode(
            name="exit",
            public_host="exit.example",
            entry_enabled=False,
            exit_enabled=True,
        )
        self.db.add_all([entry, exit_node])
        self.db.commit()

        production.update_user_policy(
            self.db,
            user,
            enabled_protocols=["hysteria2", "vless"],
            exit_node_id=exit_node.id,
        )

        connections = production.get_user_connections(self.db, user)
        self.assertEqual(len(connections), 2)
        self.assertEqual({connection.protocol for connection in connections}, {"hysteria2", "vless"})
        self.assertTrue(all(connection.exit_node_id == exit_node.id for connection in connections))
        original_credentials = {
            connection.protocol: (connection.id, connection.password) for connection in connections
        }

        production.update_user_policy(
            self.db,
            user,
            enabled_protocols=["hysteria2", "vless"],
            exit_node_id=None,
        )

        updated = production.get_user_connections(self.db, user)
        self.assertTrue(all(connection.exit_node_id is None for connection in updated))
        self.assertEqual(
            {connection.protocol: (connection.id, connection.password) for connection in updated},
            original_credentials,
        )

    def test_node_upgrade_instruction_is_disabled_by_default(self):
        original_enabled = production.SINGBOX_NODE_AUTO_UPGRADE
        try:
            production.SINGBOX_NODE_AUTO_UPGRADE = False

            upgrade = production.build_node_upgrade_instruction(
                runtime="docker",
                container_image="ghcr.io/rc-chn/marzban:v0.9.3",
                sync_agent_version="0.9.3",
                agent_url="https://panel.example/api/singbox/sync-agent.sh",
            )

            self.assertIsNone(upgrade)
        finally:
            production.SINGBOX_NODE_AUTO_UPGRADE = original_enabled

    def test_node_upgrade_instruction_targets_docker_image_and_agent(self):
        original_enabled = production.SINGBOX_NODE_AUTO_UPGRADE
        original_image = production.SINGBOX_NODE_TARGET_IMAGE
        original_agent = production.SINGBOX_SYNC_AGENT_VERSION
        try:
            production.SINGBOX_NODE_AUTO_UPGRADE = True
            production.SINGBOX_NODE_TARGET_IMAGE = "ghcr.io/rc-chn/marzban:v0.9.5"
            production.SINGBOX_SYNC_AGENT_VERSION = "0.9.5"

            upgrade = production.build_node_upgrade_instruction(
                runtime="docker",
                container_image="ghcr.io/rc-chn/marzban:v0.9.4",
                sync_agent_version="0.9.4",
                agent_url="https://panel.example/api/singbox/sync-agent.sh",
            )

            self.assertEqual(upgrade["image"], "ghcr.io/rc-chn/marzban:v0.9.5")
            self.assertEqual(upgrade["agent_version"], "0.9.5")
            self.assertEqual(upgrade["agent_url"], "https://panel.example/api/singbox/sync-agent.sh")
            self.assertTrue(upgrade["apply"])
        finally:
            production.SINGBOX_NODE_AUTO_UPGRADE = original_enabled
            production.SINGBOX_NODE_TARGET_IMAGE = original_image
            production.SINGBOX_SYNC_AGENT_VERSION = original_agent

    def test_node_upgrade_instruction_is_noop_when_current(self):
        original_enabled = production.SINGBOX_NODE_AUTO_UPGRADE
        original_image = production.SINGBOX_NODE_TARGET_IMAGE
        original_agent = production.SINGBOX_SYNC_AGENT_VERSION
        try:
            production.SINGBOX_NODE_AUTO_UPGRADE = True
            production.SINGBOX_NODE_TARGET_IMAGE = "ghcr.io/rc-chn/marzban:v0.9.5"
            production.SINGBOX_SYNC_AGENT_VERSION = "0.9.5"

            upgrade = production.build_node_upgrade_instruction(
                runtime="docker",
                container_image="ghcr.io/rc-chn/marzban:v0.9.5",
                sync_agent_version="0.9.5",
                agent_url="https://panel.example/api/singbox/sync-agent.sh",
            )

            self.assertIsNone(upgrade)
        finally:
            production.SINGBOX_NODE_AUTO_UPGRADE = original_enabled
            production.SINGBOX_NODE_TARGET_IMAGE = original_image
            production.SINGBOX_SYNC_AGENT_VERSION = original_agent


if __name__ == "__main__":
    unittest.main()
