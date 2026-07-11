#!/usr/bin/env bash
set -euo pipefail

SING_BOX_VERSION="${SING_BOX_VERSION:-1.13.14}"
SING_BOX_BINARY_PATH="${SING_BOX_BINARY_PATH:-}"
RUNTIME="${RUNTIME:-systemd}"
NODE_NAME="${NODE_NAME:-}"
NODE_HOST="${NODE_HOST:-}"
PANEL_URL="${PANEL_URL:-}"
ENROLL_TOKEN="${ENROLL_TOKEN:-}"
NODE_LINK_PROTOCOL="${NODE_LINK_PROTOCOL:-anytls}"
NODE_LINK_PORT="${NODE_LINK_PORT:-12443}"
DEFAULT_PUBLIC_PORTS="11001/udp,11002/udp,11003/tcp,11004/tcp,11005/tcp,11006/tcp,11007/tcp,11007/udp"
PUBLIC_PORTS="${PUBLIC_PORTS:-$DEFAULT_PUBLIC_PORTS}"
SKIP_PORT_CHECK="${SKIP_PORT_CHECK:-false}"
CONFIG_PATH="${CONFIG_PATH:-/etc/marzban-singbox/config.json}"
SERVICE_NAME="${SERVICE_NAME:-marzban-sing-box}"
SING_BOX_BIN="${SING_BOX_BIN:-/opt/marzban-singbox/bin/sing-box}"
NODE_LINK_DIR="${NODE_LINK_DIR:-/etc/marzban-singbox/node-link}"
PUBLIC_CERT_DIR="${PUBLIC_CERT_DIR:-/etc/marzban-singbox/certs}"
DATA_DIR="${DATA_DIR:-/var/lib/marzban-singbox}"
SYNC_ENV_PATH="${SYNC_ENV_PATH:-/etc/marzban-singbox/sync.env}"
SYNC_STATE_PATH="${SYNC_STATE_PATH:-$DATA_DIR/sync-state.json}"
SYNC_SCRIPT_PATH="${SYNC_SCRIPT_PATH:-/usr/local/bin/marzban-singbox-sync}"
SYNC_AGENT_VERSION="${SYNC_AGENT_VERSION:-0.9.5}"
SYNC_INTERVAL_SECONDS="${SYNC_INTERVAL_SECONDS:-60}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/marzban-singbox}"
NODE_DOCKER_IMAGE="${NODE_DOCKER_IMAGE:-ghcr.io/rc-chn/marzban:latest}"
NODE_DOCKER_CONTAINER_NAME="${NODE_DOCKER_CONTAINER_NAME:-marzban-sing-box}"
NODE_DOCKER_PROJECT_NAME="${NODE_DOCKER_PROJECT_NAME:-marzban-singbox-node}"
NODE_DOCKER_NETWORK_MODE="${NODE_DOCKER_NETWORK_MODE:-host}"
NODE_DOCKER_CONFIG_ROOT="${NODE_DOCKER_CONFIG_ROOT:-/etc/marzban-singbox}"
NODE_DOCKER_DATA_ROOT="${NODE_DOCKER_DATA_ROOT:-$DATA_DIR}"
NODE_DOCKER_CONFIG_SOURCE="${NODE_DOCKER_CONFIG_SOURCE:-$NODE_DOCKER_CONFIG_ROOT}"
NODE_DOCKER_CONFIG_TARGET="${NODE_DOCKER_CONFIG_TARGET:-$NODE_DOCKER_CONFIG_ROOT}"
NODE_DOCKER_DATA_SOURCE="${NODE_DOCKER_DATA_SOURCE:-$NODE_DOCKER_DATA_ROOT}"
NODE_DOCKER_DATA_TARGET="${NODE_DOCKER_DATA_TARGET:-$NODE_DOCKER_DATA_ROOT}"
NODE_DOCKER_SING_BOX_BIN="${NODE_DOCKER_SING_BOX_BIN:-/usr/local/bin/sing-box}"
DOCKER_HTTP_PROXY="${DOCKER_HTTP_PROXY:-${HTTP_PROXY:-${http_proxy:-}}}"
DOCKER_HTTPS_PROXY="${DOCKER_HTTPS_PROXY:-${HTTPS_PROXY:-${https_proxy:-}}}"
DOCKER_NO_PROXY="${DOCKER_NO_PROXY:-${NO_PROXY:-${no_proxy:-localhost,127.0.0.1}}}"
PANEL_DATA_DIR="${PANEL_DATA_DIR:-/var/lib/marzban}"
PANEL_TLS_MODE="${PANEL_TLS_MODE:-self-signed}"
PANEL_HOST="${PANEL_HOST:-}"
PANEL_CERT_DAYS="${PANEL_CERT_DAYS:-397}"
PANEL_CERT_DIR="${PANEL_CERT_DIR:-$PANEL_DATA_DIR/certs/panel}"
PANEL_CERT_PATH="${PANEL_CERT_PATH:-$PANEL_CERT_DIR/fullchain.pem}"
PANEL_KEY_PATH="${PANEL_KEY_PATH:-$PANEL_CERT_DIR/privkey.pem}"
PANEL_ENV_PATH="${PANEL_ENV_PATH:-$PANEL_DATA_DIR/.env}"
PANEL_INSECURE="${PANEL_INSECURE:-false}"
NODE_LINK_CA_DIR="${NODE_LINK_CA_DIR:-/var/lib/marzban/ca/node-link}"

usage() {
  cat <<'USAGE'
Usage:
  scripts/singbox-bootstrap.sh install-node --node-name NAME --node-host HOST [--panel-url URL]
  scripts/singbox-bootstrap.sh enroll-node --node-name NAME --node-host HOST --panel-url URL --enroll-token TOKEN
  scripts/singbox-bootstrap.sh check
  scripts/singbox-bootstrap.sh restart
  scripts/singbox-bootstrap.sh logs
  scripts/singbox-bootstrap.sh status

Optional:
  --sing-box-version VERSION   default: 1.13.14
  --sing-box-binary PATH       install an existing local sing-box binary instead of downloading
  --node-link-protocol PROTO   anytls|hysteria2, default: anytls
  --node-link-port PORT        default: 12443
  --public-ports PORTS         comma-separated PORT/PROTO list; use "none" to skip public entry ports
  --skip-port-check            skip local listening-port preflight
  --panel-host HOST            panel certificate SAN for install-panel
  --panel-tls self-signed|none default: self-signed
  --panel-insecure             skip TLS verification when calling a self-signed panel
  --runtime systemd|docker     default: systemd
  --config-path PATH           default: /etc/marzban-singbox/config.json
  --sync-interval SECONDS      default: 60

Docker runtime environment:
  NODE_DOCKER_IMAGE            default: ghcr.io/rc-chn/marzban:latest
  NODE_DOCKER_NETWORK_MODE     default: host
  NODE_DOCKER_CONFIG_SOURCE    default: /etc/marzban-singbox
  NODE_DOCKER_CONFIG_TARGET    default: /etc/marzban-singbox
  NODE_DOCKER_DATA_SOURCE      default: /var/lib/marzban-singbox
  NODE_DOCKER_DATA_TARGET      default: /var/lib/marzban-singbox
  DOCKER_HTTP_PROXY            default: HTTP_PROXY/http_proxy
  DOCKER_HTTPS_PROXY           default: HTTPS_PROXY/https_proxy
  DOCKER_NO_PROXY              default: NO_PROXY/no_proxy
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
      --enroll-token)
        ENROLL_TOKEN="${2:-}"
        shift 2
        ;;
      --sing-box-version)
        SING_BOX_VERSION="${2:-}"
        shift 2
        ;;
      --sing-box-binary)
        SING_BOX_BINARY_PATH="${2:-}"
        shift 2
        ;;
      --node-link-protocol)
        NODE_LINK_PROTOCOL="${2:-}"
        shift 2
        ;;
      --node-link-port)
        NODE_LINK_PORT="${2:-}"
        shift 2
        ;;
      --public-ports)
        PUBLIC_PORTS="${2:-}"
        shift 2
        ;;
      --skip-port-check)
        SKIP_PORT_CHECK=true
        shift
        ;;
      --panel-host)
        PANEL_HOST="${2:-}"
        shift 2
        ;;
      --panel-tls)
        PANEL_TLS_MODE="${2:-}"
        shift 2
        ;;
      --panel-insecure)
        PANEL_INSECURE=true
        shift
        ;;
      --runtime)
        RUNTIME="${2:-}"
        shift 2
        ;;
      --config-path)
        CONFIG_PATH="${2:-}"
        shift 2
        ;;
      --sync-interval)
        SYNC_INTERVAL_SECONDS="${2:-}"
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

require_enroll_args() {
  require_node_args
  [ -n "$PANEL_URL" ] || die "--panel-url is required"
  [ -n "$ENROLL_TOKEN" ] || die "--enroll-token is required"
}

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    if command -v curl >/dev/null 2>&1 \
      && command -v jq >/dev/null 2>&1 \
      && command -v openssl >/dev/null 2>&1 \
      && command -v ss >/dev/null 2>&1 \
      && command -v dig >/dev/null 2>&1 \
      && command -v tar >/dev/null 2>&1; then
      return
    fi
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
      ca-certificates curl jq openssl iproute2 dnsutils tar
  fi
}

ensure_directories() {
  install -d -m 0755 "$(dirname "$CONFIG_PATH")"
  install -d -m 0755 "$DATA_DIR"
  install -d -m 0755 "$PUBLIC_CERT_DIR"
  install -d -m 0755 "$NODE_LINK_DIR"
  install -d -m 0755 "$COMPOSE_DIR"
}

install_systemd_service() {
  cat >"/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Marzban sing-box service
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

docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
    return
  fi
  return 127
}

configure_docker_daemon_proxy() {
  if [ -z "$DOCKER_HTTP_PROXY" ] && [ -z "$DOCKER_HTTPS_PROXY" ]; then
    return
  fi
  if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
    log "docker daemon proxy env detected; systemd is not active, skipping daemon proxy drop-in"
    return
  fi

  local proxy_dir proxy_file tmp_file
  proxy_dir="/etc/systemd/system/docker.service.d"
  proxy_file="$proxy_dir/http-proxy.conf"
  install -d -m 0755 "$proxy_dir"
  tmp_file="$(mktemp)"
  {
    printf '%s\n' "[Service]"
    [ -z "$DOCKER_HTTP_PROXY" ] || printf 'Environment="HTTP_PROXY=%s"\n' "$DOCKER_HTTP_PROXY"
    [ -z "$DOCKER_HTTPS_PROXY" ] || printf 'Environment="HTTPS_PROXY=%s"\n' "$DOCKER_HTTPS_PROXY"
    [ -z "$DOCKER_NO_PROXY" ] || printf 'Environment="NO_PROXY=%s"\n' "$DOCKER_NO_PROXY"
  } >"$tmp_file"
  if [ -f "$proxy_file" ] && cmp -s "$tmp_file" "$proxy_file"; then
    rm -f "$tmp_file"
    return
  fi
  install -m 0644 "$tmp_file" "$proxy_file"
  rm -f "$tmp_file"
  systemctl daemon-reload
  if systemctl is-active --quiet docker 2>/dev/null; then
    systemctl restart docker
  fi
  log "docker daemon proxy configured: $proxy_file"
}

install_docker_runtime() {
  configure_docker_daemon_proxy
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 && docker_compose version >/dev/null 2>&1; then
    return
  fi

  if ! command -v docker >/dev/null 2>&1 || ! docker_compose version >/dev/null 2>&1; then
    if ! command -v apt-get >/dev/null 2>&1; then
      die "docker runtime requires docker and docker compose"
    fi
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    if ! apt-get install -y --no-install-recommends docker.io docker-compose-plugin; then
      apt-get install -y --no-install-recommends docker.io docker-compose
    fi
  fi

  if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl enable --now docker
  elif command -v service >/dev/null 2>&1; then
    service docker start >/dev/null 2>&1 || true
  fi

  docker info >/dev/null 2>&1 || die "docker daemon is not available"
  docker_compose version >/dev/null 2>&1 || die "docker compose is not available"
}

write_docker_compose() {
  local compose_path
  compose_path="$COMPOSE_DIR/docker-compose.yml"
  install -d -m 0755 "$COMPOSE_DIR"
  install -d -m 0755 "$NODE_DOCKER_CONFIG_SOURCE"
  install -d -m 0755 "$NODE_DOCKER_DATA_SOURCE"
  cat >"$compose_path" <<EOF
services:
  sing-box:
    image: "$NODE_DOCKER_IMAGE"
    container_name: "$NODE_DOCKER_CONTAINER_NAME"
    restart: unless-stopped
    network_mode: "$NODE_DOCKER_NETWORK_MODE"
    volumes:
      - "$NODE_DOCKER_CONFIG_SOURCE:$NODE_DOCKER_CONFIG_TARGET:rw"
      - "$NODE_DOCKER_DATA_SOURCE:$NODE_DOCKER_DATA_TARGET:rw"
    command:
      - "$NODE_DOCKER_SING_BOX_BIN"
      - "run"
      - "-c"
      - "$CONFIG_PATH"
EOF
  log "docker compose written: $compose_path"
}

start_docker_runtime() {
  install_docker_runtime
  write_docker_compose
  (cd "$COMPOSE_DIR" && COMPOSE_PROJECT_NAME="$NODE_DOCKER_PROJECT_NAME" docker_compose up -d)
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

install_sing_box_binary() {
  if [ -x "$SING_BOX_BIN" ] && "$SING_BOX_BIN" version 2>/dev/null | head -n 1 | grep -q "$SING_BOX_VERSION"; then
    log "keeping existing sing-box: $SING_BOX_BIN"
    return
  fi

  install -d -m 0755 "$(dirname "$SING_BOX_BIN")"

  if [ -n "$SING_BOX_BINARY_PATH" ]; then
    [ -x "$SING_BOX_BINARY_PATH" ] || die "sing-box binary is not executable: $SING_BOX_BINARY_PATH"
    install -m 0755 "$SING_BOX_BINARY_PATH" "$SING_BOX_BIN"
    "$SING_BOX_BIN" version | head -n 1
    return
  fi

  local arch
  case "$(uname -m)" in
    x86_64|amd64)
      arch="amd64"
      ;;
    aarch64|arm64)
      arch="arm64"
      ;;
    *)
      die "unsupported architecture: $(uname -m)"
      ;;
  esac

  local tmp_dir package_dir url
  tmp_dir="$(mktemp -d)"
  package_dir="sing-box-${SING_BOX_VERSION}-linux-${arch}"
  url="https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/${package_dir}.tar.gz"
  log "downloading sing-box $SING_BOX_VERSION for linux-$arch"
  curl -fsSL "$url" -o "$tmp_dir/sing-box.tar.gz"
  tar -xzf "$tmp_dir/sing-box.tar.gz" -C "$tmp_dir"
  install -m 0755 "$tmp_dir/$package_dir/sing-box" "$SING_BOX_BIN"
  rm -rf "$tmp_dir"
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

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

validate_port() {
  local port="$1"
  case "$port" in
    ''|*[!0-9]*)
      return 1
      ;;
  esac
  [ "$port" -ge 1 ] && [ "$port" -le 65535 ]
}

normalize_proto() {
  local proto="$1"
  case "$proto" in
    tcp|TCP)
      printf '%s\n' "tcp"
      ;;
    udp|UDP)
      printf '%s\n' "udp"
      ;;
    *)
      return 1
      ;;
  esac
}

normalize_node_link_protocol() {
  case "${1:-}" in
    anytls|ANYTLS)
      printf '%s\n' "anytls"
      ;;
    hysteria2|HYSTERIA2)
      printf '%s\n' "hysteria2"
      ;;
    *)
      return 1
      ;;
  esac
}

node_link_transport_proto() {
  case "$(normalize_node_link_protocol "$NODE_LINK_PROTOCOL")" in
    anytls)
      printf '%s\n' "tcp"
      ;;
    hysteria2)
      printf '%s\n' "udp"
      ;;
  esac
}

is_ip_address() {
  local value="$1"
  case "$value" in
    *:*)
      return 0
      ;;
    *.*)
      case "$value" in
        *[!0-9.]*)
          return 1
          ;;
      esac
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

infer_panel_host() {
  if [ -n "$PANEL_HOST" ]; then
    printf '%s\n' "$PANEL_HOST"
    return
  fi

  local candidate
  for candidate in $(hostname -I 2>/dev/null || true); do
    case "$candidate" in
      127.*|::1)
        continue
        ;;
      *)
        printf '%s\n' "$candidate"
        return
        ;;
    esac
  done
  hostname -f 2>/dev/null || hostname 2>/dev/null || printf '%s\n' "localhost"
}

port_in_use() {
  local port="$1"
  local proto="$2"
  if ! command -v ss >/dev/null 2>&1; then
    log "port check skipped: ss is not installed"
    return 1
  fi
  case "$proto" in
    tcp)
      ss -H -ltn "sport = :$port" 2>/dev/null | grep -q .
      ;;
    udp)
      ss -H -lun "sport = :$port" 2>/dev/null | grep -q .
      ;;
    *)
      return 1
      ;;
  esac
}

curl_tls_args() {
  if is_true "$PANEL_INSECURE"; then
    printf '%s\n' "-fsSLk"
  else
    printf '%s\n' "-fsSL"
  fi
}

check_port_available() {
  local label="$1"
  local port="$2"
  local proto="$3"
  validate_port "$port" || die "invalid $label port: $port"
  proto="$(normalize_proto "$proto")" || die "invalid $label protocol: $proto"
  if port_in_use "$port" "$proto"; then
    die "$label port is already in use: $port/$proto. Change the node port in Dashboard or pass --public-ports/--node-link-port."
  fi
  log "$label port available: $port/$proto"
}

check_public_ports_available() {
  local raw="$PUBLIC_PORTS"
  raw="${raw//[[:space:]]/}"
  case "$raw" in
    ''|none|NONE|false|FALSE|0)
      log "public entry port check skipped"
      return
      ;;
  esac

  local old_ifs item port proto
  old_ifs="$IFS"
  IFS=","
  for item in $raw; do
    [ -n "$item" ] || continue
    case "$item" in
      */*)
        port="${item%/*}"
        proto="${item##*/}"
        ;;
      *:*)
        proto="${item%%:*}"
        port="${item##*:}"
        ;;
      *)
        die "invalid public port spec: $item (expected PORT/PROTO, for example 11001/udp)"
        ;;
    esac
    check_port_available "public entry" "$port" "$proto"
  done
  IFS="$old_ifs"
}

select_node_link_port() {
  local transport candidate
  transport="$(node_link_transport_proto)"
  validate_port "$NODE_LINK_PORT" || die "invalid node-link port: $NODE_LINK_PORT"
  if ! port_in_use "$NODE_LINK_PORT" "$transport"; then
    log "node-link port available: $NODE_LINK_PORT/$transport"
    return
  fi

  candidate=$((NODE_LINK_PORT + 1))
  while [ "$candidate" -le 65535 ]; do
    if ! port_in_use "$candidate" "$transport"; then
      log "node-link port $NODE_LINK_PORT/$transport is in use; selected $candidate/$transport"
      NODE_LINK_PORT="$candidate"
      return
    fi
    candidate=$((candidate + 1))
  done
  die "no free node-link port is available from $NODE_LINK_PORT to 65535"
}

check_ports() {
  if is_true "$SKIP_PORT_CHECK"; then
    log "port check skipped by --skip-port-check"
    return
  fi
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    log "port check skipped: $SERVICE_NAME is already active"
    return
  fi
  if [ "$RUNTIME" = "docker" ] && command -v docker >/dev/null 2>&1 \
    && docker ps --filter "name=$NODE_DOCKER_CONTAINER_NAME" --format '{{.Names}}' 2>/dev/null | grep -qx "$NODE_DOCKER_CONTAINER_NAME"; then
    log "port check skipped: docker container $NODE_DOCKER_CONTAINER_NAME is already active"
    return
  fi
  check_public_ports_available
  NODE_LINK_PROTOCOL="$(normalize_node_link_protocol "$NODE_LINK_PROTOCOL")" \
    || die "--node-link-protocol must be anytls or hysteria2"
  select_node_link_port
}

install_node() {
  need_root
  require_node_args
  log "installing node $NODE_NAME for $NODE_HOST"
  install_packages
  check_ports
  install_sing_box_binary
  ensure_directories
  write_placeholder_config
  if [ "$RUNTIME" = "systemd" ]; then
    install_systemd_service
  else
    start_docker_runtime
  fi
  check_config
  log "node installed"
  log "panel: ${PANEL_URL:-not set}"
  log "node-link files expected under $NODE_LINK_DIR"
  log "public cert files expected under $PUBLIC_CERT_DIR"
}

write_json_string_field() {
  local response_path="$1"
  local jq_expr="$2"
  local target_path="$3"
  local mode="$4"
  [ -n "$target_path" ] || die "empty target path for $jq_expr"
  install -d -m 0755 "$(dirname "$target_path")"
  jq -er "$jq_expr" "$response_path" >"$target_path"
  chmod "$mode" "$target_path"
}

install_private_key() {
  local source_path="$1"
  local target_path="$2"
  [ -n "$target_path" ] || die "empty private key target path"
  install -d -m 0755 "$(dirname "$target_path")"
  install -m 0600 "$source_path" "$target_path"
}

response_path() {
  local response_path="$1"
  local jq_expr="$2"
  local default_path="$3"
  local value
  value="$(jq -r "$jq_expr // empty" "$response_path")"
  printf '%s\n' "${value:-$default_path}"
}

write_env_var() {
  local key="$1"
  local value="$2"
  printf '%s=%q\n' "$key" "$value"
}

write_sync_env() {
  local sync_token="$1"
  local config_hash="$2"
  local tmp_path
  [ -n "$sync_token" ] || die "panel did not return a node sync token"
  install -d -m 0755 "$(dirname "$SYNC_ENV_PATH")"
  install -d -m 0755 "$(dirname "$SYNC_STATE_PATH")"
  tmp_path="$(mktemp)"
  {
    write_env_var PANEL_URL "${PANEL_URL%/}"
    write_env_var PANEL_INSECURE "$PANEL_INSECURE"
    write_env_var NODE_NAME "$NODE_NAME"
    write_env_var NODE_HOST "$NODE_HOST"
    write_env_var NODE_SYNC_TOKEN "$sync_token"
    write_env_var CONFIG_PATH "$CONFIG_PATH"
    write_env_var SING_BOX_BIN "$SING_BOX_BIN"
    write_env_var RUNTIME "$RUNTIME"
    write_env_var SERVICE_NAME "$SERVICE_NAME"
    write_env_var COMPOSE_DIR "$COMPOSE_DIR"
    write_env_var NODE_DOCKER_CONTAINER_NAME "$NODE_DOCKER_CONTAINER_NAME"
    write_env_var NODE_DOCKER_PROJECT_NAME "$NODE_DOCKER_PROJECT_NAME"
    write_env_var SYNC_STATE_PATH "$SYNC_STATE_PATH"
    write_env_var SYNC_SCRIPT_PATH "$SYNC_SCRIPT_PATH"
    write_env_var SYNC_INTERVAL_SECONDS "$SYNC_INTERVAL_SECONDS"
  } >"$tmp_path"
  install -m 0600 "$tmp_path" "$SYNC_ENV_PATH"
  rm -f "$tmp_path"
  jq -n --arg config_hash "$config_hash" --arg synced_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{config_hash: $config_hash, synced_at: $synced_at}' >"$SYNC_STATE_PATH"
  chmod 0600 "$SYNC_STATE_PATH"
}

download_sync_agent() {
  local target_path="$1"
  local agent_url
  [ -n "${PANEL_URL:-}" ] || return 1
  agent_url="${PANEL_URL%/}/api/singbox/sync-agent.sh"
  if curl "$(curl_tls_args)" "$agent_url" -o "$target_path" \
    && grep -q '^SYNC_AGENT_VERSION=' "$target_path"; then
    log "downloaded sync agent: $agent_url"
    return 0
  fi
  rm -f "$target_path"
  return 1
}

install_sync_agent() {
  local tmp_path service_path timer_path
  tmp_path="$(mktemp)"
  if ! download_sync_agent "$tmp_path"; then
    cat >"$tmp_path" <<'SYNC_AGENT'
#!/usr/bin/env bash
set -euo pipefail

ENV_PATH="${SYNC_ENV_PATH:-/etc/marzban-singbox/sync.env}"
if [ ! -f "$ENV_PATH" ]; then
  echo "[marzban-singbox-sync] missing env: $ENV_PATH" >&2
  exit 1
fi
# shellcheck disable=SC1090
. "$ENV_PATH"

PANEL_URL="${PANEL_URL%/}"
CONFIG_PATH="${CONFIG_PATH:-/etc/marzban-singbox/config.json}"
SING_BOX_BIN="${SING_BOX_BIN:-/opt/marzban-singbox/bin/sing-box}"
SYNC_STATE_PATH="${SYNC_STATE_PATH:-/var/lib/marzban-singbox/sync-state.json}"
SYNC_SCRIPT_PATH="${SYNC_SCRIPT_PATH:-/usr/local/bin/marzban-singbox-sync}"
SYNC_AGENT_VERSION="0.9.5"
REPORT_MESSAGE_MAX_CHARS=900
COMPOSE_DIR="${COMPOSE_DIR:-/opt/marzban-singbox}"
SERVICE_NAME="${SERVICE_NAME:-marzban-sing-box}"
NODE_DOCKER_CONTAINER_NAME="${NODE_DOCKER_CONTAINER_NAME:-marzban-sing-box}"
NODE_DOCKER_PROJECT_NAME="${NODE_DOCKER_PROJECT_NAME:-marzban-singbox-node}"

log() {
  printf '[marzban-singbox-sync] %s\n' "$*"
}

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

curl_tls_args() {
  if is_true "${PANEL_INSECURE:-false}"; then
    printf '%s\n' "-fsSk"
  else
    printf '%s\n' "-fsS"
  fi
}

curl_transport_args() {
  if is_true "${PANEL_INSECURE:-false}"; then
    printf '%s\n' "-sSk"
  else
    printf '%s\n' "-sS"
  fi
}

installed_sync_agent_version() {
  local installed_version
  installed_version=""
  if [ -f "$SYNC_SCRIPT_PATH" ]; then
    installed_version="$(awk -F'"' '/^SYNC_AGENT_VERSION="/ { print $2; exit }' "$SYNC_SCRIPT_PATH")"
  fi
  printf '%s\n' "${installed_version:-$SYNC_AGENT_VERSION}"
}

summarize_message() {
  local message="$1"
  local head_chars=220
  local marker=$'\n...[truncated]...\n'
  local tail_chars
  if [ "${#message}" -le "$REPORT_MESSAGE_MAX_CHARS" ]; then
    printf '%s' "$message"
    return
  fi
  tail_chars=$((REPORT_MESSAGE_MAX_CHARS - head_chars - ${#marker}))
  printf '%s%s%s' "${message:0:head_chars}" "$marker" "${message: -tail_chars}"
}

current_config_hash() {
  if [ -f "$SYNC_STATE_PATH" ]; then
    jq -r '.config_hash // empty' "$SYNC_STATE_PATH" 2>/dev/null || true
  fi
}

sing_box_version() {
  "$SING_BOX_BIN" version 2>/dev/null | head -n 1 || true
}

container_image() {
  if command -v docker >/dev/null 2>&1; then
    docker ps --filter "name=$NODE_DOCKER_CONTAINER_NAME" --format '{{.Image}}' 2>/dev/null | head -n 1 || true
  fi
}

docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
    return
  fi
  return 127
}

node_link_listening() {
  local port
  if [ ! -f "$CONFIG_PATH" ] || ! command -v ss >/dev/null 2>&1; then
    printf '%s\n' "false"
    return
  fi
  port="$(jq -r '.inbounds[]? | select((.tag // "") | startswith("node-link")) | .listen_port' "$CONFIG_PATH" 2>/dev/null | head -n 1)"
  if [ -n "$port" ] && ss -H -ltn "sport = :$port" 2>/dev/null | grep -q .; then
    printf '%s\n' "true"
  else
    printf '%s\n' "false"
  fi
}

write_state() {
  local hash="$1"
  install -d -m 0755 "$(dirname "$SYNC_STATE_PATH")"
  jq -n --arg config_hash "$hash" --arg synced_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{config_hash: $config_hash, synced_at: $synced_at}' >"$SYNC_STATE_PATH"
  chmod 0600 "$SYNC_STATE_PATH"
}

report_applied() {
  local hash="$1"
  local success="$2"
  local message="$3"
  local http_status request_path response_body response_path summarized_message
  request_path="$(mktemp)"
  response_path="$(mktemp)"
  summarized_message="$(summarize_message "$message")"
  jq -n \
    --arg token "$NODE_SYNC_TOKEN" \
    --arg config_hash "$hash" \
    --argjson success "$success" \
    --arg sing_box_version "$(sing_box_version)" \
    --arg sync_agent_version "$(installed_sync_agent_version)" \
    --arg runtime "${RUNTIME:-}" \
    --arg container_image "$(container_image)" \
    --arg message "$summarized_message" \
    '{
      token: $token,
      config_hash: $config_hash,
      success: $success,
      sing_box_version: $sing_box_version,
      sync_agent_version: $sync_agent_version,
      runtime: $runtime,
      container_image: $container_image,
      message: $message
    }' >"$request_path"
  if ! http_status="$(curl "$(curl_transport_args)" \
      -H "Content-Type: application/json" \
      --data-binary "@$request_path" \
      -o "$response_path" \
      -w '%{http_code}' \
      "$PANEL_URL/api/singbox/nodes/sync/applied")"; then
    response_body="$(summarize_message "$(<"$response_path")")"
    rm -f "$request_path" "$response_path"
    printf '%s\n' "failed to report node result${response_body:+: $response_body}" >&2
    return 1
  fi
  response_body="$(summarize_message "$(<"$response_path")")"
  rm -f "$request_path" "$response_path"
  case "$http_status" in
    2??)
      return 0
      ;;
    *)
      printf '%s\n' "panel rejected node result (HTTP $http_status)${response_body:+: $response_body}" >&2
      return 1
      ;;
  esac
}

report_applied_or_warn() {
  if ! report_applied "$@"; then
    log "warning: operation result could not be reported; the next heartbeat will reconcile node state"
  fi
}

restart_runtime() {
  if [ -n "${SYNC_RESTART_COMMAND:-}" ]; then
    sh -c "$SYNC_RESTART_COMMAND"
    return
  fi
  if [ -f "$COMPOSE_DIR/docker-compose.yml" ] && command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
      (cd "$COMPOSE_DIR" && COMPOSE_PROJECT_NAME="${NODE_DOCKER_PROJECT_NAME:-marzban-singbox-node}" docker compose restart)
      return
    fi
    if command -v docker-compose >/dev/null 2>&1; then
      (cd "$COMPOSE_DIR" && COMPOSE_PROJECT_NAME="${NODE_DOCKER_PROJECT_NAME:-marzban-singbox-node}" docker-compose restart)
      return
    fi
    log "docker compose restart skipped: docker compose is not available"
    return
  fi
  if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl restart "$SERVICE_NAME"
    return
  fi
  log "restart skipped: no docker compose or systemd runtime found"
}

rewrite_compose_image() {
  local target_image="$1"
  local compose_path tmp_path
  compose_path="$COMPOSE_DIR/docker-compose.yml"
  [ -f "$compose_path" ] || {
    printf '%s\n' "missing compose file: $compose_path" >&2
    return 1
  }
  tmp_path="$(mktemp)"
  if ! awk -v image="$target_image" '
    BEGIN { in_service = 0; replaced = 0 }
    /^  sing-box:/ { in_service = 1 }
    in_service && /^    image:/ {
      print "    image: \"" image "\""
      replaced = 1
      in_service = 0
      next
    }
    { print }
    END { if (!replaced) exit 2 }
  ' "$compose_path" >"$tmp_path"; then
    rm -f "$tmp_path"
    printf '%s\n' "failed to update image in compose file: $compose_path" >&2
    return 1
  fi
  cp "$compose_path" "${compose_path}.prev"
  mv "$tmp_path" "$compose_path"
}

upgrade_docker_image() {
  local target_image="$1"
  local current_image
  [ -n "$target_image" ] || return 0
  if [ "${RUNTIME:-}" != "docker" ]; then
    printf '%s\n' "docker image upgrade skipped for runtime: ${RUNTIME:-unknown}"
    return 0
  fi
  command -v docker >/dev/null 2>&1 || {
    printf '%s\n' "docker image upgrade requested but docker is not installed" >&2
    return 1
  }
  current_image="$(container_image)"
  if [ "$current_image" = "$target_image" ]; then
    printf '%s\n' "docker image already current: $target_image"
    return 0
  fi
  rewrite_compose_image "$target_image"
  (cd "$COMPOSE_DIR" && COMPOSE_PROJECT_NAME="$NODE_DOCKER_PROJECT_NAME" docker_compose pull)
  (cd "$COMPOSE_DIR" && COMPOSE_PROJECT_NAME="$NODE_DOCKER_PROJECT_NAME" docker_compose up -d)
  printf '%s\n' "docker image upgraded: ${current_image:-unknown} -> $target_image"
}

upgrade_sync_agent() {
  local agent_url="$1"
  local target_version="$2"
  local tmp_path
  [ -n "$agent_url" ] || return 0
  [ -n "$target_version" ] || return 0
  if [ "$target_version" = "$SYNC_AGENT_VERSION" ]; then
    printf '%s\n' "sync agent already current: $SYNC_AGENT_VERSION"
    return 0
  fi
  tmp_path="$(mktemp)"
  if ! curl "$(curl_tls_args)" "$agent_url" -o "$tmp_path"; then
    rm -f "$tmp_path"
    return 1
  fi
  if ! grep -q '^SYNC_AGENT_VERSION=' "$tmp_path"; then
    rm -f "$tmp_path"
    printf '%s\n' "downloaded sync agent does not declare SYNC_AGENT_VERSION" >&2
    return 1
  fi
  install -m 0755 "$tmp_path" "$SYNC_SCRIPT_PATH"
  rm -f "$tmp_path"
  printf '%s\n' "sync agent upgraded: $SYNC_AGENT_VERSION -> $target_version"
}

apply_upgrade() {
  local response_path="$1"
  local apply image agent_url agent_version output
  apply="$(jq -r '.upgrade.apply // false' "$response_path")"
  [ "$apply" = "true" ] || return 0

  output=""
  agent_url="$(jq -r '.upgrade.agent_url // empty' "$response_path")"
  agent_version="$(jq -r '.upgrade.agent_version // empty' "$response_path")"
  if [ -n "$agent_url" ] || [ -n "$agent_version" ]; then
    output="$(upgrade_sync_agent "$agent_url" "$agent_version" 2>&1)"
    printf '%s\n' "$output"
  fi

  image="$(jq -r '.upgrade.image // empty' "$response_path")"
  if [ -n "$image" ]; then
    output="$(upgrade_docker_image "$image" 2>&1)"
    printf '%s\n' "$output"
  fi
}

main() {
  local response changed hash next_path previous_path check_output restart_output current_hash upgrade_output
  response="$(mktemp)"
  trap 'rm -f "${response:-}"' EXIT
  current_hash="$(current_config_hash)"
  jq -n \
    --arg token "$NODE_SYNC_TOKEN" \
    --arg node_name "${NODE_NAME:-}" \
    --arg current_config_hash "$current_hash" \
    --arg sing_box_version "$(sing_box_version)" \
    --arg sync_agent_version "$(installed_sync_agent_version)" \
    --arg runtime "${RUNTIME:-}" \
    --arg container_image "$(container_image)" \
    --argjson node_link_listening "$(node_link_listening)" \
    --arg message "heartbeat" \
    '{
      token: $token,
      node_name: $node_name,
      current_config_hash: $current_config_hash,
      sing_box_version: $sing_box_version,
      sync_agent_version: $sync_agent_version,
      runtime: $runtime,
      container_image: $container_image,
      node_link_listening: $node_link_listening,
      message: $message
    }' |
    curl "$(curl_tls_args)" \
      -H "Content-Type: application/json" \
      --data-binary @- \
      "$PANEL_URL/api/singbox/nodes/sync" \
      -o "$response"

  changed="$(jq -r '.changed' "$response")"
  hash="$(jq -r '.config_hash' "$response")"
  if [ "$changed" != "true" ]; then
    write_state "$hash"
    if ! upgrade_output="$(apply_upgrade "$response" 2>&1)"; then
      report_applied_or_warn "$hash" false "$upgrade_output"
      printf '%s\n' "$upgrade_output" >&2
      exit 1
    fi
    if [ -n "$upgrade_output" ]; then
      report_applied_or_warn "$hash" true "$upgrade_output"
      printf '%s\n' "$upgrade_output"
    fi
    log "config already current: $hash"
    return
  fi

  next_path="${CONFIG_PATH}.next"
  previous_path="${CONFIG_PATH}.prev"
  install -d -m 0755 "$(dirname "$CONFIG_PATH")"
  jq '.config' "$response" >"$next_path"
  if ! check_output="$("$SING_BOX_BIN" check -c "$next_path" 2>&1)"; then
    rm -f "$next_path"
    report_applied_or_warn "$hash" false "$check_output"
    printf '%s\n' "$check_output" >&2
    exit 1
  fi
  if [ -f "$CONFIG_PATH" ]; then
    cp "$CONFIG_PATH" "$previous_path"
  fi
  mv "$next_path" "$CONFIG_PATH"
  chmod 0644 "$CONFIG_PATH"
  if ! restart_output="$(restart_runtime 2>&1)"; then
    report_applied_or_warn "$hash" false "$restart_output"
    printf '%s\n' "$restart_output" >&2
    exit 1
  fi
  write_state "$hash"
  report_applied_or_warn "$hash" true "${restart_output:-applied}"
  log "applied config: $hash"
  if ! upgrade_output="$(apply_upgrade "$response" 2>&1)"; then
    report_applied_or_warn "$hash" false "$upgrade_output"
    printf '%s\n' "$upgrade_output" >&2
    exit 1
  fi
  if [ -n "$upgrade_output" ]; then
    report_applied_or_warn "$hash" true "$upgrade_output"
    printf '%s\n' "$upgrade_output"
  fi
}

main "$@"
SYNC_AGENT
  fi
  install -m 0755 "$tmp_path" "$SYNC_SCRIPT_PATH"
  rm -f "$tmp_path"

  if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    service_path="/etc/systemd/system/marzban-singbox-sync.service"
    timer_path="/etc/systemd/system/marzban-singbox-sync.timer"
    cat >"$service_path" <<EOF
[Unit]
Description=Marzban sing-box node config sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=SYNC_ENV_PATH=$SYNC_ENV_PATH
ExecStart=$SYNC_SCRIPT_PATH
EOF
    cat >"$timer_path" <<EOF
[Unit]
Description=Run Marzban sing-box node config sync periodically

[Timer]
OnBootSec=30s
OnUnitActiveSec=${SYNC_INTERVAL_SECONDS}s
AccuracySec=10s
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now marzban-singbox-sync.timer
    log "sync timer enabled: every ${SYNC_INTERVAL_SECONDS}s"
  else
    log "sync timer skipped: systemd is not active"
  fi
}

generate_csr() {
  local key_path="$1"
  local csr_path="$2"
  local common_name="$3"
  common_name="${common_name//\//_}"
  common_name="${common_name//$'\n'/_}"
  common_name="${common_name//$'\r'/_}"
  openssl req -newkey rsa:2048 \
    -keyout "$key_path" \
    -out "$csr_path" \
    -nodes \
    -subj "/CN=$common_name"
  chmod 600 "$key_path"
}

enroll_node() {
  need_root
  require_enroll_args
  log "enrolling node $NODE_NAME for $NODE_HOST"
  install_packages
  check_ports
  install_sing_box_binary
  ensure_directories

  local tmp_dir request_path response_path panel
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"' EXIT
  request_path="$tmp_dir/enroll-request.json"
  response_path="$tmp_dir/enroll-response.json"
  panel="${PANEL_URL%/}"

  generate_csr "$tmp_dir/node.key" "$tmp_dir/node.csr" "$NODE_NAME"
  generate_csr "$tmp_dir/client.key" "$tmp_dir/client.csr" "$NODE_NAME-client"
  generate_csr "$tmp_dir/public.key" "$tmp_dir/public.csr" "$NODE_HOST"

  jq -n \
    --arg token "$ENROLL_TOKEN" \
    --arg node_name "$NODE_NAME" \
    --arg node_host "$NODE_HOST" \
    --argjson node_link_port "$NODE_LINK_PORT" \
    --rawfile node_csr "$tmp_dir/node.csr" \
    --rawfile client_csr "$tmp_dir/client.csr" \
    --rawfile public_csr "$tmp_dir/public.csr" \
    '{
      token: $token,
      node_name: $node_name,
      node_host: $node_host,
      node_link_port: $node_link_port,
      node_csr: $node_csr,
      client_csr: $client_csr,
      public_csr: $public_csr
    }' >"$request_path"

  curl "$(curl_tls_args)" \
    -H "Content-Type: application/json" \
    --data-binary "@$request_path" \
    "$panel/api/singbox/nodes/enroll" \
    -o "$response_path"

  local node_link_ca_path node_cert_path node_key_path client_cert_path client_key_path
  local public_cert_path public_key_path public_ca_path config_next sync_token config_hash
  node_link_ca_path="$(response_path "$response_path" '.paths.node_link_ca_cert_path' "$NODE_LINK_DIR/ca.crt")"
  node_cert_path="$(response_path "$response_path" '.paths.node_link_cert_path' "$NODE_LINK_DIR/node.crt")"
  node_key_path="$(response_path "$response_path" '.paths.node_link_key_path' "$NODE_LINK_DIR/node.key")"
  client_cert_path="$(response_path "$response_path" '.paths.node_link_client_cert_path' "$NODE_LINK_DIR/client.crt")"
  client_key_path="$(response_path "$response_path" '.paths.node_link_client_key_path' "$NODE_LINK_DIR/client.key")"
  public_cert_path="$(response_path "$response_path" '.paths.public_tls_cert_path' "$PUBLIC_CERT_DIR/fullchain.pem")"
  public_key_path="$(response_path "$response_path" '.paths.public_tls_key_path' "$PUBLIC_CERT_DIR/privkey.pem")"
  public_ca_path="$(response_path "$response_path" '.paths.public_tls_ca_cert_path' "$PUBLIC_CERT_DIR/ca.crt")"
  CONFIG_PATH="$(response_path "$response_path" '.paths.config_path' "$CONFIG_PATH")"

  write_json_string_field "$response_path" '.files["node-link-ca.crt"]' "$node_link_ca_path" 0644
  write_json_string_field "$response_path" '.files["node.crt"]' "$node_cert_path" 0644
  write_json_string_field "$response_path" '.files["client.crt"]' "$client_cert_path" 0644
  write_json_string_field "$response_path" '.files["public.crt"]' "$public_cert_path" 0644
  write_json_string_field "$response_path" '.files["public-ca.crt"]' "$public_ca_path" 0644
  install_private_key "$tmp_dir/node.key" "$node_key_path"
  install_private_key "$tmp_dir/client.key" "$client_key_path"
  install_private_key "$tmp_dir/public.key" "$public_key_path"

  config_next="${CONFIG_PATH}.next"
  install -d -m 0755 "$(dirname "$CONFIG_PATH")"
  jq '.config' "$response_path" >"$config_next"
  "$SING_BOX_BIN" check -c "$config_next"
  if [ -f "$CONFIG_PATH" ]; then
    cp "$CONFIG_PATH" "${CONFIG_PATH}.prev"
  fi
  mv "$config_next" "$CONFIG_PATH"
  chmod 0644 "$CONFIG_PATH"
  sync_token="$(response_path "$response_path" '.sync_token' '')"
  config_hash="$(jq -r '.config_hash' "$response_path" 2>/dev/null || true)"
  write_sync_env "$sync_token" "$config_hash"
  install_sync_agent

  if [ "$RUNTIME" = "systemd" ]; then
    install_systemd_service
    systemctl restart "$SERVICE_NAME"
  else
    start_docker_runtime
  fi

  log "node enrolled"
  log "config hash: $config_hash"
  rm -rf "$tmp_dir"
  trap - EXIT
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

set_panel_env_var() {
  local key="$1"
  local value="$2"
  local tmp_path
  install -d -m 0755 "$(dirname "$PANEL_ENV_PATH")"
  tmp_path="$(mktemp)"
  if [ -f "$PANEL_ENV_PATH" ]; then
    grep -v -E "^${key}[[:space:]]*=" "$PANEL_ENV_PATH" >"$tmp_path" || true
  fi
  printf '%s=%s\n' "$key" "$value" >>"$tmp_path"
  install -m 0600 "$tmp_path" "$PANEL_ENV_PATH"
  rm -f "$tmp_path"
}

init_panel_tls() {
  case "$PANEL_TLS_MODE" in
    self-signed)
      ;;
    none|disabled|off)
      log "panel TLS disabled by --panel-tls $PANEL_TLS_MODE"
      return
      ;;
    *)
      die "--panel-tls must be self-signed or none"
      ;;
  esac

  local host san_type san_value tmp_config
  host="$(infer_panel_host)"
  case "$host" in
    ''|*/*|*$'\n'*|*$'\r'*)
      die "invalid panel host for self-signed certificate: $host"
      ;;
  esac
  if is_ip_address "$host"; then
    san_type="IP"
  else
    san_type="DNS"
  fi
  san_value="$host"

  install -d -m 0755 "$PANEL_CERT_DIR"
  if [ -f "$PANEL_CERT_PATH" ] && [ -f "$PANEL_KEY_PATH" ]; then
    log "keeping existing panel certificate: $PANEL_CERT_PATH"
  else
    tmp_config="$(mktemp)"
    cat >"$tmp_config" <<EOF
[req]
default_bits = 2048
prompt = no
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = $host

[v3_req]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
$san_type.1 = $san_value
DNS.2 = localhost
IP.2 = 127.0.0.1
EOF
    openssl req -x509 -newkey rsa:2048 \
      -keyout "$PANEL_KEY_PATH" \
      -out "$PANEL_CERT_PATH" \
      -days "$PANEL_CERT_DAYS" \
      -nodes \
      -config "$tmp_config" \
      -extensions v3_req
    rm -f "$tmp_config"
    chmod 0644 "$PANEL_CERT_PATH"
    chmod 0600 "$PANEL_KEY_PATH"
    log "generated self-signed panel certificate for $host"
  fi

  set_panel_env_var UVICORN_SSL_CERTFILE "$PANEL_CERT_PATH"
  set_panel_env_var UVICORN_SSL_KEYFILE "$PANEL_KEY_PATH"
  set_panel_env_var UVICORN_SSL_CA_TYPE private
  log "panel TLS env written: $PANEL_ENV_PATH"
}

install_panel() {
  need_root
  install_packages
  install -d -m 0755 "$PANEL_DATA_DIR"
  install -d -m 0755 "$PANEL_DATA_DIR/singbox/configs"
  init_panel_ca
  init_panel_tls
  log "panel data dir: $PANEL_DATA_DIR"
  log "node-link CA dir: $NODE_LINK_CA_DIR"
  log "panel cert: $PANEL_CERT_PATH"
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
  check_cert "$PANEL_CERT_PATH" "panel cert"
  check_cert "$NODE_LINK_DIR/ca.crt" "node-link ca"
  check_cert "$NODE_LINK_DIR/node.crt" "node-link cert"
  check_cert "$PUBLIC_CERT_DIR/fullchain.pem" "public cert"
  if command -v systemctl >/dev/null 2>&1; then
    log "service: $(systemctl is-active "$SERVICE_NAME" 2>/dev/null || true)"
  fi
  if [ "$RUNTIME" = "docker" ] && command -v docker >/dev/null 2>&1; then
    log "container: $(docker ps --filter "name=$NODE_DOCKER_CONTAINER_NAME" --format '{{.Status}}' 2>/dev/null | head -n 1 || true)"
  fi
  check_ports
}

restart() {
  need_root
  check_config
  if [ "$RUNTIME" = "docker" ]; then
    install_docker_runtime
    write_docker_compose
    (cd "$COMPOSE_DIR" && COMPOSE_PROJECT_NAME="$NODE_DOCKER_PROJECT_NAME" docker_compose up -d)
  elif command -v systemctl >/dev/null 2>&1; then
    systemctl restart "$SERVICE_NAME"
  else
    die "systemctl not available"
  fi
}

logs() {
  if [ "$RUNTIME" = "docker" ] && command -v docker >/dev/null 2>&1; then
    docker logs --tail 200 "$NODE_DOCKER_CONTAINER_NAME"
  elif command -v journalctl >/dev/null 2>&1; then
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
  enroll-node)
    enroll_node
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
