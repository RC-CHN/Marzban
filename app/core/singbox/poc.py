from __future__ import annotations

from app.core.singbox.config import (
    RoutePolicy,
    ShadowsocksSettings,
    SingBoxConfigBuilder,
    SingBoxNode,
    SingBoxUser,
    SingBoxUserCredentials,
    config_hash,
)
from app.core.singbox.subscription import build_clash_subscription, build_singbox_subscription


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

TEST_CASES = {
    "hysteria2": {"protocol": "hysteria2", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "tuic": {"protocol": "tuic", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "anytls": {"protocol": "anytls", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "vmess": {"protocol": "vmess", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "vless": {"protocol": "vless", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "trojan": {"protocol": "trojan", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
    "shadowsocks": {"protocol": "shadowsocks", "entry": "node-a", "expected_exit": "node-b", "user": REMOTE_USER},
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


def build_poc_builder() -> SingBoxConfigBuilder:
    return SingBoxConfigBuilder(
        nodes=NODES,
        users=[REMOTE_USER, DIRECT_USER],
        route_policies=[
            RoutePolicy(entry_node="node-a", auth_name=REMOTE_USER.auth_name, exit_node="node-b"),
            RoutePolicy(entry_node="node-b", auth_name=REMOTE_USER.auth_name, exit_node="node-c"),
            RoutePolicy(entry_node="node-c", auth_name=REMOTE_USER.auth_name, exit_node="node-a"),
            RoutePolicy(entry_node="node-a", auth_name=DIRECT_USER.auth_name, exit_node=None),
        ],
        shadowsocks=ShadowsocksSettings(
            method="2022-blake3-aes-128-gcm",
            server_password="MDEyMzQ1Njc4OWFiY2RlZg==",
        ),
    )


def build_poc_manifest() -> dict:
    builder = build_poc_builder()
    node_hashes = {
        node_name: config_hash(builder.build_node_config(node_name))
        for node_name in NODES
    }
    case_hashes = {}
    cases = {}
    for case_name, case in TEST_CASES.items():
        config = builder.build_client_config(case["protocol"], case["entry"], case["user"])
        case_hashes[case_name] = config_hash(config)
        cases[case_name] = {
            "protocol": case["protocol"],
            "entry": case["entry"],
            "expected_exit": case["expected_exit"],
            "auth_user": case["user"].auth_name,
        }
    return {
        "nodes": list(NODES),
        "node_hashes": node_hashes,
        "client_hashes": case_hashes,
        "cases": cases,
    }


def build_poc_singbox_subscription(entry_node: str = "node-a") -> dict:
    return build_singbox_subscription(
        build_poc_builder(),
        entry_node,
        REMOTE_USER,
        ("hysteria2", "tuic", "anytls", "vmess", "vless", "trojan", "shadowsocks"),
    )


def build_poc_clash_subscription(entry_node: str = "node-a") -> str:
    return build_clash_subscription(
        build_poc_builder(),
        entry_node,
        REMOTE_USER,
        ("hysteria2", "tuic", "anytls", "vmess", "vless", "trojan", "shadowsocks"),
    )
