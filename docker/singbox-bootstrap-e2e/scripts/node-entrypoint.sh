#!/usr/bin/env bash
set -euo pipefail

NODE_NAME="${NODE_NAME:?NODE_NAME is required}"
STATE_DIR="${STATE_DIR:-/state}"

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

test -f /etc/sing-box/config.json
test -f /etc/sing-box/node-link/ca.crt
test -f /etc/sing-box/node-link/node.crt
test -f /etc/sing-box/node-link/node.key
test -f /etc/sing-box/node-link/client.crt
test -f /etc/sing-box/node-link/client.key

openssl verify -CAfile /etc/sing-box/node-link/ca.crt /etc/sing-box/node-link/node.crt
openssl verify -CAfile /etc/sing-box/node-link/ca.crt /etc/sing-box/node-link/client.crt
sing-box check -c /etc/sing-box/config.json

log "starting sing-box"
exec sing-box run -c /etc/sing-box/config.json
