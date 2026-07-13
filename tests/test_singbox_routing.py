import unittest

from app.core.singbox.routing import (
    ComputedPath,
    DirectedEdge,
    NoRoute,
    RoutingPolicy,
    compute_path,
    compute_paths,
)
from app.core.singbox.routing.compiler import (
    CompiledLinkInbound,
    CompiledLinkUser,
    CompiledNodeIntent,
    merge_intents,
)


class SingBoxRoutingTestCase(unittest.TestCase):
    def test_zero_hop_route(self):
        result = compute_path([], 1, 1)
        self.assertEqual(result, ComputedPath((1,), (), 0))

    def test_selects_lower_cost_multi_hop_over_direct(self):
        result = compute_path(
            [
                DirectedEdge(1, 1, 4, 100),
                DirectedEdge(2, 1, 2, 20),
                DirectedEdge(3, 2, 3, 20),
                DirectedEdge(4, 3, 4, 20),
            ],
            1,
            4,
        )
        self.assertEqual(result, ComputedPath((1, 2, 3, 4), (2, 3, 4), 60))

    def test_directed_costs_are_asymmetric(self):
        edges = [
            DirectedEdge(1, 1, 2, 10),
            DirectedEdge(2, 2, 1, 90),
        ]
        self.assertEqual(compute_path(edges, 1, 2), ComputedPath((1, 2), (1,), 10))
        self.assertEqual(compute_path(edges, 2, 1), ComputedPath((2, 1), (2,), 90))

    def test_skips_disabled_down_and_degraded_edges(self):
        edges = [
            DirectedEdge(1, 1, 2, 1, enabled=False),
            DirectedEdge(2, 1, 2, 2, oper_state="down"),
            DirectedEdge(3, 1, 2, 3, oper_state="degraded"),
            DirectedEdge(4, 1, 2, 4),
        ]
        self.assertEqual(compute_path(edges, 1, 2), ComputedPath((1, 2), (4,), 4))
        self.assertEqual(
            compute_path(edges, 1, 2, RoutingPolicy(allow_degraded=True)),
            ComputedPath((1, 2), (3,), 3),
        )

    def test_cost_tie_prefers_fewer_hops_then_edge_ids(self):
        edges = [
            DirectedEdge(9, 1, 4, 20),
            DirectedEdge(2, 1, 2, 10),
            DirectedEdge(3, 2, 4, 10),
            DirectedEdge(4, 1, 3, 10),
            DirectedEdge(5, 3, 4, 10),
        ]
        paths = compute_paths(edges, 1, 4, limit=3)
        self.assertEqual([path.edge_ids for path in paths], [(9,), (2, 3), (4, 5)])

    def test_hop_limit_keeps_more_expensive_shorter_prefix(self):
        edges = [
            DirectedEdge(1, 1, 2, 1),
            DirectedEdge(2, 2, 3, 1),
            DirectedEdge(3, 1, 3, 5),
            DirectedEdge(4, 3, 4, 1),
        ]
        result = compute_path(edges, 1, 4, RoutingPolicy(max_hops=2))
        self.assertEqual(result, ComputedPath((1, 3, 4), (3, 4), 6))

    def test_cycles_are_not_returned(self):
        edges = [
            DirectedEdge(1, 1, 2, 1),
            DirectedEdge(2, 2, 1, 1),
            DirectedEdge(3, 2, 3, 1),
        ]
        paths = compute_paths(edges, 1, 3, limit=3)
        self.assertEqual(paths, [ComputedPath((1, 2, 3), (1, 3), 2)])

    def test_required_and_avoided_nodes(self):
        edges = [
            DirectedEdge(1, 1, 2, 1),
            DirectedEdge(2, 2, 4, 1),
            DirectedEdge(3, 1, 3, 2),
            DirectedEdge(4, 3, 4, 2),
        ]
        required = compute_path(edges, 1, 4, RoutingPolicy(required_node_ids=frozenset({3})))
        avoided = compute_path(edges, 1, 4, RoutingPolicy(avoided_node_ids=frozenset({2})))
        expected = ComputedPath((1, 3, 4), (3, 4), 4)
        self.assertEqual(required, expected)
        self.assertEqual(avoided, expected)

    def test_no_route_has_reason(self):
        result = compute_path([DirectedEdge(1, 1, 2)], 2, 1)
        self.assertIsInstance(result, NoRoute)
        self.assertIn("No eligible path", result.reason)

    def test_rejects_invalid_edges_and_duplicate_ids(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
            DirectedEdge(1, 1, 2, 0)
        with self.assertRaisesRegex(ValueError, "Duplicate edge ID"):
            compute_path([DirectedEdge(1, 1, 2), DirectedEdge(1, 2, 3)], 1, 3)

    def test_rollout_merge_preserves_settings_and_combines_users(self):
        settings = {"idle_session_timeout": "45s"}
        primary = CompiledNodeIntent(
            node_id=1,
            link_inbounds=(
                CompiledLinkInbound(
                    direction_id=9,
                    transport="anytls",
                    listen_port=22001,
                    settings=settings,
                    users=(CompiledLinkUser("old", "old-secret"),),
                ),
            ),
            link_outbounds=(),
            route_rules=(),
        )
        additional = CompiledNodeIntent(
            node_id=1,
            link_inbounds=(
                CompiledLinkInbound(
                    direction_id=9,
                    transport="anytls",
                    listen_port=22001,
                    settings=settings,
                    users=(CompiledLinkUser("new", "new-secret"),),
                ),
            ),
            link_outbounds=(),
            route_rules=(),
        )

        merged = merge_intents(primary, additional)

        self.assertEqual(merged.link_inbounds[0].settings, settings)
        self.assertEqual(
            [user.auth_name for user in merged.link_inbounds[0].users],
            ["new", "old"],
        )


if __name__ == "__main__":
    unittest.main()
