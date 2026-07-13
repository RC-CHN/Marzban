#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -p marzban-singbox-bootstrap-e2e -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.dev.yml")

for node in node-a node-b node-c node-d; do
  docker rm -f "marzban-singbox-e2e-$node" >/dev/null 2>&1 || true
done
"${COMPOSE[@]}" down -v --remove-orphans
