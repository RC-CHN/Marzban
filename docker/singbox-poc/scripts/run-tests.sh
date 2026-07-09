#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml")
CASES=(
  hysteria2
  hysteria2-direct
  hysteria2-node-b
  hysteria2-node-c
  tuic
  anytls
  vmess
  vless
  trojan
  shadowsocks
)

cd "$ROOT"

python3 "$ROOT/scripts/generate.py"

echo "Checking bootstrap script..."
bash -n "$ROOT/../../scripts/singbox-bootstrap.sh"
bash "$ROOT/../../scripts/singbox-bootstrap.sh" check >/tmp/singbox-bootstrap-check.log

docker build -t marzban-singbox-poc:ubuntu2204 "$ROOT"

echo "Checking generated node configs..."
for config in generated/node-a/config.json generated/node-b/config.json generated/node-c/config.json; do
  "${COMPOSE[@]}" run --rm -T client sing-box check -c "/poc/$config"
done
grep -q '"client_authentication": "require-and-verify"' "$ROOT/generated/node-a/config.json"
grep -q '"client_certificate_path": "/etc/sing-box/node-link/client.crt"' "$ROOT/generated/node-a/config.json"
if grep -q '"insecure": true' "$ROOT/generated/node-a/config.json"; then
  echo "node-link mTLS config must not use insecure=true" >&2
  exit 1
fi

echo "Checking generated client configs..."
for config in generated/clients/*.json; do
  "${COMPOSE[@]}" run --rm -T client sing-box check -c "/poc/$config"
done

echo "Checking generated subscription config..."
"${COMPOSE[@]}" run --rm -T client sing-box check -c /poc/generated/subscriptions/sing-box.json
for protocol in hysteria2 tuic anytls vmess vless trojan shadowsocks; do
  grep -q "node-a-$protocol" "$ROOT/generated/subscriptions/clash.yaml"
done

echo "Checking ten-node generated configs..."
for config in generated/ten-node/*/config.json; do
  "${COMPOSE[@]}" run --rm -T client sing-box check -c "/poc/$config"
done

echo "Running runtime smoke..."
"${COMPOSE[@]}" run --rm -T client python3 /poc/scripts/runtime-smoke.py

echo "Running main.py sing-box standalone smoke..."
timeout 8 docker run --rm \
  --network singbox-poc_poc_net \
  -v "$ROOT/../..:/repo:ro" \
  -v "$ROOT/generated/certs:/etc/sing-box/certs:ro" \
  -v "$ROOT/generated/node-link:/etc/sing-box/node-link:ro" \
  marzban-singbox-poc:ubuntu2204 \
  bash -lc 'cd /repo && CORE_RUNTIME=singbox SINGBOX_STANDALONE_CONFIG_PATH=/repo/docker/singbox-poc/generated/node-a/config.json python3 main.py' \
  >/tmp/singbox-poc-main.log 2>&1 || status=$?
status="${status:-0}"
if [ "$status" != "124" ]; then
  cat /tmp/singbox-poc-main.log
  echo "main.py sing-box standalone smoke exited unexpectedly with status $status" >&2
  exit 1
fi
grep -q "sing-box started" /tmp/singbox-poc-main.log

cleanup() {
  "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

"${COMPOSE[@]}" up -d node-a node-b node-c whoami

echo "Waiting for nodes to start..."
sleep 3

run_case() {
  local case_name="$1"
  local expected_ip
  expected_ip="$(python3 - "$case_name" "$ROOT/generated/expected-results.json" <<'PY'
import json
import sys
case = sys.argv[1]
path = sys.argv[2]
print(json.load(open(path))[case]["expected_ip"])
PY
)"

  echo "==> $case_name expects exit $expected_ip"
  local output
  if ! output="$("${COMPOSE[@]}" run --rm -T client bash -lc "
set -euo pipefail
sing-box run -c /etc/sing-box/clients/${case_name}.json >/tmp/sing-box-client.log 2>&1 &
pid=\$!
trap 'kill \$pid >/dev/null 2>&1 || true' EXIT
for i in \$(seq 1 12); do
  if response=\$(curl -fsS --connect-timeout 3 --max-time 8 -x socks5h://127.0.0.1:2080 http://whoami:8080/ 2>/tmp/curl.err); then
    printf '%s\n' \"\$response\"
    exit 0
  fi
  sleep 1
done
echo 'curl failed:' >&2
cat /tmp/curl.err >&2 || true
echo 'sing-box client log:' >&2
cat /tmp/sing-box-client.log >&2 || true
exit 1
")"; then
    echo "$output"
    echo "Case $case_name failed; node logs follow."
    "${COMPOSE[@]}" logs --tail=120 node-a node-b node-c whoami || true
    return 1
  fi

  echo "$output"
  if ! grep -q "\"remote_addr\": \"$expected_ip\"" <<<"$output"; then
    echo "Case $case_name returned unexpected exit; expected $expected_ip" >&2
    return 1
  fi
}

for case_name in "${CASES[@]}"; do
  run_case "$case_name"
done

echo "==> restart-apply node-a expects exit 172.29.10.13 after config swap"
cp "$ROOT/generated/node-a/config-exit-node-c.json" "$ROOT/generated/node-a/config.json"
"${COMPOSE[@]}" restart node-a >/dev/null
sleep 3
restart_output="$("${COMPOSE[@]}" run --rm -T client bash -lc "
set -euo pipefail
sing-box run -c /etc/sing-box/clients/hysteria2.json >/tmp/sing-box-client.log 2>&1 &
pid=\$!
trap 'kill \$pid >/dev/null 2>&1 || true' EXIT
for i in \$(seq 1 12); do
  if response=\$(curl -fsS --connect-timeout 3 --max-time 8 -x socks5h://127.0.0.1:2080 http://whoami:8080/ 2>/tmp/curl.err); then
    printf '%s\n' \"\$response\"
    exit 0
  fi
  sleep 1
done
cat /tmp/curl.err >&2 || true
cat /tmp/sing-box-client.log >&2 || true
exit 1
")"
echo "$restart_output"
if ! grep -q '"remote_addr": "172.29.10.13"' <<<"$restart_output"; then
  echo "restart-apply returned unexpected exit; expected 172.29.10.13" >&2
  exit 1
fi

echo "All sing-box POC cases passed."
