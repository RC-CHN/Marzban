#!/usr/bin/env bash
set -euo pipefail

NODE_NAME="${NODE_NAME:?NODE_NAME is required}"
STATE_DIR="${STATE_DIR:-/state}"
SING_BOX_BIN="${SING_BOX_BIN:-/opt/marzban-singbox/bin/sing-box}"
CONFIG_PATH="${CONFIG_PATH:-/etc/marzban-singbox/config.json}"
NODE_LINK_DIR="${NODE_LINK_DIR:-/etc/marzban-singbox/node-link}"

log() {
  printf '[bootstrap-e2e:%s] %s\n' "$NODE_NAME" "$*"
}

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl

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

openssl verify -CAfile "$NODE_LINK_DIR/ca.crt" "$NODE_LINK_DIR/node.crt"
openssl verify -CAfile "$NODE_LINK_DIR/ca.crt" "$NODE_LINK_DIR/client.crt"
"$SING_BOX_BIN" check -c "$CONFIG_PATH"

log "starting sing-box"
exec "$SING_BOX_BIN" run -c "$CONFIG_PATH"
