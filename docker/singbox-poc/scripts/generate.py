#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import importlib.util
import types
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
GENERATED = LAB_ROOT / "generated"
CERT_DIR = GENERATED / "certs"
NODE_LINK_CERT_DIR = GENERATED / "node-link"
CLIENT_DIR = GENERATED / "clients"

def load_builder_module():
    module_path = PROJECT_ROOT / "app" / "core" / "singbox" / "config.py"
    spec = importlib.util.spec_from_file_location("app.core.singbox.config", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder_module = load_builder_module()
sys.modules.setdefault("app", types.ModuleType("app"))
sys.modules.setdefault("app.core", types.ModuleType("app.core"))
sys.modules.setdefault("app.core.singbox", types.ModuleType("app.core.singbox"))
sys.modules["app.core.singbox.config"] = builder_module


def load_subscription_module():
    module_path = PROJECT_ROOT / "app" / "core" / "singbox" / "subscription.py"
    spec = importlib.util.spec_from_file_location("app.core.singbox.subscription", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


subscription_module = load_subscription_module()
RoutePolicy = builder_module.RoutePolicy
ShadowsocksSettings = builder_module.ShadowsocksSettings
SingBoxConfigBuilder = builder_module.SingBoxConfigBuilder
SingBoxNode = builder_module.SingBoxNode
SingBoxUser = builder_module.SingBoxUser
SingBoxUserCredentials = builder_module.SingBoxUserCredentials
TLSSettings = builder_module.TLSSettings
config_hash = builder_module.config_hash
SUPPORTED_PROTOCOLS = builder_module.SUPPORTED_PROTOCOLS
build_clash_subscription = subscription_module.build_clash_subscription
build_singbox_subscription = subscription_module.build_singbox_subscription


REMOTE_USER = SingBoxUser(
    auth_name="u1",
    credentials=SingBoxUserCredentials(
        password="u1-password-for-singbox-poc",
        vmess_uuid="11111111-1111-4111-8111-111111111111",
        vless_uuid="22222222-2222-4222-8222-222222222222",
        tuic_uuid="33333333-3333-4333-8333-333333333333",
        shadowsocks_password="YWJjZGVmMDEyMzQ1Njc4OQ==",
    ),
)

DIRECT_USER = SingBoxUser(
    auth_name="u2",
    credentials=SingBoxUserCredentials(password="u2-direct-password-for-singbox-poc"),
    protocols=("hysteria2",),
)

NODES = {
    "node-a": SingBoxNode(name="node-a", public_host="node-a"),
    "node-b": SingBoxNode(name="node-b", public_host="node-b"),
    "node-c": SingBoxNode(name="node-c", public_host="node-c"),
}

NODE_IPS = {
    "node-a": "172.29.10.11",
    "node-b": "172.29.10.12",
    "node-c": "172.29.10.13",
}

TEST_CASES = {
    "hysteria2": {"protocol": "hysteria2", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "tuic": {"protocol": "tuic", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "anytls": {"protocol": "anytls", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "vmess": {"protocol": "vmess", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "vless": {"protocol": "vless", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "trojan": {"protocol": "trojan", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "shadowsocks": {
        "protocol": "shadowsocks",
        "entry": "node-a",
        "expected_exit": "node-b",
        "user": REMOTE_USER,
    },
    "hysteria2-direct": {
        "protocol": "hysteria2",
        "entry": "node-a",
        "expected_exit": "node-a",
        "user": DIRECT_USER,
    },
    "hysteria2-node-b": {
        "protocol": "hysteria2",
        "entry": "node-b",
        "expected_exit": "node-c",
        "user": REMOTE_USER,
    },
    "hysteria2-node-c": {
        "protocol": "hysteria2",
        "entry": "node-c",
        "expected_exit": "node-a",
        "user": REMOTE_USER,
    },
}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def ensure_cert() -> None:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    crt = CERT_DIR / "poc.crt"
    key = CERT_DIR / "poc.key"
    if crt.exists() and key.exists():
        return

    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(crt),
            "-days",
            "7",
            "-nodes",
            "-subj",
            "/CN=singbox-poc",
            "-addext",
            "subjectAltName=DNS:node-a,DNS:node-b,DNS:node-c,DNS:singbox-poc",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure_node_link_ca() -> None:
    NODE_LINK_CERT_DIR.mkdir(parents=True, exist_ok=True)
    ca_crt = NODE_LINK_CERT_DIR / "ca.crt"
    ca_key = NODE_LINK_CERT_DIR / "ca.key"
    node_crt = NODE_LINK_CERT_DIR / "node.crt"
    node_key = NODE_LINK_CERT_DIR / "node.key"
    client_crt = NODE_LINK_CERT_DIR / "client.crt"
    client_key = NODE_LINK_CERT_DIR / "client.key"
    if ca_crt.exists() and node_crt.exists() and node_key.exists() and client_crt.exists() and client_key.exists():
        return

    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_crt),
            "-days",
            "7",
            "-nodes",
            "-subj",
            "/CN=Marzban POC Node Link CA",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _sign_cert(
        ca_crt,
        ca_key,
        "node",
        node_crt,
        node_key,
        "subjectAltName=DNS:node-a,DNS:node-b,DNS:node-c,DNS:node-link\nextendedKeyUsage=serverAuth\n",
    )
    _sign_cert(
        ca_crt,
        ca_key,
        "node-link-client",
        client_crt,
        client_key,
        "extendedKeyUsage=clientAuth\n",
    )


def _sign_cert(
    ca_crt: Path,
    ca_key: Path,
    common_name: str,
    cert_path: Path,
    key_path: Path,
    ext_text: str,
) -> None:
    csr_path = cert_path.with_suffix(".csr")
    ext_path = cert_path.with_suffix(".ext")
    subprocess.run(
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(csr_path),
            "-nodes",
            "-subj",
            f"/CN={common_name}",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ext_path.write_text(ext_text)
    subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr_path),
            "-CA",
            str(ca_crt),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(cert_path),
            "-days",
            "7",
            "-sha256",
            "-extfile",
            str(ext_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def node_link_tls() -> TLSSettings:
    return TLSSettings(
        certificate_path="/etc/sing-box/node-link/node.crt",
        key_path="/etc/sing-box/node-link/node.key",
        client_insecure=False,
        ca_certificate_path="/etc/sing-box/node-link/ca.crt",
        client_certificate_path="/etc/sing-box/node-link/client.crt",
        client_key_path="/etc/sing-box/node-link/client.key",
        server_client_authentication="require-and-verify",
        server_client_certificate_path=["/etc/sing-box/node-link/ca.crt"],
    )


def build_builder() -> SingBoxConfigBuilder:
    return build_builder_with_node_a_exit("node-b")


def build_builder_with_node_a_exit(exit_node: str) -> SingBoxConfigBuilder:
    return SingBoxConfigBuilder(
        nodes=NODES,
        users=[REMOTE_USER, DIRECT_USER],
        route_policies=[
            RoutePolicy(entry_node="node-a", auth_name=REMOTE_USER.auth_name, exit_node=exit_node),
            RoutePolicy(entry_node="node-b", auth_name=REMOTE_USER.auth_name, exit_node="node-c"),
            RoutePolicy(entry_node="node-c", auth_name=REMOTE_USER.auth_name, exit_node="node-a"),
            RoutePolicy(entry_node="node-a", auth_name=DIRECT_USER.auth_name, exit_node=None),
        ],
        shadowsocks=ShadowsocksSettings(
            method="2022-blake3-aes-128-gcm",
            server_password="MDEyMzQ1Njc4OWFiY2RlZg==",
        ),
        node_link_tls=node_link_tls(),
    )


def write_manifest(config_hashes: dict[str, str]) -> None:
    manifest = {
        "nodes": NODE_IPS,
        "config_hashes": config_hashes,
        "cases": {
            case_name: {
                "entry": case["entry"],
                "protocol": case["protocol"],
                "expected_exit": case["expected_exit"],
                "expected_ip": NODE_IPS[case["expected_exit"]],
                "auth_user": case["user"].auth_name,
            }
            for case_name, case in TEST_CASES.items()
        },
    }
    write_json(GENERATED / "manifest.json", manifest)
    write_json(GENERATED / "expected-results.json", manifest["cases"])


def write_subscriptions(builder: SingBoxConfigBuilder, config_hashes: dict[str, str]) -> None:
    subscriptions = GENERATED / "subscriptions"
    singbox = build_singbox_subscription(builder, "node-a", REMOTE_USER, SUPPORTED_PROTOCOLS)
    clash = build_clash_subscription(builder, "node-a", REMOTE_USER, SUPPORTED_PROTOCOLS)
    write_json(subscriptions / "sing-box.json", singbox)
    (subscriptions / "clash.yaml").write_text(clash + "\n")
    config_hashes["subscription:sing-box"] = config_hash(singbox)
    config_hashes["subscription:clash"] = builder_module.hashlib.sha256(clash.encode()).hexdigest()


def write_ten_node_configs(config_hashes: dict[str, str]) -> None:
    nodes = {
        f"node-{index:02d}": SingBoxNode(name=f"node-{index:02d}", public_host=f"node-{index:02d}")
        for index in range(1, 11)
    }
    builder = SingBoxConfigBuilder(
        nodes=nodes,
        users=[REMOTE_USER, DIRECT_USER],
        route_policies=[
            RoutePolicy(entry_node=node_name, auth_name=REMOTE_USER.auth_name, exit_node="node-10")
            for node_name in nodes
            if node_name != "node-10"
        ],
        shadowsocks=ShadowsocksSettings(
            method="2022-blake3-aes-128-gcm",
            server_password="MDEyMzQ1Njc4OWFiY2RlZg==",
        ),
        node_link_tls=node_link_tls(),
    )
    for node_name in nodes:
        config = builder.build_node_config(node_name)
        config_hashes[f"ten-node:{node_name}"] = config_hash(config)
        write_json(GENERATED / "ten-node" / node_name / "config.json", config)


def main() -> None:
    os.chdir(LAB_ROOT)
    ensure_cert()
    ensure_node_link_ca()
    CLIENT_DIR.mkdir(parents=True, exist_ok=True)

    builder = build_builder()
    config_hashes = {}

    for node_name in NODES:
        config = builder.build_node_config(node_name)
        config_hashes[node_name] = config_hash(config)
        write_json(GENERATED / node_name / "config.json", config)

    node_a_exit_node_c_config = build_builder_with_node_a_exit("node-c").build_node_config("node-a")
    config_hashes["node-a:exit-node-c"] = config_hash(node_a_exit_node_c_config)
    write_json(GENERATED / "node-a" / "config-exit-node-c.json", node_a_exit_node_c_config)

    for case_name, case in TEST_CASES.items():
        config = builder.build_client_config(
            case["protocol"],
            case["entry"],
            case["user"],
        )
        config_hashes[f"client:{case_name}"] = config_hash(config)
        write_json(CLIENT_DIR / f"{case_name}.json", config)

    write_subscriptions(builder, config_hashes)
    write_ten_node_configs(config_hashes)
    write_manifest(config_hashes)
    print(f"Generated sing-box POC files under {GENERATED.relative_to(LAB_ROOT)}")


if __name__ == "__main__":
    main()
