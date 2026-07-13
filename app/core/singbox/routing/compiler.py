from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import (
    SingBoxAdjacencyDirection,
    SingBoxComputedPath,
    SingBoxNode,
    SingBoxRouteHopCredential,
    SingBoxRouteRevision,
)


@dataclass(frozen=True, slots=True)
class CompiledLinkUser:
    auth_name: str
    password: str


@dataclass(frozen=True, slots=True)
class CompiledLinkInbound:
    direction_id: int
    transport: str
    listen_port: int
    settings: dict
    users: tuple[CompiledLinkUser, ...]


@dataclass(frozen=True, slots=True)
class CompiledLinkOutbound:
    tag: str
    direction_id: int
    transport: str
    target_host: str
    target_port: int
    password: str
    settings: dict


@dataclass(frozen=True, slots=True)
class CompiledRouteRule:
    inbound_tag: str
    auth_name: str
    outbound_tag: str


@dataclass(frozen=True, slots=True)
class CompiledNodeIntent:
    node_id: int
    link_inbounds: tuple[CompiledLinkInbound, ...]
    link_outbounds: tuple[CompiledLinkOutbound, ...]
    route_rules: tuple[CompiledRouteRule, ...]


def ensure_route_credentials(db: Session, route: SingBoxRouteRevision) -> None:
    existing = {
        (
            item.egress_service_id,
            item.routing_policy_id,
            item.adjacency_direction_id,
        )
        for item in route.hop_credentials
    }
    for path in route.computed_paths:
        if path.status != "reachable":
            continue
        connection = path.connection
        for hop in path.hops:
            key = (
                connection.egress_service_id,
                connection.routing_policy_id,
                hop.adjacency_direction_id,
            )
            if key in existing:
                continue
            db.add(
                SingBoxRouteHopCredential(
                    route_revision_id=route.id,
                    egress_service_id=connection.egress_service_id,
                    routing_policy_id=connection.routing_policy_id,
                    adjacency_direction_id=hop.adjacency_direction_id,
                    auth_name=(
                        f"route-r{route.number}-e{connection.egress_service_id}"
                        f"-p{connection.routing_policy_id}-d{hop.adjacency_direction_id}"
                    ),
                    password=secrets.token_urlsafe(32),
                )
            )
            existing.add(key)
    db.flush()


def compile_route_revision(db: Session, route: SingBoxRouteRevision) -> dict[int, CompiledNodeIntent]:
    ensure_route_credentials(db, route)
    credentials = {
        (
            item.egress_service_id,
            item.routing_policy_id,
            item.adjacency_direction_id,
        ): item
        for item in route.hop_credentials
    }
    inbound_users: dict[int, dict[int, dict[str, CompiledLinkUser]]] = {}
    outbounds: dict[int, dict[str, CompiledLinkOutbound]] = {}
    rules: dict[int, dict[tuple[str, str], CompiledRouteRule]] = {}
    nodes = {node_id for (node_id,) in db.query(SingBoxNode.id).all()}

    probe_directions = (
        db.query(SingBoxAdjacencyDirection)
        .join(SingBoxAdjacencyDirection.adjacency)
        .filter(
            SingBoxAdjacencyDirection.enabled.is_(True),
            SingBoxAdjacencyDirection.adjacency.has(enabled=True),
        )
        .order_by(SingBoxAdjacencyDirection.id)
        .all()
    )
    direction_map = {direction.id: direction for direction in probe_directions}
    for direction in probe_directions:
        probe_tag = f"overlay-probe-d{direction.id}"
        inbound_users.setdefault(direction.to_node_id, {}).setdefault(direction.id, {})[
            direction.probe_auth_name
        ] = CompiledLinkUser(direction.probe_auth_name, direction.probe_password)
        outbounds.setdefault(direction.from_node_id, {})[probe_tag] = CompiledLinkOutbound(
            tag=probe_tag,
            direction_id=direction.id,
            transport=direction.transport,
            target_host=direction.to_node.public_host,
            target_port=direction.listen_port,
            password=direction.probe_password,
            settings=dict(direction.settings or {}),
        )
        _add_rule(
            rules,
            direction.to_node_id,
            f"overlay-in-{direction.id}",
            direction.probe_auth_name,
            "direct",
        )

    paths = (
        db.query(SingBoxComputedPath)
        .filter(SingBoxComputedPath.route_revision_id == route.id)
        .order_by(SingBoxComputedPath.connection_id)
        .all()
    )
    for path in paths:
        connection = path.connection
        ingress_node_id = connection.ingress_service.node_id
        nodes.add(ingress_node_id)
        if path.status != "reachable":
            _add_rule(
                rules,
                ingress_node_id,
                f"public-ingress-{connection.ingress_service_id}",
                connection.auth_name,
                "block",
            )
            continue
        hops = sorted(path.hops, key=lambda item: item.position)
        if not hops:
            continue

        hop_credentials = [
            credentials[
                (
                    connection.egress_service_id,
                    connection.routing_policy_id,
                    hop.adjacency_direction_id,
                )
            ]
            for hop in hops
        ]
        first_outbound = _outbound_tag(route.number, hop_credentials[0])
        _add_rule(
            rules,
            ingress_node_id,
            f"public-ingress-{connection.ingress_service_id}",
            connection.auth_name,
            first_outbound,
        )

        for index, hop in enumerate(hops):
            credential = hop_credentials[index]
            direction = hop.adjacency_direction
            direction_map[direction.id] = direction
            source_node_id = hop.from_node_id
            target_node_id = hop.to_node_id
            nodes.update((source_node_id, target_node_id))
            outbound_tag = _outbound_tag(route.number, credential)
            outbounds.setdefault(source_node_id, {})[outbound_tag] = CompiledLinkOutbound(
                tag=outbound_tag,
                direction_id=direction.id,
                transport=direction.transport,
                target_host=direction.to_node.public_host,
                target_port=direction.listen_port,
                password=credential.password,
                settings=dict(direction.settings or {}),
            )
            inbound_users.setdefault(target_node_id, {}).setdefault(direction.id, {})[
                credential.auth_name
            ] = CompiledLinkUser(credential.auth_name, credential.password)

            next_outbound = (
                _outbound_tag(route.number, hop_credentials[index + 1])
                if index + 1 < len(hops)
                else "direct"
            )
            _add_rule(
                rules,
                target_node_id,
                f"overlay-in-{direction.id}",
                credential.auth_name,
                next_outbound,
            )

    intents = {}
    for node_id in sorted(nodes):
        node_inbounds = []
        for direction_id, users in sorted(inbound_users.get(node_id, {}).items()):
            direction = direction_map[direction_id]
            node_inbounds.append(
                CompiledLinkInbound(
                    direction_id=direction_id,
                    transport=direction.transport,
                    listen_port=direction.listen_port,
                    settings=dict(direction.settings or {}),
                    users=tuple(users[name] for name in sorted(users)),
                )
            )
        intents[node_id] = CompiledNodeIntent(
            node_id=node_id,
            link_inbounds=tuple(node_inbounds),
            link_outbounds=tuple(outbounds.get(node_id, {}).values()),
            route_rules=tuple(rules.get(node_id, {}).values()),
        )
    return intents


def internal_only(intent: CompiledNodeIntent) -> CompiledNodeIntent:
    return CompiledNodeIntent(
        node_id=intent.node_id,
        link_inbounds=intent.link_inbounds,
        link_outbounds=intent.link_outbounds,
        route_rules=tuple(
            rule for rule in intent.route_rules if rule.inbound_tag.startswith("overlay-in-")
        ),
    )


def with_public_routes_blocked(intent: CompiledNodeIntent) -> CompiledNodeIntent:
    return CompiledNodeIntent(
        node_id=intent.node_id,
        link_inbounds=intent.link_inbounds,
        link_outbounds=intent.link_outbounds,
        route_rules=tuple(
            CompiledRouteRule(
                inbound_tag=rule.inbound_tag,
                auth_name=rule.auth_name,
                outbound_tag=(
                    "block" if rule.inbound_tag.startswith("public-") else rule.outbound_tag
                ),
            )
            for rule in intent.route_rules
        ),
    )


def merge_intents(
    primary: CompiledNodeIntent,
    additional: CompiledNodeIntent,
) -> CompiledNodeIntent:
    if primary.node_id != additional.node_id:
        raise ValueError("Cannot merge intents for different nodes")
    inbound_map = {item.direction_id: item for item in primary.link_inbounds}
    for inbound in additional.link_inbounds:
        existing = inbound_map.get(inbound.direction_id)
        if existing is None:
            inbound_map[inbound.direction_id] = inbound
            continue
        if (existing.transport, existing.listen_port, existing.settings) != (
            inbound.transport,
            inbound.listen_port,
            inbound.settings,
        ):
            raise ValueError(
                f"Direction {inbound.direction_id} changed transport, port or settings during rollout"
            )
        users = {user.auth_name: user for user in existing.users}
        users.update({user.auth_name: user for user in inbound.users})
        inbound_map[inbound.direction_id] = CompiledLinkInbound(
            direction_id=inbound.direction_id,
            transport=inbound.transport,
            listen_port=inbound.listen_port,
            settings=inbound.settings,
            users=tuple(users[name] for name in sorted(users)),
        )

    outbound_map = {item.tag: item for item in primary.link_outbounds}
    outbound_map.update({item.tag: item for item in additional.link_outbounds})
    rule_map = {(item.inbound_tag, item.auth_name): item for item in primary.route_rules}
    for rule in additional.route_rules:
        key = (rule.inbound_tag, rule.auth_name)
        existing = rule_map.get(key)
        if existing and existing.outbound_tag != rule.outbound_tag:
            raise ValueError(f"Conflicting rollout rule for {rule.inbound_tag}/{rule.auth_name}")
        rule_map[key] = rule
    return CompiledNodeIntent(
        node_id=primary.node_id,
        link_inbounds=tuple(inbound_map[key] for key in sorted(inbound_map)),
        link_outbounds=tuple(outbound_map[key] for key in sorted(outbound_map)),
        route_rules=tuple(rule_map[key] for key in sorted(rule_map)),
    )


def _add_rule(rules, node_id, inbound_tag, auth_name, outbound_tag):
    key = (inbound_tag, auth_name)
    node_rules = rules.setdefault(node_id, {})
    existing = node_rules.get(key)
    if existing and existing.outbound_tag != outbound_tag:
        raise ValueError(
            f"Ambiguous route for {inbound_tag}/{auth_name}: "
            f"{existing.outbound_tag} and {outbound_tag}"
        )
    node_rules[key] = CompiledRouteRule(inbound_tag, auth_name, outbound_tag)


def _outbound_tag(route_number, credential):
    return (
        f"overlay-r{route_number}-e{credential.egress_service_id}"
        f"-p{credential.routing_policy_id}-d{credential.adjacency_direction_id}"
    )
