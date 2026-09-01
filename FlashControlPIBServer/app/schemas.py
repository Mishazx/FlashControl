import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ObservationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    probe_version: str = Field(min_length=1, max_length=64)
    event_id: uuid.UUID
    event_type: Literal["snapshot", "connected", "disconnected"]
    observed_at_utc: datetime.datetime
    host: dict[str, Any]
    session: dict[str, Any]
    device: dict[str, Any]
    capabilities: dict[str, bool]
    capability_status: dict[str, str]
    collector_errors: list[dict[str, Any]]

    @field_validator("observed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at_utc must include a UTC offset")
        return value


class IngestResult(BaseModel):
    received: int
    accepted: int
    duplicates: int
    event_ids: list[uuid.UUID]


class AgentHeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: uuid.UUID
    agent_version: str = Field(min_length=1, max_length=64)
    hostname: str = Field(min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    current_ips: list[str] = Field(default_factory=list, max_length=128)
    queue_size: int = Field(ge=0, le=100000000)
    selected_route: Literal["direct", "proxy", "offline"]
    proxy_id: uuid.UUID | None = None

    @field_validator("current_ips")
    @classmethod
    def validate_ip_addresses(cls, values: list[str]) -> list[str]:
        import ipaddress

        result = []
        for value in values:
            normalized = str(ipaddress.ip_address(value))
            if normalized not in result:
                result.append(normalized)
        return result

    @model_validator(mode="after")
    def require_proxy_for_proxy_route(self):
        if self.selected_route == "proxy" and self.proxy_id is None:
            raise ValueError("proxy_id is required for proxy route")
        if self.selected_route != "proxy" and self.proxy_id is not None:
            raise ValueError("proxy_id is only valid for proxy route")
        return self
