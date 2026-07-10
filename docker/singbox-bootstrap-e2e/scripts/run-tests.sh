#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -p marzban-singbox-bootstrap-e2e -f "$ROOT/docker-compose.yml")
PROTOCOLS=(hysteria2 tuic anytls vmess vless trojan shadowsocks)
EXPECTED_EXIT="172.30.10.12"
NODE_CONFIG_PATH="/etc/marzban-singbox/config.json"
NODE_LINK_DIR="/etc/marzban-singbox/node-link"
SING_BOX_BIN="/opt/marzban-singbox/bin/sing-box"

if [ -n "${E2E_HTTP_PROXY:-}" ] && [ -z "${E2E_HTTPS_PROXY:-}" ]; then
  export E2E_HTTPS_PROXY="$E2E_HTTP_PROXY"
fi
export E2E_NO_PROXY="${E2E_NO_PROXY:-localhost,127.0.0.1,panel,node-a,node-b,node-c,whoami,172.30.10.0/24}"

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$ROOT"

test -x "$ROOT/../../sing-box-1.13.14-linux-amd64/sing-box"

cleanup
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
  for _ in $(seq 1 180); do
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

echo "All bootstrap e2e cases passed."
