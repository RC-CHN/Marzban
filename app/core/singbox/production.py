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
    SUPPORTED_NODE_LINK_PROTOCOLS,
    NodeLink,
    PublicIngress,
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
    SingBoxAdjacency,
    SingBoxComputedPathHop,
    SingBoxEgressService,
    SingBoxEnrollmentToken,
    SingBoxIngressService,
    SingBoxNode as DBSingBoxNode,
    SingBoxNodeAddress,
    SingBoxNodeLink,
    SingBoxNodeUsage,
    SingBoxRoutePolicy,
    SingBoxRoutingPolicy,
    SingBoxRouteRevision,
    SingBoxUserCredential,
    SingBoxUserConnection,
    User,
)
from app.models.node import NodeStatus
from app.models.singbox import (
    SingBoxConnectionWrite,
    SingBoxNodeCreate,
    SingBoxNodeModify,
    SingBoxProtocol,
)
from app.models.user import UserStatus
from config import (
    SINGBOX_NODE_LINK_CA_CERT_PATH,
    SINGBOX_NODE_LINK_CERT_PATH,
    SINGBOX_NODE_LINK_CLIENT_CERT_PATH,
    SINGBOX_NODE_LINK_CLIENT_KEY_PATH,
    SINGBOX_NODE_LINK_KEY_PATH,
    SINGBOX_NODE_LINK_MTLS,
    SINGBOX_NODE_LINK_PROTOCOL,
    SINGBOX_NODE_LINK_PORT,
    SINGBOX_NODE_AUTO_UPGRADE,
    SINGBOX_NODE_TARGET_IMAGE,
    SINGBOX_SHADOWSOCKS_METHOD,
    SINGBOX_SHADOWSOCKS_SERVER_PASSWORD,
    SINGBOX_SYNC_AGENT_VERSION,
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


def node_protocol_connection_counts(db: Session, node_id: int) -> dict[str, int]:
    counts = {protocol: 0 for protocol in SUPPORTED_PROTOCOLS}
    rows = (
        db.query(SingBoxUserConnection.protocol, SingBoxUserConnection.id)
        .filter(
            SingBoxUserConnection.entry_node_id == node_id,
            SingBoxUserConnection.enabled.is_(True),
        )
        .all()
    )
    for protocol, _ in rows:
        if protocol in counts:
            counts[protocol] += 1
    return counts


def issue_node_sync_token(db: Session, node: DBSingBoxNode) -> str:
    token = secrets.token_urlsafe(32)
    node.sync_token_hash = _token_hash(token)
    node.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(node)
    return token


def get_node_by_sync_token(db: Session, token: str) -> DBSingBoxNode | None:
    return (
        db.query(DBSingBoxNode)
        .filter(DBSingBoxNode.sync_token_hash == _token_hash(token))
        .first()
    )


def create_node(db: Session, payload: SingBoxNodeCreate) -> DBSingBoxNode:
    dbnode = DBSingBoxNode(
        name=payload.name,
        public_host=payload.public_host,
        entry_enabled=payload.entry_enabled,
        exit_enabled=payload.exit_enabled,
        node_link_port=payload.node_link_port,
        public_ports=_ports_dict(payload.public_ports),
        protocol_settings=(
            _settings_dict(payload.protocol_settings)
            if "protocol_settings" in payload.model_fields_set
            else None
        ),
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
    ensure_node_overlay_services(db, dbnode)
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
        elif field_name == "protocol_settings":
            setattr(dbnode, field_name, _settings_dict(value))
        else:
            setattr(dbnode, field_name, value)
    dbnode.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(dbnode)
    rebuild_all_route_policies(db)
    return dbnode


def delete_node(db: Session, dbnode: DBSingBoxNode) -> None:
    connection_count = (
        db.query(SingBoxUserConnection)
        .filter(
            (SingBoxUserConnection.entry_node_id == dbnode.id)
            | (SingBoxUserConnection.exit_node_id == dbnode.id)
        )
        .count()
    )
    legacy_user_count = (
        db.query(SingBoxUserCredential)
        .filter(SingBoxUserCredential.exit_node_id == dbnode.id)
        .count()
    )
    enabled_adjacencies = (
        db.query(SingBoxAdjacency)
        .filter(
            SingBoxAdjacency.enabled.is_(True),
            (SingBoxAdjacency.node_a_id == dbnode.id)
            | (SingBoxAdjacency.node_b_id == dbnode.id),
        )
        .count()
    )
    historical_hops = (
        db.query(SingBoxComputedPathHop)
        .filter(
            (SingBoxComputedPathHop.from_node_id == dbnode.id)
            | (SingBoxComputedPathHop.to_node_id == dbnode.id)
        )
        .count()
    )
    constrained_policies = [
        policy.name
        for policy in db.query(SingBoxRoutingPolicy).all()
        if dbnode.id in (policy.required_node_ids or [])
        or dbnode.id in (policy.avoided_node_ids or [])
    ]
    if connection_count or legacy_user_count or enabled_adjacencies or historical_hops or constrained_policies:
        references = []
        if connection_count:
            references.append(f"{connection_count} connection(s)")
        if legacy_user_count:
            references.append(f"{legacy_user_count} legacy user policy/policies")
        if enabled_adjacencies:
            references.append(f"{enabled_adjacencies} enabled adjacency/adjacencies")
        if historical_hops:
            references.append(f"{historical_hops} retained route hop(s)")
        if constrained_policies:
            references.append(f"routing policy/policies: {', '.join(constrained_policies)}")
        raise ValueError(f'Node "{dbnode.name}" is used by {" and ".join(references)}')

    db.query(SingBoxRoutePolicy).filter(
        (SingBoxRoutePolicy.entry_node_id == dbnode.id)
        | (SingBoxRoutePolicy.exit_node_id == dbnode.id)
    ).delete(synchronize_session=False)
    for adjacency in (
        db.query(SingBoxAdjacency)
        .filter(
            (SingBoxAdjacency.node_a_id == dbnode.id)
            | (SingBoxAdjacency.node_b_id == dbnode.id)
        )
        .all()
    ):
        db.delete(adjacency)
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
    protocol = _node_link_protocol()
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
                existing[pair].protocol = protocol
                existing[pair].mtls_enabled = from_node.node_link_mtls_enabled and to_node.node_link_mtls_enabled
                continue
            db.add(
                SingBoxNodeLink(
                    from_node_id=from_node.id,
                    to_node_id=to_node.id,
                    protocol=protocol,
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
        credential = user.singbox_credentials
        if not credential.subscription_token:
            credential.subscription_token = _subscription_token(db)
            credential.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(credential)
        return credential

    credential = SingBoxUserCredential(
        user=user,
        subscription_token=_subscription_token(db),
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


def get_user_credential_by_subscription_token(
    db: Session,
    token: str,
) -> SingBoxUserCredential | None:
    return (
        db.query(SingBoxUserCredential)
        .join(User)
        .filter(
            SingBoxUserCredential.subscription_token == token,
            User.status == UserStatus.active,
        )
        .first()
    )


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
    existing_connections = get_user_connections(db, user)
    existing_by_entry_protocol = {
        (connection.entry_node_id, connection.protocol): connection
        for connection in existing_connections
    }
    default_connections = []
    for entry in get_nodes(db):
        if not entry.entry_enabled:
            continue
        for protocol in _protocols(credential.enabled_protocols):
            existing = existing_by_entry_protocol.get((entry.id, protocol))
            default_connections.append(
                SingBoxConnectionWrite(
                    id=existing.id if existing else None,
                    label=existing.label if existing else None,
                    protocol=protocol,
                    entry_node_id=entry.id,
                    exit_node_id=credential.exit_node_id
                    if credential.exit_node_id != entry.id
                    else None,
                    enabled=existing.enabled if existing else True,
                    sort_order=existing.sort_order if existing else len(default_connections) * 100,
                )
            )
    replace_user_connections(db, user, default_connections)
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


def get_user_connections(db: Session, user: User) -> list[SingBoxUserConnection]:
    return (
        db.query(SingBoxUserConnection)
        .filter(SingBoxUserConnection.user_id == user.id)
        .order_by(SingBoxUserConnection.sort_order, SingBoxUserConnection.id)
        .all()
    )


def replace_user_connections(
    db: Session,
    user: User,
    payloads: list[SingBoxConnectionWrite],
) -> list[SingBoxUserConnection]:
    ensure_user_credentials(db, user)
    existing = {connection.id: connection for connection in get_user_connections(db, user)}
    seen_ids: set[int] = set()

    for payload in payloads:
        requested_ingress = (
            db.query(SingBoxIngressService)
            .filter(SingBoxIngressService.id == payload.ingress_service_id)
            .first()
            if payload.ingress_service_id is not None
            else None
        )
        entry_node_id = requested_ingress.node_id if requested_ingress else payload.entry_node_id
        entry = get_node(db, entry_node_id)
        if not entry or (payload.enabled and not entry.entry_enabled):
            raise ValueError("Entry node is missing or does not accept public connections")
        protocol = requested_ingress.protocol if requested_ingress else payload.protocol
        ingress = requested_ingress or ensure_node_overlay_services(db, entry)["ingresses"].get(protocol)
        if ingress is None or (payload.enabled and not ingress.enabled):
            raise ValueError("Ingress service is missing or disabled")
        if requested_ingress and payload.protocol and requested_ingress.protocol != payload.protocol:
            raise ValueError("Connection protocol does not match the ingress service")

        requested_egress = (
            db.query(SingBoxEgressService)
            .filter(SingBoxEgressService.id == payload.egress_service_id)
            .first()
            if payload.egress_service_id is not None
            else None
        )
        requested_exit_node_id = requested_egress.node_id if requested_egress else payload.exit_node_id
        exit_node = get_node(db, requested_exit_node_id) if requested_exit_node_id is not None else None
        if requested_exit_node_id is not None and not exit_node:
            raise ValueError("Exit node is missing or is not enabled as an exit")
        if not requested_egress and exit_node and payload.enabled and not exit_node.exit_enabled:
            raise ValueError("Exit node is missing or is not enabled as an exit")
        if not requested_egress and exit_node and exit_node.id == entry.id:
            raise ValueError("Use Direct when the entry and exit node are the same")
        egress_node = exit_node or entry
        egress = requested_egress or ensure_node_overlay_services(db, egress_node)["egress"]
        policy = (
            db.query(SingBoxRoutingPolicy)
            .filter(SingBoxRoutingPolicy.id == payload.routing_policy_id)
            .first()
            if payload.routing_policy_id is not None
            else ensure_default_routing_policy(db)
        )
        if not egress or not egress.enabled:
            raise ValueError("Egress service is missing or disabled")
        if policy is None:
            raise ValueError("Routing policy is missing")
        if payload.id is not None:
            connection = existing.get(payload.id)
            if connection is None:
                raise ValueError("Connection does not belong to this user")
            seen_ids.add(connection.id)
        else:
            connection = _new_connection(user.id)
            db.add(connection)

        connection.entry_node_id = entry.id
        connection.exit_node_id = exit_node.id if exit_node and exit_node.id != entry.id else None
        connection.ingress_service_id = ingress.id
        connection.egress_service_id = egress.id
        connection.routing_policy_id = policy.id
        connection.protocol = protocol
        connection.label = (payload.label or "").strip() or _connection_label(
            entry.name,
            exit_node.name if exit_node else None,
            protocol,
        )
        connection.enabled = payload.enabled
        connection.sort_order = payload.sort_order
        connection.updated_at = datetime.utcnow()

    for connection_id, connection in existing.items():
        if connection_id not in seen_ids:
            db.delete(connection)
    db.commit()
    return get_user_connections(db, user)


def ensure_default_routing_policy(db: Session) -> SingBoxRoutingPolicy:
    policy = db.query(SingBoxRoutingPolicy).filter(SingBoxRoutingPolicy.name == "Default").first()
    if policy is None:
        policy = SingBoxRoutingPolicy(
            name="Default",
            metric_mode="admin_only",
            max_hops=8,
            allow_degraded=False,
            failover=True,
            required_node_ids=[],
            avoided_node_ids=[],
        )
        db.add(policy)
        db.flush()
    return policy


def ensure_node_overlay_services(db: Session, node: DBSingBoxNode) -> dict:
    address = (
        db.query(SingBoxNodeAddress)
        .filter(
            SingBoxNodeAddress.node_id == node.id,
            SingBoxNodeAddress.address == node.public_host,
        )
        .first()
    )
    if address is None:
        address = SingBoxNodeAddress(
            node_id=node.id,
            address=node.public_host,
            kind="public",
            is_primary=True,
            enabled=True,
        )
        db.add(address)
        db.flush()

    ports = _protocol_ports(node.public_ports) or ProtocolPorts()
    settings = node.protocol_settings or {}
    ingresses = {
        service.protocol: service
        for service in db.query(SingBoxIngressService)
        .filter(SingBoxIngressService.node_id == node.id)
        .all()
    }
    if node.entry_enabled:
        for protocol in SUPPORTED_PROTOCOLS:
            if protocol in ingresses:
                continue
            service = SingBoxIngressService(
                node_id=node.id,
                advertised_address_id=address.id,
                name=f"{node.name} / {protocol}",
                protocol=protocol,
                listen_port=ports.get(protocol),
                enabled=True,
                tls_mode=node.public_tls_mode,
                tls_profile={
                    "cert_path": node.public_tls_cert_path,
                    "key_path": node.public_tls_key_path,
                    "ca_cert_path": node.public_tls_ca_cert_path,
                },
                protocol_profile=settings.get(protocol, {}),
            )
            db.add(service)
            db.flush()
            ingresses[protocol] = service

    egress = (
        db.query(SingBoxEgressService)
        .filter(
            SingBoxEgressService.node_id == node.id,
            SingBoxEgressService.kind == "direct",
        )
        .first()
    )
    if egress is None:
        egress = SingBoxEgressService(
            node_id=node.id,
            name=f"Direct @ {node.name}",
            kind="direct",
            enabled=True,
            settings={},
        )
        db.add(egress)
    ensure_default_routing_policy(db)
    db.flush()
    return {"address": address, "ingresses": ingresses, "egress": egress}


def build_builder(db: Session) -> SingBoxConfigBuilder:
    dbnodes = get_nodes(db)
    nodes = {_node.name: _builder_node(_node) for _node in dbnodes}
    active_connections = _active_connections(db)
    connection_user_ids = {connection.user_id for connection in active_connections}
    users = [_builder_connection(connection) for connection in active_connections]
    users.extend(
        _builder_user(credential)
        for credential in _active_credentials(db)
        if credential.user_id not in connection_user_ids
    )
    links = [_builder_link(link) for link in db.query(SingBoxNodeLink).all()]
    public_ingresses = [
        _builder_ingress(ingress)
        for ingress in db.query(SingBoxIngressService).order_by(SingBoxIngressService.id).all()
    ]
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
        public_ingresses=public_ingresses,
    )


def build_node_config(db: Session, node_id: int) -> tuple[dict, str]:
    node = get_node(db, node_id)
    if node is None:
        raise ValueError("Node not found")
    builder = build_builder(db)
    route = (
        db.query(SingBoxRouteRevision)
        .filter(SingBoxRouteRevision.status == "active")
        .order_by(SingBoxRouteRevision.number.desc())
        .first()
    )
    if route is None:
        config = builder.build_node_config(node.name)
    else:
        from app.core.singbox.routing.compiler import (
            compile_route_revision,
            internal_only,
            merge_intents,
        )

        intent = compile_route_revision(db, route)[node.id]
        draining = (
            db.query(SingBoxRouteRevision)
            .filter(
                SingBoxRouteRevision.status == "draining",
                SingBoxRouteRevision.drain_until > datetime.utcnow(),
            )
            .order_by(SingBoxRouteRevision.number.desc())
            .first()
        )
        if draining:
            intent = merge_intents(intent, internal_only(compile_route_revision(db, draining)[node.id]))
        config = builder.build_node_config(node.name, intent)
    return config, config_hash(config)


def build_node_config_for_route(
    db: Session,
    node_id: int,
    route_revision_id: int,
) -> tuple[dict, str]:
    node = get_node(db, node_id)
    route = (
        db.query(SingBoxRouteRevision)
        .filter(SingBoxRouteRevision.id == route_revision_id)
        .first()
    )
    if node is None:
        raise ValueError("Node not found")
    if route is None:
        raise ValueError("Route revision not found")
    from app.core.singbox.routing.compiler import compile_route_revision

    intent = compile_route_revision(db, route).get(node.id)
    config = build_builder(db).build_node_config(node.name, intent)
    return config, config_hash(config)


def build_user_subscription(
    db: Session,
    user: User,
    entry_node_id: int | None = None,
    config_format: str = "sing-box",
) -> str | dict:
    from app.core.singbox.subscription import (
        SubscriptionTarget,
        build_clash_connection_subscription,
        build_singbox_connection_subscription,
        build_v2rayn_connection_subscription,
    )

    ensure_user_credentials(db, user)
    builder = build_builder(db)
    connections = [
        connection
        for connection in get_user_connections(db, user)
        if connection.enabled
        and connection.entry_node
        and connection.entry_node.entry_enabled
        and (entry_node_id is None or connection.entry_node_id == entry_node_id)
    ]
    if not connections:
        raise ValueError("User has no enabled sing-box connections")
    targets = [
        SubscriptionTarget(
            tag=f"connection-{connection.id}",
            name=connection.label,
            entry_node=connection.entry_node.name,
            protocol=_protocol(connection.protocol),
            user=_builder_connection(connection),
        )
        for connection in connections
    ]
    if config_format in {"clash", "clash-meta"}:
        return build_clash_connection_subscription(builder, targets)
    if config_format in {"v2rayn", "v2ray"}:
        return build_v2rayn_connection_subscription(builder, targets)
    return build_singbox_connection_subscription(builder, targets)


def build_node_upgrade_instruction(
    *,
    runtime: str | None,
    container_image: str | None,
    sync_agent_version: str | None,
    agent_url: str,
) -> dict | None:
    if not SINGBOX_NODE_AUTO_UPGRADE:
        return None

    instruction: dict[str, str | bool | None] = {
        "apply": True,
        "image": None,
        "agent_version": None,
        "agent_url": None,
    }
    if (
        SINGBOX_NODE_TARGET_IMAGE
        and (runtime or "").lower() == "docker"
        and container_image != SINGBOX_NODE_TARGET_IMAGE
    ):
        instruction["image"] = SINGBOX_NODE_TARGET_IMAGE

    if SINGBOX_SYNC_AGENT_VERSION and sync_agent_version != SINGBOX_SYNC_AGENT_VERSION:
        instruction["agent_version"] = SINGBOX_SYNC_AGENT_VERSION
        instruction["agent_url"] = agent_url

    if instruction["image"] or instruction["agent_version"]:
        return instruction
    return None


def update_node_config_hash(db: Session, node: DBSingBoxNode, hash_value: str, applied: bool = False) -> None:
    node.last_config_hash = hash_value
    if applied:
        node.applied_config_hash = hash_value
        node.status = NodeStatus.connected
        node.last_seen_at = datetime.utcnow()
    node.updated_at = datetime.utcnow()
    db.commit()


def update_node_heartbeat(
    db: Session,
    node: DBSingBoxNode,
    *,
    desired_hash: str,
    applied_hash: str | None = None,
    status: NodeStatus = NodeStatus.connected,
    version: str | None = None,
    message: str | None = None,
) -> None:
    node.last_config_hash = desired_hash
    if applied_hash:
        node.applied_config_hash = applied_hash
    node.status = status
    if version:
        node.version = version[:32]
    node.message = (message or "")[:1024] or None
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


def _active_connections(db: Session) -> list[SingBoxUserConnection]:
    connections = (
        db.query(SingBoxUserConnection)
        .join(User)
        .filter(
            User.status == UserStatus.active,
            SingBoxUserConnection.enabled.is_(True),
        )
        .order_by(SingBoxUserConnection.sort_order, SingBoxUserConnection.id)
        .all()
    )
    return [
        connection
        for connection in connections
        if connection.entry_node
        and connection.entry_node.entry_enabled
        and (connection.exit_node is None or connection.exit_node.exit_enabled)
    ]


def _route_policies(db: Session) -> list[RoutePolicy]:
    policies = []
    connection_user_ids = set()
    for connection in _active_connections(db):
        if not connection.entry_node or not connection.entry_node.entry_enabled:
            continue
        if connection.exit_node and not connection.exit_node.exit_enabled:
            continue
        connection_user_ids.add(connection.user_id)
        policies.append(
            RoutePolicy(
                entry_node=connection.entry_node.name,
                auth_name=connection.auth_name,
                exit_node=connection.exit_node.name if connection.exit_node else None,
                protocol=_protocol(connection.protocol),
            )
        )

    credential_user_ids = set(connection_user_ids)
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
        if user.id in connection_user_ids:
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
        protocol_settings=node.protocol_settings or {},
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
        protocol=_node_link_protocol(link.protocol),
        enabled=link.enabled,
    )


def _node_link_protocol(value: str | None = None) -> str:
    protocol = (value or SINGBOX_NODE_LINK_PROTOCOL or "anytls").lower()
    if protocol not in SUPPORTED_NODE_LINK_PROTOCOLS:
        raise ValueError(
            "Unsupported SINGBOX_NODE_LINK_PROTOCOL: "
            f"{protocol}. Supported values: {', '.join(SUPPORTED_NODE_LINK_PROTOCOLS)}"
        )
    return protocol


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


def _builder_connection(connection: SingBoxUserConnection) -> SingBoxUser:
    return SingBoxUser(
        auth_name=connection.auth_name,
        credentials=SingBoxUserCredentials(
            password=connection.password,
            vmess_uuid=connection.vmess_uuid,
            vless_uuid=connection.vless_uuid,
            tuic_uuid=connection.tuic_uuid,
            shadowsocks_password=connection.shadowsocks_password,
        ),
        protocols=(_protocol(connection.protocol),),
        entry_node=connection.entry_node.name,
        ingress_service_id=connection.ingress_service_id,
    )


def _builder_ingress(ingress: SingBoxIngressService) -> PublicIngress:
    address = ingress.advertised_address
    if address is None:
        address = next(
            (item for item in ingress.node.addresses if item.is_primary and item.enabled),
            None,
        )
    return PublicIngress(
        id=ingress.id,
        node_name=ingress.node.name,
        address=address.address if address else ingress.node.public_host,
        protocol=_protocol(ingress.protocol),
        listen_port=ingress.listen_port,
        enabled=ingress.enabled,
        tls_mode=ingress.tls_mode,
        tls_profile=ingress.tls_profile or {},
        protocol_profile=ingress.protocol_profile or {},
    )


def _new_connection(user_id: int) -> SingBoxUserConnection:
    return SingBoxUserConnection(
        user_id=user_id,
        auth_name=f"u{user_id}-{secrets.token_hex(8)}",
        password=_secret(24),
        vmess_uuid=str(uuid.uuid4()),
        vless_uuid=str(uuid.uuid4()),
        tuic_uuid=str(uuid.uuid4()),
        shadowsocks_password=_base64_secret(16),
    )


def _connection_label(entry_name: str, exit_name: str | None, protocol: str) -> str:
    return f"{entry_name} -> {exit_name or 'Direct'} / {protocol}"


def _protocol(value: str) -> Protocol:
    if value not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"Unsupported sing-box protocol: {value}")
    return value  # type: ignore[return-value]


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


def _settings_dict(value) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return value.model_dump(exclude_none=True)


def _secret(length: int) -> str:
    return secrets.token_urlsafe(length)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _subscription_token(db: Session) -> str:
    for _ in range(8):
        token = secrets.token_urlsafe(32)
        exists = (
            db.query(SingBoxUserCredential.id)
            .filter(SingBoxUserCredential.subscription_token == token)
            .first()
        )
        if not exists:
            return token
    raise RuntimeError("Unable to generate a unique subscription token")


def _base64_secret(length: int) -> str:
    return base64.b64encode(secrets.token_bytes(length)).decode()
