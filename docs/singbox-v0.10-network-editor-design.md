# sing-box v0.10 Network Editor and Multi-hop Routing Design

## Status

- Target release: `v0.10.0`
- Status: implementation baseline
- Scale target: at most 10-20 managed nodes
- Control plane: centralized SPF and configuration publication
- Data plane: sing-box application-level proxy hops over mTLS

This document is the source of truth for the v0.10 network model. The older
`singbox-link-state-routing.md` remains the protocol roadmap; where it differs
from this document, this document wins.

## Product model

An operator builds an overlay network from four kinds of objects:

1. **Server**: a managed machine running the node agent and sing-box.
2. **Ingress service**: one public protocol/port/profile tuple attached to
   exactly one server.
3. **Egress service**: an allowed exit attached to exactly one server. v0.10
   initially implements only `direct` egress.
4. **Adjacency**: a logical connection between two servers. Each direction is
   configured and observed independently.

A user Connection contains intent, not a manually selected route:

```text
user + ingress service + egress service + routing policy
```

The controller computes the intermediate path. The subscription exposes only
the ingress server address, ingress protocol, ingress port and user credential.
It does not expose the egress or any overlay hop.

## Goals

- Support arbitrary directed multi-hop paths from the first v0.10 schema.
- Keep the normal user workflow to selecting an ingress and an egress.
- Allow independent transport, port, cost and state in each adjacency direction.
- Converge to another valid path after a link or node failure.
- Publish route changes without loops or partially installed paths.
- Explain the selected path and alternatives in the UI.
- Migrate existing v0.9.6 nodes, public protocol profiles and one-hop links.
- Keep a small deployment operational without external routing infrastructure.

## Non-goals for v0.10

- Sending or receiving IP OSPF packets.
- A fully distributed control plane or peer-to-peer LSA flooding.
- Dynamic cost derived from RTT, loss or bandwidth by default.
- Arbitrary raw sing-box JSON in the editor.
- General-purpose IP routing, NAT orchestration or site-to-site subnets.
- Per-user selection of individual intermediate nodes.

## Editor information architecture

### Global Network Editor

The global editor is the authoritative infrastructure workspace. `Topology`
and `Resources` are two views over the same in-memory draft; switching views
does not save, discard or fork the draft. The top-level Save and Discard actions
therefore have identical semantics in both views.

`Topology` contains server nodes, attached service nodes and adjacency edges.
Apache ECharts renders the complete graph through its Canvas force layout,
keeping animation and pointer movement outside React rendering. Servers,
ingress services and egress services are compact circles distinguished by color
and size. Ingress services share one blue type color and egress services share
one amber type color; protocols do not introduce additional colors. Server
status rings and edges use green, red or gray for operational state. Server
names are always visible; hovering other objects reveals their identity.
Clicking an object opens its inspector, with right-click retained as a secondary
action. Edges show only their name on hover.

The force layout settles after structural changes. Polling, heartbeat updates
and unchanged workspace revisions are rejected by a graph structure signature
and must not restart it. Manual movement and layout state never make the draft
dirty or create a revision. The first structural layout is fitted into the
canvas with a fixed safe margin; later operator pan and zoom are preserved.
`Re-layout` is the only operator action that resets an unchanged graph.

All topology construction happens in the canvas:

- Right-click empty space to add an unbound ingress or direct egress at that
  position, add a routing policy, or enter server management.
- A new service initially owns only its name, protocol, port and typed profile.
  It does not ask for a server in the creation flow.
- The pointer tool left-drags circles to move them and left-drags empty canvas
  to pan the graph. The link tool left-drags from any part of one circle to
  another to create a connection. There is no fixed source or target handle,
  and right-drag is never used by the editor.
- During a link drag, the source has an amber ring, valid targets have a green
  ring and invalid targets have a red ring. Dropping on empty canvas cancels.
- Existing server adjacencies, existing service attachments and duplicate
  listen ports on the target server are invalid drop targets. Port conflicts
  include enabled ingress services and enabled adjacency directions that listen
  on the target server.
- Connecting a service and a server creates or replaces its single attachment;
  endpoint order has no meaning.
- Connecting two servers creates one adjacency with two independently editable
  directions and automatically allocated target ports.
- Moving one circle near another never changes the topology.

A visual server-to-server adjacency contains two directed directions. Selecting
the edge opens an inspector split into `General`, `A -> B` and `B -> A` tabs.
Only one direction's fields are displayed at a time. Each direction edits:

- Administrative enabled state.
- Transport and target listen port.
- Administrative cost from 1 through 65535; default 100.
- Typed transport settings.
- Probe interval and hold time when advanced settings are expanded.

Operational state, RTT, loss, last probe and failure message are read-only and
must not be visually confused with administrative settings.

### Resource view and inspectors

`Resources` is the complete non-graph management surface. It has separate
tables for Servers, Ingresses, Egresses, Adjacencies and Policies. Table rows
are selectable, expose the important identity and operational fields, and open
the same draft inspector used by the topology. Servers link to their existing
server detail page. Adding or editing a resource here must produce the same
validated payload as the equivalent graph operation.

Inspectors are grouped by operator task instead of exposing one large form:

- Ingress: `General`, `TLS`, and protocol-specific settings.
- Egress: one compact general form while only `direct` exists.
- Adjacency: `General` plus one tab per directed edge.
- Policy: `General` and node constraints.

On desktop, the resource table and a 460 px sticky inspector are shown side by
side. The inspector scrolls independently when its active category exceeds the
viewport. On narrow screens, the inspector flows below the horizontally
scrollable table. Advanced categories are lazy-rendered so hidden settings do
not add visual or keyboard-navigation noise.

List status reflects the current draft. When a saved resource differs from its
latest observation, both the list and inspector show `provisioning`; the list
must not continue to show the old `up` state while edited runtime fields await
apply.

### Language and operator guidance

The control-plane routes provide Simplified Chinese and English through the
shared i18next resource files. A stored language preference wins; a new browser
session without a preference starts in Simplified Chinese. Switching language
updates the current route and draft in place.

Short muted helper text is reserved for configuration semantics that are easy
to misinterpret, including advertised subscription addresses, public ingress
TLS versus the internal node CA, directional cost, maximum hops and the shared
Topology/Resources draft. It must not become a second documentation layer or
repeat self-explanatory field labels.

### Connection Editor

The user editor has two modes:

- **Edit intent**: choose ingress service, egress service and routing policy.
- **Inspect route**: view the currently applied path and its status.

The route view is computed and read-only:

```text
ENTRY -> ingress service -> server -> zero or more servers -> egress service -> EXIT
```

It shows total cost, hop count, topology revision, route revision, convergence
state and the reason this path won. A `Why this path?` panel lists up to three
valid candidates and the first rejection reason for invalid candidates.

Connections never edit a server's shared public port. Editing a port means
editing the selected ingress service and therefore shows the number of affected
Connections before apply.

### Draft and apply workflow

Graph mutations operate on a draft topology:

1. Edit, connect, add or remove objects locally.
2. `Save` validates ports, reachability, capabilities and affected routes.
3. The save review shows impact counts; confirmation creates one immutable
   topology revision.
4. `Discard` restores the last server topology without changing local layout.
5. The rollout controller stages node route revisions and reports progress.

Dirty detection compares semantic topology content and excludes
`base_topology_revision`, observed link state, selection and coordinates. A
heartbeat or link-state refresh therefore cannot manufacture a new draft, and
Save remains disabled when no logical change exists.

Closing or reloading a browser tab with a dirty editor triggers the browser's
discard prompt. The current React Router 6.4 shell does not intercept internal
sidebar navigation, so the persistent Draft badge and explicit Discard action
remain the in-app safeguards. There is no auto-apply.
Node deletion remains a separate decommission operation and is blocked while a
Connection, enabled adjacency, policy constraint or retained route hop
references the node. Disabled, unreferenced services and adjacencies are
removed with the node.

## Domain model

### Server

`singbox_nodes` remains the managed server identity. The following v0.9 fields
become transitional after migration:

- `entry_enabled`
- `exit_enabled`
- `node_link_port`
- `public_ports`
- `protocol_settings`

They are retained during a compatibility window, then removed after all callers
use services and adjacency directions.

### Ingress service

```text
id
node_id
name
protocol
listen_port
enabled
tls_mode
tls_profile
protocol_profile
advertised_address_id (nullable)
created_at
updated_at
```

The service does not store a literal public address by default. Its subscription
address is derived from the attached server's primary advertised address. The
optional `advertised_address_id` selects another validated server address.

Constraint: `(node_id, transport_family, listen_port)` must not conflict.
Hysteria2 and TUIC consume UDP; AnyTLS, VMess, VLESS and Trojan consume TCP;
Shadowsocks may consume both TCP and UDP.

### Egress service

```text
id
node_id
name
kind                 # direct in v0.10
enabled
settings
created_at
updated_at
```

Egress identity is server-bound. `Direct @ Frankfurt` and `Direct @ Tokyo` are
different route destinations even though both use the same outbound type.

### Adjacency and direction

`adjacencies` owns the visual pairing:

```text
id
node_a_id
node_b_id
name
enabled
created_at
updated_at
```

`adjacency_directions` owns routable directed edges:

```text
id
adjacency_id
from_node_id
to_node_id
enabled
transport
listen_port
admin_cost
settings
credential_generation
generation
created_at
updated_at
```

There are normally two direction rows per adjacency. A unidirectional adjacency
is valid. `listen_port` is allocated on `to_node_id`; each enabled direction has
an independent target listener and therefore can safely use different settings.
mTLS is mandatory and is not an editable boolean.

### Link-state observation

Configuration and observations are separate records:

```text
adjacency_direction_id
reporting_node_id
resource_generation
session_epoch
snapshot_sequence
oper_state            # unknown, up, degraded, down
rtt_ms
loss_ppm
bandwidth_mbps
observed_at
hold_expires_at
message
```

Freshness is compared using `(resource_generation, session_epoch,
snapshot_sequence)`. Resource configuration changes invalidate old
observations, and a restarted agent receives a higher epoch so its snapshot
sequence can safely restart at one. An expired hold timer makes the direction
unavailable to SPF.

### Connection intent

`singbox_user_connections` changes from node/protocol fields to service intent:

```text
ingress_service_id
egress_service_id
routing_policy_id
```

Credentials remain on the Connection. During migration, the existing protocol
and entry/exit node columns remain populated for compatibility, but new code
must treat service IDs as authoritative.

The initial routing policy is:

```text
metric_mode = admin_only
max_hops = 8
allow_degraded = false
failover = true
required_nodes = []
avoided_nodes = []
```

Eight hops is an operational guardrail, not a one-hop data-model restriction.

### Revisions and calculated state

```text
topology_revisions
  id, number, status, content_hash, created_by, created_at

route_revisions
  id, number, topology_revision_id, status, created_at, activated_at

computed_paths
  id, route_revision_id, connection_id, total_cost, hop_count, status, reason

computed_path_hops
  computed_path_id, position, adjacency_direction_id, from_node_id, to_node_id

node_route_revisions
  node_id, route_revision_id, desired_hash, applied_hash, state, message
```

Topology revisions snapshot operator intent. Route revisions snapshot the
calculated forwarding plan. Historical records make apply and failure
diagnosis deterministic and provide the basis for a later operator-initiated
rollback API.

## Path calculation

### Effective graph

An edge is eligible when all conditions hold:

- Adjacency and direction are administratively enabled.
- The direction is operationally up.
- Policy constraints allow both endpoints.

Endpoint references and target-port conflicts are checked while validating a
draft. Transport capabilities are reported for operator diagnostics. At
runtime, authenticated probe state is authoritative; panel heartbeat state
alone does not withdraw a still-working data path.

During initial provisioning, an operator may explicitly validate a direction as
`provisioning`; it cannot carry user routes until both endpoint agents report the
new revision applied and the first probe succeeds.

### SPF algorithm

Run bounded uniform-cost search from each distinct ingress server to each
distinct egress server referenced by an enabled Connection. State includes the
visited node sequence and hop count so `max_hops` and loop prevention are
enforced during exploration.

Initial effective cost is exactly `admin_cost`. RTT, loss and bandwidth are
collected and displayed but do not affect selection in `admin_only` mode.

Candidate ordering is deterministic:

1. Lowest total effective cost.
2. Lowest hop count.
3. Lexicographically smallest adjacency direction ID sequence.

The selected path must not contain a repeated server. A same-server ingress and
egress produces a zero-hop path. No valid path marks the Connection degraded and
does not silently change its requested egress.

SPF is pure code with no database or sing-box dependencies. Its input and output
are immutable typed objects so it can be exhaustively unit tested.

### Recalculation triggers

Recompute when effective routing state changes:

- An adjacency direction, cost or service attachment changes.
- An observation crosses `up/down` or hold expiry.
- A node enters or leaves an eligible state.
- A Connection or routing policy changes.

RTT-only changes do not create topology revisions in `admin_only` mode.
Recomputation is debounced, but a down event bypasses the normal debounce.

## Multi-hop data plane

### Destination forwarding

Intermediate nodes forward by an internal destination route identity, not by a
public user identity. For an egress service `egress-7` and route revision 42, a
path may install identities conceptually named:

```text
route-r42-egress-7-hop-0
route-r42-egress-7-hop-1
route-r42-egress-7-hop-2
```

Example path:

```text
Tokyo -> Singapore -> Warsaw -> Frankfurt -> Direct @ Frankfurt
```

Generated forwarding state is:

```text
Tokyo:     public Connection auth -> outbound to Singapore
Singapore: internal hop auth      -> outbound to Warsaw
Warsaw:    internal hop auth       -> outbound to Frankfurt
Frankfurt: internal hop auth       -> direct outbound
```

sing-box `auth_user` rules select the next-hop outbound after each node
terminates its incoming proxy connection. Public credentials exist only at the
ingress. Connections selecting the same path and egress may share internal
forwarding state; internal credentials are never included in subscriptions.

For v0.10, route credentials are generated per `(route revision, egress service,
routing policy, adjacency direction)`. The routing policy is the route class;
including it prevents two constrained paths that merge on one incoming edge but
need different next hops from sharing an ambiguous identity. This also prevents
one leaked direction credential from being accepted on unrelated listeners and
makes old revisions drainable.

### Loop prevention

Application-level proxy hops have no useful overlay TTL. The controller must
therefore reject a route unless:

- No server repeats in the path.
- Hop endpoints form one continuous sequence.
- Every generated rule belongs to one immutable route revision.
- A node receives one complete desired revision atomically.
- An acknowledgement can only advance its matching desired revision.
- An internal identity is accepted only by its intended target listener.

Agents run `sing-box check` before replacing the active configuration. A failed
check leaves the previous revision active.

### Make-before-break publication

A route revision is installed from destination to source:

1. Install the egress node's final rule.
2. Install intermediate nodes in reverse path order.
3. Wait for every required node to acknowledge and for new directions to probe
   up.
4. Switch ingress nodes last.
5. Mark the new revision active.
6. Drain the old revision for a bounded interval.
7. Remove old internal identities and outbounds, again source to destination.

If staging fails before ingress switches, discard the staged revision. If an
ingress switch partially fails, keep both revisions installed, direct new
Connections only to the last complete revision, and surface a rollout error.

Changing an existing direction's transport, target port or transport profile
is not merged with an active revision on the same listener. The apply is
rejected for zero-downtime publication; the operator must first move traffic to
another adjacency or use an explicit maintenance rollout. Cost and
administrative-state changes do not have this restriction.

## Agent protocol

The node sync request grows capability and observation sections:

```json
{
  "state_session": {
    "instance_id": "node-agent-7f1a...",
    "epoch": 4,
    "lease_token": "...",
    "snapshot_sequence": 81
  },
  "capabilities": {
    "sing_box_version": "...",
    "supported_transports": ["anytls", "hysteria2"],
    "runtime": "docker",
    "addresses": ["203.0.113.10"]
  },
  "observations": [
    {
      "adjacency_direction_id": 12,
      "sequence": 81,
      "resource_generation": 3,
      "state": "up",
      "rtt_ms": 42,
      "loss_ppm": 0
    }
  ]
}
```

The response acknowledges the state session, including its epoch, lease expiry
and accepted snapshot sequence. It also includes `topology_revision`,
`route_revision`, complete generated configuration, resource generations and
probe instructions. Existing hash-based idempotency remains. The agent never
computes policy paths in v0.10.

Probes use the configured adjacency transport and mTLS identity, not ICMP alone.
TCP/UDP reachability may be recorded as diagnostics but cannot mark the proxy
direction up without completing transport authentication.

## API surface

The first implementation exposes a normalized, revision-aware workspace. All
topology objects are edited in one draft and committed atomically; this avoids
partially applying a service without its adjacency or policy changes:

```text
GET            /api/singbox/network
POST           /api/singbox/network/drafts/validate
POST           /api/singbox/network/drafts/apply
GET            /api/singbox/connections/{id}/route
```

The route response includes the selected path and up to three deterministic
candidates. Revision history is persisted in `singbox_topology_revisions` and
`singbox_route_revisions`; a separate history endpoint is deferred until a
rollback UI is implemented.

Mutation payloads use optimistic concurrency with the base topology revision.
Applying a stale draft returns `409` with the new revision and conflicting
objects. Validation returns structured field/object errors suitable for graph
annotations.

## Security

- Node-to-node transport always uses the panel CA and mutual TLS.
- Enrollment remains the trust bootstrap; private keys are generated on nodes.
- Adjacency credentials are random, scoped and revisioned.
- Secrets are omitted from graph APIs, logs, diffs and route explanations.
- Only sudo administrators can mutate topology or publish revisions.
- Draft validation and apply endpoints use the existing API rate limiter.
- Applied topology revisions record the actor, immutable snapshot, content hash
  and result. Observed link-state revisions identify the reporting node.
- Raw restart commands and arbitrary transport JSON are not accepted from the
  network editor.

## Migration from v0.9.6

Migration is additive and resumable:

1. Create new service, adjacency, observation and revision tables.
2. For every entry-enabled node and protocol port, create one ingress service
   using the node's existing protocol profile.
3. For every exit-enabled node, create `Direct @ <node>`.
4. Convert each `SingBoxNodeLink` into one adjacency direction. Pair opposite
   directions under one visual adjacency where possible.
5. Allocate an independent target port for every migrated direction. Do not
   reuse the old shared `node_link_port` when multiple directions target a node.
6. Map every Connection to the matching ingress and egress service.
7. Keep the runtime on the compatibility path until an administrator validates
   and applies the first topology revision.
8. Keep reading old columns only when service IDs are null during the transition.

The database migration must not change active node configuration by itself.
The first explicit topology apply performs the runtime transition using
make-before-break publication.

## Implementation packages

Backend boundaries should be explicit:

```text
app/core/singbox/routing/types.py       immutable graph and path types
app/core/singbox/routing/spf.py         bounded directed uniform-cost search
app/core/singbox/routing/compiler.py    paths to per-node forwarding intent
app/core/singbox/routing/publication.py rollout state machine
app/core/singbox/network.py             workspace, validation, LSDB and revisions
```

Configuration rendering consumes compiled forwarding intent. It must not query
Connections and independently rediscover paths.

The frontend should use one normalized workspace model. React Flow nodes and
edges are view objects derived from it, not the persisted API shape. Inspector
forms own typed drafts and commit back to the workspace draft.

## Delivery plan

### Milestone 1: model and SPF

- Add additive schema and typed APIs.
- Implement services and independent adjacency directions.
- Implement bounded directed uniform-cost search and deterministic tie breaking.
- Add migration preview without changing runtime configuration.

Acceptance:

- Unit tests cover zero-hop, one-hop, multi-hop, asymmetric cost, disabled/down
  links, cycles, equal-cost ties, hop bounds and no-route results.
- Existing v0.9.6 tests remain green.

### Milestone 2: route compiler and publication

- Compile selected paths to per-node forwarding intent.
- Generate scoped internal credentials and sing-box rules.
- Add route revisions and two-phase internal-first rollout.
- Extend agent capability, probe and acknowledgement protocol.

Acceptance:

- A four-node Ubuntu 22.04 container stack passes a real three-hop request.
- Killing either an intermediate sing-box or its transport causes convergence to
  a valid alternate path without manual node changes.
- Config validation failure preserves the prior active path.

### Milestone 3: global editor

- Implement server, ingress, egress and adjacency graph objects.
- Add directional edge inspector, cost editing and operational overlays.
- Add draft validation, impact review and rollout progress.

Acceptance:

- Desktop and mobile Playwright flows cover move, edit, validate, impact review
  and explicit apply states. Stale-revision conflict is covered at the API
  validation layer.
- No graph mutation reaches production before explicit apply.

### Milestone 4: Connection UX and hardening

- Switch Connection editor to ingress/egress intent.
- Add path explanation, candidates and convergence status.
- Complete migration tooling, revision history UI and production documentation.

Acceptance:

- Subscriptions remain valid while the selected middle path changes.
- Existing public protocols still pass real client-to-exit tests.
- Upgrade from a v0.9.6 database is tested and rollback limitations documented.

## Test infrastructure

The existing cached control-panel image remains the base. E2E must use one panel
image plus ordinary Ubuntu 22.04 node containers enrolled through
`singbox-bootstrap.sh`. Node images and downloaded binaries are cached by Docker
layers and named volumes; tests must not download sing-box once per case.

Required topology fixtures:

- Linear four-node path for true multi-hop.
- Diamond topology for cost selection and failover.
- Directed asymmetric topology.
- Disconnected and cyclic invalid drafts.

Tests verify the observed public egress address, not only process health or TCP
connectivity. Failure tests wait for the alternate route revision to become
active before sending post-failure user traffic.

## POC verification record

The 2026-07-11 local POC uses one packaged panel and four ordinary Ubuntu 22.04
toolbox containers enrolled exclusively through `singbox-bootstrap.sh`.

- 28 real public cases pass: four ingress nodes multiplied by Hysteria2, TUIC,
  AnyTLS, VMess, VLESS, Trojan and Shadowsocks.
- Every case observes node-b as the actual public egress.
- The primary Connection uses `node-a -> node-c -> node-d -> node-b` with cost
  120 and three overlay hops.
- Disconnecting node-c from the Docker bridge withdraws its authenticated
  probes. The controller excludes the failed node from rollout quorum, stages
  the remaining nodes, and switches to `node-a -> node-d -> node-b` with cost
  240 without manual node configuration.
- The backup direction uses Hysteria2 salamander obfuscation; the primary
  AnyTLS direction uses non-default padding and idle-session settings. Health
  probes and user traffic both use those profiles.
- Desktop/mobile Playwright, migration-from-v0.9.6, deterministic SPF,
  publication failure and node-isolation tests pass.

Deferred beyond this POC are a revision-history/rollback UI, dynamic measured
metrics, distributed LSA exchange and in-app navigation blocking for dirty
drafts. These are not required for the centralized `admin_only` v0.10 data
plane, but the revision and observation schema keeps them possible.

## v0.10 completion criteria

v0.10.0 is ready to tag only when all of the following are true:

- The persisted model has no one-hop-only assumption.
- A real three-hop data path works in the Ubuntu 22.04 stack.
- Cost changes deterministically alter the selected path.
- A failed direction converges to a tested alternate route.
- The global editor can safely draft, validate and apply the topology.
- A Connection selects services and displays its computed route.
- Subscriptions do not change when only intermediate hops change.
- Node rollout is versioned, internal-first and observable; public ingress
  switches only after every participating node has staged internal forwarding.
- Upgrade and production operation documentation is complete.
