from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .db import get_db
from .models import Observation
from .schemas import IngestResult, ObservationIn


app = FastAPI(title="FlashControl Main Server", version="0.1.0")


def unpack_payload(payload: Any) -> list[ObservationIn]:
    if isinstance(payload, dict) and "observations" in payload:
        values = payload.get("observations")
    else:
        values = [payload]
    if not isinstance(values, list) or not values:
        raise ValueError("payload must contain at least one observation")
    return [ObservationIn.model_validate(value) for value in values]


def observation_values(item: ObservationIn, source_ip: str | None) -> dict:
    raw = item.model_dump(mode="json")
    device = item.device
    return {
        "event_id": item.event_id,
        "schema_version": item.schema_version,
        "probe_version": item.probe_version,
        "event_type": item.event_type,
        "observed_at_utc": item.observed_at_utc,
        "hostname": item.host.get("hostname"),
        "user_sid": item.session.get("sid"),
        "hardware_evidence_sha256": device.get("hardware_evidence_sha256"),
        "media_evidence_sha256": device.get("media_evidence_sha256"),
        "observation_sha256": device.get("observation_sha256"),
        "host": item.host,
        "session": item.session,
        "device": device,
        "capabilities": item.capabilities,
        "capability_status": item.capability_status,
        "collector_errors": item.collector_errors,
        "raw_observation": raw,
        "source_ip": source_ip,
    }


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/api/v1/observations", response_model=IngestResult)
def ingest_observations(
    request: Request,
    payload: Any = Body(...),
    db: Session = Depends(get_db),
) -> IngestResult:
    try:
        observations = unpack_payload(payload)
    except (ValidationError, ValueError) as exc:
        detail = exc.errors() if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc

    source_ip = request.client.host if request.client else None
    accepted_ids = []
    for item in observations:
        statement = (
            insert(Observation)
            .values(**observation_values(item, source_ip))
            .on_conflict_do_nothing(index_elements=[Observation.event_id])
            .returning(Observation.event_id)
        )
        inserted = db.execute(statement).scalar_one_or_none()
        if inserted is not None:
            accepted_ids.append(inserted)
    db.commit()

    accepted = len(accepted_ids)
    return IngestResult(
        received=len(observations),
        accepted=accepted,
        duplicates=len(observations) - accepted,
        event_ids=accepted_ids,
    )
