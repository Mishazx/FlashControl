import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

