import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ObservationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    probe_version: str = Field(min_length=1, max_length=64)
    event: dict[str, Any] | None = None
    event_id: uuid.UUID | None = None
    event_type: Literal["snapshot", "connected", "disconnected"] | None = None
    observed_at_utc: datetime.datetime | None = None
    host: dict[str, Any]
    session: dict[str, Any]
    device: dict[str, Any]
    hashes: dict[str, Any] | None = None
    capabilities: dict[str, bool] | None = None
    capability_status: dict[str, str] | None = None
    collector_errors: list[dict[str, Any]] | None = None

    @model_validator(mode="before")
    @classmethod
    def lift_event_envelope(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        event = data.get("event")
        if not isinstance(event, dict):
            return data
        lifted = dict(data)
        if lifted.get("event_id") is None and event.get("id") is not None:
            lifted["event_id"] = event["id"]
        if lifted.get("event_type") is None and event.get("type") is not None:
            lifted["event_type"] = event["type"]
        if lifted.get("observed_at_utc") is None and event.get("observed_at_utc") is not None:
            lifted["observed_at_utc"] = event["observed_at_utc"]
        return lifted

    @field_validator("observed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime.datetime | None) -> datetime.datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at_utc must include a UTC offset")
        return value

    @model_validator(mode="after")
    def require_event_fields(self):
        if self.event_id is None:
            raise ValueError("event.id or event_id is required")
        if self.event_type is None:
            raise ValueError("event.type or event_type is required")
        if self.observed_at_utc is None:
            raise ValueError("event.observed_at_utc or observed_at_utc is required")
        return self


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


class AgentEnrollIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: uuid.UUID
    agent_version: str = Field(min_length=1, max_length=64)
    hostname: str = Field(min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    current_ips: list[str] = Field(default_factory=list, max_length=128)

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


class AgentEnrollOut(BaseModel):
    agent_id: uuid.UUID
    machine_token: str
