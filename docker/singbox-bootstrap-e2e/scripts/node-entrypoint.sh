#!/usr/bin/env bash
set -euo pipefail

NODE_NAME="${NODE_NAME:?NODE_NAME is required}"
STATE_DIR="${STATE_DIR:-/state}"
SING_BOX_BIN="${SING_BOX_BIN:-/opt/marzban-singbox/bin/sing-box}"
CONFIG_PATH="${CONFIG_PATH:-/etc/marzban-singbox/config.json}"
NODE_LINK_DIR="${NODE_LINK_DIR:-/etc/marzban-singbox/node-link}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/marzban-singbox}"
NODE_DOCKER_CONTAINER_NAME="${NODE_DOCKER_CONTAINER_NAME:-marzban-sing-box}"
SYNC_ENV_PATH="${SYNC_ENV_PATH:-/etc/marzban-singbox/sync.env}"
SYNC_STATE_PATH="${SYNC_STATE_PATH:-/var/lib/marzban-singbox/sync-state.json}"

log() {
  printf '[bootstrap-e2e:%s] %s\n' "$NODE_NAME" "$*"
}

if [ "${E2E_INSTALL_DEPS:-false}" = "true" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl
fi

command_path="$STATE_DIR/$NODE_NAME.sh"
if [ ! -f "$command_path" ]; then
  log "missing enrollment command: $command_path"
  exit 1
fi

log "running enrollment bootstrap"
bash "$command_path"

test -f "$CONFIG_PATH"
test -f "$NODE_LINK_DIR/ca.crt"
test -f "$NODE_LINK_DIR/node.crt"
test -f "$NODE_LINK_DIR/node.key"
test -f "$NODE_LINK_DIR/client.crt"
test -f "$NODE_LINK_DIR/client.key"
test -f "$SYNC_ENV_PATH"
test -f "$SYNC_STATE_PATH"
test -x /usr/local/bin/marzban-singbox-sync

openssl verify -CAfile "$NODE_LINK_DIR/ca.crt" "$NODE_LINK_DIR/node.crt"
openssl verify -CAfile "$NODE_LINK_DIR/ca.crt" "$NODE_LINK_DIR/client.crt"
"$SING_BOX_BIN" check -c "$CONFIG_PATH"

if [ -f "$COMPOSE_DIR/docker-compose.yml" ]; then
  log "sing-box is managed by docker compose"
  docker ps --filter "name=$NODE_DOCKER_CONTAINER_NAME" --format '{{.Names}}' | grep -qx "$NODE_DOCKER_CONTAINER_NAME"
  exec tail -f /dev/null
fi

log "starting sing-box directly"
exec "$SING_BOX_BIN" run -c "$CONFIG_PATH"
