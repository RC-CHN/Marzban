from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


Protocol = Literal[
    "hysteria2",
    "tuic",
    "anytls",
    "vmess",
    "vless",
    "trojan",
    "shadowsocks",
]

SUPPORTED_PROTOCOLS: tuple[Protocol, ...] = (
    "hysteria2",
    "tuic",
    "anytls",
    "vmess",
    "vless",
    "trojan",
    "shadowsocks",
)


@dataclass(frozen=True)
class ProtocolPorts:
    hysteria2: int = 11001
    tuic: int = 11002
    anytls: int = 11003
    vmess: int = 11004
    vless: int = 11005
    trojan: int = 11006
    shadowsocks: int = 11007

    def get(self, protocol: Protocol) -> int:
        return getattr(self, protocol)


@dataclass(frozen=True)
class ShadowsocksSettings:
    method: str = "2022-blake3-aes-128-gcm"
    server_password: str = "MDEyMzQ1Njc4OWFiY2RlZg=="


@dataclass(frozen=True)
class SingBoxNode:
    name: str
    public_host: str
    node_link_port: int = 12443
    entry_enabled: bool = True
    exit_enabled: bool = True
    public_ports: ProtocolPorts | None = None


@dataclass(frozen=True)
class SingBoxUserCredentials:
    password: str
    vmess_uuid: str | None = None
    vless_uuid: str | None = None
    tuic_uuid: str | None = None
    shadowsocks_password: str | None = None


@dataclass(frozen=True)
class SingBoxUser:
    auth_name: str
    credentials: SingBoxUserCredentials
    protocols: tuple[Protocol, ...] = SUPPORTED_PROTOCOLS

    def supports(self, protocol: Protocol) -> bool:
        return protocol in self.protocols


@dataclass(frozen=True)
class NodeLink:
    from_node: str
    to_node: str
    auth_name: str
    password: str
    enabled: bool = True


@dataclass(frozen=True)
class RoutePolicy:
    entry_node: str
    auth_name: str
    exit_node: str | None


@dataclass(frozen=True)
class TLSSettings:
    certificate_path: str = "/etc/sing-box/certs/poc.crt"
    key_path: str = "/etc/sing-box/certs/poc.key"
    client_insecure: bool = True
    ca_certificate_path: str | None = None
    client_certificate_path: str | None = None
    client_key_path: str | None = None
    server_client_authentication: str | None = None
    server_client_certificate_path: str | list[str] | None = None


@dataclass
class SingBoxConfigBuilder:
    nodes: dict[str, SingBoxNode]
    users: list[SingBoxUser]
    route_policies: list[RoutePolicy]
    ports: ProtocolPorts = field(default_factory=ProtocolPorts)
    shadowsocks: ShadowsocksSettings = field(default_factory=ShadowsocksSettings)
    tls_cert_path: str = "/etc/sing-box/certs/poc.crt"
    tls_key_path: str = "/etc/sing-box/certs/poc.key"
    public_tls: TLSSettings | None = None
    node_link_tls: TLSSettings | None = None
    log_level: str = "info"
    node_links: list[NodeLink] | None = None

    def __post_init__(self) -> None:
        if self.node_links is None:
            self.node_links = self.build_full_mesh_links()
        if self.public_tls is None:
            self.public_tls = TLSSettings(
                certificate_path=self.tls_cert_path,
                key_path=self.tls_key_path,
            )
        if self.node_link_tls is None:
            self.node_link_tls = TLSSettings(
                certificate_path=self.tls_cert_path,
                key_path=self.tls_key_path,
            )

    def build_full_mesh_links(self) -> list[NodeLink]:
        links = []
        for from_node in self.nodes:
            for to_node in self.nodes:
                if from_node == to_node:
                    continue
                links.append(
                    NodeLink(
                        from_node=from_node,
                        to_node=to_node,
                        auth_name=f"link-{from_node}",
                        password=f"link-secret-{from_node}-to-{to_node}",
                    )
                )
        return links

    def build_node_config(self, node_name: str) -> dict[str, Any]:
        node = self._node(node_name)
        public_tags = [f"public-{protocol}" for protocol in SUPPORTED_PROTOCOLS]
        return {
            "log": {
                "level": self.log_level,
                "timestamp": True,
            },
            "inbounds": [
                *(self._public_inbounds(node) if node.entry_enabled else []),
                self._node_link_inbound(node_name),
            ],
            "outbounds": [
                {"type": "direct", "tag": "direct"},
                {"type": "block", "tag": "block"},
                *self._node_link_outbounds(node_name),
            ],
            "route": {
                "rules": self._route_rules(node_name, public_tags),
                "final": "direct",
            },
        }

    def build_client_config(
        self,
        protocol: Protocol,
        entry_node: str,
        user: SingBoxUser,
        listen_port: int = 2080,
    ) -> dict[str, Any]:
        outbound = self._client_outbound(protocol, entry_node, user)
        return {
            "log": {
                "level": self.log_level,
                "timestamp": True,
            },
            "inbounds": [
                {
                    "type": "mixed",
                    "tag": "mixed-in",
                    "listen": "127.0.0.1",
                    "listen_port": listen_port,
                }
            ],
            "outbounds": [
                outbound,
                {"type": "direct", "tag": "direct"},
                {"type": "block", "tag": "block"},
            ],
            "route": {
                "final": outbound["tag"],
            },
        }

    def _public_inbounds(self, node: SingBoxNode) -> list[dict[str, Any]]:
        return [
            self._hysteria2_inbound(node),
            self._tuic_inbound(node),
            self._anytls_inbound(node),
            self._vmess_inbound(node),
            self._vless_inbound(node),
            self._trojan_inbound(node),
            self._shadowsocks_inbound(node),
        ]

    def _hysteria2_inbound(self, node: SingBoxNode) -> dict[str, Any]:
        return {
            "type": "hysteria2",
            "tag": "public-hysteria2",
            "listen": "::",
            "listen_port": self._port(node, "hysteria2"),
            "users": [
                {"name": user.auth_name, "password": user.credentials.password}
                for user in self._users_for("hysteria2")
            ],
            "ignore_client_bandwidth": True,
            "tls": self._server_tls(self.public_tls),
        }

    def _tuic_inbound(self, node: SingBoxNode) -> dict[str, Any]:
        return {
            "type": "tuic",
            "tag": "public-tuic",
            "listen": "::",
            "listen_port": self._port(node, "tuic"),
            "users": [
                {
                    "name": user.auth_name,
                    "uuid": self._require(user.credentials.tuic_uuid, user.auth_name, "tuic_uuid"),
                    "password": user.credentials.password,
                }
                for user in self._users_for("tuic")
            ],
            "congestion_control": "bbr",
            "zero_rtt_handshake": False,
            "tls": self._server_tls(self.public_tls),
        }

    def _anytls_inbound(self, node: SingBoxNode) -> dict[str, Any]:
        return {
            "type": "anytls",
            "tag": "public-anytls",
            "listen": "::",
            "listen_port": self._port(node, "anytls"),
            "users": [
                {"name": user.auth_name, "password": user.credentials.password}
                for user in self._users_for("anytls")
            ],
            "tls": self._server_tls(self.public_tls),
        }

    def _vmess_inbound(self, node: SingBoxNode) -> dict[str, Any]:
        return {
            "type": "vmess",
            "tag": "public-vmess",
            "listen": "::",
            "listen_port": self._port(node, "vmess"),
            "users": [
                {
                    "name": user.auth_name,
                    "uuid": self._require(user.credentials.vmess_uuid, user.auth_name, "vmess_uuid"),
                    "alterId": 0,
                }
                for user in self._users_for("vmess")
            ],
        }

    def _vless_inbound(self, node: SingBoxNode) -> dict[str, Any]:
        return {
            "type": "vless",
            "tag": "public-vless",
            "listen": "::",
            "listen_port": self._port(node, "vless"),
            "users": [
                {
                    "name": user.auth_name,
                    "uuid": self._require(user.credentials.vless_uuid, user.auth_name, "vless_uuid"),
                    "flow": "",
                }
                for user in self._users_for("vless")
            ],
        }

    def _trojan_inbound(self, node: SingBoxNode) -> dict[str, Any]:
        return {
            "type": "trojan",
            "tag": "public-trojan",
            "listen": "::",
            "listen_port": self._port(node, "trojan"),
            "users": [
                {"name": user.auth_name, "password": user.credentials.password}
                for user in self._users_for("trojan")
            ],
            "tls": self._server_tls(self.public_tls),
        }

    def _shadowsocks_inbound(self, node: SingBoxNode) -> dict[str, Any]:
        return {
            "type": "shadowsocks",
            "tag": "public-shadowsocks",
            "listen": "::",
            "listen_port": self._port(node, "shadowsocks"),
            "method": self.shadowsocks.method,
            "password": self.shadowsocks.server_password,
            "users": [
                {
                    "name": user.auth_name,
                    "password": self._require(
                        user.credentials.shadowsocks_password,
                        user.auth_name,
                        "shadowsocks_password",
                    ),
                }
                for user in self._users_for("shadowsocks")
            ],
        }

    def _node_link_inbound(self, node_name: str) -> dict[str, Any]:
        node = self._node(node_name)
        links = [
            link
            for link in self.node_links or []
            if link.enabled and link.to_node == node_name and link.from_node != node_name
        ]
        return {
            "type": "hysteria2",
            "tag": "node-link-hysteria2",
            "listen": "::",
            "listen_port": node.node_link_port,
            "users": [
                {"name": link.auth_name, "password": link.password}
                for link in links
            ],
            "ignore_client_bandwidth": True,
            "tls": self._server_tls(self.node_link_tls),
        }

    def _node_link_outbounds(self, node_name: str) -> list[dict[str, Any]]:
        outbounds = []
        for link in self.node_links or []:
            if not link.enabled or link.from_node != node_name or link.to_node == node_name:
                continue
            target = self._node(link.to_node)
            if not target.exit_enabled:
                continue
            outbounds.append(
                {
                    "type": "hysteria2",
                    "tag": f"exit-{link.to_node}",
                    "server": target.public_host,
                    "server_port": target.node_link_port,
                    "password": link.password,
                    "tls": self._client_tls(target.public_host, self.node_link_tls),
                }
            )
        return outbounds

    def _route_rules(self, node_name: str, public_tags: list[str]) -> list[dict[str, Any]]:
        rules = []
        for policy in self.route_policies:
            if policy.entry_node != node_name:
                continue
            if not policy.exit_node or policy.exit_node == node_name:
                continue
            rules.append(
                {
                    "inbound": public_tags,
                    "auth_user": [policy.auth_name],
                    "action": "route",
                    "outbound": f"exit-{policy.exit_node}",
                }
            )
        return rules

    def _client_outbound(
        self,
        protocol: Protocol,
        entry_node_name: str,
        user: SingBoxUser,
    ) -> dict[str, Any]:
        entry_node = self._node(entry_node_name)
        credentials = user.credentials
        if protocol == "hysteria2":
            return {
                "type": "hysteria2",
                "tag": "proxy",
                "server": entry_node.public_host,
                "server_port": self._port(entry_node, "hysteria2"),
                "password": credentials.password,
                "tls": self._client_tls(entry_node.public_host, self.public_tls),
            }
        if protocol == "tuic":
            return {
                "type": "tuic",
                "tag": "proxy",
                "server": entry_node.public_host,
                "server_port": self._port(entry_node, "tuic"),
                "uuid": self._require(credentials.tuic_uuid, user.auth_name, "tuic_uuid"),
                "password": credentials.password,
                "congestion_control": "bbr",
                "tls": self._client_tls(entry_node.public_host, self.public_tls),
            }
        if protocol == "anytls":
            return {
                "type": "anytls",
                "tag": "proxy",
                "server": entry_node.public_host,
                "server_port": self._port(entry_node, "anytls"),
                "password": credentials.password,
                "tls": self._client_tls(entry_node.public_host, self.public_tls),
            }
        if protocol == "vmess":
            return {
                "type": "vmess",
                "tag": "proxy",
                "server": entry_node.public_host,
                "server_port": self._port(entry_node, "vmess"),
                "uuid": self._require(credentials.vmess_uuid, user.auth_name, "vmess_uuid"),
                "security": "auto",
                "alter_id": 0,
                "network": "tcp",
            }
        if protocol == "vless":
            return {
                "type": "vless",
                "tag": "proxy",
                "server": entry_node.public_host,
                "server_port": self._port(entry_node, "vless"),
                "uuid": self._require(credentials.vless_uuid, user.auth_name, "vless_uuid"),
                "flow": "",
                "network": "tcp",
            }
        if protocol == "trojan":
            return {
                "type": "trojan",
                "tag": "proxy",
                "server": entry_node.public_host,
                "server_port": self._port(entry_node, "trojan"),
                "password": credentials.password,
                "network": "tcp",
                "tls": self._client_tls(entry_node.public_host, self.public_tls),
            }
        if protocol == "shadowsocks":
            user_password = self._require(
                credentials.shadowsocks_password,
                user.auth_name,
                "shadowsocks_password",
            )
            return {
                "type": "shadowsocks",
                "tag": "proxy",
                "server": entry_node.public_host,
                "server_port": self._port(entry_node, "shadowsocks"),
                "method": self.shadowsocks.method,
                "password": f"{self.shadowsocks.server_password}:{user_password}",
                "network": "tcp",
            }
        raise ValueError(f"Unsupported protocol: {protocol}")

    def _users_for(self, protocol: Protocol) -> Iterable[SingBoxUser]:
        return (user for user in self.users if user.supports(protocol))

    def _node(self, node_name: str) -> SingBoxNode:
        try:
            return self.nodes[node_name]
        except KeyError as exc:
            raise ValueError(f"Unknown node: {node_name}") from exc

    def _port(self, node: SingBoxNode, protocol: Protocol) -> int:
        ports = node.public_ports or self.ports
        return ports.get(protocol)

    def _server_tls(self, tls: TLSSettings | None) -> dict[str, Any]:
        tls = tls or self.public_tls or TLSSettings()
        config: dict[str, Any] = {
            "enabled": True,
            "certificate_path": tls.certificate_path,
            "key_path": tls.key_path,
        }
        if tls.server_client_authentication:
            config["client_authentication"] = tls.server_client_authentication
        if tls.server_client_certificate_path:
            config["client_certificate_path"] = tls.server_client_certificate_path
        return config

    def _client_tls(self, server_name: str, tls: TLSSettings | None) -> dict[str, Any]:
        tls = tls or self.public_tls or TLSSettings()
        config: dict[str, Any] = {
            "enabled": True,
            "server_name": server_name,
        }
        if tls.client_insecure:
            config["insecure"] = True
        if tls.ca_certificate_path:
            config["certificate_path"] = tls.ca_certificate_path
        if tls.client_certificate_path:
            config["client_certificate_path"] = tls.client_certificate_path
        if tls.client_key_path:
            config["client_key_path"] = tls.client_key_path
        return config

    @staticmethod
    def _require(value: str | None, auth_name: str, field_name: str) -> str:
        if not value:
            raise ValueError(f"User {auth_name} is missing {field_name}")
        return value


def stable_json(config: dict[str, Any]) -> str:
    return json.dumps(config, sort_keys=True, separators=(",", ":"))


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(stable_json(config).encode()).hexdigest()
