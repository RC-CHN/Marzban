from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


OperState = Literal["unknown", "provisioning", "up", "degraded", "down"]
MetricMode = Literal["admin_only"]


@dataclass(frozen=True, slots=True)
class DirectedEdge:
    id: int
    from_node_id: int
    to_node_id: int
    admin_cost: int = 100
    enabled: bool = True
    oper_state: OperState = "up"

    def __post_init__(self) -> None:
        if self.id <= 0:
            raise ValueError("Edge ID must be positive")
        if self.from_node_id <= 0 or self.to_node_id <= 0:
            raise ValueError("Node IDs must be positive")
        if self.from_node_id == self.to_node_id:
            raise ValueError("An adjacency direction cannot point to itself")
        if not 1 <= self.admin_cost <= 65535:
            raise ValueError("Administrative cost must be between 1 and 65535")


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    max_hops: int = 8
    metric_mode: MetricMode = "admin_only"
    allow_degraded: bool = False
    avoided_node_ids: frozenset[int] = frozenset()
    required_node_ids: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if not 0 <= self.max_hops <= 32:
            raise ValueError("Maximum hops must be between 0 and 32")
        if self.avoided_node_ids & self.required_node_ids:
            raise ValueError("A node cannot be both required and avoided")


@dataclass(frozen=True, slots=True)
class ComputedPath:
    node_ids: tuple[int, ...]
    edge_ids: tuple[int, ...]
    total_cost: int

    def __post_init__(self) -> None:
        if not self.node_ids:
            raise ValueError("A path must contain at least one node")
        if len(self.edge_ids) != len(self.node_ids) - 1:
            raise ValueError("Path edge and node sequences are inconsistent")
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("A path cannot contain a repeated node")
        if self.total_cost < 0:
            raise ValueError("Path cost cannot be negative")

    @property
    def hop_count(self) -> int:
        return len(self.edge_ids)


@dataclass(frozen=True, slots=True)
class NoRoute:
    source_node_id: int
    target_node_id: int
    reason: str
