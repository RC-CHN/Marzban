#!/usr/bin/env bash
set -euo pipefail

SING_BOX_VERSION="${SING_BOX_VERSION:-1.13.14}"
RUNTIME="${RUNTIME:-systemd}"
NODE_NAME="${NODE_NAME:-}"
NODE_HOST="${NODE_HOST:-}"
PANEL_URL="${PANEL_URL:-}"
NODE_LINK_PORT="${NODE_LINK_PORT:-12443}"
CONFIG_PATH="${CONFIG_PATH:-/etc/sing-box/config.json}"
SERVICE_NAME="${SERVICE_NAME:-sing-box}"
SING_BOX_BIN="${SING_BOX_BIN:-/usr/local/bin/sing-box}"
NODE_LINK_DIR="${NODE_LINK_DIR:-/etc/sing-box/node-link}"
PUBLIC_CERT_DIR="${PUBLIC_CERT_DIR:-/etc/sing-box/certs}"
DATA_DIR="${DATA_DIR:-/var/lib/sing-box}"
PANEL_DATA_DIR="${PANEL_DATA_DIR:-/var/lib/marzban}"
NODE_LINK_CA_DIR="${NODE_LINK_CA_DIR:-/var/lib/marzban/ca/node-link}"

usage() {
  cat <<'USAGE'
Usage:
  scripts/singbox-bootstrap.sh install-node --node-name NAME --node-host HOST [--panel-url URL]
  scripts/singbox-bootstrap.sh check
  scripts/singbox-bootstrap.sh restart
  scripts/singbox-bootstrap.sh logs
  scripts/singbox-bootstrap.sh status

Optional:
  --sing-box-version VERSION   default: 1.13.14
  --node-link-port PORT        default: 12443
  --runtime systemd|docker     default: systemd
  --config-path PATH           default: /etc/sing-box/config.json
USAGE
}

log() {
  printf '[singbox-bootstrap] %s\n' "$*"
}

die() {
  printf '[singbox-bootstrap] error: %s\n' "$*" >&2
  exit 1
}

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    die "run as root"
  fi
}

parse_args() {
  COMMAND="${1:-}"
  if [ -z "$COMMAND" ]; then
    usage
    exit 1
  fi
  shift || true
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --node-name)
        NODE_NAME="${2:-}"
        shift 2
        ;;
      --node-host)
        NODE_HOST="${2:-}"
        shift 2
        ;;
      --panel-url)
        PANEL_URL="${2:-}"
        shift 2
        ;;
      --sing-box-version)
        SING_BOX_VERSION="${2:-}"
        shift 2
        ;;
      --node-link-port)
        NODE_LINK_PORT="${2:-}"
        shift 2
        ;;
      --runtime)
        RUNTIME="${2:-}"
        shift 2
        ;;
      --config-path)
        CONFIG_PATH="${2:-}"
        shift 2
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        die "unknown argument: $1"
        ;;
    esac
  done
}

require_node_args() {
  [ -n "$NODE_NAME" ] || die "--node-name is required"
  [ -n "$NODE_HOST" ] || die "--node-host is required"
  case "$RUNTIME" in
    systemd|docker) ;;
    *) die "--runtime must be systemd or docker" ;;
  esac
}

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
      ca-certificates curl jq openssl iproute2 dnsutils
  fi
}

ensure_directories() {
  install -d -m 0755 "$(dirname "$CONFIG_PATH")"
  install -d -m 0755 "$DATA_DIR"
  install -d -m 0755 "$PUBLIC_CERT_DIR"
  install -d -m 0755 "$NODE_LINK_DIR"
}

install_systemd_service() {
  cat >"/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=sing-box service
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=${SING_BOX_BIN} run -c ${CONFIG_PATH}
Restart=on-failure
RestartSec=5s
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
}

write_placeholder_config() {
  if [ -f "$CONFIG_PATH" ]; then
    log "keeping existing config: $CONFIG_PATH"
    return
  fi
  cat >"$CONFIG_PATH" <<EOF
{
  "log": {
    "level": "info",
    "timestamp": true
  },
  "inbounds": [],
  "outbounds": [
    {
      "type": "direct",
      "tag": "direct"
    },
    {
      "type": "block",
      "tag": "block"
    }
  ],
  "route": {
    "final": "direct"
  }
}
EOF
}

check_sing_box_binary() {
  if ! command -v "$SING_BOX_BIN" >/dev/null 2>&1; then
    log "sing-box binary is missing at $SING_BOX_BIN"
    log "install the pinned binary for version $SING_BOX_VERSION before applying production configs"
    return 1
  fi
  "$SING_BOX_BIN" version | head -n 1
}

check_config() {
  if command -v "$SING_BOX_BIN" >/dev/null 2>&1 && [ -f "$CONFIG_PATH" ]; then
    "$SING_BOX_BIN" check -c "$CONFIG_PATH"
  else
    log "config check skipped: missing sing-box binary or config"
  fi
}

check_cert() {
  local path="$1"
  local label="$2"
  if [ -f "$path" ]; then
    local expiry
    expiry="$(openssl x509 -in "$path" -noout -enddate 2>/dev/null | cut -d= -f2 || true)"
    log "$label: ok${expiry:+, expires at $expiry}"
  else
    log "$label: missing ($path)"
  fi
}

check_ports() {
  if command -v ss >/dev/null 2>&1; then
    ss -lntu | grep -E "(:11001|:11002|:11003|:11004|:11005|:11006|:11007|:${NODE_LINK_PORT})" || true
  fi
}

install_node() {
  need_root
  require_node_args
  log "installing node $NODE_NAME for $NODE_HOST"
  install_packages
  ensure_directories
  write_placeholder_config
  if [ "$RUNTIME" = "systemd" ]; then
    install_systemd_service
  else
    log "docker runtime selected; create compose/service outside this minimal bootstrap"
  fi
  check_config
  log "node installed"
  log "panel: ${PANEL_URL:-not set}"
  log "node-link files expected under $NODE_LINK_DIR"
  log "public cert files expected under $PUBLIC_CERT_DIR"
}

init_panel_ca() {
  install -d -m 0700 "$NODE_LINK_CA_DIR"
  local ca_crt="$NODE_LINK_CA_DIR/root-ca.crt"
  local ca_key="$NODE_LINK_CA_DIR/root-ca.key"
  if [ -f "$ca_crt" ] && [ -f "$ca_key" ]; then
    log "keeping existing node-link CA: $ca_crt"
    return
  fi
  openssl req -x509 -newkey rsa:4096 \
    -keyout "$ca_key" \
    -out "$ca_crt" \
    -days 3650 \
    -nodes \
    -subj "/CN=Marzban Node Link CA"
  chmod 600 "$ca_key"
}

install_panel() {
  need_root
  install_packages
  install -d -m 0755 "$PANEL_DATA_DIR"
  install -d -m 0755 "$PANEL_DATA_DIR/singbox/configs"
  init_panel_ca
  log "panel data dir: $PANEL_DATA_DIR"
  log "node-link CA dir: $NODE_LINK_CA_DIR"
  log "next: start Marzban and create sing-box nodes from the Dashboard or /api/singbox"
}

status() {
  log "OS: $(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}" || uname -a)"
  if check_sing_box_binary; then
    true
  fi
  log "runtime: $RUNTIME"
  log "config: $CONFIG_PATH"
  check_config || true
  check_cert "$NODE_LINK_DIR/ca.crt" "node-link ca"
  check_cert "$NODE_LINK_DIR/node.crt" "node-link cert"
  check_cert "$PUBLIC_CERT_DIR/fullchain.pem" "public cert"
  if command -v systemctl >/dev/null 2>&1; then
    log "service: $(systemctl is-active "$SERVICE_NAME" 2>/dev/null || true)"
  fi
  check_ports
}

restart() {
  need_root
  check_config
  if command -v systemctl >/dev/null 2>&1; then
    systemctl restart "$SERVICE_NAME"
  else
    die "systemctl not available"
  fi
}

logs() {
  if command -v journalctl >/dev/null 2>&1; then
    journalctl -u "$SERVICE_NAME" -n 200 --no-pager
  else
    die "journalctl not available"
  fi
}

parse_args "$@"

case "$COMMAND" in
  install-node)
    install_node
    ;;
  install|install-panel)
    install_panel
    ;;
  update|uninstall)
    die "$COMMAND is documented but not implemented in this minimal node bootstrap yet"
    ;;
  check|status)
    status
    ;;
  restart)
    restart
    ;;
  logs)
    logs
    ;;
  *)
    usage
    exit 1
    ;;
esac
