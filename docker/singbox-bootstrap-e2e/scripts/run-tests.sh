#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -p marzban-singbox-bootstrap-e2e -f "$ROOT/docker-compose.yml")
PROTOCOLS=(hysteria2 tuic anytls vmess vless trojan shadowsocks)
EXPECTED_EXIT="172.30.10.12"
SING_BOX_BIN="/opt/marzban-singbox/bin/sing-box"
RUNTIME_DIR="$ROOT/runtime"
NODE_CONFIG_PATH="/etc/marzban-singbox/config.json"
NODE_LINK_DIR="/etc/marzban-singbox/node-link"

if [ -n "${E2E_HTTP_PROXY:-}" ] && [ -z "${E2E_HTTPS_PROXY:-}" ]; then
  export E2E_HTTPS_PROXY="$E2E_HTTP_PROXY"
fi
export E2E_NO_PROXY="${E2E_NO_PROXY:-localhost,127.0.0.1,panel,node-a,node-b,node-c,whoami,172.30.10.0/24}"

cleanup() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    "${COMPOSE[@]}" ps -a || true
    "${COMPOSE[@]}" logs --tail=160 panel node-a node-b node-c || true
    docker ps -a --format '{{.Names}} {{.Status}} {{.Image}}' | grep -E 'marzban-singbox-e2e|marzban-singbox-bootstrap-e2e' || true
  fi
  for node in node-a node-b node-c; do
    docker rm -f "marzban-singbox-e2e-$node" >/dev/null 2>&1 || true
  done
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  if [ -d "$RUNTIME_DIR" ]; then
    docker run --rm -v "$RUNTIME_DIR:/runtime" ubuntu:22.04 bash -lc 'rm -rf /runtime/*' >/dev/null 2>&1 || true
    rmdir "$RUNTIME_DIR" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

cd "$ROOT"

test -x "$ROOT/../../sing-box-1.13.14-linux-amd64/sing-box"

cleanup
mkdir -p "$RUNTIME_DIR"
if [ "${E2E_SKIP_PANEL_BUILD:-0}" != "1" ]; then
  "${COMPOSE[@]}" build panel
else
  echo "Skipping panel image build; using existing marzban-bootstrap-e2e-panel:latest"
fi
"${COMPOSE[@]}" up -d panel
"${COMPOSE[@]}" run --rm provisioner
"${COMPOSE[@]}" up -d whoami node-a node-b node-c

echo "Waiting for bootstrapped nodes..."
for node in node-a node-b node-c; do
  for _ in $(seq 1 600); do
    if "${COMPOSE[@]}" exec -T "$node" bash -lc "test -f $NODE_CONFIG_PATH && ss -lntu | grep -q ':11001'" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  "${COMPOSE[@]}" exec -T "$node" bash -lc "test -f $NODE_CONFIG_PATH && ss -lntu | grep -q ':11001'"
done

echo "Checking node-link CA and mTLS config..."
for node in node-a node-b node-c; do
  "${COMPOSE[@]}" exec -T "$node" env \
    NODE_CONFIG_PATH="$NODE_CONFIG_PATH" \
    NODE_LINK_DIR="$NODE_LINK_DIR" \
    SING_BOX_BIN="$SING_BOX_BIN" \
    bash -lc '
set -euo pipefail
openssl verify -CAfile "$NODE_LINK_DIR/ca.crt" "$NODE_LINK_DIR/node.crt" >/dev/null
openssl verify -CAfile "$NODE_LINK_DIR/ca.crt" "$NODE_LINK_DIR/client.crt" >/dev/null
grep -q "\"client_authentication\": \"require-and-verify\"" "$NODE_CONFIG_PATH"
grep -q "\"client_certificate_path\": \"$NODE_LINK_DIR/client.crt\"" "$NODE_CONFIG_PATH"
if jq -e ".outbounds[]? | select((.tag // \"\") | startswith(\"exit-\")) | select(.tls.insecure == true)" "$NODE_CONFIG_PATH" >/dev/null; then
  echo "node-link outbound must not use insecure=true" >&2
  exit 1
fi
"$SING_BOX_BIN" check -c "$NODE_CONFIG_PATH" >/dev/null
'
done

run_case() {
  local protocol="$1"
  local output
  echo "==> $protocol expects exit $EXPECTED_EXIT"
  if ! output="$("${COMPOSE[@]}" exec -T node-a bash -lc "
set -euo pipefail
$SING_BOX_BIN check -c /state/client-$protocol.json >/dev/null
$SING_BOX_BIN run -c /state/client-$protocol.json >/tmp/sing-box-client-$protocol.log 2>&1 &
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
cat /tmp/sing-box-client-$protocol.log >&2 || true
exit 1
")"; then
    echo "$output"
    echo "Case $protocol failed; node logs follow."
    "${COMPOSE[@]}" logs --tail=160 node-a node-b node-c whoami || true
    return 1
  fi

  echo "$output"
  if ! grep -q "\"remote_addr\": \"$EXPECTED_EXIT\"" <<<"$output"; then
    echo "Case $protocol returned unexpected exit; expected $EXPECTED_EXIT" >&2
    return 1
  fi
}

for protocol in "${PROTOCOLS[@]}"; do
  run_case "$protocol"
done

echo "Checking node pull-sync heartbeat and config apply..."
TOKEN="$("${COMPOSE[@]}" exec -T node-a bash -lc "
curl -kfsS \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=admin&password=admin' \
  https://panel:8000/api/admin/token | jq -r '.access_token'
")"
[ -n "$TOKEN" ] && [ "$TOKEN" != "null" ]
nodes_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/nodes
')"
node_b_id="$(jq -r '.[] | select(.name == "node-b") | .id' <<<"$nodes_json")"
node_c_id="$(jq -r '.[] | select(.name == "node-c") | .id' <<<"$nodes_json")"
[ -n "$node_b_id" ] && [ "$node_b_id" != "null" ]
[ -n "$node_c_id" ] && [ "$node_c_id" != "null" ]

"${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" NODE_C_ID="$node_c_id" bash -lc '
curl -kfsS -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"exit_node_id\":$NODE_C_ID}" \
  https://panel:8000/api/singbox/users/bootstrap_user/policy >/dev/null
'
for node in node-a node-b node-c; do
  "${COMPOSE[@]}" exec -T "$node" /usr/local/bin/marzban-singbox-sync >/tmp/"$node"-sync-to-c.log
done
"${COMPOSE[@]}" exec -T node-a bash -lc '
jq -e ".route.rules[]? | select(.outbound == \"exit-node-c\")" /etc/marzban-singbox/config.json >/dev/null
'
status_json="$("${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" bash -lc '
curl -kfsS -H "Authorization: Bearer $TOKEN" https://panel:8000/api/singbox/status
')"
jq -e '.nodes[] | select(.name == "node-a") | (.sync_enabled == true and .sync_pending == false and .heartbeat_stale == false)' <<<"$status_json" >/dev/null

"${COMPOSE[@]}" exec -T node-a env TOKEN="$TOKEN" NODE_B_ID="$node_b_id" bash -lc '
curl -kfsS -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"exit_node_id\":$NODE_B_ID}" \
  https://panel:8000/api/singbox/users/bootstrap_user/policy >/dev/null
'
for node in node-a node-b node-c; do
  "${COMPOSE[@]}" exec -T "$node" /usr/local/bin/marzban-singbox-sync >/tmp/"$node"-sync-to-b.log
done
"${COMPOSE[@]}" exec -T node-a bash -lc '
jq -e ".route.rules[]? | select(.outbound == \"exit-node-b\")" /etc/marzban-singbox/config.json >/dev/null
'

echo "All bootstrap e2e cases passed."
