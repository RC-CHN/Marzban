import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.singbox import network
from app.core.singbox import production
from app.core.singbox.routing.compiler import compile_route_revision
from app.core.singbox.routing import publication
from app.db.base import Base
from app.db.models import (
    SingBoxAdjacency,
    SingBoxAdjacencyDirection,
    SingBoxEgressService,
    SingBoxIngressObservation,
    SingBoxIngressService,
    SingBoxLinkStateObservation,
    SingBoxNode,
    SingBoxNodeAddress,
    SingBoxRouteRevision,
    SingBoxRoutingPolicy,
    SingBoxUserConnection,
    User,
)
from app.models.singbox import (
    SingBoxIngressObservationReport,
    SingBoxLinkObservationReport,
    SingBoxNetworkDraft,
    SingBoxNodeCapabilities,
    SingBoxNodeStateSessionRequest,
)
from app.models.user import UserStatus


class SingBoxNetworkTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self._seed_diamond()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_apply_computes_multi_hop_and_cost_change_selects_alternate(self):
        first = network.apply_draft(self.db, self._draft(), actor="admin")
        self.assertEqual(first.topology_revision, 1)
        self.assertEqual(first.route_revision, 1)
        self.assertEqual(first.reachable_connections, 1)
        path = self._latest_path()
        self.assertEqual(path.total_cost, 30)
        self.assertEqual([hop.to_node_id for hop in path.hops], [self.nodes[1].id, self.nodes[3].id])
        route_view = network.get_connection_route(self.db, path.connection_id)
        self.assertEqual([candidate.total_cost for candidate in route_view.candidates], [30, 55])
        self.assertTrue(route_view.candidates[0].selected)

        draft = self._draft()
        draft.base_topology_revision = 1
        direction = next(
            direction
            for adjacency in draft.adjacencies
            for direction in adjacency.directions
            if direction.from_node_id == self.nodes[0].id and direction.to_node_id == self.nodes[1].id
        )
        direction.admin_cost = 100
        self._latest_path().route_revision.status = "active"
        self.db.commit()
        second = network.apply_draft(self.db, draft, actor="admin")
        self.assertEqual(second.topology_revision, 2)
        path = self._latest_path()
        self.assertEqual(path.total_cost, 55)
        self.assertEqual([hop.to_node_id for hop in path.hops], [self.nodes[2].id, self.nodes[3].id])

    def test_validation_rejects_stale_revision_and_port_conflict(self):
        network.apply_draft(self.db, self._draft(), actor="admin")
        stale = self._draft()
        stale.base_topology_revision = 0
        directions_to_exit = [
            direction
            for adjacency in stale.adjacencies
            for direction in adjacency.directions
            if direction.to_node_id == self.nodes[3].id
        ]
        directions_to_exit[1].listen_port = directions_to_exit[0].listen_port

        result = network.validate_draft(self.db, stale)

        self.assertFalse(result.valid)
        self.assertEqual(
            {issue.code for issue in result.issues},
            {"stale_revision", "port_conflict", "route_rollout_in_progress"},
        )

    def test_validation_rejects_unchanged_revision(self):
        network.apply_draft(self.db, self._draft(), actor="admin")

        result = network.validate_draft(self.db, self._draft())

        self.assertFalse(result.valid)
        self.assertEqual(
            [issue.code for issue in result.issues],
            ["unchanged_draft", "route_rollout_in_progress"],
        )

    def test_apply_rejects_a_second_revision_during_publication(self):
        network.apply_draft(self.db, self._draft(), actor="admin")
        draft = self._draft()
        draft.ingresses[0].listen_port += 1

        with self.assertRaises(ValueError) as raised:
            network.apply_draft(self.db, draft, actor="admin")

        validation = raised.exception.args[0]
        self.assertIn(
            "route_rollout_in_progress",
            {issue.code for issue in validation.issues},
        )

    def test_validation_requires_maintenance_rollout_for_live_profile_change(self):
        network.apply_draft(self.db, self._draft(), actor="admin")
        draft = self._draft()
        draft.adjacencies[0].directions[0].settings = {"min_idle_session": 2}

        result = network.validate_draft(self.db, draft)

        self.assertFalse(result.valid)
        self.assertIn(
            "maintenance_rollout_required",
            {issue.code for issue in result.issues},
        )

    def test_down_direction_is_excluded_from_applied_route(self):
        primary = next(
            direction
            for direction in self.db.query(SingBoxAdjacencyDirection).all()
            if direction.from_node_id == self.nodes[0].id and direction.to_node_id == self.nodes[1].id
        )
        primary.observation.oper_state = "down"
        self.db.commit()

        network.apply_draft(self.db, self._draft(), actor="admin")

        path = self._latest_path()
        self.assertEqual(path.total_cost, 55)
        self.assertEqual([hop.to_node_id for hop in path.hops], [self.nodes[2].id, self.nodes[3].id])

    def test_route_compiler_installs_public_and_internal_forwarding(self):
        network.apply_draft(self.db, self._draft(), actor="admin")
        path = self._latest_path()

        intents = compile_route_revision(self.db, path.route_revision)

        entry = intents[self.nodes[0].id]
        fast = intents[self.nodes[1].id]
        exit_node = intents[self.nodes[3].id]
        public_tag = f"public-ingress-{path.connection.ingress_service_id}"
        entry_public_rule = next(rule for rule in entry.route_rules if rule.inbound_tag == public_tag)
        self.assertEqual(entry_public_rule.auth_name, "alice-route")
        self.assertTrue(entry_public_rule.outbound_tag.startswith("overlay-r1-"))
        self.assertEqual(len(fast.link_inbounds), 1)
        fast_route_rule = next(
            rule for rule in fast.route_rules if rule.auth_name.startswith("route-r1-")
        )
        self.assertTrue(fast_route_rule.outbound_tag.startswith("overlay-r1-"))
        self.assertEqual(len(exit_node.link_inbounds), 2)
        exit_route_rule = next(
            rule for rule in exit_node.route_rules if rule.auth_name.startswith("route-r1-")
        )
        self.assertEqual(exit_route_rule.outbound_tag, "direct")
        self.assertEqual(len(path.route_revision.hop_credentials), 2)
        self.assertNotEqual(
            path.route_revision.hop_credentials[0].password,
            path.route_revision.hop_credentials[1].password,
        )

    def test_route_revision_renders_independent_singbox_listeners_and_rules(self):
        draft = self._draft()
        draft.adjacencies[0].directions[0].settings = {
            "idle_session_check_interval": "12s",
            "idle_session_timeout": "45s",
            "min_idle_session": 2,
            "padding_scheme": ["stop=4", "0=16-32"],
        }
        network.apply_draft(self.db, draft, actor="admin")
        route = self._latest_path().route_revision

        entry, _ = production.build_node_config_for_route(self.db, self.nodes[0].id, route.id)
        intermediate, _ = production.build_node_config_for_route(self.db, self.nodes[1].id, route.id)
        unused, _ = production.build_node_config_for_route(self.db, self.nodes[2].id, route.id)
        exit_config, _ = production.build_node_config_for_route(self.db, self.nodes[3].id, route.id)

        entry_overlay = [item for item in entry["outbounds"] if item["tag"].startswith("overlay-r")]
        self.assertEqual(len(entry_overlay), 1)
        self.assertEqual(entry_overlay[0]["idle_session_check_interval"], "12s")
        self.assertEqual(entry_overlay[0]["idle_session_timeout"], "45s")
        self.assertEqual(entry_overlay[0]["min_idle_session"], 2)
        self.assertEqual(entry["route"]["rules"][0]["auth_user"], ["alice-route"])
        intermediate_inbounds = [
            item for item in intermediate["inbounds"] if item["tag"].startswith("overlay-in-")
        ]
        self.assertEqual(len(intermediate_inbounds), 1)
        self.assertEqual(intermediate_inbounds[0]["listen_port"], 21001)
        self.assertEqual(intermediate_inbounds[0]["padding_scheme"], ["stop=4", "0=16-32"])
        self.assertTrue(
            any(
                rule["auth_user"][0].startswith("route-r1-")
                for rule in intermediate["route"]["rules"]
            )
        )
        self.assertFalse(any(item["tag"].startswith("node-link-") for item in unused["inbounds"]))
        self.assertFalse(any(item["tag"].startswith("overlay-r") for item in unused["outbounds"]))
        exit_route_rule = next(
            rule
            for rule in exit_config["route"]["rules"]
            if rule["auth_user"][0].startswith("route-r1-")
        )
        self.assertEqual(exit_route_rule["outbound"], "direct")

    def test_two_phase_publication_stages_internal_routes_before_activation(self):
        result = network.apply_draft(self.db, self._draft(), actor="admin")
        path = self._latest_path()
        route = path.route_revision
        self.assertEqual(result.status, "staged")

        stage_hashes = {}
        for node in self.nodes:
            config, hash_value, route_number, phase = publication.desired_node_config(self.db, node)
            stage_hashes[node.id] = hash_value
            self.assertEqual(route_number, route.number)
            self.assertEqual(phase, "staging")
            if node.id == self.nodes[0].id:
                public_rule = next(
                    rule
                    for rule in config["route"]["rules"]
                    if rule["inbound"] == [f"public-ingress-{path.connection.ingress_service_id}"]
                )
                self.assertEqual(public_rule["outbound"], "block")

        for node in self.nodes:
            publication.report_applied(self.db, node, stage_hashes[node.id], True, None)
        self.db.refresh(route)
        self.assertEqual(route.status, "activating")

        activation_hashes = {}
        for node in self.nodes:
            config, hash_value, _, phase = publication.desired_node_config(self.db, node)
            activation_hashes[node.id] = hash_value
            self.assertEqual(phase, "activating")
            if node.id == self.nodes[0].id:
                public_rule = next(
                    rule
                    for rule in config["route"]["rules"]
                    if rule["inbound"] == [f"public-ingress-{path.connection.ingress_service_id}"]
                )
                self.assertTrue(public_rule["outbound"].startswith("overlay-r1-"))

        for node in self.nodes:
            publication.report_applied(self.db, node, activation_hashes[node.id], True, None)
        self.db.refresh(route)
        self.assertEqual(route.status, "active")
        active_config, _ = production.build_node_config(self.db, self.nodes[0].id)
        self.assertTrue(active_config["route"]["rules"][0]["outbound"].startswith("overlay-r1-"))

    def test_failed_staging_preserves_active_revision(self):
        first = network.apply_draft(self.db, self._draft(), actor="admin")
        route = self._latest_path().route_revision
        stage_hashes = {}
        for node in self.nodes:
            _, stage_hashes[node.id], _, _ = publication.desired_node_config(self.db, node)
        for node in self.nodes:
            publication.report_applied(self.db, node, stage_hashes[node.id], True, None)
        activation_hashes = {}
        for node in self.nodes:
            _, activation_hashes[node.id], _, _ = publication.desired_node_config(self.db, node)
        for node in self.nodes:
            publication.report_applied(self.db, node, activation_hashes[node.id], True, None)
        self.db.refresh(route)
        self.assertEqual(route.status, "active")

        draft = self._draft()
        draft.base_topology_revision = first.topology_revision
        draft.adjacencies[0].directions[0].admin_cost = 99
        second = network.apply_draft(self.db, draft, actor="admin")
        _, failed_hash, _, _ = publication.desired_node_config(self.db, self.nodes[0])
        publication.report_applied(self.db, self.nodes[0], failed_hash, False, "sing-box check failed")

        failed = (
            self.db.query(SingBoxRouteRevision)
            .filter(SingBoxRouteRevision.number == second.route_revision)
            .one()
        )
        self.assertEqual(failed.status, "failed")
        active_config, _ = production.build_node_config(self.db, self.nodes[0].id)
        public_rule = next(
            rule
            for rule in active_config["route"]["rules"]
            if rule["inbound"] == [f"public-ingress-{self._latest_path().connection.ingress_service_id}"]
        )
        self.assertTrue(public_rule["outbound"].startswith("overlay-r1-"))

    def test_link_report_sequence_updates_capabilities_and_recomputes_route(self):
        network.apply_draft(self.db, self._draft(), actor="admin")
        self._latest_path().route_revision.status = "active"
        self.db.commit()
        primary = next(
            direction
            for direction in self.db.query(SingBoxAdjacencyDirection).all()
            if direction.from_node_id == self.nodes[0].id and direction.to_node_id == self.nodes[1].id
        )
        report = SingBoxLinkObservationReport(
            adjacency_direction_id=primary.id,
            sequence=2,
            state="down",
            hold_seconds=15,
            message="transport timeout",
        )
        primary.observation.hold_expires_at = datetime.utcnow() - timedelta(seconds=1)
        self.db.commit()

        result = network.record_link_state(
            self.db,
            self.nodes[0],
            SingBoxNodeCapabilities(
                sing_box_version="1.12.0",
                supported_transports=["anytls", "hysteria2"],
                runtime="docker",
                addresses=["192.0.2.1"],
            ),
            [report],
        )

        self.assertTrue(result["effective_changed"])
        self.assertEqual(result["route_revision"], 2)
        self.assertEqual(self.nodes[0].capabilities["runtime"], "docker")
        self.assertEqual(self._latest_path().total_cost, 55)
        stale = network.record_link_state(self.db, self.nodes[0], None, [report])
        self.assertEqual(stale["accepted"], 0)
        self.assertEqual(stale["stale"], 1)
        self.assertIsNone(stale["route_revision"])

        primary.observation.hold_expires_at = datetime.utcnow() - timedelta(seconds=1)
        reset = report.model_copy(update={"sequence": 1, "state": "up"})
        recovered = network.record_link_state(self.db, self.nodes[0], None, [reset])
        self.assertEqual(recovered["accepted"], 1)
        self.assertEqual(recovered["stale"], 0)

    def test_state_session_epoch_allows_sequence_restart_and_rejects_old_stream(self):
        node = self.nodes[0]
        direction = next(
            item
            for item in self.db.query(SingBoxAdjacencyDirection).all()
            if item.from_node_id == node.id
        )
        opened = network.reconcile_state_session(
            self.db,
            node,
            SingBoxNodeStateSessionRequest(instance_id="agent-instance-0001"),
        )
        self.assertFalse(opened.accept_reports)
        self.assertEqual(opened.epoch, 1)
        self.assertIsNotNone(opened.lease_token)
        current = network.reconcile_state_session(
            self.db,
            node,
            SingBoxNodeStateSessionRequest(
                instance_id="agent-instance-0001",
                epoch=opened.epoch,
                lease_token=opened.lease_token,
                snapshot_sequence=1,
            ),
        )
        report = SingBoxLinkObservationReport(
            adjacency_direction_id=direction.id,
            sequence=1,
            resource_generation=direction.generation,
            state="up",
        )
        result = network.record_link_state(
            self.db,
            node,
            None,
            [report],
            state_session=current,
        )
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(direction.observation.session_epoch, 1)
        self.assertEqual(direction.observation.snapshot_sequence, 1)

        restarted = network.reconcile_state_session(
            self.db,
            node,
            SingBoxNodeStateSessionRequest(instance_id="agent-instance-0001"),
        )
        self.assertEqual(restarted.epoch, 2)
        self.assertEqual(restarted.accepted_sequence, 0)
        resumed = network.reconcile_state_session(
            self.db,
            node,
            SingBoxNodeStateSessionRequest(
                instance_id="agent-instance-0001",
                epoch=restarted.epoch,
                lease_token=restarted.lease_token,
                snapshot_sequence=1,
            ),
        )
        result = network.record_link_state(
            self.db,
            node,
            None,
            [report],
            state_session=resumed,
        )
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(direction.observation.session_epoch, 2)

        with self.assertRaisesRegex(ValueError, "stale|invalid"):
            network.reconcile_state_session(
                self.db,
                node,
                SingBoxNodeStateSessionRequest(
                    instance_id="agent-instance-0001",
                    epoch=opened.epoch,
                    lease_token=opened.lease_token,
                    snapshot_sequence=2,
                ),
            )

    def test_session_reports_require_current_resource_generation(self):
        node = self.nodes[0]
        direction = next(
            item
            for item in self.db.query(SingBoxAdjacencyDirection).all()
            if item.from_node_id == node.id
        )
        opened = network.reconcile_state_session(
            self.db,
            node,
            SingBoxNodeStateSessionRequest(instance_id="agent-instance-0002"),
        )
        current = network.reconcile_state_session(
            self.db,
            node,
            SingBoxNodeStateSessionRequest(
                instance_id="agent-instance-0002",
                epoch=opened.epoch,
                lease_token=opened.lease_token,
                snapshot_sequence=1,
            ),
        )
        direction.generation += 1
        self.db.flush()

        result = network.record_link_state(
            self.db,
            node,
            None,
            [
                SingBoxLinkObservationReport(
                    adjacency_direction_id=direction.id,
                    sequence=1,
                    resource_generation=direction.generation - 1,
                    state="up",
                )
            ],
            state_session=current,
        )

        self.assertEqual(result["accepted"], 0)
        self.assertEqual(result["stale"], 1)
        self.assertEqual(network._effective_direction_state(direction, datetime.utcnow()), "unknown")

    def test_ingress_report_tracks_listener_independently_from_node_heartbeat(self):
        ingress = self.db.query(SingBoxIngressService).one()
        node = self.nodes[0]
        node.last_config_hash = "a" * 64
        node.applied_config_hash = "a" * 64
        self.db.commit()
        report = SingBoxIngressObservationReport(
            ingress_service_id=ingress.id,
            sequence=1,
            state="up",
            hold_seconds=15,
            message="anytls listener is active on port 11003",
        )

        result = network.record_ingress_state(
            self.db,
            node,
            [report],
            config_is_current=True,
        )

        self.assertEqual(result, {"accepted": 1, "stale": 0, "ignored": 0})
        observed = network.get_workspace(self.db).ingresses[0]
        self.assertEqual(observed.oper_state, "up")
        self.assertIn("listener is active", observed.message)
        stale = network.record_ingress_state(
            self.db,
            node,
            [report],
            config_is_current=True,
        )
        self.assertEqual(stale, {"accepted": 0, "stale": 1, "ignored": 0})

        ingress.observation.hold_expires_at = datetime.utcnow() - timedelta(seconds=1)
        self.db.commit()
        expired = network.get_workspace(self.db).ingresses[0]
        self.assertEqual(expired.oper_state, "down")
        self.assertEqual(expired.message, "Listener observation expired")

    def test_ingress_report_requires_current_config_and_owning_node(self):
        ingress = self.db.query(SingBoxIngressService).one()
        report = SingBoxIngressObservationReport(
            ingress_service_id=ingress.id,
            sequence=1,
            state="up",
        )

        ignored = network.record_ingress_state(
            self.db,
            self.nodes[0],
            [report],
            config_is_current=False,
        )
        self.assertEqual(ignored, {"accepted": 0, "stale": 0, "ignored": 1})
        self.assertIsNone(self.db.query(SingBoxIngressObservation).first())

        with self.assertRaisesRegex(ValueError, "cannot report ingress service"):
            network.record_ingress_state(
                self.db,
                self.nodes[1],
                [report],
                config_is_current=True,
            )

    def test_link_failure_does_not_switch_when_failover_is_disabled(self):
        draft = self._draft()
        draft.routing_policies[0].failover = False
        network.apply_draft(self.db, draft, actor="admin")
        self._latest_path().route_revision.status = "active"
        self.db.commit()
        primary = next(
            direction
            for direction in self.db.query(SingBoxAdjacencyDirection).all()
            if direction.from_node_id == self.nodes[0].id
            and direction.to_node_id == self.nodes[1].id
        )
        primary.observation.hold_expires_at = datetime.utcnow() - timedelta(seconds=1)
        self.db.commit()

        network.record_link_state(
            self.db,
            self.nodes[0],
            None,
            [
                SingBoxLinkObservationReport(
                    adjacency_direction_id=primary.id,
                    sequence=2,
                    state="down",
                    hold_seconds=15,
                )
            ],
        )

        self.assertEqual(self._latest_path().status, "unreachable")
        self.assertIn("failover is disabled", self._latest_path().reason)

    def test_single_failed_probe_keeps_up_state_until_hold_timer_expires(self):
        network.apply_draft(self.db, self._draft(), actor="admin")
        self._latest_path().route_revision.status = "active"
        primary = next(
            direction
            for direction in self.db.query(SingBoxAdjacencyDirection).all()
            if direction.from_node_id == self.nodes[0].id
            and direction.to_node_id == self.nodes[1].id
        )
        self.db.commit()

        result = network.record_link_state(
            self.db,
            self.nodes[0],
            None,
            [
                SingBoxLinkObservationReport(
                    adjacency_direction_id=primary.id,
                    sequence=2,
                    state="down",
                    hold_seconds=15,
                )
            ],
        )

        self.assertFalse(result["effective_changed"])
        self.assertIsNone(result["route_revision"])
        self.assertEqual(primary.observation.oper_state, "up")
        self.assertIn("hold timer", primary.observation.message)

    def test_link_state_change_is_coalesced_during_an_active_rollout(self):
        network.apply_draft(self.db, self._draft(), actor="admin")
        primary = next(
            direction
            for direction in self.db.query(SingBoxAdjacencyDirection).all()
            if direction.from_node_id == self.nodes[0].id
            and direction.to_node_id == self.nodes[1].id
        )

        primary.observation.hold_expires_at = datetime.utcnow() - timedelta(seconds=1)
        self.db.commit()
        deferred = network.record_link_state(
            self.db,
            self.nodes[0],
            None,
            [
                SingBoxLinkObservationReport(
                    adjacency_direction_id=primary.id,
                    sequence=2,
                    state="down",
                    hold_seconds=15,
                )
            ],
        )

        self.assertTrue(deferred["effective_changed"])
        self.assertIsNone(deferred["route_revision"])
        self.assertEqual(primary.observation.oper_state, "down")

        self._latest_path().route_revision.status = "active"
        self.db.commit()
        applied = network.record_link_state(
            self.db,
            self.nodes[0],
            None,
            [
                SingBoxLinkObservationReport(
                    adjacency_direction_id=primary.id,
                    sequence=3,
                    state="down",
                    hold_seconds=15,
                )
            ],
        )
        self.assertFalse(applied["effective_changed"])
        self.assertEqual(applied["route_revision"], 2)

    def test_isolated_node_does_not_block_link_state_rollout(self):
        network.apply_draft(self.db, self._draft(), actor="admin")
        self._latest_path().route_revision.status = "active"
        isolated_id = self.nodes[2].id
        for direction in self.db.query(SingBoxAdjacencyDirection).all():
            if isolated_id in (direction.from_node_id, direction.to_node_id):
                direction.observation.oper_state = "down"
        route = network._recompute_after_link_state(self.db, actor="test:isolation")
        self.db.commit()

        participants = {item.node_id for item in route.node_revisions}
        self.assertNotIn(isolated_id, participants)
        self.assertEqual(participants, {self.nodes[0].id, self.nodes[1].id, self.nodes[3].id})
        config, _, _, phase = publication.desired_node_config(self.db, self.nodes[2])
        self.assertEqual(phase, "excluded")
        self.assertIsInstance(config, dict)

    def test_stale_node_heartbeat_removes_all_incident_edges_from_routing(self):
        network.apply_draft(self.db, self._draft(), actor="admin")
        self._latest_path().route_revision.status = "active"
        now = datetime.utcnow()
        for node in self.nodes:
            node.last_seen_at = now
        self.nodes[1].last_seen_at = now - timedelta(
            seconds=network.ROUTING_DEAD_INTERVAL_SECONDS + 1
        )
        route = network._recompute_after_link_state(self.db, actor="test:stale-node")
        self.db.commit()

        path = self._latest_path()
        self.assertEqual(path.total_cost, 55)
        self.assertEqual([hop.to_node_id for hop in path.hops], [self.nodes[2].id, self.nodes[3].id])
        self.assertNotIn(self.nodes[1].id, {item.node_id for item in route.node_revisions})

    def test_dead_node_is_excluded_from_the_publication_quorum(self):
        network.apply_draft(self.db, self._draft(), actor="admin")
        route = self._latest_path().route_revision
        dead_node = self.nodes[2]
        for item in route.node_revisions:
            item.state = "pending" if item.node_id == dead_node.id else "staged"
        self.db.commit()

        revision, phase = publication.exclude_dead_participants(self.db, {dead_node.id})

        self.assertEqual(revision, route.number)
        self.assertEqual(phase, "activating")
        self.assertEqual(route.status, "activating")
        excluded = next(item for item in route.node_revisions if item.node_id == dead_node.id)
        self.assertEqual(excluded.state, "excluded")
        self.assertTrue(all(
            item.state == "pending"
            for item in route.node_revisions
            if item.node_id != dead_node.id
        ))

        for item in route.node_revisions:
            if item.state != "excluded":
                item.state = "applied"
        self.db.commit()
        _, phase = publication.exclude_dead_participants(self.db, {dead_node.id})
        self.assertEqual(phase, "active")
        self.assertEqual(route.status, "active")

    def test_node_delete_is_blocked_by_retained_route_history(self):
        network.apply_draft(self.db, self._draft(), actor="admin")

        with self.assertRaisesRegex(ValueError, "retained route hop"):
            production.delete_node(self.db, self.nodes[1])

    def _seed_diamond(self):
        self.nodes = [
            SingBoxNode(
                name=name,
                public_host=f"{name}.example",
                entry_enabled=index == 0,
                exit_enabled=index == 3,
            )
            for index, name in enumerate(("entry", "fast", "backup", "exit"))
        ]
        self.db.add_all(self.nodes)
        self.db.flush()
        addresses = [
            SingBoxNodeAddress(node_id=node.id, address=node.public_host, is_primary=True)
            for node in self.nodes
        ]
        self.db.add_all(addresses)
        self.db.flush()
        ingress = SingBoxIngressService(
            node_id=self.nodes[0].id,
            advertised_address_id=addresses[0].id,
            name="Entry AnyTLS",
            protocol="anytls",
            listen_port=11003,
            tls_mode="system-ca",
            enabled=True,
        )
        egress = SingBoxEgressService(
            node_id=self.nodes[3].id,
            name="Direct @ exit",
            kind="direct",
            enabled=True,
        )
        policy = SingBoxRoutingPolicy(name="Default", max_hops=8, failover=True)
        self.db.add_all([ingress, egress, policy])
        self.db.flush()
        edges = (
            (0, 1, 10, 21001),
            (1, 3, 20, 21002),
            (0, 2, 5, 21003),
            (2, 3, 50, 21004),
        )
        for index, (source, target, cost, port) in enumerate(edges):
            adjacency = SingBoxAdjacency(
                node_a_id=min(self.nodes[source].id, self.nodes[target].id),
                node_b_id=max(self.nodes[source].id, self.nodes[target].id),
                name=f"edge-{index}",
                enabled=True,
            )
            self.db.add(adjacency)
            self.db.flush()
            direction = SingBoxAdjacencyDirection(
                adjacency_id=adjacency.id,
                from_node_id=self.nodes[source].id,
                to_node_id=self.nodes[target].id,
                transport="anytls",
                listen_port=port,
                admin_cost=cost,
                enabled=True,
            )
            self.db.add(direction)
            self.db.flush()
            self.db.add(
                SingBoxLinkStateObservation(
                    adjacency_direction_id=direction.id,
                    reporting_node_id=self.nodes[source].id,
                    sequence=1,
                    oper_state="up",
                    observed_at=datetime.utcnow(),
                    hold_expires_at=datetime.utcnow() + timedelta(minutes=5),
                )
            )
        user = User(username="alice", status=UserStatus.active)
        self.db.add(user)
        self.db.flush()
        self.db.add(
            SingBoxUserConnection(
                user_id=user.id,
                entry_node_id=self.nodes[0].id,
                exit_node_id=self.nodes[3].id,
                ingress_service_id=ingress.id,
                egress_service_id=egress.id,
                routing_policy_id=policy.id,
                protocol="anytls",
                label="Entry to exit",
                auth_name="alice-route",
                password="secret",
                enabled=True,
            )
        )
        self.db.commit()

    def _draft(self):
        workspace = network.get_workspace(self.db)
        return SingBoxNetworkDraft(
            base_topology_revision=workspace.topology_revision,
            ingresses=workspace.ingresses,
            egresses=workspace.egresses,
            adjacencies=workspace.adjacencies,
            routing_policies=workspace.routing_policies,
        )

    def _latest_path(self):
        from app.db.models import SingBoxComputedPath

        return self.db.query(SingBoxComputedPath).order_by(SingBoxComputedPath.id.desc()).first()


if __name__ == "__main__":
    unittest.main()
