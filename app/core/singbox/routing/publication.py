from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.singbox.config import config_hash
from app.core.singbox.routing.compiler import (
    compile_route_revision,
    internal_only,
    merge_intents,
    with_public_routes_blocked,
)
from app.db.models import (
    SingBoxNode,
    SingBoxNodeRouteRevision,
    SingBoxRouteRevision,
)


_DRAIN_SECONDS = 120


def desired_node_config(db: Session, node: SingBoxNode) -> tuple[dict, str, int | None, str | None]:
    from app.core.singbox import production

    rollout = _current_rollout(db)
    if rollout is None:
        config, hash_value = production.build_node_config(db, node.id)
        active = _active_route(db)
        return config, hash_value, active.number if active else None, "active" if active else None

    node_revision = _node_revision(db, node.id, rollout.id)
    if node_revision is None:
        config, hash_value = production.build_node_config(db, node.id)
        active = _active_route(db)
        return (
            config,
            hash_value,
            active.number if active else None,
            "excluded",
        )
    builder = production.build_builder(db)
    new_intent = compile_route_revision(db, rollout)[node.id]
    active = _active_route(db)
    if rollout.status == "staged":
        if active is None:
            has_legacy_links = any(
                link.enabled and (link.from_node == node.name or link.to_node == node.name)
                for link in builder.node_links or []
            )
            if has_legacy_links:
                config = builder.build_node_config(
                    node.name,
                    new_intent,
                    preserve_legacy=True,
                    include_overlay_public_rules=False,
                )
            else:
                config = builder.build_node_config(
                    node.name,
                    with_public_routes_blocked(new_intent),
                )
        else:
            current_intent = compile_route_revision(db, active)[node.id]
            config = builder.build_node_config(
                node.name,
                merge_intents(current_intent, internal_only(new_intent)),
            )
        phase = "staging"
    else:
        if active is None:
            intent = new_intent
        else:
            current_intent = compile_route_revision(db, active)[node.id]
            intent = merge_intents(new_intent, internal_only(current_intent))
        config = builder.build_node_config(node.name, intent)
        phase = "activating"

    hash_value = config_hash(config)
    if node_revision.desired_hash != hash_value or node_revision.state == "pending":
        node_revision.desired_hash = hash_value
        node_revision.state = phase
        node_revision.message = None
        node_revision.updated_at = datetime.utcnow()
        db.commit()
    return config, hash_value, rollout.number, phase


def report_applied(
    db: Session,
    node: SingBoxNode,
    config_hash_value: str,
    success: bool,
    message: str | None,
) -> tuple[int | None, str | None]:
    rollout = _current_rollout(db)
    if rollout is None:
        return None, None
    node_revision = _node_revision(db, node.id, rollout.id)
    if node_revision is None or node_revision.desired_hash != config_hash_value:
        return rollout.number, "superseded"
    if not success:
        node_revision.state = "error"
        node_revision.message = message
        rollout.status = "failed"
        db.commit()
        return rollout.number, "error"

    if rollout.status == "staged":
        node_revision.state = "staged"
        phase = "staged"
        phase = _advance_rollout(db, rollout) or phase
    elif rollout.status == "activating":
        node_revision.state = "applied"
        phase = "applied"
        phase = _advance_rollout(db, rollout) or phase
    else:
        phase = rollout.status
    node_revision.applied_hash = config_hash_value
    node_revision.message = message
    node_revision.updated_at = datetime.utcnow()
    db.commit()
    return rollout.number, phase


def exclude_dead_participants(db: Session, node_ids: set[int]) -> tuple[int | None, str | None]:
    """Remove routers past their Dead Interval from the current publication quorum."""
    rollout = _current_rollout(db)
    if rollout is None:
        return None, None
    now = datetime.utcnow()
    for item in rollout.node_revisions:
        if item.node_id not in node_ids or item.state == "excluded":
            continue
        item.state = "excluded"
        item.message = "Excluded from publication after the overlay Dead Interval expired"
        item.updated_at = now
    phase = _advance_rollout(db, rollout) or rollout.status
    db.commit()
    return rollout.number, phase


def _current_rollout(db: Session) -> SingBoxRouteRevision | None:
    return (
        db.query(SingBoxRouteRevision)
        .filter(SingBoxRouteRevision.status.in_(("staged", "activating")))
        .order_by(SingBoxRouteRevision.number.desc())
        .first()
    )


def _active_route(db: Session) -> SingBoxRouteRevision | None:
    return (
        db.query(SingBoxRouteRevision)
        .filter(SingBoxRouteRevision.status == "active")
        .order_by(SingBoxRouteRevision.number.desc())
        .first()
    )


def _node_revision(db, node_id, route_id):
    return (
        db.query(SingBoxNodeRouteRevision)
        .filter(
            SingBoxNodeRouteRevision.node_id == node_id,
            SingBoxNodeRouteRevision.route_revision_id == route_id,
        )
        .first()
    )


def _advance_rollout(db: Session, rollout: SingBoxRouteRevision) -> str | None:
    if rollout.status == "staged" and _all_nodes_in_states(
        db,
        rollout.id,
        {"staged", "excluded"},
    ):
        rollout.status = "activating"
        for item in rollout.node_revisions:
            if item.state == "excluded":
                continue
            item.state = "pending"
            item.desired_hash = None
            item.updated_at = datetime.utcnow()
        return "activating"
    if rollout.status == "activating" and _all_nodes_in_states(
        db,
        rollout.id,
        {"applied", "excluded"},
    ):
        active = _active_route(db)
        if active:
            active.status = "draining"
            active.drain_until = datetime.utcnow() + timedelta(seconds=_DRAIN_SECONDS)
        rollout.status = "active"
        rollout.activated_at = datetime.utcnow()
        return "active"
    return None


def _all_nodes_in_states(db, route_id, states):
    rows = (
        db.query(SingBoxNodeRouteRevision)
        .filter(SingBoxNodeRouteRevision.route_revision_id == route_id)
        .all()
    )
    return bool(rows) and all(item.state in states for item in rows)
