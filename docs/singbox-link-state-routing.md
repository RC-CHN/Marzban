# sing-box Link-State Overlay Routing

## Objective

Build an OSPF-like link-state control plane for a sing-box proxy overlay. This
does not put IP OSPF packets on the wire. Nodes advertise signed overlay
adjacencies and health, the control plane computes paths, and node agents apply
the resulting sing-box configuration.

The control plane remains centrally computed in v0.10, but its persisted model
and SPF implementation support bounded multi-hop paths from the first release.
See `singbox-v0.10-network-editor-design.md` for the implementation baseline.

## OSPF model and deliberate differences

The overlay follows OSPF's convergence model without attempting to speak the
OSPF wire protocol:

| OSPF concept | Overlay implementation |
| --- | --- |
| Router ID | Persisted node ID and scoped sync identity |
| Hello / Dead intervals | 5 second node sync and 30 second Dead Interval |
| Adjacency | Directed, authenticated sing-box transport between two nodes |
| Router LSA / LSDB | Leased node snapshot streams and persisted effective routing snapshots |
| Interface cost | Non-negative administrative cost on each direction |
| SPF | Deterministic bounded shortest-path calculation |
| RIB / FIB install | Immutable route revision followed by two-phase node publication |

Unlike OSPF, v0.10 has one authoritative panel LSDB and SPF calculator. Nodes
pull desired state over HTTPS instead of flooding LSAs to every neighbor. This
keeps the first production version inspectable while preserving the state and
revision boundaries needed for distributed LSA flooding later.

## Configuration ownership

| Object | Owns |
| --- | --- |
| Connection | User, ingress service, egress service, routing policy |
| Ingress service | Public protocol, port and profile attached to one node |
| Egress service | Allowed exit behavior attached to one node |
| Adjacency | Directed node-to-node transport, port, credentials and metrics |
| Computed path | Ordered adjacency IDs selected for a connection revision |
| Node | Identity, public address, capabilities, certificates and heartbeat |

Connections express intent. They must not embed generated outbound tags or a
specific intermediate route. The initial operational guardrail is
`max_hops=8`; this is not a schema restriction.

## Why the current node-link is transitional

The current implementation creates one node-link listener per target node and
shares its port across all source nodes. This is valid while every incoming
link uses the same transport and server settings. It cannot safely support
edge-specific protocols or padding/obfuscation because two different
inbounds cannot bind the same target port.

Before edge editing is enabled, node links must become real adjacencies with
an independently allocated target port, or be grouped into explicit listener
profiles whose members share an identical transport configuration.

## Link-state database

An adjacency record should contain:

```text
id
from_node_id
to_node_id
transport
listen_port
admin_enabled
admin_cost
oper_state
observed_rtt_ms
observed_loss_ppm
observed_bandwidth_mbps
settings
resource_generation
session_epoch
snapshot_sequence
last_probe_at
hold_expires_at
```

`settings` is a versioned, protocol-discriminated object validated by the
control plane. Arbitrary sing-box JSON is not accepted.

Nodes advertise capabilities separately from observations:

```text
sing_box_version
supported_transports
available_ports
public_addresses
runtime
config_revision
```

## LSA lifecycle

1. The agent opens one leased state session using its stable instance ID. The
   panel assigns a monotonically increasing session epoch.
2. The agent probes configured neighbors over the actual node-link transport
   and submits one complete node snapshot with a session-local sequence.
3. Every observed ingress or direction echoes the control-plane-owned resource
   generation from its probe assignment.
4. The panel verifies node identity from the scoped sync token over HTTPS;
   node-to-node probes authenticate the actual transport with mTLS.
5. The panel compares `(resource_generation, session_epoch,
   snapshot_sequence)`. Reports from an old configuration or an old agent
   session cannot overwrite current state.
6. Newer snapshots replace older state; the Dead Interval marks a silent router and
   all of its incident directions down atomically.
7. A topology revision is created only when effective routing state changes.
8. Paths are recomputed and desired node configuration revisions are updated.
9. Agents pull, validate with `sing-box check`, apply atomically and acknowledge.

Disabling, re-enabling or changing a resource increments its generation. A
new generation starts as unknown until a current snapshot arrives. Agent
restart or local state loss opens a higher epoch and safely restarts the
snapshot sequence at one. The server keeps only one active lease per node, so
delayed reports from the previous epoch are rejected. The legacy per-resource
`sequence` columns remain temporarily for rolling upgrades from pre-session
agents and are not part of the new freshness comparison.

The initial target is a 5 second Hello/probe interval and 30 second Dead
Interval. A failed probe preserves the last eligible state until its existing
Dead timer expires; failures do not refresh that timer. The initial
`admin_only` metric does not react to latency variation. Dynamic metric
hysteresis is required before latency or loss can influence path selection.

### SPF and publication throttling

LSDB updates and route publication are separate state machines. Observations
continue to advance while a route revision is `staged` or `activating`, but an
in-flight revision is never superseded by every transient update. If the
effective LSDB differs when publication completes, the next Hello coalesces all
pending changes into one SPF run and one new revision.

A participant that passes the Dead Interval is marked `excluded` from the
current publication quorum. Remaining live participants may advance from
`staged` to `activating`, then to `active`. If the excluded node returns, its
Hello updates the LSDB and a later immutable revision includes it again. This
is the central-control equivalent of OSPF continuing to install routes on live
routers while a dead router is absent.

## Path calculation

Use a bounded uniform-cost search over loop-free directed path states. This is
equivalent to Dijkstra ordering for the initial non-negative `admin_cost`
metric while preserving the hop and required-node constraints. Measured
latency, loss and bandwidth may contribute only when the operator enables
dynamic metrics.

Tie breaking must be deterministic:

1. Lowest total cost.
2. Lowest hop count.
3. Lexicographically smallest adjacency ID sequence.

The initial routing policy is:

```text
max_hops = 8
metric_mode = admin_only
failover = enabled
```

With failover enabled, an effective link-state change selects the next eligible
lowest-cost path. With failover disabled, the selected path is retained while
eligible and becomes unreachable if it fails; an alternate is selected only
after an explicit topology apply.

Future policies may enable preferred regions, avoided nodes, minimum
bandwidth, failover candidates and multi-hop limits.

## Loop and revision safety

sing-box proxy routes do not carry an IP TTL across application-level hops.
Loop prevention therefore belongs to the control plane:

- A computed path cannot contain a node twice.
- Every generated route references one immutable topology revision.
- LSDB changes never mutate an existing route revision.
- A node applies a complete revision atomically, never a partial edge update.
- The controller rejects paths whose adjacency endpoints do not form a
  continuous sequence.
- Old acknowledgements cannot overwrite a newer desired revision.

## UI model

The global topology is an infrastructure view. Nodes and adjacencies are
editable there, with operational state visually separate from administrative
state.

The per-Connection topology is a route inspection view:

```text
ENTRY -> public ingress -> computed adjacencies -> EXIT
```

It shows the selected path revision, total cost, reason for selection and any
fallback candidates. Editing a Connection changes intent; editing an edge
changes the shared adjacency and displays the affected path count before
apply.

## Delivery phases

### Phase 0: stable ingress profiles

- Typed node/protocol settings.
- Impact count and generated configuration preview.
- Pull-based application and acknowledgement.

### Phase 1: adjacency foundation

- Independent adjacency identity and target port.
- Administrative cost and state.
- Agent capability and observation reports.
- Central LSDB and topology revisions.

### Phase 2: computed routes

- Connection intent references ingress and egress services.
- Deterministic path computation and failure status.
- Global topology editor and per-Connection path inspection.

### Phase 3: multi-hop publication and failover

- Destination-based bounded multi-hop generation.
- Alternate paths and hysteresis.
- Failure convergence and rollback tests.

### Phase 4: distributed LSAs

- Signed node-originated LSAs exchanged over mTLS.
- Panel acts as an observer and policy authority rather than the sole state
  distributor.
- Sequence, replay and partition reconciliation rules are mandatory before
  this phase is enabled.
