from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.singbox.config import (
    SUPPORTED_PROTOCOLS,
    NodeLink,
    Protocol,
    ProtocolPorts,
    RoutePolicy,
    ShadowsocksSettings,
    SingBoxConfigBuilder,
    SingBoxNode,
    SingBoxUser,
    SingBoxUserCredentials,
    TLSSettings,
    config_hash,
)
from app.db.models import (
    SingBoxEnrollmentToken,
    SingBoxNode as DBSingBoxNode,
    SingBoxNodeLink,
    SingBoxNodeUsage,
    SingBoxRoutePolicy,
    SingBoxUserCredential,
    User,
)
from app.models.node import NodeStatus
from app.models.singbox import SingBoxNodeCreate, SingBoxNodeModify, SingBoxProtocol
from app.models.user import UserStatus
from config import (
    SINGBOX_NODE_LINK_CA_CERT_PATH,
    SINGBOX_NODE_LINK_CERT_PATH,
    SINGBOX_NODE_LINK_CLIENT_CERT_PATH,
    SINGBOX_NODE_LINK_CLIENT_KEY_PATH,
    SINGBOX_NODE_LINK_KEY_PATH,
    SINGBOX_NODE_LINK_MTLS,
    SINGBOX_NODE_LINK_PORT,
    SINGBOX_SHADOWSOCKS_METHOD,
    SINGBOX_SHADOWSOCKS_SERVER_PASSWORD,
    SINGBOX_PUBLIC_TLS_CA_CERT_PATH,
    SINGBOX_TLS_CERT_PATH,
    SINGBOX_TLS_INSECURE,
    SINGBOX_TLS_KEY_PATH,
)


def get_nodes(db: Session) -> list[DBSingBoxNode]:
    return db.query(DBSingBoxNode).order_by(DBSingBoxNode.id).all()


def get_node(db: Session, node_id: int) -> DBSingBoxNode | None:
    return db.query(DBSingBoxNode).filter(DBSingBoxNode.id == node_id).first()


def get_node_by_name(db: Session, name: str) -> DBSingBoxNode | None:
    return db.query(DBSingBoxNode).filter(DBSingBoxNode.name == name).first()


def create_node(db: Session, payload: SingBoxNodeCreate) -> DBSingBoxNode:
    dbnode = DBSingBoxNode(
        name=payload.name,
        public_host=payload.public_host,
        entry_enabled=payload.entry_enabled,
        exit_enabled=payload.exit_enabled,
        node_link_port=payload.node_link_port,
        public_ports=_ports_dict(payload.public_ports),
        deploy_method=payload.deploy_method,
        ssh_host=payload.ssh_host,
        ssh_user=payload.ssh_user,
        ssh_port=payload.ssh_port,
        config_path=payload.config_path,
        restart_command=payload.restart_command,
        public_tls_mode=payload.public_tls_mode,
        public_tls_cert_path=payload.public_tls_cert_path,
        public_tls_key_path=payload.public_tls_key_path,
        public_tls_ca_cert_path=payload.public_tls_ca_cert_path,
        node_link_ca_cert_path=payload.node_link_ca_cert_path,
        node_link_cert_path=payload.node_link_cert_path,
        node_link_key_path=payload.node_link_key_path,
        node_link_client_cert_path=payload.node_link_client_cert_path,
        node_link_client_key_path=payload.node_link_client_key_path,
        node_link_mtls_enabled=payload.node_link_mtls_enabled,
        status=NodeStatus.connecting,
        usage_coefficient=payload.usage_coefficient,
    )
    db.add(dbnode)
    db.commit()
    db.refresh(dbnode)
    if payload.rebuild_links:
        rebuild_full_mesh_links(db)
        rebuild_all_route_policies(db)
        db.refresh(dbnode)
    return dbnode


def update_node(db: Session, dbnode: DBSingBoxNode, payload: SingBoxNodeModify) -> DBSingBoxNode:
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        if field_name == "public_ports":
            setattr(dbnode, field_name, _ports_dict(value))
        else:
            setattr(dbnode, field_name, value)
    dbnode.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(dbnode)
    rebuild_all_route_policies(db)
    return dbnode


def delete_node(db: Session, dbnode: DBSingBoxNode) -> None:
    db.delete(dbnode)
    db.commit()
    rebuild_full_mesh_links(db)
    rebuild_all_route_policies(db)


def create_enrollment_token(
    db: Session,
    node: DBSingBoxNode,
    *,
    expires_in_seconds: int,
    created_by: str | None = None,
) -> tuple[SingBoxEnrollmentToken, str]:
    token = secrets.token_urlsafe(32)
    enrollment = SingBoxEnrollmentToken(
        node_id=node.id,
        token_hash=_token_hash(token),
        expires_at=datetime.utcnow() + timedelta(seconds=expires_in_seconds),
        created_by=created_by,
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment, token


def get_valid_enrollment(db: Session, token: str) -> SingBoxEnrollmentToken | None:
    return (
        db.query(SingBoxEnrollmentToken)
        .filter(
            SingBoxEnrollmentToken.token_hash == _token_hash(token),
            SingBoxEnrollmentToken.used_at.is_(None),
            SingBoxEnrollmentToken.expires_at > datetime.utcnow(),
        )
        .first()
    )


def consume_enrollment(db: Session, enrollment: SingBoxEnrollmentToken) -> None:
    enrollment.used_at = datetime.utcnow()
    db.commit()


def rebuild_full_mesh_links(db: Session) -> list[SingBoxNodeLink]:
    nodes = get_nodes(db)
    existing = {
        (link.from_node_id, link.to_node_id): link
        for link in db.query(SingBoxNodeLink).all()
    }
    valid_pairs = set()
    for from_node in nodes:
        for to_node in nodes:
            if from_node.id == to_node.id:
                continue
            pair = (from_node.id, to_node.id)
            valid_pairs.add(pair)
            if pair in existing:
                continue
            db.add(
                SingBoxNodeLink(
                    from_node_id=from_node.id,
                    to_node_id=to_node.id,
                    auth_name=f"link-{from_node.name}",
                    password=_secret(32),
                    mtls_enabled=from_node.node_link_mtls_enabled and to_node.node_link_mtls_enabled,
                    enabled=True,
                    last_rotated_at=datetime.utcnow(),
                )
            )

    for pair, link in existing.items():
        if pair not in valid_pairs:
            db.delete(link)

    db.commit()
    return db.query(SingBoxNodeLink).order_by(SingBoxNodeLink.id).all()


def rotate_node_links(db: Session) -> list[SingBoxNodeLink]:
    links = db.query(SingBoxNodeLink).all()
    now = datetime.utcnow()
    for link in links:
        link.password = _secret(32)
        link.last_rotated_at = now
    db.commit()
    return db.query(SingBoxNodeLink).order_by(SingBoxNodeLink.id).all()


def ensure_user_credentials(db: Session, user: User) -> SingBoxUserCredential:
    if user.singbox_credentials:
        return user.singbox_credentials

    credential = SingBoxUserCredential(
        user=user,
        password=_secret(24),
        vmess_uuid=str(uuid.uuid4()),
        vless_uuid=str(uuid.uuid4()),
        tuic_uuid=str(uuid.uuid4()),
        shadowsocks_password=_base64_secret(16),
        enabled_protocols=list(SUPPORTED_PROTOCOLS),
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    return credential


def update_user_policy(
    db: Session,
    user: User,
    enabled_protocols: list[SingBoxProtocol] | None = None,
    exit_node_id: int | None = None,
) -> SingBoxUserCredential:
    credential = ensure_user_credentials(db, user)
    if enabled_protocols is not None:
        credential.enabled_protocols = list(enabled_protocols)
    credential.exit_node_id = exit_node_id
    credential.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(credential)
    rebuild_route_policies_for_user(db, user)
    db.refresh(credential)
    return credential


def rebuild_route_policies_for_user(db: Session, user: User) -> list[SingBoxRoutePolicy]:
    credential = ensure_user_credentials(db, user)
    nodes = get_nodes(db)
    existing = {
        policy.entry_node_id: policy
        for policy in db.query(SingBoxRoutePolicy).filter(SingBoxRoutePolicy.user_id == user.id)
    }
    valid_entry_ids = set()
    for node in nodes:
        if not node.entry_enabled:
            continue
        valid_entry_ids.add(node.id)
        policy = existing.get(node.id)
        if policy is None:
            db.add(
                SingBoxRoutePolicy(
                    user_id=user.id,
                    entry_node_id=node.id,
                    exit_node_id=credential.exit_node_id,
                    enabled=True,
                )
            )
        else:
            policy.exit_node_id = credential.exit_node_id
            policy.enabled = True
            policy.updated_at = datetime.utcnow()

    for entry_id, policy in existing.items():
        if entry_id not in valid_entry_ids:
            db.delete(policy)

    db.commit()
    return (
        db.query(SingBoxRoutePolicy)
        .filter(SingBoxRoutePolicy.user_id == user.id)
        .order_by(SingBoxRoutePolicy.entry_node_id)
        .all()
    )


def rebuild_all_route_policies(db: Session) -> None:
    for credential in db.query(SingBoxUserCredential).all():
        rebuild_route_policies_for_user(db, credential.user)


def build_builder(db: Session) -> SingBoxConfigBuilder:
    dbnodes = get_nodes(db)
    nodes = {_node.name: _builder_node(_node) for _node in dbnodes}
    users = [_builder_user(credential) for credential in _active_credentials(db)]
    links = [_builder_link(link) for link in db.query(SingBoxNodeLink).all()]
    policies = _route_policies(db)
    return SingBoxConfigBuilder(
        nodes=nodes,
        users=users,
        route_policies=policies,
        shadowsocks=ShadowsocksSettings(
            method=SINGBOX_SHADOWSOCKS_METHOD,
            server_password=SINGBOX_SHADOWSOCKS_SERVER_PASSWORD,
        ),
        public_tls=_public_tls(),
        node_link_tls=_node_link_tls(),
        node_links=links,
    )


def build_node_config(db: Session, node_id: int) -> tuple[dict, str]:
    node = get_node(db, node_id)
    if node is None:
        raise ValueError("Node not found")
    builder = build_builder(db)
    config = builder.build_node_config(node.name)
    return config, config_hash(config)


def build_user_subscription(
    db: Session,
    user: User,
    entry_node_id: int | None = None,
    config_format: str = "sing-box",
) -> str | dict:
    from app.core.singbox.subscription import build_clash_subscription, build_singbox_subscription

    credential = ensure_user_credentials(db, user)
    builder = build_builder(db)
    entry_node = _select_entry_node(db, entry_node_id)
    protocols = _protocols(credential.enabled_protocols)
    singbox_user = _builder_user(credential)
    if config_format in {"clash", "clash-meta"}:
        return build_clash_subscription(builder, entry_node.name, singbox_user, protocols)
    return build_singbox_subscription(builder, entry_node.name, singbox_user, protocols)


def update_node_config_hash(db: Session, node: DBSingBoxNode, hash_value: str, applied: bool = False) -> None:
    node.last_config_hash = hash_value
    if applied:
        node.applied_config_hash = hash_value
        node.status = NodeStatus.connected
        node.last_seen_at = datetime.utcnow()
    node.updated_at = datetime.utcnow()
    db.commit()


def record_node_usage(db: Session, node: DBSingBoxNode, uplink: int, downlink: int) -> SingBoxNodeUsage:
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    usage = (
        db.query(SingBoxNodeUsage)
        .filter(SingBoxNodeUsage.node_id == node.id, SingBoxNodeUsage.created_at == now)
        .first()
    )
    if usage is None:
        usage = SingBoxNodeUsage(
            node_id=node.id,
            created_at=now,
            uplink=0,
            downlink=0,
        )
        db.add(usage)
    usage.uplink = (usage.uplink or 0) + uplink
    usage.downlink = (usage.downlink or 0) + downlink
    node.last_seen_at = datetime.utcnow()
    db.commit()
    db.refresh(usage)
    return usage


def _active_credentials(db: Session) -> Iterable[SingBoxUserCredential]:
    return (
        db.query(SingBoxUserCredential)
        .join(User)
        .filter(User.status == UserStatus.active)
        .all()
    )


def _route_policies(db: Session) -> list[RoutePolicy]:
    policies = []
    credential_user_ids = set()
    for policy in (
        db.query(SingBoxRoutePolicy)
        .filter(SingBoxRoutePolicy.enabled.is_(True))
        .all()
    ):
        if not policy.entry_node:
            continue
        user = policy.user
        if not user or not user.singbox_credentials:
            continue
        credential_user_ids.add(user.id)
        exit_node = policy.exit_node.name if policy.exit_node else None
        policies.append(
            RoutePolicy(
                entry_node=policy.entry_node.name,
                auth_name=user.username,
                exit_node=exit_node,
            )
        )
    entry_nodes = [node for node in get_nodes(db) if node.entry_enabled]
    for credential in _active_credentials(db):
        if credential.user_id in credential_user_ids:
            continue
        for entry_node in entry_nodes:
            exit_node = credential.exit_node.name if credential.exit_node else None
            policies.append(
                RoutePolicy(
                    entry_node=entry_node.name,
                    auth_name=credential.user.username,
                    exit_node=exit_node,
                )
            )
    return policies


def _builder_node(node: DBSingBoxNode) -> SingBoxNode:
    return SingBoxNode(
        name=node.name,
        public_host=node.public_host,
        node_link_port=node.node_link_port or SINGBOX_NODE_LINK_PORT,
        entry_enabled=node.entry_enabled,
        exit_enabled=node.exit_enabled,
        public_ports=_protocol_ports(node.public_ports),
        public_tls_mode=node.public_tls_mode or _default_public_tls_mode(),
        public_tls_cert_path=node.public_tls_cert_path or SINGBOX_TLS_CERT_PATH,
        public_tls_key_path=node.public_tls_key_path or SINGBOX_TLS_KEY_PATH,
        public_tls_ca_cert_path=node.public_tls_ca_cert_path or SINGBOX_PUBLIC_TLS_CA_CERT_PATH or None,
    )


def _builder_link(link: SingBoxNodeLink) -> NodeLink:
    return NodeLink(
        from_node=link.from_node.name,
        to_node=link.to_node.name,
        auth_name=link.auth_name,
        password=link.password,
        enabled=link.enabled,
    )


def _builder_user(credential: SingBoxUserCredential) -> SingBoxUser:
    return SingBoxUser(
        auth_name=credential.user.username,
        credentials=SingBoxUserCredentials(
            password=credential.password,
            vmess_uuid=credential.vmess_uuid,
            vless_uuid=credential.vless_uuid,
            tuic_uuid=credential.tuic_uuid,
            shadowsocks_password=credential.shadowsocks_password,
        ),
        protocols=_protocols(credential.enabled_protocols),
    )


def _public_tls() -> TLSSettings:
    return TLSSettings(
        certificate_path=SINGBOX_TLS_CERT_PATH,
        key_path=SINGBOX_TLS_KEY_PATH,
        client_insecure=SINGBOX_TLS_INSECURE,
        ca_certificate_path=SINGBOX_PUBLIC_TLS_CA_CERT_PATH or None,
    )


def _default_public_tls_mode() -> str:
    if SINGBOX_TLS_INSECURE:
        return "ip-insecure"
    if SINGBOX_PUBLIC_TLS_CA_CERT_PATH:
        return "ip-ca"
    return "system-ca"


def _node_link_tls() -> TLSSettings:
    return TLSSettings(
        certificate_path=SINGBOX_NODE_LINK_CERT_PATH,
        key_path=SINGBOX_NODE_LINK_KEY_PATH,
        client_insecure=False,
        ca_certificate_path=SINGBOX_NODE_LINK_CA_CERT_PATH,
        client_certificate_path=SINGBOX_NODE_LINK_CLIENT_CERT_PATH if SINGBOX_NODE_LINK_MTLS else None,
        client_key_path=SINGBOX_NODE_LINK_CLIENT_KEY_PATH if SINGBOX_NODE_LINK_MTLS else None,
        server_client_authentication="require-and-verify" if SINGBOX_NODE_LINK_MTLS else None,
        server_client_certificate_path=[SINGBOX_NODE_LINK_CA_CERT_PATH] if SINGBOX_NODE_LINK_MTLS else None,
    )


def _select_entry_node(db: Session, entry_node_id: int | None) -> DBSingBoxNode:
    query = db.query(DBSingBoxNode).filter(DBSingBoxNode.entry_enabled.is_(True))
    if entry_node_id:
        node = query.filter(DBSingBoxNode.id == entry_node_id).first()
    else:
        node = query.order_by(DBSingBoxNode.id).first()
    if node is None:
        raise ValueError("No sing-box entry node is available")
    return node


def _protocols(protocols: Iterable[str] | None) -> tuple[Protocol, ...]:
    allowed = set(SUPPORTED_PROTOCOLS)
    selected = tuple(protocol for protocol in protocols or SUPPORTED_PROTOCOLS if protocol in allowed)
    return selected or SUPPORTED_PROTOCOLS


def _protocol_ports(value: dict | None) -> ProtocolPorts | None:
    if not value:
        return None
    return ProtocolPorts(**{protocol: int(value[protocol]) for protocol in SUPPORTED_PROTOCOLS if protocol in value})


def _ports_dict(value) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return value.model_dump()


def _secret(length: int) -> str:
    return secrets.token_urlsafe(length)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _base64_secret(length: int) -> str:
    return base64.b64encode(secrets.token_bytes(length)).decode()
