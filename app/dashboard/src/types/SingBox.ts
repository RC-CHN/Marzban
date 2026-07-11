export type SingBoxProtocol =
  | "hysteria2"
  | "tuic"
  | "anytls"
  | "vmess"
  | "vless"
  | "trojan"
  | "shadowsocks";

export type SingBoxTLSMode = "system-ca" | "ip-ca" | "ip-insecure";

export type Hysteria2Settings = {
  up_mbps?: number | null;
  down_mbps?: number | null;
  ignore_client_bandwidth: boolean;
  obfs_type: "none" | "salamander";
  obfs_password?: string | null;
  masquerade_url?: string | null;
};

export type TUICSettings = {
  congestion_control: "cubic" | "new_reno" | "bbr";
  auth_timeout: string;
  zero_rtt_handshake: boolean;
  heartbeat: string;
};

export type AnyTLSSettings = {
  padding_scheme?: string[] | null;
  idle_session_check_interval: string;
  idle_session_timeout: string;
  min_idle_session: number;
};

export type ProtocolSettings = {
  hysteria2: Hysteria2Settings;
  tuic: TUICSettings;
  anytls: AnyTLSSettings;
};

export type SingBoxNode = {
  id: number;
  name: string;
  public_host: string;
  entry_enabled: boolean;
  exit_enabled: boolean;
  node_link_port: number;
  public_ports?: Partial<Record<SingBoxProtocol, number>> | null;
  protocol_settings?: ProtocolSettings | null;
  public_tls_mode: SingBoxTLSMode;
  public_tls_ca_cert_path?: string | null;
  status: "connected" | "connecting" | "error" | "disabled";
  version?: string | null;
  message?: string | null;
  sync_enabled?: boolean | null;
  last_config_hash?: string | null;
  applied_config_hash?: string | null;
  last_seen_at?: string | null;
  node_link_cert_expires_at?: string | null;
  usage_coefficient: number;
};

export type SingBoxNodeLink = {
  id: number;
  from_node_id: number;
  to_node_id: number;
  protocol: string;
  mtls_enabled: boolean;
  enabled: boolean;
};

export type SubscriptionLinks = {
  token: string;
  singbox: string;
  clash: string;
  v2rayn: string;
};

export type UserSummary = {
  username: string;
  status: string;
  data_limit?: number | null;
  used_traffic: number;
  expire?: number | null;
  connection_count: number;
  public_subscription?: SubscriptionLinks | null;
};

export type SingBoxConnection = {
  id: number;
  label: string;
  protocol: SingBoxProtocol;
  entry_node_id: number;
  entry_node_name: string;
  exit_node_id?: number | null;
  exit_node_name?: string | null;
  enabled: boolean;
  sort_order: number;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ConnectionDraft = Omit<
  SingBoxConnection,
  "id" | "entry_node_name" | "exit_node_name"
> & {
  id?: number;
  clientId: string;
};

export type UserWorkspace = {
  username: string;
  status: string;
  data_limit?: number | null;
  used_traffic: number;
  expire?: number | null;
  connections: SingBoxConnection[];
  public_subscription: SubscriptionLinks;
};

export const SINGBOX_PROTOCOLS: SingBoxProtocol[] = [
  "hysteria2",
  "tuic",
  "anytls",
  "vmess",
  "vless",
  "trojan",
  "shadowsocks",
];

export const DEFAULT_PUBLIC_PORTS: Record<SingBoxProtocol, number> = {
  hysteria2: 11001,
  tuic: 11002,
  anytls: 11003,
  vmess: 11004,
  vless: 11005,
  trojan: 11006,
  shadowsocks: 11007,
};

export const DEFAULT_PROTOCOL_SETTINGS: ProtocolSettings = {
  hysteria2: {
    up_mbps: null,
    down_mbps: null,
    ignore_client_bandwidth: true,
    obfs_type: "none",
    obfs_password: null,
    masquerade_url: null,
  },
  tuic: {
    congestion_control: "bbr",
    auth_timeout: "3s",
    zero_rtt_handshake: false,
    heartbeat: "10s",
  },
  anytls: {
    padding_scheme: null,
    idle_session_check_interval: "30s",
    idle_session_timeout: "30s",
    min_idle_session: 0,
  },
};
