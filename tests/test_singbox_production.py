import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.singbox import production
from app.db.base import Base
from app.db.models import SingBoxUserCredential, User
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
