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

check_ports() {
  if is_true "$SKIP_PORT_CHECK"; then
    log "port check skipped by --skip-port-check"
    return
  fi
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    log "port check skipped: $SERVICE_NAME is already active"
    return
  fi
  check_public_ports_available
  NODE_LINK_PROTOCOL="$(normalize_node_link_protocol "$NODE_LINK_PROTOCOL")" \
    || die "--node-link-protocol must be anytls or hysteria2"
  check_port_available "node-link" "$NODE_LINK_PORT" "$(node_link_transport_proto)"
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
    log "docker runtime selected; create compose/service outside this minimal bootstrap"
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
    --rawfile node_csr "$tmp_dir/node.csr" \
    --rawfile client_csr "$tmp_dir/client.csr" \
    --rawfile public_csr "$tmp_dir/public.csr" \
    '{
      token: $token,
      node_name: $node_name,
      node_host: $node_host,
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
  local public_cert_path public_key_path public_ca_path config_next
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

  if [ "$RUNTIME" = "systemd" ]; then
    install_systemd_service
    systemctl restart "$SERVICE_NAME"
  else
    log "docker runtime selected; config and certs were written but service restart is external"
  fi

  log "node enrolled"
  log "config hash: $(jq -r '.config_hash' "$response_path" 2>/dev/null || true)"
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
