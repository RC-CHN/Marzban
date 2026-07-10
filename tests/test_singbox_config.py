import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _ensure_package(name: str) -> None:
    if name in sys.modules:
        return
    package = types.ModuleType(name)
    package.__path__ = []
    sys.modules[name] = package


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


for package_name in ("app", "app.core", "app.core.singbox"):
    _ensure_package(package_name)

config = _load_module("app.core.singbox.config", ROOT / "app/core/singbox/config.py")
subscription = _load_module("app.core.singbox.subscription", ROOT / "app/core/singbox/subscription.py")


SUPPORTED_PROTOCOLS = config.SUPPORTED_PROTOCOLS
NodeLink = config.NodeLink
RoutePolicy = config.RoutePolicy
SingBoxConfigBuilder = config.SingBoxConfigBuilder
SingBoxNode = config.SingBoxNode
SingBoxUser = config.SingBoxUser
SingBoxUserCredentials = config.SingBoxUserCredentials
TLSSettings = config.TLSSettings


class SingBoxConfigBuilderTest(unittest.TestCase):
    def _user(self, auth_name: str = "u1") -> SingBoxUser:
        return SingBoxUser(
            auth_name=auth_name,
            credentials=SingBoxUserCredentials(
                password="shared-password",
                vmess_uuid="11111111-1111-4111-8111-111111111111",
                vless_uuid="22222222-2222-4222-8222-222222222222",
                tuic_uuid="33333333-3333-4333-8333-333333333333",
                shadowsocks_password="per-user-shadowsocks-secret",
            ),
        )

    def _builder(self) -> SingBoxConfigBuilder:
        nodes = {
            "node-a": SingBoxNode(
                name="node-a",
                public_host="node-a.example",
                public_tls_mode="ip-ca",
                public_tls_ca_cert_path="/etc/sing-box/public/ca.crt",
            ),
            "node-b": SingBoxNode(name="node-b", public_host="node-b.example"),
            "node-c": SingBoxNode(name="node-c", public_host="node-c.example"),
        }
        return SingBoxConfigBuilder(
            nodes=nodes,
            users=[self._user()],
            route_policies=[RoutePolicy(entry_node="node-a", auth_name="u1", exit_node="node-b")],
            node_links=[
                NodeLink(from_node="node-a", to_node="node-b", auth_name="link-a", password="link-secret"),
                NodeLink(from_node="node-b", to_node="node-a", auth_name="link-b", password="link-secret"),
            ],
            node_link_tls=TLSSettings(
                certificate_path="/etc/sing-box/node-link/node.crt",
                key_path="/etc/sing-box/node-link/node.key",
                client_insecure=False,
                ca_certificate_path="/etc/sing-box/node-link/ca.crt",
                client_certificate_path="/etc/sing-box/node-link/client.crt",
                client_key_path="/etc/sing-box/node-link/client.key",
                server_client_authentication="require-and-verify",
                server_client_certificate_path="/etc/sing-box/node-link/ca.crt",
            ),
        )

    def test_public_inbounds_cover_all_supported_protocols(self):
        node_config = self._builder().build_node_config("node-a")
        inbounds_by_tag = {inbound["tag"]: inbound for inbound in node_config["inbounds"]}

        expected_tags = {f"public-{protocol}" for protocol in SUPPORTED_PROTOCOLS}
        self.assertTrue(expected_tags.issubset(inbounds_by_tag))
        for protocol in SUPPORTED_PROTOCOLS:
            inbound = inbounds_by_tag[f"public-{protocol}"]
            self.assertEqual(inbound["listen_port"], getattr(config.ProtocolPorts(), protocol))

    def test_route_policy_sends_user_to_selected_exit_node(self):
        node_config = self._builder().build_node_config("node-a")
        route_rules = node_config["route"]["rules"]
        outbounds_by_tag = {outbound["tag"]: outbound for outbound in node_config["outbounds"]}

        self.assertIn("exit-node-b", outbounds_by_tag)
        self.assertEqual(
            route_rules,
            [
                {
                    "inbound": [f"public-{protocol}" for protocol in SUPPORTED_PROTOCOLS],
                    "auth_user": ["u1"],
                    "action": "route",
                    "outbound": "exit-node-b",
                }
            ],
        )

    def test_node_link_uses_mtls_without_insecure_outbound(self):
        node_config = self._builder().build_node_config("node-a")
        inbounds_by_tag = {inbound["tag"]: inbound for inbound in node_config["inbounds"]}
        outbounds_by_tag = {outbound["tag"]: outbound for outbound in node_config["outbounds"]}

        link_inbound_tls = inbounds_by_tag["node-link-hysteria2"]["tls"]
        self.assertEqual(link_inbound_tls["client_authentication"], "require-and-verify")
        self.assertEqual(link_inbound_tls["client_certificate_path"], "/etc/sing-box/node-link/ca.crt")

        exit_tls = outbounds_by_tag["exit-node-b"]["tls"]
        self.assertNotIn("insecure", exit_tls)
        self.assertEqual(exit_tls["certificate_path"], "/etc/sing-box/node-link/ca.crt")
        self.assertEqual(exit_tls["client_certificate_path"], "/etc/sing-box/node-link/client.crt")
        self.assertEqual(exit_tls["client_key_path"], "/etc/sing-box/node-link/client.key")

    def test_anytls_node_link_uses_tcp_transport_with_mtls(self):
        nodes = {
            "node-a": SingBoxNode(name="node-a", public_host="node-a.example"),
            "node-b": SingBoxNode(name="node-b", public_host="node-b.example"),
        }
        builder = SingBoxConfigBuilder(
            nodes=nodes,
            users=[self._user()],
            route_policies=[RoutePolicy(entry_node="node-a", auth_name="u1", exit_node="node-b")],
            node_links=[
                NodeLink(
                    from_node="node-a",
                    to_node="node-b",
                    auth_name="link-a",
                    password="link-secret",
                    protocol="anytls",
                )
            ],
            node_link_tls=TLSSettings(
                certificate_path="/etc/sing-box/node-link/node.crt",
                key_path="/etc/sing-box/node-link/node.key",
                client_insecure=False,
                ca_certificate_path="/etc/sing-box/node-link/ca.crt",
                client_certificate_path="/etc/sing-box/node-link/client.crt",
                client_key_path="/etc/sing-box/node-link/client.key",
                server_client_authentication="require-and-verify",
                server_client_certificate_path="/etc/sing-box/node-link/ca.crt",
            ),
        )

        entry_config = builder.build_node_config("node-a")
        exit_config = builder.build_node_config("node-b")
        entry_outbounds = {outbound["tag"]: outbound for outbound in entry_config["outbounds"]}
        exit_inbounds = {inbound["tag"]: inbound for inbound in exit_config["inbounds"]}

        self.assertEqual(entry_outbounds["exit-node-b"]["type"], "anytls")
        self.assertNotIn("insecure", entry_outbounds["exit-node-b"]["tls"])
        self.assertEqual(entry_outbounds["exit-node-b"]["tls"]["client_key_path"], "/etc/sing-box/node-link/client.key")
        self.assertEqual(exit_inbounds["node-link-anytls"]["type"], "anytls")
        self.assertEqual(exit_inbounds["node-link-anytls"]["tls"]["client_authentication"], "require-and-verify")

    def test_subscriptions_include_each_enabled_protocol(self):
        builder = self._builder()
        user = self._user()
        singbox_doc = subscription.build_singbox_subscription(builder, "node-a", user, SUPPORTED_PROTOCOLS)
        selector = singbox_doc["outbounds"][0]

        self.assertEqual(selector["type"], "selector")
        self.assertEqual(selector["outbounds"], [f"node-a-{protocol}" for protocol in SUPPORTED_PROTOCOLS])

        clash_doc = subscription.build_clash_subscription(builder, "node-a", user, SUPPORTED_PROTOCOLS)
        for protocol in SUPPORTED_PROTOCOLS:
            self.assertIn(f'"node-a-{protocol}"', clash_doc)


if __name__ == "__main__":
    unittest.main()
