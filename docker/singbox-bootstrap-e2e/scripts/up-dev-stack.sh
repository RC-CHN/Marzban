#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/../.." && pwd)"
PROJECT="marzban-singbox-bootstrap-e2e"
PANEL_PORT="${E2E_PANEL_PORT:-18444}"
DASHBOARD_BUILD="${E2E_DASHBOARD_BUILD:-/tmp/marzban-dashboard-e2e}"
TOOLBOX_IMAGE="${E2E_TOOLBOX_IMAGE:-marzban-singbox-e2e-toolbox:ubuntu22.04}"
COMPOSE=(docker compose -p "$PROJECT" -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.dev.yml")

export E2E_PANEL_PORT="$PANEL_PORT"
export E2E_DASHBOARD_BUILD="$DASHBOARD_BUILD"
export E2E_NO_PROXY="${E2E_NO_PROXY:-localhost,127.0.0.1,panel,node-a,node-b,node-c,node-d,whoami,172.30.10.0/24}"

for node in node-a node-b node-c node-d; do
  docker rm -f "marzban-singbox-e2e-$node" >/dev/null 2>&1 || true
done
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true

if [ -d "$ROOT/runtime" ]; then
  cleanup_image="$TOOLBOX_IMAGE"
  if ! docker image inspect "$cleanup_image" >/dev/null 2>&1; then
    cleanup_image="ubuntu:22.04"
  fi
  docker run --rm -v "$ROOT/runtime:/runtime" "$cleanup_image" bash -lc 'rm -rf /runtime/*'
fi
mkdir -p "$ROOT/runtime"

(
  cd "$REPO_ROOT/app/dashboard"
  VITE_BASE_API=/api/ npm run build -- \
    --outDir "$DASHBOARD_BUILD" \
    --assetsDir statics \
    --emptyOutDir
)
cp "$DASHBOARD_BUILD/index.html" "$DASHBOARD_BUILD/404.html"

if ! docker image inspect "$TOOLBOX_IMAGE" >/dev/null 2>&1; then
  "${COMPOSE[@]}" --profile build build toolbox
fi
if [ "${E2E_SKIP_PANEL_BUILD:-0}" != "1" ]; then
  "${COMPOSE[@]}" build panel
fi

"${COMPOSE[@]}" up -d panel
"${COMPOSE[@]}" run --rm provisioner
"${COMPOSE[@]}" up -d whoami node-a node-b node-c node-d

echo "Waiting for enrolled nodes and first heartbeats..."
for node in node-a node-b node-c node-d; do
  for _ in $(seq 1 180); do
    if "${COMPOSE[@]}" exec -T "$node" test -f /var/lib/marzban-singbox/sync-state.json >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  "${COMPOSE[@]}" exec -T "$node" test -f /var/lib/marzban-singbox/sync-state.json
done

for _ in $(seq 1 60); do
  token="$(curl -kfsS \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    -d 'username=admin&password=admin' \
    "https://127.0.0.1:$PANEL_PORT/api/admin/token" | jq -r '.access_token')"
  nodes="$(curl -kfsS -H "Authorization: Bearer $token" "https://127.0.0.1:$PANEL_PORT/api/singbox/nodes")"
  if [ "$(jq '[.[] | select(.status == "connected")] | length' <<<"$nodes")" = "4" ]; then
    break
  fi
  sleep 1
done
jq -e 'length == 4 and all(.status == "connected")' <<<"$nodes" >/dev/null

printf '\nDevelopment stack is running:\n'
printf '  URL:      https://127.0.0.1:%s/dashboard/\n' "$PANEL_PORT"
printf '  Username: admin\n'
printf '  Password: admin\n'
printf '  Nodes:    node-a, node-b, node-c, node-d (enrolled and connected)\n'
