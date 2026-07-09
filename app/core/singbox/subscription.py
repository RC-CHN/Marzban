from __future__ import annotations

import json
from typing import Any

from app.core.singbox.config import Protocol, SingBoxConfigBuilder, SingBoxUser


def build_singbox_subscription(
    builder: SingBoxConfigBuilder,
    entry_node: str,
    user: SingBoxUser,
    protocols: tuple[Protocol, ...],
) -> dict[str, Any]:
    """Build a sing-box client subscription with one outbound per entry protocol."""

    outbounds = []
    for protocol in protocols:
        outbound = builder.build_client_config(protocol, entry_node, user)["outbounds"][0]
        outbounds.append({**outbound, "tag": f"{entry_node}-{protocol}"})
    selector_tag = "select"
    return {
        "log": {"level": "info", "timestamp": True},
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 2080,
            }
        ],
        "outbounds": [
            {
                "type": "selector",
                "tag": selector_tag,
                "outbounds": [outbound["tag"] for outbound in outbounds],
            },
            *outbounds,
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {"final": selector_tag},
    }


def build_clash_subscription(
    builder: SingBoxConfigBuilder,
    entry_node: str,
    user: SingBoxUser,
    protocols: tuple[Protocol, ...],
) -> str:
    """Build a minimal Clash/Mihomo YAML subscription for POC protocols.

    This deliberately covers the same fields validated by the Docker POC. It is
    not intended to be a full production renderer.
    """

    proxies = []
    for protocol in protocols:
        outbound = builder.build_client_config(protocol, entry_node, user)["outbounds"][0]
        proxies.append(_clash_proxy_from_outbound(entry_node, outbound))

    proxy_names = [proxy["name"] for proxy in proxies]
    doc = {
        "mixed-port": 2080,
        "allow-lan": False,
        "mode": "rule",
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "select",
                "type": "select",
                "proxies": proxy_names,
            }
        ],
        "rules": ["MATCH,select"],
    }
    return _dump_simple_yaml(doc)


def _clash_proxy_from_outbound(entry_node: str, outbound: dict[str, Any]) -> dict[str, Any]:
    protocol = outbound["type"]
    name = f"{entry_node}-{protocol}"
    base = {
        "name": name,
        "type": protocol,
        "server": outbound["server"],
        "port": outbound["server_port"],
    }
    if protocol == "hysteria2":
        return {
            **base,
            "password": outbound["password"],
            "sni": outbound.get("tls", {}).get("server_name"),
            "skip-cert-verify": outbound.get("tls", {}).get("insecure", False),
        }
    if protocol == "tuic":
        return {
            **base,
            "uuid": outbound["uuid"],
            "password": outbound["password"],
            "sni": outbound.get("tls", {}).get("server_name"),
            "skip-cert-verify": outbound.get("tls", {}).get("insecure", False),
            "congestion-controller": outbound.get("congestion_control", "bbr"),
        }
    if protocol == "anytls":
        return {
            **base,
            "password": outbound["password"],
            "sni": outbound.get("tls", {}).get("server_name"),
            "skip-cert-verify": outbound.get("tls", {}).get("insecure", False),
        }
    if protocol == "vmess":
        return {
            **base,
            "uuid": outbound["uuid"],
            "alterId": outbound.get("alter_id", 0),
            "cipher": outbound.get("security", "auto"),
            "network": "tcp",
        }
    if protocol == "vless":
        return {
            **base,
            "uuid": outbound["uuid"],
            "network": "tcp",
        }
    if protocol == "trojan":
        return {
            **base,
            "password": outbound["password"],
            "sni": outbound.get("tls", {}).get("server_name"),
            "skip-cert-verify": outbound.get("tls", {}).get("insecure", False),
            "network": "tcp",
        }
    if protocol == "shadowsocks":
        return {
            **base,
            "cipher": outbound["method"],
            "password": outbound["password"],
        }
    raise ValueError(f"Unsupported protocol for Clash subscription: {protocol}")


def _dump_simple_yaml(value: Any, indent: int = 0) -> str:
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            prefix = " " * indent + f"{key}:"
            if isinstance(item, (dict, list)):
                lines.append(prefix)
                lines.append(_dump_simple_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix} {_yaml_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(" " * indent + "-")
                lines.append(_dump_simple_yaml(item, indent + 2))
            else:
                lines.append(" " * indent + f"- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return " " * indent + _yaml_scalar(value)


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)
