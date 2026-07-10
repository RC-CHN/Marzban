from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import quote, urlencode

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


def build_v2rayn_subscription(
    builder: SingBoxConfigBuilder,
    entry_node: str,
    user: SingBoxUser,
    protocols: tuple[Protocol, ...],
) -> str:
    """Build a v2rayN-compatible base64 subscription.

    v2rayN's subscription importer accepts either plain newline-delimited share
    URIs or the same content wrapped in base64. We use base64 to match the common
    subscription convention while keeping each enabled protocol as a separate
    imported node.
    """

    links = []
    for protocol in protocols:
        outbound = builder.build_client_config(protocol, entry_node, user)["outbounds"][0]
        links.append(_v2rayn_uri_from_outbound(entry_node, outbound))
    return _base64("\n".join(links))


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


def _v2rayn_uri_from_outbound(entry_node: str, outbound: dict[str, Any]) -> str:
    protocol = outbound["type"]
    name = f"{entry_node}-{protocol}"
    server = _host_for_uri(outbound["server"])
    port = outbound["server_port"]

    if protocol == "vmess":
        doc = {
            "v": 2,
            "ps": name,
            "add": outbound["server"],
            "port": port,
            "id": outbound["uuid"],
            "aid": outbound.get("alter_id", 0),
            "scy": outbound.get("security", "auto"),
            "net": "tcp",
            "type": "none",
            "host": "",
            "path": "",
            "tls": "",
            "sni": "",
            "alpn": "",
            "fp": "",
            "insecure": "0",
        }
        return f"vmess://{_base64(json.dumps(doc, separators=(',', ':'), ensure_ascii=False))}"

    if protocol == "vless":
        query = {"encryption": "none", "security": "none", "type": "tcp", "headerType": "none"}
        return _share_uri("vless", server, port, outbound["uuid"], query, name)

    if protocol == "trojan":
        query = {"type": "tcp", "headerType": "none", **_tls_query(outbound)}
        return _share_uri("trojan", server, port, outbound["password"], query, name)

    if protocol == "shadowsocks":
        userinfo = _urlsafe_base64_no_pad(f"{outbound['method']}:{outbound['password']}")
        return _share_uri("ss", server, port, userinfo, {}, name, encode_userinfo=False)

    if protocol == "hysteria2":
        return _share_uri("hysteria2", server, port, outbound["password"], _tls_query(outbound), name)

    if protocol == "tuic":
        query = {
            **_tls_query(outbound),
            "congestion_control": outbound.get("congestion_control", "bbr"),
        }
        return _share_uri(
            "tuic",
            server,
            port,
            f"{outbound['uuid']}:{outbound['password']}",
            query,
            name,
        )

    if protocol == "anytls":
        query = {"type": "tcp", "headerType": "none", **_tls_query(outbound)}
        return _share_uri("anytls", server, port, outbound["password"], query, name)

    raise ValueError(f"Unsupported protocol for v2rayN subscription: {protocol}")


def _tls_query(outbound: dict[str, Any]) -> dict[str, str]:
    tls = outbound.get("tls") or {}
    if not tls.get("enabled"):
        return {"security": "none"}

    query = {"security": "tls"}
    if tls.get("server_name"):
        query["sni"] = str(tls["server_name"])
    if tls.get("insecure"):
        query["insecure"] = "1"
        query["allowInsecure"] = "1"
    else:
        query["insecure"] = "0"
        query["allowInsecure"] = "0"
    return query


def _share_uri(
    scheme: str,
    server: str,
    port: int,
    userinfo: str,
    query: dict[str, str],
    name: str,
    *,
    encode_userinfo: bool = True,
) -> str:
    encoded_userinfo = quote(userinfo, safe="") if encode_userinfo else userinfo
    query_string = f"?{urlencode(query)}" if query else ""
    return f"{scheme}://{encoded_userinfo}@{server}:{port}{query_string}#{quote(name, safe='')}"


def _host_for_uri(host: str) -> str:
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        return f"[{host}]"
    return host


def _base64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def _urlsafe_base64_no_pad(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


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
