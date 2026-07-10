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


if __name__ == "__main__":
    unittest.main()
