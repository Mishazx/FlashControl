import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    event_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), nullable=False, unique=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    probe_version: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at_utc: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    hostname: Mapped[str | None] = mapped_column(String(255))
    user_sid: Mapped[str | None] = mapped_column(String(255))
    hardware_stable_sha256: Mapped[str | None] = mapped_column(String(64))
    pnp_observation_sha256: Mapped[str | None] = mapped_column(String(64))
    media_identity_sha256: Mapped[str | None] = mapped_column(String(64))
    media_state_sha256: Mapped[str | None] = mapped_column(String(64))
    observation_sha256: Mapped[str | None] = mapped_column(String(64))

    json_type = JSON().with_variant(JSONB, "postgresql")
    host: Mapped[dict] = mapped_column(json_type, nullable=False)
    session: Mapped[dict] = mapped_column(json_type, nullable=False)
    device: Mapped[dict] = mapped_column(json_type, nullable=False)
    capabilities: Mapped[dict] = mapped_column(json_type, nullable=False)
    capability_status: Mapped[dict] = mapped_column(json_type, nullable=False)
    collector_errors: Mapped[list] = mapped_column(json_type, nullable=False)
    raw_observation: Mapped[dict] = mapped_column(json_type, nullable=False)

    source_ip: Mapped[str | None] = mapped_column(Text)
    agent_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), index=True)
    proxy_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), index=True)
    computer_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("computers.id"))
    physical_device_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("physical_devices.id"))
    media_state_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("media_states.id"))


json_type = JSON().with_variant(JSONB, "postgresql")


class Computer(Base):
    __tablename__ = "computers"

    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    computer_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    first_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_host: Mapped[dict] = mapped_column(json_type, nullable=False)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    computer_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("computers.id"), index=True
    )
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    agent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    current_ips: Mapped[list] = mapped_column(json_type, nullable=False)
    queue_size: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_route: Mapped[str] = mapped_column(String(32), nullable=False)
    proxy_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True))
    source_ip: Mapped[str | None] = mapped_column(String(128))
    first_seen_at_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class PhysicalDevice(Base):
    __tablename__ = "physical_devices"

    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    hardware_stable_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="provisional")
    identity_confidence: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    first_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    representative_device: Mapped[dict] = mapped_column(json_type, nullable=False)


class MediaState(Base):
    __tablename__ = "media_states"
    __table_args__ = (
        UniqueConstraint(
            "physical_device_id", "media_identity_sha256", "media_state_sha256",
            name="uq_media_state_device_hashes",
        ),
    )

    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    physical_device_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("physical_devices.id"), nullable=False, index=True
    )
    media_identity_sha256: Mapped[str | None] = mapped_column(String(64))
    media_state_sha256: Mapped[str | None] = mapped_column(String(64))
    first_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    representative_media: Mapped[dict] = mapped_column(json_type, nullable=False)


class IdentityDecision(Base):
    __tablename__ = "identity_decisions"

    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    observation_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("observations.id"), nullable=False, unique=True,
    )
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    auto_linked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    candidate_physical_device_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("physical_devices.id")
    )
    assigned_physical_device_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("physical_devices.id"), nullable=False
    )
    reasons: Mapped[list] = mapped_column(json_type, nullable=False)
    decided_at_utc: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class AuthUser(Base):
    __tablename__ = "auth_users"

    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at_utc: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_login_at_utc: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("auth_users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_ip: Mapped[str | None] = mapped_column(String(128))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class OidcIdentity(Base):
    __tablename__ = "oidc_identities"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_oidc_identity_subject"),)

    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("auth_users.id"), nullable=False, unique=True
    )
    issuer: Mapped[str] = mapped_column(String(1024), nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    groups: Mapped[list] = mapped_column(json_type, nullable=False)
    created_at_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OidcTransaction(Base):
    __tablename__ = "oidc_transactions"

    id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    browser_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    user_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("auth_users.id"))
    username: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_ip: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict] = mapped_column(json_type, nullable=False)
    created_at_utc: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


Index("ix_observations_observed_at", Observation.observed_at_utc)
Index("ix_observations_hostname", Observation.hostname)
Index("ix_observations_user_sid", Observation.user_sid)
Index("ix_observations_hardware_stable_hash", Observation.hardware_stable_sha256)
Index("ix_observations_computer_id", Observation.computer_id)
Index("ix_observations_physical_device_id", Observation.physical_device_id)
Index("ix_audit_log_created_at", AuditLog.created_at_utc)
Index("ix_audit_log_action", AuditLog.action)
