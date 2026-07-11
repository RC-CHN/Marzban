# sing-box Link-State Overlay Routing

## Objective

Build an OSPF-like link-state control plane for a sing-box proxy overlay. This
does not put IP OSPF packets on the wire. Nodes advertise signed overlay
adjacencies and health, the control plane computes paths, and node agents apply
the resulting sing-box configuration.

The first production phase remains centrally computed and limits paths to one
overlay hop. The model must still support later multi-hop routing without
changing user connection semantics.

## Configuration ownership

| Object | Owns |
| --- | --- |
| Connection | User, public protocol, entry node, exit node, path constraints |
| Ingress profile | Shared settings for one public protocol on one node |
| Adjacency | Directed node-to-node transport, port, credentials and metrics |
| Computed path | Ordered adjacency IDs selected for a connection revision |
| Node | Identity, public address, capabilities, certificates and heartbeat |

Connections express intent. They must not embed generated outbound tags or a
specific intermediate route. For the current product, `max_hops=1` means the
computed path is either direct or one adjacency from entry to exit.

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
sequence
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

1. The agent probes configured neighbors over the actual node-link transport.
2. It submits an LSA containing a monotonic sequence number and observations.
3. The panel verifies node identity from the sync token and mTLS certificate.
4. Newer LSAs replace older state; expired hold timers mark links down.
5. A topology revision is created only when effective routing state changes.
6. Paths are recomputed and desired node configuration revisions are updated.
7. Agents pull, validate with `sing-box check`, apply atomically and acknowledge.

The initial target is a 5 second probe interval and 15 second hold timer.
Route changes use hysteresis so small latency differences do not flap paths.

## Path calculation

Use directed Dijkstra with a bounded hop count. The effective edge cost starts
with `admin_cost`; measured latency, loss and bandwidth may contribute only
when the operator enables dynamic metrics.

Tie breaking must be deterministic:

1. Lowest total cost.
2. Lowest hop count.
3. Lexicographically smallest adjacency ID sequence.

The current compatibility policy is:

```text
max_hops = 1
metric_mode = admin_only
failover = disabled
```

Future policies may enable preferred regions, avoided nodes, minimum
bandwidth, failover candidates and multi-hop limits.

## Loop and revision safety

sing-box proxy routes do not carry an IP TTL across application-level hops.
Loop prevention therefore belongs to the control plane:

- A computed path cannot contain a node twice.
- Every generated route references one immutable topology revision.
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

### Phase 2: computed one-hop

- Connection route intent with `max_hops=1`.
- Deterministic path computation and failure status.
- Global topology editor and per-Connection path inspection.

### Phase 3: multi-hop and failover

- Bounded multi-hop generation.
- Alternate paths and hysteresis.
- Failure convergence and rollback tests.

### Phase 4: distributed LSAs

- Signed node-originated LSAs exchanged over mTLS.
- Panel acts as an observer and policy authority rather than the sole state
  distributor.
- Sequence, replay and partition reconciliation rules are mandatory before
  this phase is enabled.
