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

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl jq

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
for node in node-a node-b node-c; do
  log "creating node $node"
  payload="$(
    jq -n \
      --arg name "$node" \
      --arg host "$node" \
      '{
        name: $name,
        public_host: $host,
        entry_enabled: true,
        exit_enabled: true,
        public_tls_mode: "ip-insecure",
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

for node in node-a node-b node-c; do
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

entry_node_id="$(jq -r '.[] | select(.name == "node-a") | .id' "$STATE_DIR/nodes.json")"
public_subscription="$(jq -r '.public_subscription.singbox' <<<"$user_response")"
[ -n "$public_subscription" ] && [ "$public_subscription" != "null" ]
subscription_url="${public_subscription}?entry_node_id=$entry_node_id"
curl -kfsS "$PANEL_URL$subscription_url" >"$STATE_DIR/client-all.json"
for protocol in "${PROTOCOLS[@]}"; do
  jq --arg tag "node-a-$protocol" '.route.final = $tag' "$STATE_DIR/client-all.json" >"$STATE_DIR/client-$protocol.json"
done

log "provisioning complete"
