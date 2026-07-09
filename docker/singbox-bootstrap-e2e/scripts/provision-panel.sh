#!/usr/bin/env bash
set -euo pipefail

PANEL_URL="${PANEL_URL:-http://panel:8000}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
STATE_DIR="${STATE_DIR:-/state}"
USER_NAME="${USER_NAME:-bootstrap_user}"
EXIT_NODE="${EXIT_NODE:-node-b}"
PROTOCOLS=(hysteria2 tuic anytls vmess vless trojan shadowsocks)

log() {
  printf '[bootstrap-e2e:provisioner] %s\n' "$*"
}

api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  if [ -n "$data" ]; then
    curl -fsS \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -X "$method" \
      -d "$data" \
      "$PANEL_URL$path"
  else
    curl -fsS \
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
  if curl -fsS "$PANEL_URL/api/singbox/bootstrap.sh" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS "$PANEL_URL/api/singbox/bootstrap.sh" >/dev/null

TOKEN="$(
  curl -fsS \
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
api POST /api/singbox/users "$user_payload" >/dev/null
api POST /api/singbox/links/rebuild >/dev/null

for node in node-a node-b node-c; do
  node_id="$(jq -r --arg name "$node" '.[] | select(.name == $name) | .id' "$STATE_DIR/nodes.json")"
  response="$(api POST "/api/singbox/nodes/$node_id/enrollment" '{"expires_in_seconds":3600}')"
  token="$(jq -r '.token' <<<"$response")"
  cat >"$STATE_DIR/$node.sh" <<EOF
curl -fsSL "$PANEL_URL/api/singbox/bootstrap.sh" | bash -s -- enroll-node --runtime docker --panel-url "$PANEL_URL" --enroll-token "$token" --node-name "$node" --node-host "$node"
EOF
  chmod 0755 "$STATE_DIR/$node.sh"
done

entry_node_id="$(jq -r '.[] | select(.name == "node-a") | .id' "$STATE_DIR/nodes.json")"
subscription="$(api GET "/api/singbox/subscription/$USER_NAME/sing-box?entry_node_id=$entry_node_id")"
jq '.config' <<<"$subscription" >"$STATE_DIR/client-all.json"
for protocol in "${PROTOCOLS[@]}"; do
  jq --arg tag "node-a-$protocol" '.route.final = $tag' "$STATE_DIR/client-all.json" >"$STATE_DIR/client-$protocol.json"
done

log "provisioning complete"
