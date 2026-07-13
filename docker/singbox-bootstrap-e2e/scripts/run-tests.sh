#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -p marzban-singbox-bootstrap-e2e -f "$ROOT/docker-compose.yml")
TOOLBOX_IMAGE="${E2E_TOOLBOX_IMAGE:-marzban-singbox-e2e-toolbox:ubuntu22.04}"
PROTOCOLS=(hysteria2 tuic anytls vmess vless trojan shadowsocks)
EXPECTED_EXIT="172.30.10.12"
SING_BOX_BIN="/opt/marzban-singbox/bin/sing-box"
RUNTIME_DIR="$ROOT/runtime"
NODE_CONFIG_PATH="/etc/marzban-singbox/config.json"
NODE_LINK_DIR="/etc/marzban-singbox/node-link"
PUBLIC_CERT_DIR="/etc/marzban-singbox/certs"

if [ -n "${E2E_HTTP_PROXY:-}" ] && [ -z "${E2E_HTTPS_PROXY:-}" ]; then
  export E2E_HTTPS_PROXY="$E2E_HTTP_PROXY"
fi
export E2E_NO_PROXY="${E2E_NO_PROXY:-localhost,127.0.0.1,panel,node-a,node-b,node-c,node-d,whoami,172.30.10.0/24}"
if [ "${E2E_CLEAN_ROOM:-0}" = "1" ]; then
  COMPOSE+=(-f "$ROOT/docker-compose.clean-room.yml")
fi

cleanup() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    "${COMPOSE[@]}" ps -a || true
    "${COMPOSE[@]}" logs --tail=160 panel node-a node-b node-c node-d || true
    docker ps -a --format '{{.Names}} {{.Status}} {{.Image}}' | grep -E 'marzban-singbox-e2e|marzban-singbox-bootstrap-e2e' || true
  fi
  for node in node-a node-b node-c node-d; do
    docker rm -f "marzban-singbox-e2e-$node" >/dev/null 2>&1 || true
  done
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  if [ -d "$RUNTIME_DIR" ]; then
    cleanup_image="$TOOLBOX_IMAGE"
    if ! docker image inspect "$cleanup_image" >/dev/null 2>&1; then
      cleanup_image="ubuntu:22.04"
    fi
    docker run --rm -v "$RUNTIME_DIR:/runtime" "$cleanup_image" bash -lc 'rm -rf /runtime/*' >/dev/null 2>&1 || true
    rmdir "$RUNTIME_DIR" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

cd "$ROOT"

test -x "$ROOT/../../sing-box-1.13.14-linux-amd64/sing-box"

cleanup
mkdir -p "$RUNTIME_DIR"
if [ "${E2E_CLEAN_ROOM:-0}" != "1" ] && [ "${E2E_SKIP_TOOLBOX_BUILD:-0}" != "1" ]; then
  "${COMPOSE[@]}" build toolbox
elif [ "${E2E_CLEAN_ROOM:-0}" != "1" ]; then
  echo "Skipping toolbox image build; using $TOOLBOX_IMAGE"
fi
if [ "${E2E_SKIP_PANEL_BUILD:-0}" != "1" ]; then
  "${COMPOSE[@]}" build panel
else
  echo "Skipping panel image build; using existing marzban-bootstrap-e2e-panel:latest"
fi
"${COMPOSE[@]}" up -d panel
"${COMPOSE[@]}" run --rm provisioner
"${COMPOSE[@]}" up -d whoami node-a node-b node-c node-d

echo "Waiting for bootstrapped nodes..."
for node in node-a node-b node-c node-d; do
  for _ in $(seq 1 600); do
    if "${COMPOSE[@]}" exec -T "$node" bash -lc "test -f $NODE_CONFIG_PATH && ss -lntu | grep -q ':11001'" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  "${COMPOSE[@]}" exec -T "$node" bash -lc "test -f $NODE_CONFIG_PATH && ss -lntu | grep -q ':11001'"
done

TOKEN="$("${COMPOSE[@]}" exec -T node-a bash -lc "
curl -kfsS \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=admin&password=admin' \
  https://panel:8000/api/admin/token | jq -r '.access_token'
")"
[ -n "$TOKEN" ] && [ "$TOKEN" != "null" ]

echo "Waiting for link probes and multi-hop route activation..."
status_json='{}'
network_json='{}'
for _ in $(seq 1 240); do
  status_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
    curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/status
  ')"
  network_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
    curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/network
  ')"
  if jq -e '.routing.status == "active" and .routing.unreachable_connections == 0' <<<"$status_json" >/dev/null \
      && jq -e '[.adjacencies[].directions[].oper_state] | length == 10 and all(. == "up")' <<<"$network_json" >/dev/null \
      && jq -e '[.ingresses[].oper_state] | length == 28 and all(. == "up")' <<<"$network_json" >/dev/null; then
    break
  fi
  sleep 2
done
jq -e '.routing.status == "active" and .routing.unreachable_connections == 0' <<<"$status_json" >/dev/null
jq -e '[.adjacencies[].directions[].oper_state] | length == 10 and all(. == "up")' <<<"$network_json" >/dev/null
jq -e '[.ingresses[].oper_state] | length == 28 and all(. == "up")' <<<"$network_json" >/dev/null

echo "Checking node-link CA and mTLS config..."
for node in node-a node-b node-c node-d; do
  case "$node" in
    node-a) node_ip="172.30.10.11" ;;
    node-b) node_ip="172.30.10.12" ;;
    node-c) node_ip="172.30.10.13" ;;
    node-d) node_ip="172.30.10.14" ;;
  esac
  "${COMPOSE[@]}" exec -T "$node" env \
    NODE_CONFIG_PATH="$NODE_CONFIG_PATH" \
    NODE_LINK_DIR="$NODE_LINK_DIR" \
    PUBLIC_CERT_DIR="$PUBLIC_CERT_DIR" \
    NODE_IP="$node_ip" \
    SING_BOX_BIN="$SING_BOX_BIN" \
    bash -lc '
set -euo pipefail
openssl verify -CAfile "$NODE_LINK_DIR/ca.crt" "$NODE_LINK_DIR/node.crt" >/dev/null
openssl verify -CAfile "$NODE_LINK_DIR/ca.crt" "$NODE_LINK_DIR/client.crt" >/dev/null
openssl verify -CAfile "$PUBLIC_CERT_DIR/ca.crt" -verify_ip "$NODE_IP" "$PUBLIC_CERT_DIR/fullchain.pem" >/dev/null
grep -q "\"client_authentication\": \"require-and-verify\"" "$NODE_CONFIG_PATH"
grep -q "\"client_certificate_path\": \"$NODE_LINK_DIR/client.crt\"" "$NODE_CONFIG_PATH"
if jq -e ".outbounds[]? | select((.tag // \"\") | startswith(\"overlay-\")) | select(.tls.insecure == true)" "$NODE_CONFIG_PATH" >/dev/null; then
  echo "node-link outbound must not use insecure=true" >&2
  exit 1
fi
"$SING_BOX_BIN" check -c "$NODE_CONFIG_PATH" >/dev/null
'
done

echo "Checking node-a protocol profile rendering..."
"${COMPOSE[@]}" exec -T node-a bash -lc '
set -euo pipefail
config=/etc/marzban-singbox/config.json
jq -e '\''.inbounds[] | select(.type == "hysteria2" and ((.tag // "") | startswith("public-ingress-"))) | (.up_mbps == 250 and .down_mbps == 500 and .obfs.type == "salamander")'\'' "$config" >/dev/null
jq -e '\''.inbounds[] | select(.type == "tuic" and ((.tag // "") | startswith("public-ingress-"))) | (.congestion_control == "cubic" and .heartbeat == "15s")'\'' "$config" >/dev/null
jq -e '\''.inbounds[] | select(.type == "anytls" and ((.tag // "") | startswith("public-ingress-"))) | (.padding_scheme == ["stop=4", "0=16-32"])'\'' "$config" >/dev/null
jq -e '\''.outbounds[] | select(.type == "hysteria2") | .obfs.password == "e2e-hysteria2-obfs"'\'' /state/client-node-a-hysteria2.json >/dev/null
jq -e '\''.outbounds[] | select(.type == "anytls") | (.idle_session_timeout == "45s" and .min_idle_session == 2)'\'' /state/client-node-a-anytls.json >/dev/null
'

run_case() {
  local entry_node="$1"
  local protocol="$2"
  local output
  echo "==> $entry_node / $protocol expects exit $EXPECTED_EXIT"
  if ! output="$("${COMPOSE[@]}" exec -T node-a bash -lc "
set -euo pipefail
$SING_BOX_BIN check -c /state/client-$entry_node-$protocol.json >/dev/null
case "$protocol" in
  hysteria2|tuic|anytls|trojan)
    if jq -e '.outbounds[]? | select(.tls.enabled == true) | select(.tls.insecure == true)' /state/client-$entry_node-$protocol.json >/dev/null; then
      echo 'public TLS outbound must not use insecure=true' >&2
      exit 1
    fi
    jq -e '.outbounds[] | select(.tls.enabled == true)' /state/client-$entry_node-$protocol.json >/dev/null
    jq -e '.outbounds[] | select(.tls.enabled == true) | (.tls.certificate_path | length > 0)' /state/client-$entry_node-$protocol.json >/dev/null
    ;;
esac
$SING_BOX_BIN run -c /state/client-$entry_node-$protocol.json >/tmp/sing-box-client-$entry_node-$protocol.log 2>&1 &
pid=\$!
trap 'kill \$pid >/dev/null 2>&1 || true' EXIT
for _ in \$(seq 1 20); do
  if response=\$(curl --noproxy "" -fsS --connect-timeout 3 --max-time 8 -x socks5h://127.0.0.1:2080 http://whoami:8080/ 2>/tmp/curl-$protocol.err); then
    printf '%s\n' \"\$response\"
    exit 0
  fi
  sleep 1
done
echo 'curl failed:' >&2
cat /tmp/curl-$protocol.err >&2 || true
echo 'sing-box client log:' >&2
cat /tmp/sing-box-client-$entry_node-$protocol.log >&2 || true
exit 1
")"; then
    echo "$output"
    echo "Case $entry_node / $protocol failed; node logs follow."
    "${COMPOSE[@]}" logs --tail=160 node-a node-b node-c node-d whoami || true
    return 1
  fi

  echo "$output"
  if ! grep -q "\"remote_addr\": \"$EXPECTED_EXIT\"" <<<"$output"; then
    echo "Case $protocol returned unexpected exit; expected $EXPECTED_EXIT" >&2
    return 1
  fi
}

for entry_node in node-a node-b node-c node-d; do
  for protocol in "${PROTOCOLS[@]}"; do
    run_case "$entry_node" "$protocol"
  done
done

echo "Stopping node-a sing-box to verify listener health independently from its heartbeat..."
docker stop marzban-singbox-e2e-node-a >/dev/null
for _ in $(seq 1 30); do
  network_json="$("${COMPOSE[@]}" exec -T node-b env TOKEN="$TOKEN" bash -lc '
    curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/network
  ')"
  if jq -e '[.ingresses[] | select(.node_name == "node-a") | .oper_state] | length == 7 and all(. == "down")' <<<"$network_json" >/dev/null; then
    break
  fi
  sleep 1
done
jq -e '[.ingresses[] | select(.node_name == "node-a") | .oper_state] | length == 7 and all(. == "down")' <<<"$network_json" >/dev/null
status_json="$("${COMPOSE[@]}" exec -T node-b env TOKEN="$TOKEN" bash -lc '
  curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/status
')"
jq -e '.nodes[] | select(.name == "node-a") | .heartbeat_stale == false' <<<"$status_json" >/dev/null

echo "Restarting node-a sing-box and waiting for listener health recovery..."
docker start marzban-singbox-e2e-node-a >/dev/null
for _ in $(seq 1 120); do
  network_json="$("${COMPOSE[@]}" exec -T node-b env TOKEN="$TOKEN" bash -lc '
    curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/network
  ')"
  status_json="$("${COMPOSE[@]}" exec -T node-b env TOKEN="$TOKEN" bash -lc '
    curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/status
  ')"
  if jq -e '[.ingresses[] | select(.node_name == "node-a") | .oper_state] | length == 7 and all(. == "up")' <<<"$network_json" >/dev/null \
      && jq -e '.routing.status == "active"' <<<"$status_json" >/dev/null; then
    break
  fi
  sleep 2
done
jq -e '[.ingresses[] | select(.node_name == "node-a") | .oper_state] | length == 7 and all(. == "up")' <<<"$network_json" >/dev/null
jq -e '.routing.status == "active"' <<<"$status_json" >/dev/null

echo "Checking node pull-sync heartbeat and selected three-hop route..."
nodes_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/nodes
')"
node_a_link_port="$(jq -r '.[] | select(.name == "node-a") | .node_link_port' <<<"$nodes_json")"
[ -n "$node_a_link_port" ] && [ "$node_a_link_port" != "null" ]
if [ "$node_a_link_port" = "12443" ]; then
  echo "node-a did not replace the occupied node-link port" >&2
  exit 1
fi
node_b_id="$(jq -r '.[] | select(.name == "node-b") | .id' <<<"$nodes_json")"
node_c_id="$(jq -r '.[] | select(.name == "node-c") | .id' <<<"$nodes_json")"
node_d_id="$(jq -r '.[] | select(.name == "node-d") | .id' <<<"$nodes_json")"
node_a_id="$(jq -r '.[] | select(.name == "node-a") | .id' <<<"$nodes_json")"
[ -n "$node_b_id" ] && [ "$node_b_id" != "null" ]
[ -n "$node_c_id" ] && [ "$node_c_id" != "null" ]
status_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/status
')"
jq -e '.nodes[] | select(.name == "node-a") | (.sync_enabled == true and .sync_pending == false and .heartbeat_stale == false)' <<<"$status_json" >/dev/null
user_workspace="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/users/bootstrap_user/connections
')"
node_a_anytls_connection="$(jq -r --argjson node_id "$node_a_id" '.connections[] | select(.entry_node_id == $node_id and .protocol == "anytls") | .id' <<<"$user_workspace")"
route_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" CONNECTION_ID="$node_a_anytls_connection" bash -lc '
curl -kfsS -H "Authorization: Bearer $TOKEN" "https://panel:8000/api/singbox/connections/$CONNECTION_ID/route"
')"
jq -e '.status == "reachable" and .hop_count == 3 and .total_cost == 120 and ([.hops[].to_node_name] == ["node-c", "node-d", "node-b"])' <<<"$route_json" >/dev/null

apply_adjacency_state() {
  local adjacency_id="$1"
  local enabled="$2"
  "${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" ADJACENCY_ID="$adjacency_id" ENABLED="$enabled" bash -lc '
    set -euo pipefail
    workspace="$(curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/network)"
    draft="$(jq -c --argjson adjacency_id "$ADJACENCY_ID" --argjson enabled "$ENABLED" '\''{
      base_topology_revision: .topology_revision,
      ingresses,
      egresses,
      adjacencies: (.adjacencies | map(if .id == $adjacency_id then .enabled = $enabled else . end)),
      routing_policies
    }'\'' <<<"$workspace")"
    curl -kfsS \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      --data-binary "$draft" \
      https://panel:8000/api/singbox/network/drafts/apply >/dev/null
  '
}

network_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
  curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/network
')"
node_cd_adjacency_id="$(jq -r --argjson node_c_id "$node_c_id" --argjson node_d_id "$node_d_id" '
  .adjacencies[] | select(.node_a_id == $node_c_id and .node_b_id == $node_d_id) | .id
' <<<"$network_json")"

echo "Disabling and re-enabling node-c/node-d adjacency through the control-plane API..."
apply_adjacency_state "$node_cd_adjacency_id" false
for _ in $(seq 1 90); do
  status_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
    curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/status
  ')"
  if jq -e '.routing.status == "active"' <<<"$status_json" >/dev/null; then
    break
  fi
  sleep 1
done
apply_adjacency_state "$node_cd_adjacency_id" true
for _ in $(seq 1 120); do
  network_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
    curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/network
  ')"
  status_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
    curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/status
  ')"
  if jq -e --argjson adjacency_id "$node_cd_adjacency_id" '
      .adjacencies[] | select(.id == $adjacency_id) | [.directions[].oper_state] | all(. == "up")
    ' <<<"$network_json" >/dev/null \
      && jq -e '.routing.status == "active"' <<<"$status_json" >/dev/null; then
    break
  fi
  sleep 1
done
jq -e --argjson adjacency_id "$node_cd_adjacency_id" '
  .adjacencies[] | select(.id == $adjacency_id) | [.directions[].oper_state] | all(. == "up")
' <<<"$network_json" >/dev/null

echo "Clearing node-c session state to verify epoch-based restart recovery..."
old_epoch="$("${COMPOSE[@]}" exec -T node-c jq -r '.state_session.epoch' /var/lib/marzban-singbox/sync-state.json)"
"${COMPOSE[@]}" exec -T node-c bash -lc '
  jq "del(.state_session)" /var/lib/marzban-singbox/sync-state.json >/tmp/sync-state.json
  mv /tmp/sync-state.json /var/lib/marzban-singbox/sync-state.json
'
for _ in $(seq 1 60); do
  session_json="$("${COMPOSE[@]}" exec -T node-c jq -c '.state_session' /var/lib/marzban-singbox/sync-state.json)"
  if jq -e --argjson old_epoch "$old_epoch" '
      .epoch > $old_epoch and .snapshot_sequence > 0
    ' <<<"$session_json" >/dev/null; then
    break
  fi
  sleep 1
done
jq -e --argjson old_epoch "$old_epoch" '
  .epoch > $old_epoch and .snapshot_sequence > 0
' <<<"$session_json" >/dev/null

echo "Isolating node-c network to verify automatic failover..."
# Stopped or paused runtimes are intentionally healed by the sync agent. A
# bridge disconnect models a durable node partition across control and data
# traffic, including the network namespace shared by its sing-box container.
docker network disconnect \
  marzban-singbox-bootstrap-e2e_e2e_net \
  marzban-singbox-bootstrap-e2e-node-c-1
for _ in $(seq 1 120); do
  route_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" CONNECTION_ID="$node_a_anytls_connection" bash -lc '
    curl -kfsS -H "Authorization: Bearer $TOKEN" "https://panel:8000/api/singbox/connections/$CONNECTION_ID/route"
  ')"
  status_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
    curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/status
  ')"
  if jq -e '.status == "reachable" and .hop_count == 2 and .total_cost == 240 and ([.hops[].to_node_name] == ["node-d", "node-b"])' <<<"$route_json" >/dev/null \
      && jq -e '.routing.status == "active"' <<<"$status_json" >/dev/null; then
    break
  fi
  sleep 2
done
jq -e '.status == "reachable" and .hop_count == 2 and .total_cost == 240 and ([.hops[].to_node_name] == ["node-d", "node-b"])' <<<"$route_json" >/dev/null
run_case node-a anytls
docker network connect --ip 172.30.10.13 \
  marzban-singbox-bootstrap-e2e_e2e_net \
  marzban-singbox-bootstrap-e2e-node-c-1

echo "Checking oversized legacy agent report compatibility..."
"${COMPOSE[@]}" exec -T node-a bash -lc '
set -euo pipefail
. /etc/marzban-singbox/sync.env
config_hash="$(jq -r .config_hash /var/lib/marzban-singbox/sync-state.json)"
message="upgrade-start-$(printf "x%.0s" {1..4096})-upgrade-finished"
jq -n \
  --arg token "$NODE_SYNC_TOKEN" \
  --arg config_hash "$config_hash" \
  --arg message "$message" \
  "{token: \$token, config_hash: \$config_hash, success: true, message: \$message}" |
  curl -kfsS \
    -H "Content-Type: application/json" \
    --data-binary @- \
    https://panel:8000/api/singbox/nodes/sync/applied >/dev/null
'
nodes_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/nodes
')"
jq -e '.[] | select(.name == "node-a") | (.message | length == 1024 and startswith("[truncated]\n") and endswith("upgrade-finished"))' <<<"$nodes_json" >/dev/null

echo "All bootstrap e2e cases passed."
