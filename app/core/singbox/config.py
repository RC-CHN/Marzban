from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
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
PublicTLSMode = Literal["system-ca", "ip-ca", "ip-insecure"]
NodeLinkProtocol = Literal["hysteria2", "anytls"]

SUPPORTED_PROTOCOLS: tuple[Protocol, ...] = (
    "hysteria2",
    "tuic",
    "anytls",
    "vmess",
    "vless",
    "trojan",
    "shadowsocks",
)
SUPPORTED_NODE_LINK_PROTOCOLS: tuple[NodeLinkProtocol, ...] = ("hysteria2", "anytls")


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
    protocol_settings: dict[str, Any] | None = None
    public_tls_mode: PublicTLSMode = "ip-insecure"
    public_tls_cert_path: str | None = None
    public_tls_key_path: str | None = None
    public_tls_ca_cert_path: str | None = None


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
    entry_node: str | None = None
    ingress_service_id: int | None = None

    def supports(self, protocol: Protocol) -> bool:
        return protocol in self.protocols


@dataclass(frozen=True)
class NodeLink:
    from_node: str
    to_node: str
    auth_name: str
    password: str
    protocol: NodeLinkProtocol = "hysteria2"
    enabled: bool = True


@dataclass(frozen=True)
class PublicIngress:
    id: int
    node_name: str
    address: str
    protocol: Protocol
    listen_port: int
    enabled: bool = True
    tls_mode: PublicTLSMode = "system-ca"
    tls_profile: dict[str, Any] | None = None
    protocol_profile: dict[str, Any] | None = None


@dataclass(frozen=True)
class RoutePolicy:
    entry_node: str
    auth_name: str
    exit_node: str | None
    protocol: Protocol | None = None


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
    node_link_protocol: NodeLinkProtocol = "hysteria2"
    log_level: str = "info"
    node_links: list[NodeLink] | None = None
    public_ingresses: list[PublicIngress] | None = None

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
                        protocol=self.node_link_protocol,
                    )
                )
        return links

    def build_node_config(
        self,
        node_name: str,
        overlay_intent: Any | None = None,
        *,
        preserve_legacy: bool = False,
        include_overlay_public_rules: bool = True,
    ) -> dict[str, Any]:
        node = self._node(node_name)
        public_tags = [f"public-{protocol}" for protocol in SUPPORTED_PROTOCOLS]
        return {
            "log": {
                "level": self.log_level,
                "timestamp": True,
            },
            "inbounds": [
                *(self._public_inbounds(node) if node.entry_enabled else []),
                *(
                    (
                        (self._node_link_inbounds(node_name) if preserve_legacy else [])
                        + self._overlay_link_inbounds(overlay_intent)
                    )
                    if overlay_intent is not None
                    else self._node_link_inbounds(node_name)
                ),
            ],
            "outbounds": [
                {"type": "direct", "tag": "direct"},
                {"type": "block", "tag": "block"},
                *(
                    (
                        (self._node_link_outbounds(node_name) if preserve_legacy else [])
                        + self._overlay_link_outbounds(overlay_intent)
                    )
                    if overlay_intent is not None
                    else self._node_link_outbounds(node_name)
                ),
            ],
            "route": {
                "rules": (
                    (
                        (self._route_rules(node_name, public_tags) if preserve_legacy else [])
                        + self._overlay_route_rules(
                            overlay_intent,
                            include_public=include_overlay_public_rules,
                        )
                    )
                    if overlay_intent is not None
                    else self._route_rules(node_name, public_tags)
                ),
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
        if self.public_ingresses is not None:
            builders = {
                "hysteria2": self._hysteria2_inbound,
                "tuic": self._tuic_inbound,
                "anytls": self._anytls_inbound,
                "vmess": self._vmess_inbound,
                "vless": self._vless_inbound,
                "trojan": self._trojan_inbound,
                "shadowsocks": self._shadowsocks_inbound,
            }
            inbounds = []
            for ingress in self.public_ingresses:
                if not ingress.enabled or ingress.node_name != node.name:
                    continue
                inbound = builders[ingress.protocol](self._node_for_ingress(node, ingress))
                inbound["tag"] = f"public-ingress-{ingress.id}"
                inbound["listen_port"] = ingress.listen_port
                allowed_users = {
                    user.auth_name
                    for user in self.users
                    if user.ingress_service_id == ingress.id and user.supports(ingress.protocol)
                }
                inbound["users"] = [
                    user for user in inbound.get("users", []) if user.get("name") in allowed_users
                ]
                inbounds.append(inbound)
            return inbounds
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
        settings = self._protocol_settings(node, "hysteria2")
        inbound: dict[str, Any] = {
            "type": "hysteria2",
            "tag": "public-hysteria2",
            "listen": "::",
            "listen_port": self._port(node, "hysteria2"),
            "users": [
                {"name": user.auth_name, "password": user.credentials.password}
                for user in self._users_for("hysteria2", node.name)
            ],
            "ignore_client_bandwidth": settings.get("ignore_client_bandwidth", True),
            "tls": self._public_server_tls(node),
        }
        for field_name in ("up_mbps", "down_mbps"):
            if settings.get(field_name) is not None:
                inbound[field_name] = settings[field_name]
        if settings.get("obfs_type") == "salamander":
            inbound["obfs"] = {"type": "salamander", "password": settings["obfs_password"]}
        if settings.get("masquerade_url"):
            inbound["masquerade"] = settings["masquerade_url"]
        return inbound

    def _tuic_inbound(self, node: SingBoxNode) -> dict[str, Any]:
        settings = self._protocol_settings(node, "tuic")
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
                for user in self._users_for("tuic", node.name)
            ],
            "congestion_control": settings.get("congestion_control", "bbr"),
            "auth_timeout": settings.get("auth_timeout", "3s"),
            "zero_rtt_handshake": settings.get("zero_rtt_handshake", False),
            "heartbeat": settings.get("heartbeat", "10s"),
            "tls": self._public_server_tls(node),
        }

    def _anytls_inbound(self, node: SingBoxNode) -> dict[str, Any]:
        settings = self._protocol_settings(node, "anytls")
        inbound: dict[str, Any] = {
            "type": "anytls",
            "tag": "public-anytls",
            "listen": "::",
            "listen_port": self._port(node, "anytls"),
            "users": [
                {"name": user.auth_name, "password": user.credentials.password}
                for user in self._users_for("anytls", node.name)
            ],
            "tls": self._public_server_tls(node),
        }
        if settings.get("padding_scheme") is not None:
            inbound["padding_scheme"] = settings["padding_scheme"]
        return inbound

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
                for user in self._users_for("vmess", node.name)
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
                for user in self._users_for("vless", node.name)
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
                for user in self._users_for("trojan", node.name)
            ],
            "tls": self._public_server_tls(node),
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
                for user in self._users_for("shadowsocks", node.name)
            ],
        }

    def _node_link_inbounds(self, node_name: str) -> list[dict[str, Any]]:
        protocols = {
            link.protocol
            for link in self.node_links or []
            if link.enabled and link.to_node == node_name and link.from_node != node_name
        }
        if not protocols:
            protocols = {self.node_link_protocol}
        return [
            self._node_link_inbound(node_name, protocol)
            for protocol in SUPPORTED_NODE_LINK_PROTOCOLS
            if protocol in protocols
        ]

    def _node_link_inbound(self, node_name: str, protocol: NodeLinkProtocol) -> dict[str, Any]:
        node = self._node(node_name)
        links = [
            link
            for link in self.node_links or []
            if (
                link.enabled
                and link.protocol == protocol
                and link.to_node == node_name
                and link.from_node != node_name
            )
        ]
        inbound: dict[str, Any] = {
            "type": protocol,
            "tag": f"node-link-{protocol}",
            "listen": "::",
            "listen_port": node.node_link_port,
            "users": [
                {"name": link.auth_name, "password": link.password}
                for link in links
            ],
            "tls": self._server_tls(self.node_link_tls),
        }
        if protocol == "hysteria2":
            inbound["ignore_client_bandwidth"] = True
        return inbound

    def _overlay_link_inbounds(self, intent: Any) -> list[dict[str, Any]]:
        inbounds = []
        for link in intent.link_inbounds:
            inbound: dict[str, Any] = {
                "type": link.transport,
                "tag": f"overlay-in-{link.direction_id}",
                "listen": "::",
                "listen_port": link.listen_port,
                "users": [
                    {"name": user.auth_name, "password": user.password}
                    for user in link.users
                ],
                "tls": self._server_tls(self.node_link_tls),
            }
            if link.transport == "hysteria2":
                inbound["ignore_client_bandwidth"] = link.settings.get(
                    "ignore_client_bandwidth", True
                )
                for field_name in ("up_mbps", "down_mbps"):
                    if link.settings.get(field_name) is not None:
                        inbound[field_name] = link.settings[field_name]
                if link.settings.get("obfs_type") == "salamander":
                    inbound["obfs"] = {
                        "type": "salamander",
                        "password": link.settings["obfs_password"],
                    }
            elif link.settings.get("padding_scheme") is not None:
                inbound["padding_scheme"] = link.settings["padding_scheme"]
            inbounds.append(inbound)
        return inbounds

    def _node_link_outbounds(self, node_name: str) -> list[dict[str, Any]]:
        outbounds = []
        for link in self.node_links or []:
            if not link.enabled or link.from_node != node_name or link.to_node == node_name:
                continue
            target = self._node(link.to_node)
            if not target.exit_enabled:
                continue
            outbounds.append(self._node_link_outbound(link, target))
        return outbounds

    def _overlay_link_outbounds(self, intent: Any) -> list[dict[str, Any]]:
        outbounds = []
        for link in intent.link_outbounds:
            if link.transport not in SUPPORTED_NODE_LINK_PROTOCOLS:
                raise ValueError(f"Unsupported overlay transport: {link.transport}")
            outbound = {
                    "type": link.transport,
                    "tag": link.tag,
                    "server": link.target_host,
                    "server_port": link.target_port,
                    "password": link.password,
                    "tls": self._client_tls(link.target_host, self.node_link_tls),
                }
            if link.transport == "hysteria2":
                for field_name in ("up_mbps", "down_mbps"):
                    if link.settings.get(field_name) is not None:
                        outbound[field_name] = link.settings[field_name]
                if link.settings.get("obfs_type") == "salamander":
                    outbound["obfs"] = {
                        "type": "salamander",
                        "password": link.settings["obfs_password"],
                    }
            else:
                outbound.update(
                    {
                        "idle_session_check_interval": link.settings.get(
                            "idle_session_check_interval", "30s"
                        ),
                        "idle_session_timeout": link.settings.get(
                            "idle_session_timeout", "30s"
                        ),
                        "min_idle_session": link.settings.get("min_idle_session", 0),
                    }
                )
            outbounds.append(outbound)
        return outbounds

    def _node_link_outbound(self, link: NodeLink, target: SingBoxNode) -> dict[str, Any]:
        if link.protocol not in SUPPORTED_NODE_LINK_PROTOCOLS:
            raise ValueError(f"Unsupported node-link protocol: {link.protocol}")
        return {
            "type": link.protocol,
            "tag": f"exit-{link.to_node}",
            "server": target.public_host,
            "server_port": target.node_link_port,
            "password": link.password,
            "tls": self._client_tls(target.public_host, self.node_link_tls),
        }

    def _route_rules(self, node_name: str, public_tags: list[str]) -> list[dict[str, Any]]:
        rules = []
        for policy in self.route_policies:
            if policy.entry_node != node_name:
                continue
            if not policy.exit_node or policy.exit_node == node_name:
                continue
            inbound_tags = [f"public-{policy.protocol}"] if policy.protocol else public_tags
            rules.append(
                {
                    "inbound": inbound_tags,
                    "auth_user": [policy.auth_name],
                    "action": "route",
                    "outbound": f"exit-{policy.exit_node}",
                }
            )
        return rules

    def _overlay_route_rules(self, intent: Any, *, include_public: bool = True) -> list[dict[str, Any]]:
        return [
            {
                "inbound": [rule.inbound_tag],
                "auth_user": [rule.auth_name],
                "action": "route",
                "outbound": rule.outbound_tag,
            }
            for rule in intent.route_rules
            if include_public or rule.inbound_tag.startswith("overlay-in-")
        ]

    def _client_outbound(
        self,
        protocol: Protocol,
        entry_node_name: str,
        user: SingBoxUser,
    ) -> dict[str, Any]:
        entry_node = self._node(entry_node_name)
        if user.ingress_service_id is not None and self.public_ingresses is not None:
            ingress = next(
                (
                    item
                    for item in self.public_ingresses
                    if item.id == user.ingress_service_id and item.enabled
                ),
                None,
            )
            if ingress is None:
                raise ValueError(f"Ingress service {user.ingress_service_id} is unavailable")
            if ingress.node_name != entry_node_name or ingress.protocol != protocol:
                raise ValueError("Ingress service does not match the client target")
            entry_node = self._node_for_ingress(entry_node, ingress)
        credentials = user.credentials
        if protocol == "hysteria2":
            settings = self._protocol_settings(entry_node, "hysteria2")
            outbound: dict[str, Any] = {
                "type": "hysteria2",
                "tag": "proxy",
                "server": entry_node.public_host,
                "server_port": self._port(entry_node, "hysteria2"),
                "password": credentials.password,
                "tls": self._public_client_tls(entry_node),
            }
            if settings.get("obfs_type") == "salamander":
                outbound["obfs"] = {"type": "salamander", "password": settings["obfs_password"]}
            return outbound
        if protocol == "tuic":
            settings = self._protocol_settings(entry_node, "tuic")
            return {
                "type": "tuic",
                "tag": "proxy",
                "server": entry_node.public_host,
                "server_port": self._port(entry_node, "tuic"),
                "uuid": self._require(credentials.tuic_uuid, user.auth_name, "tuic_uuid"),
                "password": credentials.password,
                "congestion_control": settings.get("congestion_control", "bbr"),
                "zero_rtt_handshake": settings.get("zero_rtt_handshake", False),
                "heartbeat": settings.get("heartbeat", "10s"),
                "tls": self._public_client_tls(entry_node),
            }
        if protocol == "anytls":
            settings = self._protocol_settings(entry_node, "anytls")
            return {
                "type": "anytls",
                "tag": "proxy",
                "server": entry_node.public_host,
                "server_port": self._port(entry_node, "anytls"),
                "password": credentials.password,
                "idle_session_check_interval": settings.get("idle_session_check_interval", "30s"),
                "idle_session_timeout": settings.get("idle_session_timeout", "30s"),
                "min_idle_session": settings.get("min_idle_session", 0),
                "tls": self._public_client_tls(entry_node),
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
                "tls": self._public_client_tls(entry_node),
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

    def _users_for(self, protocol: Protocol, node_name: str) -> Iterable[SingBoxUser]:
        return (
            user
            for user in self.users
            if user.supports(protocol) and (user.entry_node is None or user.entry_node == node_name)
        )

    def _node(self, node_name: str) -> SingBoxNode:
        try:
            return self.nodes[node_name]
        except KeyError as exc:
            raise ValueError(f"Unknown node: {node_name}") from exc

    def _port(self, node: SingBoxNode, protocol: Protocol) -> int:
        ports = node.public_ports or self.ports
        return ports.get(protocol)

    def _node_for_ingress(self, node: SingBoxNode, ingress: PublicIngress) -> SingBoxNode:
        current_ports = node.public_ports or self.ports
        ports = ProtocolPorts(
            **{
                protocol: ingress.listen_port
                if protocol == ingress.protocol
                else current_ports.get(protocol)
                for protocol in SUPPORTED_PROTOCOLS
            }
        )
        tls_profile = ingress.tls_profile or {}
        return replace(
            node,
            public_host=ingress.address,
            public_ports=ports,
            protocol_settings={ingress.protocol: ingress.protocol_profile or {}},
            public_tls_mode=ingress.tls_mode,
            public_tls_cert_path=tls_profile.get("cert_path") or node.public_tls_cert_path,
            public_tls_key_path=tls_profile.get("key_path") or node.public_tls_key_path,
            public_tls_ca_cert_path=tls_profile.get("ca_cert_path") or node.public_tls_ca_cert_path,
        )

    @staticmethod
    def _protocol_settings(node: SingBoxNode, protocol: Protocol) -> dict[str, Any]:
        return dict((node.protocol_settings or {}).get(protocol) or {})

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

    def _public_server_tls(self, node: SingBoxNode) -> dict[str, Any]:
        return self._server_tls(self._public_tls_for_node(node))

    def _public_client_tls(self, node: SingBoxNode) -> dict[str, Any]:
        return self._client_tls(node.public_host, self._public_tls_for_node(node))

    def _public_tls_for_node(self, node: SingBoxNode) -> TLSSettings:
        fallback = self.public_tls or TLSSettings()
        return TLSSettings(
            certificate_path=node.public_tls_cert_path or fallback.certificate_path,
            key_path=node.public_tls_key_path or fallback.key_path,
            client_insecure=node.public_tls_mode == "ip-insecure",
            ca_certificate_path=node.public_tls_ca_cert_path if node.public_tls_mode == "ip-ca" else None,
        )

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
