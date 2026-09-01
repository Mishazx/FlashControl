import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[object] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    probe_version: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at_utc: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="CURRENT_TIMESTAMP",
    )

    hostname: Mapped[str | None] = mapped_column(String(255))
    user_sid: Mapped[str | None] = mapped_column(String(255))
    hardware_stable_sha256: Mapped[str | None] = mapped_column(String(64))
    pnp_observation_sha256: Mapped[str | None] = mapped_column(String(64))
    media_identity_sha256: Mapped[str | None] = mapped_column(String(64))
    media_state_sha256: Mapped[str | None] = mapped_column(String(64))
    observation_sha256: Mapped[str | None] = mapped_column(String(64))

    host: Mapped[dict] = mapped_column(JSONB, nullable=False)
    session: Mapped[dict] = mapped_column(JSONB, nullable=False)
    device: Mapped[dict] = mapped_column(JSONB, nullable=False)
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False)
    capability_status: Mapped[dict] = mapped_column(JSONB, nullable=False)
    collector_errors: Mapped[list] = mapped_column(JSONB, nullable=False)
    raw_observation: Mapped[dict] = mapped_column(JSONB, nullable=False)

    source_ip: Mapped[str | None] = mapped_column(Text)


Index("ix_observations_observed_at", Observation.observed_at_utc)
Index("ix_observations_hostname", Observation.hostname)
Index("ix_observations_user_sid", Observation.user_sid)
Index("ix_observations_hardware_stable_hash", Observation.hardware_stable_sha256)

