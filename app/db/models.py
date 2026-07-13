import os
import secrets
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.sql.expression import select, text

from app.db.base import Base
from app.models.node import NodeStatus
from app.models.proxy import (
    ProxyHostALPN,
    ProxyHostFingerprint,
    ProxyHostSecurity,
    ProxyTypes,
)
from app.models.user import ReminderType, UserDataLimitResetStrategy, UserStatus


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True)
    username = Column(String(34), unique=True, index=True)
    hashed_password = Column(String(128))
    users = relationship("User", back_populates="admin")
    created_at = Column(DateTime, default=datetime.utcnow)
    is_sudo = Column(Boolean, default=False)
    password_reset_at = Column(DateTime, nullable=True)
    telegram_id = Column(BigInteger, nullable=True, default=None)
    discord_webhook = Column(String(1024), nullable=True, default=None)
    users_usage = Column(BigInteger, nullable=False, default=0)
    usage_logs = relationship("AdminUsageLogs", back_populates="admin")


class AdminUsageLogs(Base):
    __tablename__ = "admin_usage_logs"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"))
    admin = relationship("Admin", back_populates="usage_logs")
    used_traffic_at_reset = Column(BigInteger, nullable=False)
    reset_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(34, collation='NOCASE'), unique=True, index=True)
    proxies = relationship("Proxy", back_populates="user", cascade="all, delete-orphan")
    status = Column(Enum(UserStatus), nullable=False, default=UserStatus.active)
    used_traffic = Column(BigInteger, default=0)
    node_usages = relationship("NodeUserUsage", back_populates="user", cascade="all, delete-orphan")
    notification_reminders = relationship("NotificationReminder", back_populates="user", cascade="all, delete-orphan")
    data_limit = Column(BigInteger, nullable=True)
    data_limit_reset_strategy = Column(
        Enum(UserDataLimitResetStrategy),
        nullable=False,
        default=UserDataLimitResetStrategy.no_reset,
    )
    usage_logs = relationship("UserUsageResetLogs", back_populates="user")  # maybe rename it to reset_usage_logs?
    expire = Column(Integer, nullable=True)
    admin_id = Column(Integer, ForeignKey("admins.id"))
    admin = relationship("Admin", back_populates="users")
    sub_revoked_at = Column(DateTime, nullable=True, default=None)
    sub_updated_at = Column(DateTime, nullable=True, default=None)
    sub_last_user_agent = Column(String(512), nullable=True, default=None)
    created_at = Column(DateTime, default=datetime.utcnow)
    note = Column(String(500), nullable=True, default=None)
    online_at = Column(DateTime, nullable=True, default=None)
    on_hold_expire_duration = Column(BigInteger, nullable=True, default=None)
    on_hold_timeout = Column(DateTime, nullable=True, default=None)

    # * Positive values: User will be deleted after the value of this field in days automatically.
    # * Negative values: User won't be deleted automatically at all.
    # * NULL: Uses global settings.
    auto_delete_in_days = Column(Integer, nullable=True, default=None)

    edit_at = Column(DateTime, nullable=True, default=None)
    last_status_change = Column(DateTime, default=datetime.utcnow, nullable=True)

    next_plan = relationship(
        "NextPlan",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan"
    )
    singbox_credentials = relationship(
        "SingBoxUserCredential",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan",
    )
    singbox_connections = relationship(
        "SingBoxUserConnection",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @hybrid_property
    def reseted_usage(self) -> int:
        return int(sum([log.used_traffic_at_reset for log in self.usage_logs]))

    @reseted_usage.expression
    def reseted_usage(cls):
        return (
            select(func.sum(UserUsageResetLogs.used_traffic_at_reset)).
            where(UserUsageResetLogs.user_id == cls.id).
            label('reseted_usage')
        )

    @property
    def lifetime_used_traffic(self) -> int:
        return int(
            sum([log.used_traffic_at_reset for log in self.usage_logs])
            + self.used_traffic
        )

    @property
    def last_traffic_reset_time(self):
        return self.usage_logs[-1].reset_at if self.usage_logs else self.created_at

    @property
    def excluded_inbounds(self):
        _ = {}
        for proxy in self.proxies:
            _[proxy.type] = [i.tag for i in proxy.excluded_inbounds]
        return _

    @property
    def inbounds(self):
        return {
            proxy.type: [
                inbound.tag
                for inbound in proxy.excluded_inbounds
            ]
            for proxy in self.proxies
        }


excluded_inbounds_association = Table(
    "exclude_inbounds_association",
    Base.metadata,
    Column("proxy_id", ForeignKey("proxies.id")),
    Column("inbound_tag", ForeignKey("inbounds.tag")),
)

template_inbounds_association = Table(
    "template_inbounds_association",
    Base.metadata,
    Column("user_template_id", ForeignKey("user_templates.id")),
    Column("inbound_tag", ForeignKey("inbounds.tag")),
)


class NextPlan(Base):
    __tablename__ = 'next_plans'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    data_limit = Column(BigInteger, nullable=False)
    expire = Column(Integer, nullable=True)
    add_remaining_traffic = Column(Boolean, nullable=False, default=False, server_default='0')
    fire_on_either = Column(Boolean, nullable=False, default=True, server_default='0')

    user = relationship("User", back_populates="next_plan")


class UserTemplate(Base):
    __tablename__ = "user_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False, unique=True)
    data_limit = Column(BigInteger, default=0)
    expire_duration = Column(BigInteger, default=0)  # in seconds
    username_prefix = Column(String(20), nullable=True)
    username_suffix = Column(String(20), nullable=True)

    inbounds = relationship(
        "ProxyInbound", secondary=template_inbounds_association
    )


class UserUsageResetLogs(Base):
    __tablename__ = "user_usage_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="usage_logs")
    used_traffic_at_reset = Column(BigInteger, nullable=False)
    reset_at = Column(DateTime, default=datetime.utcnow)


class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="proxies")
    type = Column(Enum(ProxyTypes), nullable=False)
    settings = Column(JSON, nullable=False)
    excluded_inbounds = relationship(
        "ProxyInbound", secondary=excluded_inbounds_association
    )


class ProxyInbound(Base):
    __tablename__ = "inbounds"

    id = Column(Integer, primary_key=True)
    tag = Column(String(256), unique=True, nullable=False, index=True)
    hosts = relationship(
        "ProxyHost", back_populates="inbound", cascade="all, delete-orphan"
    )


class ProxyHost(Base):
    __tablename__ = "hosts"
    # __table_args__ = (
    #     UniqueConstraint('inbound_tag', 'remark'),
    # )

    id = Column(Integer, primary_key=True)
    remark = Column(String(256), unique=False, nullable=False)
    address = Column(String(256), unique=False, nullable=False)
    port = Column(Integer, nullable=True)
    path = Column(String(256), unique=False, nullable=True)
    sni = Column(String(1000), unique=False, nullable=True)
    host = Column(String(1000), unique=False, nullable=True)
    security = Column(
        Enum(ProxyHostSecurity),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.inbound_default,
    )
    alpn = Column(
        Enum(ProxyHostALPN),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.none,
        server_default=ProxyHostSecurity.none.name
    )
    fingerprint = Column(
        Enum(ProxyHostFingerprint),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.none,
        server_default=ProxyHostSecurity.none.name
    )

    inbound_tag = Column(String(256), ForeignKey("inbounds.tag"), nullable=False)
    inbound = relationship("ProxyInbound", back_populates="hosts")
    allowinsecure = Column(Boolean, nullable=True)
    is_disabled = Column(Boolean, nullable=True, default=False)
    mux_enable = Column(Boolean, nullable=False, default=False, server_default='0')
    fragment_setting = Column(String(100), nullable=True)
    noise_setting = Column(String(2000), nullable=True)
    random_user_agent = Column(Boolean, nullable=False, default=False, server_default='0')
    use_sni_as_host = Column(Boolean, nullable=False, default=False, server_default="0")


class System(Base):
    __tablename__ = "system"

    id = Column(Integer, primary_key=True)
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)


class JWT(Base):
    __tablename__ = "jwt"

    id = Column(Integer, primary_key=True)
    secret_key = Column(
        String(64), nullable=False, default=lambda: os.urandom(32).hex()
    )


class TLS(Base):
    __tablename__ = "tls"

    id = Column(Integer, primary_key=True)
    key = Column(String(4096), nullable=False)
    certificate = Column(String(2048), nullable=False)


class Node(Base):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True)
    name = Column(String(256, collation='NOCASE'), unique=True)
    address = Column(String(256), unique=False, nullable=False)
    port = Column(Integer, unique=False, nullable=False)
    api_port = Column(Integer, unique=False, nullable=False)
    core_version = Column(String(32), nullable=True)
    status = Column(Enum(NodeStatus), nullable=False, default=NodeStatus.connecting)
    last_status_change = Column(DateTime, default=datetime.utcnow)
    message = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)
    user_usages = relationship("NodeUserUsage", back_populates="node", cascade="all, delete-orphan")
    usages = relationship("NodeUsage", back_populates="node", cascade="all, delete-orphan")
    usage_coefficient = Column(Float, nullable=False, server_default=text("1.0"), default=1)


class NodeUserUsage(Base):
    __tablename__ = "node_user_usages"
    __table_args__ = (
        UniqueConstraint('created_at', 'user_id', 'node_id'),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, unique=False, nullable=False)  # one hour per record
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="node_usages")
    node_id = Column(Integer, ForeignKey("nodes.id"))
    node = relationship("Node", back_populates="user_usages")
    used_traffic = Column(BigInteger, default=0)


class NodeUsage(Base):
    __tablename__ = "node_usages"
    __table_args__ = (
        UniqueConstraint('created_at', 'node_id'),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, unique=False, nullable=False)  # one hour per record
    node_id = Column(Integer, ForeignKey("nodes.id"))
    node = relationship("Node", back_populates="usages")
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)


class SingBoxNode(Base):
    __tablename__ = "singbox_nodes"

    id = Column(Integer, primary_key=True)
    name = Column(String(256, collation='NOCASE'), unique=True, nullable=False)
    public_host = Column(String(256), nullable=False)
    entry_enabled = Column(Boolean, nullable=False, default=True, server_default='1')
    exit_enabled = Column(Boolean, nullable=False, default=True, server_default='1')
    node_link_port = Column(Integer, nullable=False, default=12443, server_default='12443')
    public_ports = Column(JSON, nullable=True)
    protocol_settings = Column(JSON, nullable=True)
    capabilities = Column(JSON, nullable=True)
    deploy_method = Column(String(32), nullable=False, default="manual", server_default="manual")
    ssh_host = Column(String(256), nullable=True)
    ssh_user = Column(String(64), nullable=True)
    ssh_port = Column(Integer, nullable=True)
    config_path = Column(String(512), nullable=False, default="/etc/marzban-singbox/config.json")
    restart_command = Column(String(512), nullable=True, default="systemctl restart marzban-sing-box")
    public_tls_mode = Column(String(32), nullable=False, default="system-ca", server_default="system-ca")
    public_tls_cert_path = Column(String(512), nullable=True, default="/etc/marzban-singbox/certs/fullchain.pem")
    public_tls_key_path = Column(String(512), nullable=True, default="/etc/marzban-singbox/certs/privkey.pem")
    public_tls_ca_cert_path = Column(String(512), nullable=True, default="/etc/marzban-singbox/certs/ca.crt")
    node_link_ca_cert_path = Column(String(512), nullable=True, default="/etc/marzban-singbox/node-link/ca.crt")
    node_link_cert_path = Column(String(512), nullable=True, default="/etc/marzban-singbox/node-link/node.crt")
    node_link_key_path = Column(String(512), nullable=True, default="/etc/marzban-singbox/node-link/node.key")
    node_link_client_cert_path = Column(String(512), nullable=True, default="/etc/marzban-singbox/node-link/client.crt")
    node_link_client_key_path = Column(String(512), nullable=True, default="/etc/marzban-singbox/node-link/client.key")
    node_link_cert_expires_at = Column(DateTime, nullable=True)
    node_link_mtls_enabled = Column(Boolean, nullable=False, default=True, server_default='1')
    status = Column(Enum(NodeStatus), nullable=False, default=NodeStatus.connecting)
    version = Column(String(32), nullable=True)
    message = Column(String(1024), nullable=True)
    sync_token_hash = Column(String(64), nullable=True, unique=True)
    last_config_hash = Column(String(64), nullable=True)
    applied_config_hash = Column(String(64), nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    usage_coefficient = Column(Float, nullable=False, server_default=text("1.0"), default=1)

    links_from = relationship(
        "SingBoxNodeLink",
        back_populates="from_node",
        cascade="all, delete-orphan",
        foreign_keys="SingBoxNodeLink.from_node_id",
    )
    links_to = relationship(
        "SingBoxNodeLink",
        back_populates="to_node",
        cascade="all, delete-orphan",
        foreign_keys="SingBoxNodeLink.to_node_id",
    )
    usages = relationship("SingBoxNodeUsage", back_populates="node", cascade="all, delete-orphan")
    enrollments = relationship("SingBoxEnrollmentToken", back_populates="node", cascade="all, delete-orphan")
    addresses = relationship("SingBoxNodeAddress", back_populates="node", cascade="all, delete-orphan")
    ingress_services = relationship("SingBoxIngressService", back_populates="node", cascade="all, delete-orphan")
    egress_services = relationship("SingBoxEgressService", back_populates="node", cascade="all, delete-orphan")
    state_session = relationship(
        "SingBoxNodeStateSession",
        back_populates="node",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def sync_enabled(self) -> bool:
        return bool(self.sync_token_hash)

    @property
    def protocol_settings_customized(self) -> bool:
        return bool(self.protocol_settings)


class SingBoxEnrollmentToken(Base):
    __tablename__ = "singbox_enrollment_tokens"

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(64), nullable=True)

    node = relationship("SingBoxNode", back_populates="enrollments")


class SingBoxNodeStateSession(Base):
    __tablename__ = "singbox_node_state_sessions"

    node_id = Column(Integer, ForeignKey("singbox_nodes.id"), primary_key=True)
    epoch = Column(BigInteger, nullable=False, default=0, server_default="0")
    instance_id = Column(String(64), nullable=False)
    lease_token_hash = Column(String(64), nullable=False)
    last_sequence = Column(BigInteger, nullable=False, default=0, server_default="0")
    status = Column(String(32), nullable=False, default="active", server_default="active")
    issued_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)

    node = relationship("SingBoxNode", back_populates="state_session")


class SingBoxNodeLink(Base):
    __tablename__ = "singbox_node_links"
    __table_args__ = (
        UniqueConstraint('from_node_id', 'to_node_id'),
    )

    id = Column(Integer, primary_key=True)
    from_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    to_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    protocol = Column(String(32), nullable=False, default="hysteria2", server_default="hysteria2")
    auth_name = Column(String(128), nullable=False)
    password = Column(String(256), nullable=False)
    mtls_enabled = Column(Boolean, nullable=False, default=True, server_default='1')
    enabled = Column(Boolean, nullable=False, default=True, server_default='1')
    client_cert_expires_at = Column(DateTime, nullable=True)
    last_rotated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    from_node = relationship("SingBoxNode", back_populates="links_from", foreign_keys=[from_node_id])
    to_node = relationship("SingBoxNode", back_populates="links_to", foreign_keys=[to_node_id])


class SingBoxNodeAddress(Base):
    __tablename__ = "singbox_node_addresses"
    __table_args__ = (UniqueConstraint("node_id", "address"),)

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False, index=True)
    address = Column(String(256), nullable=False)
    kind = Column(String(32), nullable=False, default="public", server_default="public")
    is_primary = Column(Boolean, nullable=False, default=False, server_default="0")
    enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    node = relationship("SingBoxNode", back_populates="addresses")


class SingBoxIngressService(Base):
    __tablename__ = "singbox_ingress_services"
    __table_args__ = (UniqueConstraint("node_id", "protocol", "listen_port"),)

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False, index=True)
    advertised_address_id = Column(Integer, ForeignKey("singbox_node_addresses.id"), nullable=True)
    name = Column(String(128), nullable=False)
    protocol = Column(String(32), nullable=False)
    listen_port = Column(Integer, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    tls_mode = Column(String(32), nullable=False, default="system-ca", server_default="system-ca")
    tls_profile = Column(JSON, nullable=True)
    protocol_profile = Column(JSON, nullable=True)
    generation = Column(BigInteger, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    node = relationship("SingBoxNode", back_populates="ingress_services")
    advertised_address = relationship("SingBoxNodeAddress", foreign_keys=[advertised_address_id])
    observation = relationship(
        "SingBoxIngressObservation",
        back_populates="ingress_service",
        cascade="all, delete-orphan",
        uselist=False,
    )


class SingBoxIngressObservation(Base):
    __tablename__ = "singbox_ingress_observations"

    ingress_service_id = Column(
        Integer,
        ForeignKey("singbox_ingress_services.id"),
        primary_key=True,
    )
    reporting_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    sequence = Column(BigInteger, nullable=False, default=0, server_default="0")
    resource_generation = Column(BigInteger, nullable=False, default=1, server_default="1")
    session_epoch = Column(BigInteger, nullable=False, default=0, server_default="0")
    snapshot_sequence = Column(BigInteger, nullable=False, default=0, server_default="0")
    oper_state = Column(String(32), nullable=False, default="unknown", server_default="unknown")
    observed_at = Column(DateTime, nullable=True)
    hold_expires_at = Column(DateTime, nullable=True)
    message = Column(String(1024), nullable=True)

    ingress_service = relationship("SingBoxIngressService", back_populates="observation")
    reporting_node = relationship("SingBoxNode", foreign_keys=[reporting_node_id])


class SingBoxEgressService(Base):
    __tablename__ = "singbox_egress_services"
    __table_args__ = (UniqueConstraint("node_id", "kind", "name"),)

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    kind = Column(String(32), nullable=False, default="direct", server_default="direct")
    enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    settings = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    node = relationship("SingBoxNode", back_populates="egress_services")


class SingBoxAdjacency(Base):
    __tablename__ = "singbox_adjacencies"
    __table_args__ = (UniqueConstraint("node_a_id", "node_b_id"),)

    id = Column(Integer, primary_key=True)
    node_a_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    node_b_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    name = Column(String(128), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    node_a = relationship("SingBoxNode", foreign_keys=[node_a_id])
    node_b = relationship("SingBoxNode", foreign_keys=[node_b_id])
    directions = relationship(
        "SingBoxAdjacencyDirection",
        back_populates="adjacency",
        cascade="all, delete-orphan",
    )


class SingBoxAdjacencyDirection(Base):
    __tablename__ = "singbox_adjacency_directions"
    __table_args__ = (
        UniqueConstraint("adjacency_id", "from_node_id", "to_node_id"),
    )

    id = Column(Integer, primary_key=True)
    adjacency_id = Column(Integer, ForeignKey("singbox_adjacencies.id"), nullable=False, index=True)
    from_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    to_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    transport = Column(String(32), nullable=False, default="anytls", server_default="anytls")
    listen_port = Column(Integer, nullable=False)
    admin_cost = Column(Integer, nullable=False, default=100, server_default="100")
    settings = Column(JSON, nullable=True)
    credential_generation = Column(Integer, nullable=False, default=1, server_default="1")
    generation = Column(BigInteger, nullable=False, default=1, server_default="1")
    probe_auth_name = Column(
        String(128),
        nullable=False,
        unique=True,
        default=lambda: f"probe-{secrets.token_hex(12)}",
    )
    probe_password = Column(
        String(256),
        nullable=False,
        default=lambda: secrets.token_urlsafe(32),
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    adjacency = relationship("SingBoxAdjacency", back_populates="directions")
    from_node = relationship("SingBoxNode", foreign_keys=[from_node_id])
    to_node = relationship("SingBoxNode", foreign_keys=[to_node_id])
    observation = relationship(
        "SingBoxLinkStateObservation",
        back_populates="direction",
        cascade="all, delete-orphan",
        uselist=False,
    )


class SingBoxLinkStateObservation(Base):
    __tablename__ = "singbox_link_state_observations"

    adjacency_direction_id = Column(
        Integer,
        ForeignKey("singbox_adjacency_directions.id"),
        primary_key=True,
    )
    reporting_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    sequence = Column(BigInteger, nullable=False, default=0, server_default="0")
    resource_generation = Column(BigInteger, nullable=False, default=1, server_default="1")
    session_epoch = Column(BigInteger, nullable=False, default=0, server_default="0")
    snapshot_sequence = Column(BigInteger, nullable=False, default=0, server_default="0")
    oper_state = Column(String(32), nullable=False, default="unknown", server_default="unknown")
    rtt_ms = Column(Float, nullable=True)
    loss_ppm = Column(Integer, nullable=True)
    bandwidth_mbps = Column(Float, nullable=True)
    observed_at = Column(DateTime, nullable=True)
    hold_expires_at = Column(DateTime, nullable=True)
    message = Column(String(1024), nullable=True)

    direction = relationship("SingBoxAdjacencyDirection", back_populates="observation")
    reporting_node = relationship("SingBoxNode", foreign_keys=[reporting_node_id])


class SingBoxRoutingPolicy(Base):
    __tablename__ = "singbox_routing_policies_v2"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, unique=True)
    metric_mode = Column(String(32), nullable=False, default="admin_only", server_default="admin_only")
    max_hops = Column(Integer, nullable=False, default=8, server_default="8")
    allow_degraded = Column(Boolean, nullable=False, default=False, server_default="0")
    failover = Column(Boolean, nullable=False, default=True, server_default="1")
    required_node_ids = Column(JSON, nullable=True)
    avoided_node_ids = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SingBoxTopologyRevision(Base):
    __tablename__ = "singbox_topology_revisions"

    id = Column(Integer, primary_key=True)
    number = Column(Integer, nullable=False, unique=True)
    status = Column(String(32), nullable=False)
    content_hash = Column(String(64), nullable=False)
    snapshot = Column(JSON, nullable=False)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SingBoxRouteRevision(Base):
    __tablename__ = "singbox_route_revisions"

    id = Column(Integer, primary_key=True)
    number = Column(Integer, nullable=False, unique=True)
    topology_revision_id = Column(Integer, ForeignKey("singbox_topology_revisions.id"), nullable=False)
    status = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    activated_at = Column(DateTime, nullable=True)
    drain_until = Column(DateTime, nullable=True)

    topology_revision = relationship("SingBoxTopologyRevision")
    computed_paths = relationship("SingBoxComputedPath", back_populates="route_revision", cascade="all, delete-orphan")
    node_revisions = relationship("SingBoxNodeRouteRevision", back_populates="route_revision", cascade="all, delete-orphan")
    hop_credentials = relationship(
        "SingBoxRouteHopCredential",
        back_populates="route_revision",
        cascade="all, delete-orphan",
    )


class SingBoxRouteHopCredential(Base):
    __tablename__ = "singbox_route_hop_credentials"
    __table_args__ = (
        UniqueConstraint(
            "route_revision_id",
            "egress_service_id",
            "routing_policy_id",
            "adjacency_direction_id",
        ),
        UniqueConstraint("auth_name"),
    )

    id = Column(Integer, primary_key=True)
    route_revision_id = Column(Integer, ForeignKey("singbox_route_revisions.id"), nullable=False, index=True)
    egress_service_id = Column(Integer, ForeignKey("singbox_egress_services.id"), nullable=False)
    routing_policy_id = Column(Integer, ForeignKey("singbox_routing_policies_v2.id"), nullable=False)
    adjacency_direction_id = Column(Integer, ForeignKey("singbox_adjacency_directions.id"), nullable=False)
    auth_name = Column(String(128), nullable=False)
    password = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    route_revision = relationship("SingBoxRouteRevision", back_populates="hop_credentials")
    egress_service = relationship("SingBoxEgressService")
    routing_policy = relationship("SingBoxRoutingPolicy")
    adjacency_direction = relationship("SingBoxAdjacencyDirection")


class SingBoxComputedPath(Base):
    __tablename__ = "singbox_computed_paths"
    __table_args__ = (UniqueConstraint("route_revision_id", "connection_id"),)

    id = Column(Integer, primary_key=True)
    route_revision_id = Column(Integer, ForeignKey("singbox_route_revisions.id"), nullable=False, index=True)
    connection_id = Column(Integer, ForeignKey("singbox_user_connections.id"), nullable=False, index=True)
    total_cost = Column(Integer, nullable=True)
    hop_count = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False)
    reason = Column(String(1024), nullable=True)

    route_revision = relationship("SingBoxRouteRevision", back_populates="computed_paths")
    connection = relationship("SingBoxUserConnection", foreign_keys=[connection_id])
    hops = relationship("SingBoxComputedPathHop", back_populates="computed_path", cascade="all, delete-orphan")


class SingBoxComputedPathHop(Base):
    __tablename__ = "singbox_computed_path_hops"
    __table_args__ = (UniqueConstraint("computed_path_id", "position"),)

    id = Column(Integer, primary_key=True)
    computed_path_id = Column(Integer, ForeignKey("singbox_computed_paths.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    adjacency_direction_id = Column(Integer, ForeignKey("singbox_adjacency_directions.id"), nullable=False)
    from_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    to_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)

    computed_path = relationship("SingBoxComputedPath", back_populates="hops")
    adjacency_direction = relationship("SingBoxAdjacencyDirection")
    from_node = relationship("SingBoxNode", foreign_keys=[from_node_id])
    to_node = relationship("SingBoxNode", foreign_keys=[to_node_id])


class SingBoxNodeRouteRevision(Base):
    __tablename__ = "singbox_node_route_revisions"
    __table_args__ = (UniqueConstraint("node_id", "route_revision_id"),)

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False, index=True)
    route_revision_id = Column(Integer, ForeignKey("singbox_route_revisions.id"), nullable=False, index=True)
    desired_hash = Column(String(64), nullable=True)
    applied_hash = Column(String(64), nullable=True)
    state = Column(String(32), nullable=False, default="pending", server_default="pending")
    message = Column(String(1024), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    node = relationship("SingBoxNode", foreign_keys=[node_id])
    route_revision = relationship("SingBoxRouteRevision", back_populates="node_revisions")


class SingBoxUserCredential(Base):
    __tablename__ = "singbox_user_credentials"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    subscription_token = Column(String(96), nullable=True, unique=True)
    password = Column(String(256), nullable=False)
    vmess_uuid = Column(String(36), nullable=False)
    vless_uuid = Column(String(36), nullable=False)
    tuic_uuid = Column(String(36), nullable=False)
    shadowsocks_password = Column(String(256), nullable=False)
    enabled_protocols = Column(JSON, nullable=False)
    exit_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="singbox_credentials")
    exit_node = relationship("SingBoxNode", foreign_keys=[exit_node_id])


class SingBoxRoutePolicy(Base):
    __tablename__ = "singbox_route_policies"
    __table_args__ = (
        UniqueConstraint('user_id', 'entry_node_id'),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    entry_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    exit_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=True)
    priority = Column(Integer, nullable=False, default=100, server_default='100')
    enabled = Column(Boolean, nullable=False, default=True, server_default='1')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    entry_node = relationship("SingBoxNode", foreign_keys=[entry_node_id])
    exit_node = relationship("SingBoxNode", foreign_keys=[exit_node_id])


class SingBoxUserConnection(Base):
    __tablename__ = "singbox_user_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    entry_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=False)
    exit_node_id = Column(Integer, ForeignKey("singbox_nodes.id"), nullable=True)
    ingress_service_id = Column(Integer, ForeignKey("singbox_ingress_services.id"), nullable=True)
    egress_service_id = Column(Integer, ForeignKey("singbox_egress_services.id"), nullable=True)
    routing_policy_id = Column(Integer, ForeignKey("singbox_routing_policies_v2.id"), nullable=True)
    protocol = Column(String(32), nullable=False)
    label = Column(String(128), nullable=False)
    auth_name = Column(String(128), nullable=False, unique=True)
    password = Column(String(256), nullable=False)
    vmess_uuid = Column(String(36), nullable=True)
    vless_uuid = Column(String(36), nullable=True)
    tuic_uuid = Column(String(36), nullable=True)
    shadowsocks_password = Column(String(256), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default='1')
    sort_order = Column(Integer, nullable=False, default=100, server_default='100')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="singbox_connections")
    entry_node = relationship("SingBoxNode", foreign_keys=[entry_node_id])
    exit_node = relationship("SingBoxNode", foreign_keys=[exit_node_id])
    ingress_service = relationship("SingBoxIngressService", foreign_keys=[ingress_service_id])
    egress_service = relationship("SingBoxEgressService", foreign_keys=[egress_service_id])
    routing_policy = relationship("SingBoxRoutingPolicy", foreign_keys=[routing_policy_id])


class SingBoxNodeUsage(Base):
    __tablename__ = "singbox_node_usages"
    __table_args__ = (
        UniqueConstraint('created_at', 'node_id'),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, unique=False, nullable=False)
    node_id = Column(Integer, ForeignKey("singbox_nodes.id"))
    node = relationship("SingBoxNode", back_populates="usages")
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)


class NotificationReminder(Base):
    __tablename__ = "notification_reminders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="notification_reminders")
    type = Column(Enum(ReminderType), nullable=False)
    threshold = Column(Integer, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
