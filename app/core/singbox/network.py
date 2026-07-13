from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.singbox.routing import (
    ComputedPath,
    DirectedEdge,
    NoRoute,
    RoutingPolicy,
    compute_path,
    compute_paths,
)
from app.core.singbox.routing.compiler import ensure_route_credentials
from app.db.models import (
    SingBoxAdjacency,
    SingBoxAdjacencyDirection,
    SingBoxComputedPath,
    SingBoxComputedPathHop,
    SingBoxEgressService,
    SingBoxIngressObservation,
    SingBoxIngressService,
    SingBoxLinkStateObservation,
    SingBoxNode,
    SingBoxNodeAddress,
    SingBoxNodeRouteRevision,
    SingBoxNodeStateSession,
    SingBoxRouteRevision,
    SingBoxRoutingPolicy,
    SingBoxTopologyRevision,
    SingBoxUserConnection,
)
from app.models.singbox import (
    SingBoxAdjacencyDirectionResponse,
    SingBoxAdjacencyWrite,
    SingBoxAdjacencyResponse,
    SingBoxEgressServiceWrite,
    SingBoxEgressServiceResponse,
    SingBoxConnectionRouteResponse,
    SingBoxIngressServiceResponse,
    SingBoxIngressObservationReport,
    SingBoxIngressServiceWrite,
    SingBoxNetworkApplyResponse,
    SingBoxNetworkDraft,
    SingBoxNetworkValidationIssue,
    SingBoxNetworkValidationResponse,
    SingBoxNetworkWorkspaceResponse,
    SingBoxNodeAddressResponse,
    SingBoxPathHopResponse,
    SingBoxPathCandidateResponse,
    SingBoxRoutingPolicyResponse,
    SingBoxRoutingPolicyWrite,
    SingBoxLinkObservationReport,
    SingBoxNodeCapabilities,
    SingBoxNodeStateSessionRequest,
    SingBoxProbeInstruction,
)

ROUTING_HELLO_INTERVAL_SECONDS = 5
ROUTING_DEAD_INTERVAL_SECONDS = 30


@dataclass(frozen=True)
class NodeStateSessionDecision:
    epoch: int
    accepted_sequence: int
    expires_at: datetime
    accept_reports: bool
    lease_token: str | None = None


def reconcile_state_session(
    db: Session,
    node: SingBoxNode,
    request: SingBoxNodeStateSessionRequest | None,
) -> NodeStateSessionDecision | None:
    """Establish or advance the single active link-state stream for a node."""
    if request is None:
        return None

    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=ROUTING_DEAD_INTERVAL_SECONDS)
    session = node.state_session
    supplied_lease_valid = bool(
        session
        and request.lease_token
        and secrets.compare_digest(
            session.lease_token_hash,
            hashlib.sha256(request.lease_token.encode()).hexdigest(),
        )
    )
    current_session = bool(
        session
        and session.status == "active"
        and session.instance_id == request.instance_id
        and request.epoch == session.epoch
        and supplied_lease_valid
        and session.expires_at > now
    )
    if current_session:
        sequence = request.snapshot_sequence
        if sequence is None:
            raise ValueError("An active state session requires snapshot_sequence")
        accepted = sequence > session.last_sequence
        if accepted:
            session.last_sequence = sequence
        session.last_seen_at = now
        session.expires_at = expires_at
        return NodeStateSessionDecision(
            epoch=session.epoch,
            accepted_sequence=session.last_sequence,
            expires_at=session.expires_at,
            accept_reports=accepted,
        )

    if session and session.expires_at > now and session.instance_id != request.instance_id:
        raise ValueError(
            "Another agent instance holds the active node state lease; "
            "wait for its dead interval before taking over"
        )
    if session and request.epoch is not None and session.expires_at > now:
        raise ValueError("Node state session is stale or has an invalid lease")

    lease_token = secrets.token_urlsafe(32)
    epoch = (session.epoch if session else 0) + 1
    if session is None:
        session = SingBoxNodeStateSession(node_id=node.id)
        node.state_session = session
        db.add(session)
    session.epoch = epoch
    session.instance_id = request.instance_id
    session.lease_token_hash = hashlib.sha256(lease_token.encode()).hexdigest()
    session.last_sequence = 0
    session.status = "active"
    session.issued_at = now
    session.last_seen_at = now
    session.expires_at = expires_at
    db.flush()
    return NodeStateSessionDecision(
        epoch=epoch,
        accepted_sequence=0,
        expires_at=expires_at,
        accept_reports=False,
        lease_token=lease_token,
    )


def get_workspace(db: Session) -> SingBoxNetworkWorkspaceResponse:
    nodes = db.query(SingBoxNode).order_by(SingBoxNode.id).all()
    addresses = db.query(SingBoxNodeAddress).order_by(SingBoxNodeAddress.id).all()
    ingresses = db.query(SingBoxIngressService).order_by(SingBoxIngressService.id).all()
    egresses = db.query(SingBoxEgressService).order_by(SingBoxEgressService.id).all()
    adjacencies = db.query(SingBoxAdjacency).order_by(SingBoxAdjacency.id).all()
    policies = db.query(SingBoxRoutingPolicy).order_by(SingBoxRoutingPolicy.id).all()
    return SingBoxNetworkWorkspaceResponse(
        topology_revision=_current_topology_number(db),
        nodes=nodes,
        addresses=[SingBoxNodeAddressResponse.model_validate(address) for address in addresses],
        ingresses=[_ingress_response(ingress) for ingress in ingresses],
        egresses=[_egress_response(egress) for egress in egresses],
        adjacencies=[_adjacency_response(adjacency) for adjacency in adjacencies],
        routing_policies=[_policy_response(policy) for policy in policies],
    )


def get_routing_status(db: Session) -> dict:
    topology = (
        db.query(SingBoxTopologyRevision)
        .order_by(SingBoxTopologyRevision.number.desc())
        .first()
    )
    route = db.query(SingBoxRouteRevision).order_by(SingBoxRouteRevision.number.desc()).first()
    return {
        "topology_revision": topology.number if topology else 0,
        "route_revision": route.number if route else 0,
        "status": route.status if route else "legacy",
        "reachable_connections": (
            db.query(SingBoxComputedPath)
            .filter(
                SingBoxComputedPath.route_revision_id == route.id,
                SingBoxComputedPath.status == "reachable",
            )
            .count()
            if route
            else 0
        ),
        "unreachable_connections": (
            db.query(SingBoxComputedPath)
            .filter(
                SingBoxComputedPath.route_revision_id == route.id,
                SingBoxComputedPath.status != "reachable",
            )
            .count()
            if route
            else 0
        ),
    }


def get_connection_route(db: Session, connection_id: int) -> SingBoxConnectionRouteResponse | None:
    connection = db.query(SingBoxUserConnection).filter(SingBoxUserConnection.id == connection_id).first()
    if connection is None:
        return None
    path = (
        db.query(SingBoxComputedPath)
        .join(SingBoxRouteRevision)
        .filter(SingBoxComputedPath.connection_id == connection_id)
        .order_by(SingBoxRouteRevision.number.desc())
        .first()
    )
    if path is None:
        return SingBoxConnectionRouteResponse(
            connection_id=connection_id,
            status="not_computed",
            reason="No route revision has been computed for this Connection",
        )
    route = path.route_revision
    candidates = _connection_candidates(db, connection, path)
    return SingBoxConnectionRouteResponse(
        connection_id=connection_id,
        status=path.status,
        topology_revision=route.topology_revision.number,
        route_revision=route.number,
        total_cost=path.total_cost,
        hop_count=path.hop_count,
        reason=(
            (
                f"Selected lowest cost path ({path.total_cost}); "
                "ties prefer fewer hops then stable edge IDs"
            )
            if path.status == "reachable" and path.reason == "Lowest cost eligible path"
            else path.reason
        ),
        hops=[
            SingBoxPathHopResponse(
                position=hop.position,
                adjacency_direction_id=hop.adjacency_direction_id,
                from_node_id=hop.from_node_id,
                from_node_name=hop.from_node.name,
                to_node_id=hop.to_node_id,
                to_node_name=hop.to_node.name,
                transport=hop.adjacency_direction.transport,
                admin_cost=hop.adjacency_direction.admin_cost,
            )
            for hop in sorted(path.hops, key=lambda item: item.position)
        ],
        candidates=candidates,
    )


def get_probe_instructions(db: Session, node_id: int) -> list[SingBoxProbeInstruction]:
    directions = (
        db.query(SingBoxAdjacencyDirection)
        .filter(
            SingBoxAdjacencyDirection.from_node_id == node_id,
            SingBoxAdjacencyDirection.enabled.is_(True),
        )
        .order_by(SingBoxAdjacencyDirection.id)
        .all()
    )
    return [
        SingBoxProbeInstruction(
            adjacency_direction_id=direction.id,
            resource_generation=direction.generation,
            transport=direction.transport,
            server=direction.to_node.public_host,
            server_port=direction.listen_port,
            password=direction.probe_password,
            server_name=direction.to_node.public_host,
            settings=direction.settings or {},
        )
        for direction in directions
        if direction.adjacency.enabled
    ]


def get_ingress_generations(db: Session, node_id: int) -> dict[str, int]:
    return {
        str(ingress.id): ingress.generation
        for ingress in (
            db.query(SingBoxIngressService)
            .filter(SingBoxIngressService.node_id == node_id)
            .order_by(SingBoxIngressService.id)
            .all()
        )
    }


def _connection_candidates(db, connection, selected_path):
    ingress = connection.ingress_service
    egress = connection.egress_service
    policy_row = connection.routing_policy
    if not ingress or not egress or not policy_row:
        return []
    now = datetime.utcnow()
    edges = []
    for direction in db.query(SingBoxAdjacencyDirection).all():
        edges.append(
            DirectedEdge(
                id=direction.id,
                from_node_id=direction.from_node_id,
                to_node_id=direction.to_node_id,
                admin_cost=direction.admin_cost,
                enabled=direction.enabled,
                oper_state=_effective_direction_state(direction, now),
            )
        )
    policy = RoutingPolicy(
        max_hops=policy_row.max_hops,
        allow_degraded=policy_row.allow_degraded,
        required_node_ids=frozenset(policy_row.required_node_ids or []),
        avoided_node_ids=frozenset(policy_row.avoided_node_ids or []),
    )
    candidates = compute_paths(edges, ingress.node_id, egress.node_id, policy, limit=3)
    node_names = {
        node.id: node.name
        for node in db.query(SingBoxNode).filter(
            SingBoxNode.id.in_({node_id for candidate in candidates for node_id in candidate.node_ids})
        )
    }
    selected_edges = tuple(hop.adjacency_direction_id for hop in sorted(selected_path.hops, key=lambda item: item.position))
    return [
        SingBoxPathCandidateResponse(
            node_ids=list(candidate.node_ids),
            node_names=[node_names[node_id] for node_id in candidate.node_ids],
            adjacency_direction_ids=list(candidate.edge_ids),
            total_cost=candidate.total_cost,
            hop_count=candidate.hop_count,
            selected=candidate.edge_ids == selected_edges,
        )
        for candidate in candidates
    ]


def validate_draft(db: Session, draft: SingBoxNetworkDraft) -> SingBoxNetworkValidationResponse:
    issues: list[SingBoxNetworkValidationIssue] = []
    current_revision = _current_topology_number(db)
    if draft.base_topology_revision != current_revision:
        issues.append(
            _issue(
                "topology",
                None,
                "base_topology_revision",
                "stale_revision",
                f"Draft is based on revision {draft.base_topology_revision}; current revision is {current_revision}",
            )
        )
    elif current_revision and _draft_payload(draft) == _current_draft_payload(db):
        issues.append(
            _issue(
                "topology",
                None,
                None,
                "unchanged_draft",
                "Draft does not change the current topology",
            )
        )
    if _route_rollout_in_progress(db):
        issues.append(
            _issue(
                "topology",
                None,
                None,
                "route_rollout_in_progress",
                "Wait for the current route revision to finish publishing before saving another revision",
            )
        )

    nodes = {node.id: node for node in db.query(SingBoxNode).all()}
    addresses = {address.id: address for address in db.query(SingBoxNodeAddress).all()}
    current_directions = {
        direction.id: direction
        for direction in db.query(SingBoxAdjacencyDirection).all()
    }
    _validate_unique_ids("ingress", draft.ingresses, issues)
    _validate_unique_ids("egress", draft.egresses, issues)
    _validate_unique_ids("adjacency", draft.adjacencies, issues)
    _validate_unique_ids("routing_policy", draft.routing_policies, issues)

    occupied: dict[tuple[int, str, int], tuple[str, int | None]] = {}
    for ingress in draft.ingresses:
        if ingress.node_id not in nodes:
            issues.append(_issue("ingress", ingress.id, "node_id", "missing_node", "Ingress server does not exist"))
        if ingress.advertised_address_id is not None:
            address = addresses.get(ingress.advertised_address_id)
            if address is None or address.node_id != ingress.node_id or not address.enabled:
                issues.append(
                    _issue(
                        "ingress",
                        ingress.id,
                        "advertised_address_id",
                        "invalid_address",
                        "Advertised address must be enabled and belong to the ingress server",
                    )
                )
        if ingress.enabled:
            for family in _transport_families(ingress.protocol):
                _claim_port(occupied, ingress.node_id, family, ingress.listen_port, "ingress", ingress.id, issues)

    for egress in draft.egresses:
        if egress.node_id not in nodes:
            issues.append(_issue("egress", egress.id, "node_id", "missing_node", "Egress server does not exist"))

    adjacency_pairs: set[tuple[int, int]] = set()
    for adjacency in draft.adjacencies:
        pair = tuple(sorted((adjacency.node_a_id, adjacency.node_b_id)))
        if pair in adjacency_pairs:
            issues.append(_issue("adjacency", adjacency.id, None, "duplicate_pair", "Server pair already has an adjacency"))
        adjacency_pairs.add(pair)
        if any(node_id not in nodes for node_id in pair):
            issues.append(_issue("adjacency", adjacency.id, None, "missing_node", "Adjacency server does not exist"))
        if not adjacency.enabled:
            continue
        for direction in adjacency.directions:
            current_direction = current_directions.get(direction.id)
            if (
                draft.base_topology_revision == current_revision
                and current_revision
                and current_direction is not None
                and current_direction.enabled
                and direction.enabled
                and (
                    current_direction.transport != direction.transport
                    or current_direction.listen_port != direction.listen_port
                    or (current_direction.settings or {}) != direction.settings
                )
            ):
                issues.append(
                    _issue(
                        "direction",
                        direction.id,
                        None,
                        "maintenance_rollout_required",
                        "Disable and apply this direction before changing its transport, port or profile",
                    )
                )
            if direction.enabled:
                family = "udp" if direction.transport == "hysteria2" else "tcp"
                _claim_port(
                    occupied,
                    direction.to_node_id,
                    family,
                    direction.listen_port,
                    "direction",
                    direction.id,
                    issues,
                )

    valid_node_ids = set(nodes)
    for policy in draft.routing_policies:
        unknown = (set(policy.required_node_ids) | set(policy.avoided_node_ids)) - valid_node_ids
        if unknown:
            issues.append(
                _issue(
                    "routing_policy",
                    policy.id,
                    None,
                    "missing_node",
                    f"Routing policy references missing nodes: {sorted(unknown)}",
                )
            )

    draft_ingress_ids = {item.id for item in draft.ingresses if item.id is not None}
    draft_egress_ids = {item.id for item in draft.egresses if item.id is not None}
    draft_policy_ids = {item.id for item in draft.routing_policies if item.id is not None}
    connections = db.query(SingBoxUserConnection).filter(SingBoxUserConnection.enabled.is_(True)).all()
    reachable = 0
    for connection in connections:
        if connection.ingress_service_id not in draft_ingress_ids:
            issues.append(
                _issue(
                    "connection",
                    connection.id,
                    "ingress_service_id",
                    "missing_ingress",
                    "Connection ingress is absent from the draft",
                )
            )
            continue
        if connection.egress_service_id not in draft_egress_ids:
            issues.append(
                _issue(
                    "connection",
                    connection.id,
                    "egress_service_id",
                    "missing_egress",
                    "Connection egress is absent from the draft",
                )
            )
            continue
        if connection.routing_policy_id not in draft_policy_ids:
            issues.append(
                _issue(
                    "connection",
                    connection.id,
                    "routing_policy_id",
                    "missing_policy",
                    "Connection routing policy is absent from the draft",
                )
            )
            continue
        reachable += int(_draft_connection_reachable(connection, draft))

    return SingBoxNetworkValidationResponse(
        valid=not issues,
        issues=issues,
        affected_connections=len(connections),
        reachable_connections=reachable,
    )


def apply_draft(
    db: Session,
    draft: SingBoxNetworkDraft,
    *,
    actor: str | None,
) -> SingBoxNetworkApplyResponse:
    validation = validate_draft(db, draft)
    if not validation.valid:
        raise ValueError(validation)

    _apply_policies(db, draft)
    _apply_ingresses(db, draft)
    _apply_egresses(db, draft)
    _apply_adjacencies(db, draft)
    db.flush()

    snapshot = _snapshot(db)
    topology_number = _current_topology_number(db) + 1
    topology = SingBoxTopologyRevision(
        number=topology_number,
        status="applied",
        content_hash=_content_hash(snapshot),
        snapshot=snapshot,
        created_by=actor,
        created_at=datetime.utcnow(),
    )
    db.add(topology)
    db.flush()
    route, reachable, degraded = _create_route_revision(db, topology)
    db.commit()
    return SingBoxNetworkApplyResponse(
        topology_revision=topology.number,
        route_revision=route.number,
        status=route.status,
        reachable_connections=reachable,
        degraded_connections=degraded,
    )


def record_link_state(
    db: Session,
    node: SingBoxNode,
    capabilities: SingBoxNodeCapabilities | None,
    reports: list[SingBoxLinkObservationReport],
    *,
    state_session: NodeStateSessionDecision | None = None,
) -> dict:
    if capabilities is not None:
        node.capabilities = capabilities.model_dump(mode="json")
    now = datetime.utcnow()
    # A valid sync is the overlay equivalent of receiving an OSPF Hello.
    node.last_seen_at = now
    effective_changed = False
    expired = (
        db.query(SingBoxLinkStateObservation)
        .filter(
            SingBoxLinkStateObservation.hold_expires_at.is_not(None),
            SingBoxLinkStateObservation.hold_expires_at <= now,
            SingBoxLinkStateObservation.oper_state.in_(("up", "degraded")),
        )
        .all()
    )
    for observation in expired:
        observation.oper_state = "down"
        observation.message = "Hold timer expired"
        effective_changed = True

    accepted = 0
    stale = 0
    for report in reports:
        direction = (
            db.query(SingBoxAdjacencyDirection)
            .filter(SingBoxAdjacencyDirection.id == report.adjacency_direction_id)
            .first()
        )
        if direction is None:
            raise ValueError(f"Adjacency direction {report.adjacency_direction_id} does not exist")
        if direction.from_node_id != node.id:
            raise ValueError(f"Node {node.name} cannot report direction {direction.id}")
        observation = direction.observation
        if state_session and report.resource_generation != direction.generation:
            stale += 1
            continue
        if state_session is None and observation and report.sequence <= observation.sequence:
            if not observation.hold_expires_at or observation.hold_expires_at > now:
                stale += 1
                continue
        if (
            observation
            and report.state == "down"
            and observation.oper_state in ("up", "degraded")
            and (state_session is None or observation.resource_generation == direction.generation)
            and observation.hold_expires_at
            and observation.hold_expires_at > now
        ):
            observation.sequence = report.sequence
            observation.resource_generation = direction.generation
            observation.session_epoch = state_session.epoch if state_session else 0
            observation.snapshot_sequence = (
                state_session.accepted_sequence if state_session else report.sequence
            )
            observation.rtt_ms = report.rtt_ms
            observation.loss_ppm = report.loss_ppm
            observation.bandwidth_mbps = report.bandwidth_mbps
            observation.observed_at = now
            observation.message = "Probe failed; holding the last eligible state until the hold timer expires"
            accepted += 1
            continue
        old_eligible = bool(
            observation
            and observation.oper_state == "up"
            and (state_session is None or observation.resource_generation == direction.generation)
        )
        if observation is None:
            observation = SingBoxLinkStateObservation(
                adjacency_direction_id=direction.id,
                reporting_node_id=node.id,
            )
            direction.observation = observation
            db.add(observation)
        observation.reporting_node_id = node.id
        observation.sequence = report.sequence
        observation.resource_generation = direction.generation
        observation.session_epoch = state_session.epoch if state_session else 0
        observation.snapshot_sequence = (
            state_session.accepted_sequence if state_session else report.sequence
        )
        observation.oper_state = report.state
        observation.rtt_ms = report.rtt_ms
        observation.loss_ppm = report.loss_ppm
        observation.bandwidth_mbps = report.bandwidth_mbps
        observation.observed_at = now
        observation.hold_expires_at = now + timedelta(seconds=report.hold_seconds)
        observation.message = report.message
        effective_changed = effective_changed or old_eligible != (report.state == "up")
        accepted += 1

    node.updated_at = now
    db.flush()
    dead_node_ids = {
        candidate.id
        for candidate in db.query(SingBoxNode).all()
        if _routing_node_stale(candidate, now)
    }
    if dead_node_ids:
        from app.core.singbox.routing import publication

        publication.exclude_dead_participants(db, dead_node_ids)
    route_number = None
    if not _route_rollout_in_progress(db) and _routing_state_changed(db, now):
        route = _recompute_after_link_state(db, actor=f"node:{node.name}")
        route_number = route.number
    db.commit()
    return {
        "accepted": accepted,
        "stale": stale,
        "effective_changed": effective_changed,
        "route_revision": route_number,
    }


def record_ingress_state(
    db: Session,
    node: SingBoxNode,
    reports: list[SingBoxIngressObservationReport],
    *,
    config_is_current: bool,
    state_session: NodeStateSessionDecision | None = None,
) -> dict:
    if not config_is_current:
        return {"accepted": 0, "stale": 0, "ignored": len(reports)}

    now = datetime.utcnow()
    accepted = 0
    stale = 0
    for report in reports:
        ingress = (
            db.query(SingBoxIngressService)
            .filter(SingBoxIngressService.id == report.ingress_service_id)
            .first()
        )
        if ingress is None:
            raise ValueError(f"Ingress service {report.ingress_service_id} does not exist")
        if ingress.node_id != node.id:
            raise ValueError(f"Node {node.name} cannot report ingress service {ingress.id}")
        observation = ingress.observation
        if state_session and report.resource_generation != ingress.generation:
            stale += 1
            continue
        if state_session is None and observation and report.sequence <= observation.sequence:
            if not observation.hold_expires_at or observation.hold_expires_at > now:
                stale += 1
                continue
        if observation is None:
            observation = SingBoxIngressObservation(
                ingress_service_id=ingress.id,
                reporting_node_id=node.id,
            )
            ingress.observation = observation
            db.add(observation)
        observation.reporting_node_id = node.id
        observation.sequence = report.sequence
        observation.resource_generation = ingress.generation
        observation.session_epoch = state_session.epoch if state_session else 0
        observation.snapshot_sequence = (
            state_session.accepted_sequence if state_session else report.sequence
        )
        observation.oper_state = report.state
        observation.observed_at = now
        observation.hold_expires_at = now + timedelta(seconds=report.hold_seconds)
        observation.message = report.message
        accepted += 1

    node.updated_at = now
    db.commit()
    return {"accepted": accepted, "stale": stale, "ignored": 0}


def _recompute_after_link_state(db: Session, *, actor: str) -> SingBoxRouteRevision:
    if _route_rollout_in_progress(db):
        raise RuntimeError("Cannot run SPF while a route revision is being published")
    previous_route = (
        db.query(SingBoxRouteRevision)
        .order_by(SingBoxRouteRevision.number.desc())
        .first()
    )
    snapshot = _snapshot(db)
    topology = SingBoxTopologyRevision(
        number=_current_topology_number(db) + 1,
        status="observed",
        content_hash=_content_hash(snapshot),
        snapshot=snapshot,
        created_by=actor,
        created_at=datetime.utcnow(),
    )
    db.add(topology)
    db.flush()
    route, _, _ = _create_route_revision(
        db,
        topology,
        previous_route=previous_route,
        link_state_change=True,
    )
    return route


def _create_route_revision(db, topology, *, previous_route=None, link_state_change=False):
    route = SingBoxRouteRevision(
        number=_current_route_number(db) + 1,
        topology_revision_id=topology.id,
        status="staged",
        created_at=datetime.utcnow(),
    )
    db.add(route)
    db.flush()
    reachable, degraded = _compute_and_store_paths(
        db,
        route,
        previous_route=previous_route,
        link_state_change=link_state_change,
    )
    ensure_route_credentials(db, route)
    return route, reachable, degraded


def _apply_policies(db: Session, draft: SingBoxNetworkDraft) -> None:
    existing = {item.id: item for item in db.query(SingBoxRoutingPolicy).all()}
    kept = set()
    for item in draft.routing_policies:
        row = existing.get(item.id) if item.id is not None else None
        if row is None:
            row = SingBoxRoutingPolicy()
            db.add(row)
        else:
            kept.add(row.id)
        for field in (
            "name",
            "metric_mode",
            "max_hops",
            "allow_degraded",
            "failover",
            "required_node_ids",
            "avoided_node_ids",
        ):
            setattr(row, field, getattr(item, field))
        row.updated_at = datetime.utcnow()
    for row_id, row in existing.items():
        if row_id not in kept and not _policy_referenced(db, row_id):
            db.delete(row)


def _apply_ingresses(db: Session, draft: SingBoxNetworkDraft) -> None:
    existing = {item.id: item for item in db.query(SingBoxIngressService).all()}
    kept = set()
    track_generations = _current_topology_number(db) > 0
    generation_fields = (
        "node_id",
        "protocol",
        "listen_port",
        "enabled",
        "tls_mode",
        "tls_profile",
        "protocol_profile",
    )
    for item in draft.ingresses:
        row = existing.get(item.id) if item.id is not None else None
        if row is None:
            row = SingBoxIngressService(generation=1)
            db.add(row)
        else:
            kept.add(row.id)
            if track_generations and any(
                (getattr(row, field) or {} if field.endswith("_profile") else getattr(row, field))
                != getattr(item, field)
                for field in generation_fields
            ):
                row.generation = (row.generation or 1) + 1
        for field in (
            "node_id",
            "advertised_address_id",
            "name",
            "protocol",
            "listen_port",
            "enabled",
            "tls_mode",
            "tls_profile",
            "protocol_profile",
        ):
            setattr(row, field, getattr(item, field))
        row.updated_at = datetime.utcnow()
    for row_id, row in existing.items():
        if row_id not in kept:
            if row.enabled:
                row.enabled = False
                row.generation = (row.generation or 1) + 1


def _apply_egresses(db: Session, draft: SingBoxNetworkDraft) -> None:
    existing = {item.id: item for item in db.query(SingBoxEgressService).all()}
    kept = set()
    for item in draft.egresses:
        row = existing.get(item.id) if item.id is not None else None
        if row is None:
            row = SingBoxEgressService()
            db.add(row)
        else:
            kept.add(row.id)
        for field in ("node_id", "name", "kind", "enabled", "settings"):
            setattr(row, field, getattr(item, field))
        row.updated_at = datetime.utcnow()
    for row_id, row in existing.items():
        if row_id not in kept:
            row.enabled = False


def _apply_adjacencies(db: Session, draft: SingBoxNetworkDraft) -> None:
    existing = {item.id: item for item in db.query(SingBoxAdjacency).all()}
    existing_directions = {item.id: item for item in db.query(SingBoxAdjacencyDirection).all()}
    kept_adjacencies = set()
    kept_directions = set()
    track_generations = _current_topology_number(db) > 0
    for item in draft.adjacencies:
        adjacency = existing.get(item.id) if item.id is not None else None
        if adjacency is None:
            adjacency = SingBoxAdjacency()
            db.add(adjacency)
            parent_generation_changed = False
        else:
            kept_adjacencies.add(adjacency.id)
            parent_generation_changed = any(
                getattr(adjacency, field) != getattr(item, field)
                for field in ("node_a_id", "node_b_id", "enabled")
            )
        adjacency.node_a_id = item.node_a_id
        adjacency.node_b_id = item.node_b_id
        adjacency.name = item.name
        adjacency.enabled = item.enabled
        adjacency.updated_at = datetime.utcnow()
        db.flush()
        for direction_item in item.directions:
            direction = existing_directions.get(direction_item.id) if direction_item.id is not None else None
            if direction is None:
                direction = SingBoxAdjacencyDirection(adjacency_id=adjacency.id, generation=1)
                db.add(direction)
            else:
                kept_directions.add(direction.id)
                direction.adjacency_id = adjacency.id
                generation_fields = (
                    "from_node_id",
                    "to_node_id",
                    "enabled",
                    "transport",
                    "listen_port",
                    "settings",
                )
                direction_changed = any(
                    (getattr(direction, field) or {} if field == "settings" else getattr(direction, field))
                    != getattr(direction_item, field)
                    for field in generation_fields
                )
                if track_generations and (parent_generation_changed or direction_changed):
                    direction.generation = (direction.generation or 1) + 1
            for field in (
                "from_node_id",
                "to_node_id",
                "enabled",
                "transport",
                "listen_port",
                "admin_cost",
                "settings",
            ):
                setattr(direction, field, getattr(direction_item, field))
            direction.updated_at = datetime.utcnow()
    for row_id, row in existing_directions.items():
        if row_id not in kept_directions:
            if row.enabled:
                row.enabled = False
                row.generation = (row.generation or 1) + 1
    for row_id, row in existing.items():
        if row_id not in kept_adjacencies:
            row.enabled = False


def _compute_and_store_paths(
    db: Session,
    route: SingBoxRouteRevision,
    *,
    previous_route: SingBoxRouteRevision | None = None,
    link_state_change: bool = False,
) -> tuple[int, int]:
    directions = db.query(SingBoxAdjacencyDirection).all()
    now = datetime.utcnow()
    edges = []
    direction_by_id = {}
    for direction in directions:
        direction_by_id[direction.id] = direction
        edges.append(
            DirectedEdge(
                id=direction.id,
                from_node_id=direction.from_node_id,
                to_node_id=direction.to_node_id,
                admin_cost=direction.admin_cost,
                enabled=direction.enabled,
                oper_state=_effective_direction_state(direction, now),
            )
        )

    reachable = 0
    degraded = 0
    node_ids = (
        set()
        if link_state_change
        else {node_id for (node_id,) in db.query(SingBoxNode.id).all()}
    )
    connections = db.query(SingBoxUserConnection).filter(SingBoxUserConnection.enabled.is_(True)).all()
    previous_paths = {
        path.connection_id: path
        for path in (previous_route.computed_paths if previous_route is not None else [])
    }
    for connection in connections:
        ingress = connection.ingress_service
        egress = connection.egress_service
        policy_row = connection.routing_policy
        if not ingress or not ingress.enabled or not egress or not egress.enabled or not policy_row:
            _store_no_route(db, route, connection, "Connection references a disabled or missing service")
            degraded += 1
            continue
        policy = RoutingPolicy(
            max_hops=policy_row.max_hops,
            allow_degraded=policy_row.allow_degraded,
            required_node_ids=frozenset(policy_row.required_node_ids or []),
            avoided_node_ids=frozenset(policy_row.avoided_node_ids or []),
        )
        if link_state_change and not policy_row.failover:
            result = _preserved_path(
                previous_paths.get(connection.id),
                edges,
                ingress.node_id,
                egress.node_id,
                policy,
            )
            if result is None:
                _store_no_route(
                    db,
                    route,
                    connection,
                    "Selected path failed and automatic failover is disabled",
                )
                degraded += 1
                continue
        else:
            result = compute_path(edges, ingress.node_id, egress.node_id, policy)
        if isinstance(result, NoRoute):
            _store_no_route(db, route, connection, result.reason)
            degraded += 1
            continue
        path = SingBoxComputedPath(
            route_revision_id=route.id,
            connection_id=connection.id,
            total_cost=result.total_cost,
            hop_count=result.hop_count,
            status="reachable",
            reason=(
                "Preserved selected path; automatic failover disabled"
                if link_state_change and not policy_row.failover
                else "Lowest cost eligible path"
            ),
        )
        db.add(path)
        db.flush()
        node_ids.update(result.node_ids)
        for position, edge_id in enumerate(result.edge_ids):
            direction = direction_by_id[edge_id]
            db.add(
                SingBoxComputedPathHop(
                    computed_path_id=path.id,
                    position=position,
                    adjacency_direction_id=edge_id,
                    from_node_id=direction.from_node_id,
                    to_node_id=direction.to_node_id,
                )
            )
        reachable += 1
    for node_id in sorted(node_ids):
        db.add(
            SingBoxNodeRouteRevision(
                node_id=node_id,
                route_revision_id=route.id,
                state="pending",
                updated_at=datetime.utcnow(),
            )
        )
    return reachable, degraded


def _routing_node_stale(node: SingBoxNode, now: datetime) -> bool:
    if node.state_session is not None:
        return bool(
            node.state_session.status != "active"
            or node.state_session.expires_at <= now
        )
    return bool(
        node.last_seen_at
        and node.last_seen_at <= now - timedelta(seconds=ROUTING_DEAD_INTERVAL_SECONDS)
    )


def _effective_direction_state(direction: SingBoxAdjacencyDirection, now: datetime) -> str:
    if not direction.enabled or not direction.adjacency.enabled:
        return "disabled"
    if _routing_node_stale(direction.from_node, now) or _routing_node_stale(
        direction.to_node,
        now,
    ):
        return "down"
    observation = direction.observation
    if observation is None or observation.resource_generation != direction.generation:
        return "unknown"
    if observation.hold_expires_at and observation.hold_expires_at <= now:
        return "down"
    return observation.oper_state


def _routing_state_snapshot(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    nodes = db.query(SingBoxNode).order_by(SingBoxNode.id).all()
    directions = db.query(SingBoxAdjacencyDirection).order_by(SingBoxAdjacencyDirection.id).all()
    return {
        "hello_interval_seconds": ROUTING_HELLO_INTERVAL_SECONDS,
        "dead_interval_seconds": ROUTING_DEAD_INTERVAL_SECONDS,
        "nodes": {
            str(node.id): "dead" if _routing_node_stale(node, now) else "alive"
            for node in nodes
        },
        "directions": {
            str(direction.id): _effective_direction_state(direction, now)
            for direction in directions
        },
    }


def _route_rollout_in_progress(db: Session) -> bool:
    return (
        db.query(SingBoxRouteRevision)
        .filter(SingBoxRouteRevision.status.in_(("staged", "activating")))
        .first()
        is not None
    )


def _routing_state_changed(db: Session, now: datetime | None = None) -> bool:
    latest = (
        db.query(SingBoxTopologyRevision)
        .order_by(SingBoxTopologyRevision.number.desc())
        .first()
    )
    published = latest.snapshot.get("routing_state") if latest else None
    return published != _routing_state_snapshot(db, now)


def _preserved_path(previous, edges, source_node_id, target_node_id, policy):
    if previous is None or previous.status != "reachable":
        return None
    hops = sorted(previous.hops, key=lambda item: item.position)
    if len(hops) > policy.max_hops:
        return None
    expected_node_id = source_node_id
    for hop in hops:
        if hop.from_node_id != expected_node_id:
            return None
        expected_node_id = hop.to_node_id
    node_ids = (source_node_id, *(hop.to_node_id for hop in hops))
    if node_ids[-1] != target_node_id or len(set(node_ids)) != len(node_ids):
        return None
    if not policy.required_node_ids.issubset(node_ids):
        return None
    edge_by_id = {edge.id: edge for edge in edges}
    selected = []
    for hop in hops:
        edge = edge_by_id.get(hop.adjacency_direction_id)
        if edge is None or not edge.enabled:
            return None
        if edge.from_node_id in policy.avoided_node_ids or edge.to_node_id in policy.avoided_node_ids:
            return None
        if edge.oper_state != "up" and not (
            policy.allow_degraded and edge.oper_state == "degraded"
        ):
            return None
        selected.append(edge)
    return ComputedPath(
        node_ids=tuple(node_ids),
        edge_ids=tuple(edge.id for edge in selected),
        total_cost=sum(edge.admin_cost for edge in selected),
    )


def _store_no_route(db, route, connection, reason):
    db.add(
        SingBoxComputedPath(
            route_revision_id=route.id,
            connection_id=connection.id,
            status="unreachable",
            reason=reason,
        )
    )


def _draft_connection_reachable(connection, draft: SingBoxNetworkDraft) -> bool:
    ingress = next((item for item in draft.ingresses if item.id == connection.ingress_service_id), None)
    egress = next((item for item in draft.egresses if item.id == connection.egress_service_id), None)
    policy_row = next((item for item in draft.routing_policies if item.id == connection.routing_policy_id), None)
    if not ingress or not ingress.enabled or not egress or not egress.enabled or not policy_row:
        return False
    edges = [
        DirectedEdge(
            id=direction.id or _draft_edge_id(adjacency_index, direction_index),
            from_node_id=direction.from_node_id,
            to_node_id=direction.to_node_id,
            admin_cost=direction.admin_cost,
            enabled=adjacency.enabled and direction.enabled,
            oper_state="up",
        )
        for adjacency_index, adjacency in enumerate(draft.adjacencies)
        for direction_index, direction in enumerate(adjacency.directions)
    ]
    result = compute_path(
        edges,
        ingress.node_id,
        egress.node_id,
        RoutingPolicy(
            max_hops=policy_row.max_hops,
            allow_degraded=policy_row.allow_degraded,
            required_node_ids=frozenset(policy_row.required_node_ids),
            avoided_node_ids=frozenset(policy_row.avoided_node_ids),
        ),
    )
    return not isinstance(result, NoRoute)


def _snapshot(db: Session) -> dict:
    data = _current_draft_payload(db)
    data["routing_state"] = _routing_state_snapshot(db)
    return data


def _draft_payload(draft: SingBoxNetworkDraft) -> dict:
    return draft.model_dump(mode="json", exclude={"base_topology_revision"})


def _current_draft_payload(db: Session) -> dict:
    workspace = get_workspace(db)
    current = SingBoxNetworkDraft(
        base_topology_revision=workspace.topology_revision,
        ingresses=[SingBoxIngressServiceWrite.model_validate(item) for item in workspace.ingresses],
        egresses=[SingBoxEgressServiceWrite.model_validate(item) for item in workspace.egresses],
        adjacencies=[SingBoxAdjacencyWrite.model_validate(item) for item in workspace.adjacencies],
        routing_policies=[SingBoxRoutingPolicyWrite.model_validate(item) for item in workspace.routing_policies],
    )
    return _draft_payload(current)


def _content_hash(snapshot: dict) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _current_topology_number(db: Session) -> int:
    row = db.query(SingBoxTopologyRevision).order_by(SingBoxTopologyRevision.number.desc()).first()
    return row.number if row else 0


def _current_route_number(db: Session) -> int:
    row = db.query(SingBoxRouteRevision).order_by(SingBoxRouteRevision.number.desc()).first()
    return row.number if row else 0


def _ingress_response(row) -> SingBoxIngressServiceResponse:
    address = row.advertised_address
    if address is None:
        address = next((item for item in row.node.addresses if item.is_primary and item.enabled), None)
    observation = row.observation
    current_observation = (
        observation
        if observation is not None and observation.resource_generation == row.generation
        else None
    )
    now = datetime.utcnow()
    if not row.enabled:
        oper_state = "disabled"
        message = "Ingress is disabled"
    elif row.node.last_config_hash != row.node.applied_config_hash or not row.node.applied_config_hash:
        oper_state = "provisioning"
        message = "Waiting for the node to apply its desired config"
    elif current_observation is None:
        oper_state = "unknown"
        message = "No listener observation received for the current generation"
    elif current_observation.hold_expires_at and current_observation.hold_expires_at <= now:
        oper_state = "down"
        message = "Listener observation expired"
    else:
        oper_state = current_observation.oper_state
        message = current_observation.message
    return SingBoxIngressServiceResponse(
        id=row.id,
        node_id=row.node_id,
        node_name=row.node.name,
        advertised_address_id=row.advertised_address_id,
        address=address.address if address else row.node.public_host,
        name=row.name,
        protocol=row.protocol,
        listen_port=row.listen_port,
        enabled=row.enabled,
        tls_mode=row.tls_mode,
        tls_profile=row.tls_profile or {},
        protocol_profile=row.protocol_profile or {},
        oper_state=oper_state,
        observed_at=current_observation.observed_at if current_observation else None,
        hold_expires_at=current_observation.hold_expires_at if current_observation else None,
        message=message,
    )


def _egress_response(row) -> SingBoxEgressServiceResponse:
    return SingBoxEgressServiceResponse(
        id=row.id,
        node_id=row.node_id,
        node_name=row.node.name,
        name=row.name,
        kind=row.kind,
        enabled=row.enabled,
        settings=row.settings or {},
    )


def _adjacency_response(row) -> SingBoxAdjacencyResponse:
    return SingBoxAdjacencyResponse(
        id=row.id,
        node_a_id=row.node_a_id,
        node_b_id=row.node_b_id,
        name=row.name,
        enabled=row.enabled,
        directions=[_direction_response(item) for item in sorted(row.directions, key=lambda item: item.id)],
    )


def _direction_response(row) -> SingBoxAdjacencyDirectionResponse:
    observation = row.observation
    if observation is not None and observation.resource_generation != row.generation:
        observation = None
    return SingBoxAdjacencyDirectionResponse(
        id=row.id,
        from_node_id=row.from_node_id,
        to_node_id=row.to_node_id,
        enabled=row.enabled,
        transport=row.transport,
        listen_port=row.listen_port,
        admin_cost=row.admin_cost,
        settings=row.settings or {},
        oper_state=observation.oper_state if observation else "unknown",
        rtt_ms=observation.rtt_ms if observation else None,
        loss_ppm=observation.loss_ppm if observation else None,
        observed_at=observation.observed_at if observation else None,
        hold_expires_at=observation.hold_expires_at if observation else None,
        message=observation.message if observation else None,
    )


def _policy_response(row) -> SingBoxRoutingPolicyResponse:
    return SingBoxRoutingPolicyResponse(
        id=row.id,
        name=row.name,
        metric_mode=row.metric_mode,
        max_hops=row.max_hops,
        allow_degraded=row.allow_degraded,
        failover=row.failover,
        required_node_ids=row.required_node_ids or [],
        avoided_node_ids=row.avoided_node_ids or [],
    )


def _issue(object_type, object_id, field, code, message):
    return SingBoxNetworkValidationIssue(
        object_type=object_type,
        object_id=object_id,
        field=field,
        code=code,
        message=message,
    )


def _validate_unique_ids(object_type, items, issues):
    seen = set()
    for item in items:
        if item.id is None:
            continue
        if item.id in seen:
            issues.append(_issue(object_type, item.id, "id", "duplicate_id", "Object ID appears more than once"))
        seen.add(item.id)


def _claim_port(occupied, node_id, family, port, object_type, object_id, issues):
    key = (node_id, family, port)
    owner = occupied.get(key)
    if owner:
        issues.append(
            _issue(
                object_type,
                object_id,
                "listen_port",
                "port_conflict",
                f"{family.upper()} port {port} conflicts with {owner[0]} {owner[1]}",
            )
        )
    else:
        occupied[key] = (object_type, object_id)


def _transport_families(protocol):
    if protocol in {"hysteria2", "tuic"}:
        return ("udp",)
    if protocol == "shadowsocks":
        return ("tcp", "udp")
    return ("tcp",)


def _policy_referenced(db, policy_id):
    return (
        db.query(SingBoxUserConnection)
        .filter(SingBoxUserConnection.routing_policy_id == policy_id)
        .first()
        is not None
    )


def _draft_edge_id(adjacency_index: int, direction_index: int) -> int:
    return 1_000_000_000 + adjacency_index * 2 + direction_index
