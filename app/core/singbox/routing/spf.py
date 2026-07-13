from __future__ import annotations

import heapq
from collections import defaultdict
from collections.abc import Iterable

from app.core.singbox.routing.types import ComputedPath, DirectedEdge, NoRoute, RoutingPolicy


_MAX_EXPLORED_STATES = 100_000


def compute_path(
    edges: Iterable[DirectedEdge],
    source_node_id: int,
    target_node_id: int,
    policy: RoutingPolicy | None = None,
) -> ComputedPath | NoRoute:
    paths = compute_paths(edges, source_node_id, target_node_id, policy, limit=1)
    if paths:
        return paths[0]
    return NoRoute(
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        reason="No eligible path satisfies the routing policy",
    )


def compute_paths(
    edges: Iterable[DirectedEdge],
    source_node_id: int,
    target_node_id: int,
    policy: RoutingPolicy | None = None,
    *,
    limit: int = 3,
) -> list[ComputedPath]:
    """Return deterministic loop-free paths ordered by cost, hops and edge IDs.

    The bounded graph is intentionally explored as path states. Keeping the
    visited-node tuple in each state enforces the no-loop invariant and avoids
    incorrectly pruning a higher-cost, lower-hop prefix that can still satisfy
    the hop bound.
    """

    policy = policy or RoutingPolicy()
    if source_node_id <= 0 or target_node_id <= 0:
        raise ValueError("Source and target node IDs must be positive")
    if limit <= 0:
        raise ValueError("Path limit must be positive")
    if source_node_id in policy.avoided_node_ids or target_node_id in policy.avoided_node_ids:
        return []
    if source_node_id == target_node_id:
        if policy.required_node_ids - {source_node_id}:
            return []
        return [ComputedPath((source_node_id,), (), 0)]

    adjacency: dict[int, list[DirectedEdge]] = defaultdict(list)
    edge_ids: set[int] = set()
    for edge in edges:
        if edge.id in edge_ids:
            raise ValueError(f"Duplicate edge ID: {edge.id}")
        edge_ids.add(edge.id)
        if not _eligible(edge, policy):
            continue
        adjacency[edge.from_node_id].append(edge)
    for outgoing in adjacency.values():
        outgoing.sort(key=lambda edge: edge.id)

    # cost, hops, edge IDs and node IDs together define deterministic heap order.
    queue: list[tuple[int, int, tuple[int, ...], tuple[int, ...], int]] = [
        (0, 0, (), (source_node_id,), source_node_id)
    ]
    results: list[ComputedPath] = []
    explored = 0

    while queue and len(results) < limit:
        cost, hops, path_edge_ids, path_node_ids, node_id = heapq.heappop(queue)
        explored += 1
        if explored > _MAX_EXPLORED_STATES:
            raise RuntimeError("Path exploration limit exceeded")

        if node_id == target_node_id:
            if policy.required_node_ids.issubset(path_node_ids):
                results.append(ComputedPath(path_node_ids, path_edge_ids, cost))
            continue
        if hops >= policy.max_hops:
            continue

        for edge in adjacency.get(node_id, ()):
            if edge.to_node_id in path_node_ids:
                continue
            heapq.heappush(
                queue,
                (
                    cost + edge.admin_cost,
                    hops + 1,
                    path_edge_ids + (edge.id,),
                    path_node_ids + (edge.to_node_id,),
                    edge.to_node_id,
                ),
            )

    return results


def _eligible(edge: DirectedEdge, policy: RoutingPolicy) -> bool:
    if not edge.enabled:
        return False
    if edge.from_node_id in policy.avoided_node_ids or edge.to_node_id in policy.avoided_node_ids:
        return False
    if edge.oper_state == "up":
        return True
    return policy.allow_degraded and edge.oper_state == "degraded"
