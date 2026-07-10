from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    hysteria2: int = 11001
    tuic: int = 11002
    anytls: int = 11003
    vmess: int = 11004
    vless: int = 11005
    trojan: int = 11006
    shadowsocks: int = 11007


class SingBoxNodeBase(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    public_host: str = Field(min_length=1, max_length=256)
    entry_enabled: bool = True
    exit_enabled: bool = True
    node_link_port: int = Field(default=12443, ge=1, le=65535)
    public_ports: SingBoxProtocolPorts | None = None
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


class SingBoxNodeCreate(SingBoxNodeBase):
    rebuild_links: bool = True


class SingBoxNodeModify(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    public_host: str | None = Field(default=None, min_length=1, max_length=256)
    entry_enabled: bool | None = None
    exit_enabled: bool | None = None
    node_link_port: int | None = Field(default=None, ge=1, le=65535)
    public_ports: SingBoxProtocolPorts | None = None
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


class SingBoxSubscriptionLinks(BaseModel):
    token: str
    singbox: str
    clash: str
    v2rayn: str


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


class SingBoxNodeSyncRequest(_SingBoxNodeMessagePayload):
    token: str = Field(min_length=16)
    node_name: str | None = None
    current_config_hash: str | None = None
    sing_box_version: str | None = Field(default=None, max_length=64)
    sync_agent_version: str | None = Field(default=None, max_length=64)
    runtime: str | None = Field(default=None, max_length=64)
    container_image: str | None = Field(default=None, max_length=256)
    node_link_listening: bool | None = None


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
    sync_interval_seconds: int = 60
    config: dict | None = None
    upgrade: SingBoxNodeUpgradeInstruction | None = None


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


class SingBoxUsageRecord(BaseModel):
    node_id: int | None
    node_name: str
    uplink: int
    downlink: int


class SingBoxUsageReport(BaseModel):
    uplink: int = Field(default=0, ge=0)
    downlink: int = Field(default=0, ge=0)
