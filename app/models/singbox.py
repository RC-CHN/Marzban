from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.node import NodeStatus


SingBoxProtocol = Literal[
    "hysteria2",
    "tuic",
    "anytls",
    "vmess",
    "vless",
    "trojan",
    "shadowsocks",
]
SingBoxPublicTLSMode = Literal["system-ca", "ip-ca", "ip-insecure"]

SUPPORTED_SINGBOX_PROTOCOLS: tuple[SingBoxProtocol, ...] = (
    "hysteria2",
    "tuic",
    "anytls",
    "vmess",
    "vless",
    "trojan",
    "shadowsocks",
)

SINGBOX_NODE_MESSAGE_MAX_LENGTH = 1024
_TRUNCATED_MESSAGE_PREFIX = "[truncated]\n"


def _truncate_node_message(value: object) -> object:
    if not isinstance(value, str) or len(value) <= SINGBOX_NODE_MESSAGE_MAX_LENGTH:
        return value
    remaining = SINGBOX_NODE_MESSAGE_MAX_LENGTH - len(_TRUNCATED_MESSAGE_PREFIX)
    return _TRUNCATED_MESSAGE_PREFIX + value[-remaining:]


class _SingBoxNodeMessagePayload(BaseModel):
    message: str | None = Field(default=None, max_length=SINGBOX_NODE_MESSAGE_MAX_LENGTH)

    @field_validator("message", mode="before")
    @classmethod
    def truncate_message(cls, value: object) -> object:
        return _truncate_node_message(value)


class SingBoxProtocolPorts(BaseModel):
    hysteria2: int = Field(default=11001, ge=1, le=65535)
    tuic: int = Field(default=11002, ge=1, le=65535)
    anytls: int = Field(default=11003, ge=1, le=65535)
    vmess: int = Field(default=11004, ge=1, le=65535)
    vless: int = Field(default=11005, ge=1, le=65535)
    trojan: int = Field(default=11006, ge=1, le=65535)
    shadowsocks: int = Field(default=11007, ge=1, le=65535)

    @model_validator(mode="after")
    def validate_unique_ports(self):
        values = [getattr(self, protocol) for protocol in SUPPORTED_SINGBOX_PROTOCOLS]
        if len(values) != len(set(values)):
            raise ValueError("Public protocol ports must be unique on a node")
        return self


class SingBoxHysteria2Settings(BaseModel):
    up_mbps: int | None = Field(default=None, ge=1, le=100000)
    down_mbps: int | None = Field(default=None, ge=1, le=100000)
    ignore_client_bandwidth: bool = True
    obfs_type: Literal["none", "salamander"] = "none"
    obfs_password: str | None = Field(default=None, max_length=256)
    masquerade_url: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_obfs(self):
        if self.obfs_type == "salamander" and not self.obfs_password:
            raise ValueError("Hysteria2 Salamander obfs requires a password")
        return self


class SingBoxTUICSettings(BaseModel):
    congestion_control: Literal["cubic", "new_reno", "bbr"] = "bbr"
    auth_timeout: str = Field(default="3s", pattern=r"^[1-9][0-9]*(ms|s|m)$")
    zero_rtt_handshake: bool = False
    heartbeat: str = Field(default="10s", pattern=r"^[1-9][0-9]*(ms|s|m)$")


class SingBoxAnyTLSSettings(BaseModel):
    padding_scheme: list[str] | None = Field(default=None, max_length=64)
    idle_session_check_interval: str = Field(default="30s", pattern=r"^[1-9][0-9]*(ms|s|m)$")
    idle_session_timeout: str = Field(default="30s", pattern=r"^[1-9][0-9]*(ms|s|m)$")
    min_idle_session: int = Field(default=0, ge=0, le=1024)

    @field_validator("padding_scheme")
    @classmethod
    def validate_padding_scheme(cls, value: list[str] | None):
        if value is not None and any(not line.strip() or len(line) > 256 for line in value):
            raise ValueError("AnyTLS padding lines must be non-empty and at most 256 characters")
        return value


class SingBoxProtocolSettings(BaseModel):
    hysteria2: SingBoxHysteria2Settings = Field(default_factory=SingBoxHysteria2Settings)
    tuic: SingBoxTUICSettings = Field(default_factory=SingBoxTUICSettings)
    anytls: SingBoxAnyTLSSettings = Field(default_factory=SingBoxAnyTLSSettings)


class SingBoxNodeBase(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    public_host: str = Field(min_length=1, max_length=256)
    entry_enabled: bool = True
    exit_enabled: bool = True
    node_link_port: int = Field(default=12443, ge=1, le=65535)
    public_ports: SingBoxProtocolPorts | None = None
    protocol_settings: SingBoxProtocolSettings = Field(default_factory=SingBoxProtocolSettings)
    deploy_method: Literal["manual", "local", "ssh"] = "manual"
    ssh_host: str | None = None
    ssh_user: str | None = None
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    config_path: str = "/etc/marzban-singbox/config.json"
    restart_command: str | None = "systemctl restart marzban-sing-box"
    public_tls_mode: SingBoxPublicTLSMode = "system-ca"
    public_tls_cert_path: str | None = "/etc/marzban-singbox/certs/fullchain.pem"
    public_tls_key_path: str | None = "/etc/marzban-singbox/certs/privkey.pem"
    public_tls_ca_cert_path: str | None = "/etc/marzban-singbox/certs/ca.crt"
    node_link_ca_cert_path: str | None = "/etc/marzban-singbox/node-link/ca.crt"
    node_link_cert_path: str | None = "/etc/marzban-singbox/node-link/node.crt"
    node_link_key_path: str | None = "/etc/marzban-singbox/node-link/node.key"
    node_link_client_cert_path: str | None = "/etc/marzban-singbox/node-link/client.crt"
    node_link_client_key_path: str | None = "/etc/marzban-singbox/node-link/client.key"
    node_link_mtls_enabled: bool = True
    usage_coefficient: float = Field(default=1.0, gt=0)

    @field_validator("protocol_settings", mode="before")
    @classmethod
    def normalize_protocol_settings(cls, value):
        return value or {}


class SingBoxNodeCreate(SingBoxNodeBase):
    rebuild_links: bool = True


class SingBoxNodeModify(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    public_host: str | None = Field(default=None, min_length=1, max_length=256)
    entry_enabled: bool | None = None
    exit_enabled: bool | None = None
    node_link_port: int | None = Field(default=None, ge=1, le=65535)
    public_ports: SingBoxProtocolPorts | None = None
    protocol_settings: SingBoxProtocolSettings | None = None
    deploy_method: Literal["manual", "local", "ssh"] | None = None
    ssh_host: str | None = None
    ssh_user: str | None = None
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    config_path: str | None = None
    restart_command: str | None = None
    public_tls_mode: SingBoxPublicTLSMode | None = None
    public_tls_cert_path: str | None = None
    public_tls_key_path: str | None = None
    public_tls_ca_cert_path: str | None = None
    node_link_ca_cert_path: str | None = None
    node_link_cert_path: str | None = None
    node_link_key_path: str | None = None
    node_link_client_cert_path: str | None = None
    node_link_client_key_path: str | None = None
    node_link_mtls_enabled: bool | None = None
    status: NodeStatus | None = None
    usage_coefficient: float | None = Field(default=None, gt=0)


class SingBoxNodeResponse(SingBoxNodeBase):
    id: int
    status: NodeStatus
    version: str | None = None
    message: str | None = None
    sync_enabled: bool | None = None
    protocol_settings_customized: bool = False
    capabilities: dict[str, Any] | None = None
    last_config_hash: str | None = None
    applied_config_hash: str | None = None
    last_seen_at: datetime | None = None
    node_link_cert_expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class SingBoxNodeLinkResponse(BaseModel):
    id: int
    from_node_id: int
    to_node_id: int
    protocol: str
    auth_name: str
    mtls_enabled: bool
    enabled: bool
    last_rotated_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class SingBoxUserPolicyModify(BaseModel):
    enabled_protocols: list[SingBoxProtocol] | None = None
    exit_node_id: int | None = None


class SingBoxUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9-_@.]+$")
    enabled_protocols: list[SingBoxProtocol] | None = None
    exit_node_id: int | None = None
    data_limit: int | None = Field(default=0, ge=0)
    expire: int | None = 0
    initialize_connections: bool = True


class SingBoxSubscriptionLinks(BaseModel):
    token: str
    singbox: str
    clash: str
    v2rayn: str


class SingBoxConnectionWrite(BaseModel):
    id: int | None = None
    label: str | None = Field(default=None, max_length=128)
    protocol: SingBoxProtocol | None = None
    entry_node_id: int | None = None
    exit_node_id: int | None = None
    ingress_service_id: int | None = None
    egress_service_id: int | None = None
    routing_policy_id: int | None = None
    enabled: bool = True
    sort_order: int = Field(default=100, ge=0, le=100000)

    @model_validator(mode="after")
    def validate_ingress_selection(self):
        if self.ingress_service_id is None and (self.entry_node_id is None or self.protocol is None):
            raise ValueError("Select an ingress service or provide an entry node and protocol")
        return self


class SingBoxConnectionResponse(BaseModel):
    id: int
    label: str
    protocol: SingBoxProtocol
    entry_node_id: int
    entry_node_name: str
    exit_node_id: int | None = None
    exit_node_name: str | None = None
    ingress_service_id: int | None = None
    egress_service_id: int | None = None
    routing_policy_id: int | None = None
    enabled: bool
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SingBoxConnectionsReplace(BaseModel):
    connections: list[SingBoxConnectionWrite]


class SingBoxUserWorkspaceResponse(BaseModel):
    username: str
    status: str
    data_limit: int | None = None
    used_traffic: int = 0
    expire: int | None = None
    connections: list[SingBoxConnectionResponse]
    public_subscription: SingBoxSubscriptionLinks


class SingBoxUserSummaryResponse(BaseModel):
    username: str
    status: str
    data_limit: int | None = None
    used_traffic: int = 0
    expire: int | None = None
    connection_count: int = 0
    public_subscription: SingBoxSubscriptionLinks | None = None


class SingBoxUserPolicyResponse(BaseModel):
    username: str
    enabled_protocols: list[SingBoxProtocol]
    exit_node_id: int | None = None
    has_credentials: bool = True
    public_subscription: SingBoxSubscriptionLinks | None = None


class SingBoxDeploymentRequest(BaseModel):
    dry_run: bool = True
    apply: bool = False


class SingBoxDeploymentResponse(BaseModel):
    node_id: int
    node_name: str
    config_hash: str
    deploy_method: str
    checked: bool
    applied: bool
    output: str = ""


class SingBoxEnrollmentCreate(BaseModel):
    expires_in_seconds: int = Field(default=1800, ge=60, le=86400)


class SingBoxEnrollmentResponse(BaseModel):
    node_id: int
    node_name: str
    token: str
    expires_at: datetime
    bootstrap_url: str
    command: str


class SingBoxNodeEnrollRequest(BaseModel):
    token: str = Field(min_length=16)
    node_name: str = Field(min_length=1, max_length=256)
    node_host: str = Field(min_length=1, max_length=256)
    node_link_port: int | None = Field(default=None, ge=1, le=65535)
    node_csr: str = Field(min_length=1)
    client_csr: str = Field(min_length=1)
    public_csr: str = Field(min_length=1)


class SingBoxNodeEnrollResponse(BaseModel):
    node_id: int
    node_name: str
    config_hash: str
    sync_token: str
    expires_at: datetime
    paths: dict[str, str | None]
    files: dict[str, str]
    config: dict


class SingBoxNodeCapabilities(BaseModel):
    sing_box_version: str | None = Field(default=None, max_length=64)
    supported_transports: list[Literal["hysteria2", "anytls"]] = Field(
        default_factory=list,
        max_length=16,
    )
    runtime: str | None = Field(default=None, max_length=64)
    addresses: list[str] = Field(default_factory=list, max_length=32)


class SingBoxLinkObservationReport(BaseModel):
    adjacency_direction_id: int
    sequence: int = Field(ge=1)
    resource_generation: int = Field(default=1, ge=1)
    state: Literal["up", "degraded", "down"]
    rtt_ms: float | None = Field(default=None, ge=0, le=3_600_000)
    loss_ppm: int | None = Field(default=None, ge=0, le=1_000_000)
    bandwidth_mbps: float | None = Field(default=None, ge=0)
    hold_seconds: int = Field(default=15, ge=5, le=300)
    message: str | None = Field(default=None, max_length=1024)


class SingBoxIngressObservationReport(BaseModel):
    ingress_service_id: int
    sequence: int = Field(ge=1)
    resource_generation: int = Field(default=1, ge=1)
    state: Literal["unknown", "up", "down"]
    hold_seconds: int = Field(default=15, ge=5, le=300)
    message: str | None = Field(default=None, max_length=1024)


class SingBoxProbeInstruction(BaseModel):
    adjacency_direction_id: int
    resource_generation: int = Field(ge=1)
    transport: Literal["hysteria2", "anytls"]
    server: str
    server_port: int
    password: str
    server_name: str
    settings: dict[str, Any] = Field(default_factory=dict)


class SingBoxNodeStateSessionRequest(BaseModel):
    instance_id: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    epoch: int | None = Field(default=None, ge=1)
    lease_token: str | None = Field(default=None, min_length=16, max_length=256)
    snapshot_sequence: int | None = Field(default=None, ge=1)


class SingBoxNodeStateSessionResponse(BaseModel):
    epoch: int = Field(ge=1)
    lease_token: str | None = None
    accepted_sequence: int = Field(ge=0)
    expires_at: datetime


class SingBoxNodeSyncRequest(_SingBoxNodeMessagePayload):
    token: str = Field(min_length=16)
    node_name: str | None = None
    current_config_hash: str | None = None
    sing_box_version: str | None = Field(default=None, max_length=64)
    sync_agent_version: str | None = Field(default=None, max_length=64)
    runtime: str | None = Field(default=None, max_length=64)
    container_image: str | None = Field(default=None, max_length=256)
    node_link_listening: bool | None = None
    capabilities: SingBoxNodeCapabilities | None = None
    state_session: SingBoxNodeStateSessionRequest | None = None
    observations: list[SingBoxLinkObservationReport] = Field(default_factory=list, max_length=128)
    ingress_observations: list[SingBoxIngressObservationReport] = Field(
        default_factory=list,
        max_length=128,
    )


class SingBoxNodeUpgradeInstruction(BaseModel):
    apply: bool = True
    image: str | None = None
    agent_version: str | None = None
    agent_url: str | None = None


class SingBoxNodeSyncResponse(BaseModel):
    node_id: int
    node_name: str
    config_hash: str
    changed: bool
    sync_interval_seconds: int = 5
    config: dict | None = None
    upgrade: SingBoxNodeUpgradeInstruction | None = None
    topology_revision: int | None = None
    route_revision: int | None = None
    rollout_phase: str | None = None
    state_session: SingBoxNodeStateSessionResponse | None = None
    probes: list[SingBoxProbeInstruction] = Field(default_factory=list)
    ingress_generations: dict[str, int] = Field(default_factory=dict)


class SingBoxNodeSyncAppliedRequest(_SingBoxNodeMessagePayload):
    token: str = Field(min_length=16)
    config_hash: str = Field(min_length=64, max_length=64)
    success: bool = True
    sing_box_version: str | None = Field(default=None, max_length=64)
    sync_agent_version: str | None = Field(default=None, max_length=64)
    runtime: str | None = Field(default=None, max_length=64)
    container_image: str | None = Field(default=None, max_length=256)


class SingBoxNodeSyncAppliedResponse(BaseModel):
    node_id: int
    node_name: str
    status: NodeStatus
    config_hash: str
    applied_config_hash: str | None = None
    route_revision: int | None = None
    rollout_phase: str | None = None


class SingBoxUsageRecord(BaseModel):
    node_id: int | None
    node_name: str
    uplink: int
    downlink: int


class SingBoxUsageReport(BaseModel):
    uplink: int = Field(default=0, ge=0)
    downlink: int = Field(default=0, ge=0)


SingBoxNodeLinkTransport = Literal["hysteria2", "anytls"]
SingBoxOperState = Literal["disabled", "unknown", "provisioning", "up", "degraded", "down"]


class SingBoxNodeAddressResponse(BaseModel):
    id: int
    node_id: int
    address: str
    kind: str
    is_primary: bool
    enabled: bool
    model_config = ConfigDict(from_attributes=True)


class SingBoxIngressServiceWrite(BaseModel):
    id: int | None = None
    node_id: int
    advertised_address_id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    protocol: SingBoxProtocol
    listen_port: int = Field(ge=1, le=65535)
    enabled: bool = True
    tls_mode: SingBoxPublicTLSMode = "system-ca"
    tls_profile: dict[str, Any] = Field(default_factory=dict)
    protocol_profile: dict[str, Any] = Field(default_factory=dict)


class SingBoxIngressServiceResponse(SingBoxIngressServiceWrite):
    id: int
    node_name: str
    address: str
    oper_state: SingBoxOperState = "unknown"
    observed_at: datetime | None = None
    hold_expires_at: datetime | None = None
    message: str | None = None


class SingBoxEgressServiceWrite(BaseModel):
    id: int | None = None
    node_id: int
    name: str = Field(min_length=1, max_length=128)
    kind: Literal["direct"] = "direct"
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class SingBoxEgressServiceResponse(SingBoxEgressServiceWrite):
    id: int
    node_name: str


class SingBoxAdjacencyDirectionWrite(BaseModel):
    id: int | None = None
    from_node_id: int
    to_node_id: int
    enabled: bool = True
    transport: SingBoxNodeLinkTransport = "anytls"
    listen_port: int = Field(ge=1, le=65535)
    admin_cost: int = Field(default=100, ge=1, le=65535)
    settings: dict[str, Any] = Field(default_factory=dict)


class SingBoxAdjacencyDirectionResponse(SingBoxAdjacencyDirectionWrite):
    id: int
    oper_state: SingBoxOperState = "unknown"
    rtt_ms: float | None = None
    loss_ppm: int | None = None
    observed_at: datetime | None = None
    hold_expires_at: datetime | None = None
    message: str | None = None


class SingBoxAdjacencyWrite(BaseModel):
    id: int | None = None
    node_a_id: int
    node_b_id: int
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    directions: list[SingBoxAdjacencyDirectionWrite] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_directions(self):
        if self.node_a_id == self.node_b_id:
            raise ValueError("Adjacency endpoints must be different")
        self.node_a_id, self.node_b_id = sorted((self.node_a_id, self.node_b_id))
        endpoints = {self.node_a_id, self.node_b_id}
        pairs = set()
        for direction in self.directions:
            if {direction.from_node_id, direction.to_node_id} != endpoints:
                raise ValueError("Direction endpoints must match the adjacency")
            pair = (direction.from_node_id, direction.to_node_id)
            if pair in pairs:
                raise ValueError("Adjacency directions must be unique")
            pairs.add(pair)
        return self


class SingBoxAdjacencyResponse(SingBoxAdjacencyWrite):
    id: int
    directions: list[SingBoxAdjacencyDirectionResponse]


class SingBoxRoutingPolicyWrite(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    metric_mode: Literal["admin_only"] = "admin_only"
    max_hops: int = Field(default=8, ge=0, le=32)
    allow_degraded: bool = False
    failover: bool = True
    required_node_ids: list[int] = Field(default_factory=list)
    avoided_node_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_node_constraints(self):
        if set(self.required_node_ids) & set(self.avoided_node_ids):
            raise ValueError("A node cannot be both required and avoided")
        return self


class SingBoxRoutingPolicyResponse(SingBoxRoutingPolicyWrite):
    id: int


class SingBoxNetworkWorkspaceResponse(BaseModel):
    topology_revision: int
    nodes: list[SingBoxNodeResponse]
    addresses: list[SingBoxNodeAddressResponse]
    ingresses: list[SingBoxIngressServiceResponse]
    egresses: list[SingBoxEgressServiceResponse]
    adjacencies: list[SingBoxAdjacencyResponse]
    routing_policies: list[SingBoxRoutingPolicyResponse]


class SingBoxNetworkDraft(BaseModel):
    base_topology_revision: int
    ingresses: list[SingBoxIngressServiceWrite]
    egresses: list[SingBoxEgressServiceWrite]
    adjacencies: list[SingBoxAdjacencyWrite]
    routing_policies: list[SingBoxRoutingPolicyWrite]


class SingBoxNetworkValidationIssue(BaseModel):
    object_type: str
    object_id: int | None = None
    field: str | None = None
    code: str
    message: str


class SingBoxNetworkValidationResponse(BaseModel):
    valid: bool
    issues: list[SingBoxNetworkValidationIssue]
    affected_connections: int = 0
    reachable_connections: int = 0


class SingBoxNetworkApplyResponse(BaseModel):
    topology_revision: int
    route_revision: int
    status: str
    reachable_connections: int
    degraded_connections: int


class SingBoxPathHopResponse(BaseModel):
    position: int
    adjacency_direction_id: int
    from_node_id: int
    from_node_name: str
    to_node_id: int
    to_node_name: str
    transport: str
    admin_cost: int


class SingBoxPathCandidateResponse(BaseModel):
    node_ids: list[int]
    node_names: list[str]
    adjacency_direction_ids: list[int]
    total_cost: int
    hop_count: int
    selected: bool = False


class SingBoxConnectionRouteResponse(BaseModel):
    connection_id: int
    status: str
    topology_revision: int | None = None
    route_revision: int | None = None
    total_cost: int | None = None
    hop_count: int | None = None
    reason: str | None = None
    hops: list[SingBoxPathHopResponse] = Field(default_factory=list)
    candidates: list[SingBoxPathCandidateResponse] = Field(default_factory=list)
