#!/usr/bin/env bash
set -euo pipefail

PANEL_URL="${PANEL_URL:-https://panel:8000}"
PANEL_TLS_VERIFY="${PANEL_TLS_VERIFY:-false}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
STATE_DIR="${STATE_DIR:-/state}"
E2E_RUNTIME_ROOT="${E2E_RUNTIME_ROOT:-/workspace/projects/Marzban/docker/singbox-bootstrap-e2e/runtime}"
E2E_NODE_IMAGE="${E2E_NODE_IMAGE:-marzban-bootstrap-e2e-panel:latest}"
USER_NAME="${USER_NAME:-bootstrap_user}"
EXIT_NODE="${EXIT_NODE:-node-b}"
PROTOCOLS=(hysteria2 tuic anytls vmess vless trojan shadowsocks)

log() {
  printf '[bootstrap-e2e:provisioner] %s\n' "$*"
}

curl_args() {
  if [ "$PANEL_TLS_VERIFY" = "true" ]; then
    printf '%s\n' "-fsS"
  else
    printf '%s\n' "-fsSk"
  fi
}

api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  if [ -n "$data" ]; then
    curl "$(curl_args)" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -X "$method" \
      -d "$data" \
      "$PANEL_URL$path"
  else
    curl "$(curl_args)" \
      -H "Authorization: Bearer $TOKEN" \
      -X "$method" \
      "$PANEL_URL$path"
  fi
}

if [ "${E2E_INSTALL_DEPS:-false}" = "true" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl jq
fi

log "waiting for panel"
for _ in $(seq 1 90); do
  if curl "$(curl_args)" "$PANEL_URL/api/singbox/bootstrap.sh" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl "$(curl_args)" "$PANEL_URL/api/singbox/bootstrap.sh" >/dev/null

TOKEN="$(
  curl "$(curl_args)" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=$ADMIN_USERNAME&password=$ADMIN_PASSWORD" \
    "$PANEL_URL/api/admin/token" |
    jq -r '.access_token'
)"
[ -n "$TOKEN" ] && [ "$TOKEN" != "null" ]

install -d -m 0755 "$STATE_DIR"
nodes_json='[]'
for node in node-a node-b node-c node-d; do
  log "creating node $node"
  protocol_settings='{}'
  case "$node" in
    node-a)
      public_host="172.30.10.11"
      protocol_settings='{
        "hysteria2": {
          "up_mbps": 250,
          "down_mbps": 500,
          "ignore_client_bandwidth": false,
          "obfs_type": "salamander",
          "obfs_password": "e2e-hysteria2-obfs",
          "masquerade_url": "https://example.com"
        },
        "tuic": {
          "congestion_control": "cubic",
          "auth_timeout": "5s",
          "zero_rtt_handshake": false,
          "heartbeat": "15s"
        },
        "anytls": {
          "padding_scheme": ["stop=4", "0=16-32"],
          "idle_session_check_interval": "20s",
          "idle_session_timeout": "45s",
          "min_idle_session": 2
        }
      }'
      ;;
    node-b) public_host="172.30.10.12" ;;
    node-c) public_host="172.30.10.13" ;;
    node-d) public_host="172.30.10.14" ;;
  esac
  payload="$(
    jq -n \
      --arg name "$node" \
      --arg host "$public_host" \
      --argjson protocol_settings "$protocol_settings" \
      '{
        name: $name,
        public_host: $host,
        entry_enabled: true,
        exit_enabled: true,
        public_tls_mode: "ip-ca",
        protocol_settings: $protocol_settings,
        rebuild_links: true
      }'
  )"
  response="$(api POST /api/singbox/nodes "$payload")"
  nodes_json="$(jq -c --argjson node "$response" '. + [$node]' <<<"$nodes_json")"
done
printf '%s\n' "$nodes_json" >"$STATE_DIR/nodes.json"

exit_node_id="$(jq -r --arg name "$EXIT_NODE" '.[] | select(.name == $name) | .id' "$STATE_DIR/nodes.json")"
[ -n "$exit_node_id" ] && [ "$exit_node_id" != "null" ]
protocols_json="$(printf '%s\n' "${PROTOCOLS[@]}" | jq -R . | jq -s .)"
user_payload="$(jq -n --arg username "$USER_NAME" --argjson exit_node_id "$exit_node_id" --argjson protocols "$protocols_json" '{username: $username, exit_node_id: $exit_node_id, enabled_protocols: $protocols, data_limit: 0, expire: 0}')"
log "creating sing-box user $USER_NAME with exit policy $EXIT_NODE"
user_response="$(api POST /api/singbox/users "$user_payload")"
api POST /api/singbox/links/rebuild >/dev/null

node_a_id="$(jq -r '.[] | select(.name == "node-a") | .id' "$STATE_DIR/nodes.json")"
node_b_id="$(jq -r '.[] | select(.name == "node-b") | .id' "$STATE_DIR/nodes.json")"
node_c_id="$(jq -r '.[] | select(.name == "node-c") | .id' "$STATE_DIR/nodes.json")"
node_d_id="$(jq -r '.[] | select(.name == "node-d") | .id' "$STATE_DIR/nodes.json")"
network="$(api GET /api/singbox/network)"
adjacencies="$(jq -n \
  --argjson a "$node_a_id" --argjson b "$node_b_id" --argjson c "$node_c_id" --argjson d "$node_d_id" \
  '[
    {node_a_id: $a, node_b_id: $c, name: "node-a <-> node-c", enabled: true, directions: [
      {from_node_id: $a, to_node_id: $c, enabled: true, transport: "anytls", listen_port: 20001, admin_cost: 40, settings: {padding_scheme: ["stop=4", "0=16-32"], idle_session_check_interval: "12s", idle_session_timeout: "45s", min_idle_session: 2}},
      {from_node_id: $c, to_node_id: $a, enabled: true, transport: "anytls", listen_port: 20002, admin_cost: 40, settings: {padding_scheme: ["stop=4", "0=16-32"], idle_session_check_interval: "12s", idle_session_timeout: "45s", min_idle_session: 2}}
    ]},
    {node_a_id: $c, node_b_id: $d, name: "node-c <-> node-d", enabled: true, directions: [
      {from_node_id: $c, to_node_id: $d, enabled: true, transport: "anytls", listen_port: 20003, admin_cost: 40, settings: {}},
      {from_node_id: $d, to_node_id: $c, enabled: true, transport: "anytls", listen_port: 20004, admin_cost: 40, settings: {}}
    ]},
    {node_a_id: $b, node_b_id: $d, name: "node-d <-> node-b", enabled: true, directions: [
      {from_node_id: $d, to_node_id: $b, enabled: true, transport: "anytls", listen_port: 20005, admin_cost: 40, settings: {}},
      {from_node_id: $b, to_node_id: $d, enabled: true, transport: "anytls", listen_port: 20006, admin_cost: 40, settings: {}}
    ]},
    {node_a_id: $a, node_b_id: $d, name: "node-a <-> node-d backup", enabled: true, directions: [
      {from_node_id: $a, to_node_id: $d, enabled: true, transport: "hysteria2", listen_port: 20007, admin_cost: 200, settings: {obfs_type: "salamander", obfs_password: "overlay-e2e", ignore_client_bandwidth: true}},
      {from_node_id: $d, to_node_id: $a, enabled: true, transport: "hysteria2", listen_port: 20008, admin_cost: 200, settings: {obfs_type: "salamander", obfs_password: "overlay-e2e", ignore_client_bandwidth: true}}
    ]},
    {node_a_id: $b, node_b_id: $c, name: "node-c <-> node-b backup", enabled: true, directions: [
      {from_node_id: $c, to_node_id: $b, enabled: true, transport: "hysteria2", listen_port: 20009, admin_cost: 200, settings: {}},
      {from_node_id: $b, to_node_id: $c, enabled: true, transport: "hysteria2", listen_port: 20010, admin_cost: 200, settings: {}}
    ]}
  ]')"
network_draft="$(jq -n \
  --argjson network "$network" \
  --argjson adjacencies "$adjacencies" \
  '{
    base_topology_revision: $network.topology_revision,
    ingresses: ($network.ingresses | map(del(.node_name, .address))),
    egresses: ($network.egresses | map(del(.node_name))),
    adjacencies: $adjacencies,
    routing_policies: $network.routing_policies
  }')"
validation="$(api POST /api/singbox/network/drafts/validate "$network_draft")"
jq -e '.valid == true and .reachable_connections == .affected_connections' <<<"$validation" >/dev/null
api POST /api/singbox/network/drafts/apply "$network_draft" >"$STATE_DIR/network-apply.json"

for node in node-a node-b node-c node-d; do
  node_id="$(jq -r --arg name "$node" '.[] | select(.name == $name) | .id' "$STATE_DIR/nodes.json")"
  response="$(api POST "/api/singbox/nodes/$node_id/enrollment" '{"expires_in_seconds":3600}')"
  command="$(jq -r '.command' <<<"$response" | sed 's/| sudo bash/| bash/')"
  node_root="$E2E_RUNTIME_ROOT/$node"
  container_name="marzban-singbox-e2e-$node"
  network_container="marzban-singbox-bootstrap-e2e-${node}-1"
  cat >"$STATE_DIR/$node.sh" <<EOF
export COMPOSE_DIR="/opt/marzban-singbox"
export NODE_DOCKER_IMAGE="$E2E_NODE_IMAGE"
export NODE_DOCKER_CONTAINER_NAME="$container_name"
export NODE_DOCKER_PROJECT_NAME="$container_name"
export NODE_DOCKER_NETWORK_MODE="container:$network_container"
export NODE_DOCKER_CONFIG_SOURCE="$node_root/etc"
export NODE_DOCKER_CONFIG_TARGET="/etc/marzban-singbox"
export NODE_DOCKER_DATA_SOURCE="$node_root/data"
export NODE_DOCKER_DATA_TARGET="/var/lib/marzban-singbox"
$command --runtime docker
EOF
  chmod 0755 "$STATE_DIR/$node.sh"
done

public_subscription="$(jq -r '.public_subscription.singbox' <<<"$user_response")"
[ -n "$public_subscription" ] && [ "$public_subscription" != "null" ]
for entry_node in node-a node-b node-c node-d; do
  entry_node_id="$(jq -r --arg name "$entry_node" '.[] | select(.name == $name) | .id' "$STATE_DIR/nodes.json")"
  [ -n "$entry_node_id" ] && [ "$entry_node_id" != "null" ]
  subscription_url="${public_subscription}?entry_node_id=$entry_node_id"
  curl -kfsS "$PANEL_URL$subscription_url" >"$STATE_DIR/client-$entry_node-all.json"
  for protocol in "${PROTOCOLS[@]}"; do
    outbound_tag="$(jq -r --arg protocol "$protocol" '.outbounds[] | select(.type == $protocol) | .tag' "$STATE_DIR/client-$entry_node-all.json" | head -n 1)"
    [ -n "$outbound_tag" ] && [ "$outbound_tag" != "null" ]
    jq --arg tag "$outbound_tag" '.route.final = $tag' "$STATE_DIR/client-$entry_node-all.json" >"$STATE_DIR/client-$entry_node-$protocol.json"
  done
done

log "provisioning complete"
