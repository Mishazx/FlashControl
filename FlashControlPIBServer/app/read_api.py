import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .auth import require_read_user, require_roles
from .db import get_db
from .models import AuditLog, Computer, IdentityDecision, MediaState, Observation, PhysicalDevice


router = APIRouter(
    prefix="/api/v1",
    tags=["audit-read"],
    dependencies=[Depends(require_read_user)],
)

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def page(db: Session, statement, limit: int, offset: int, serializer):
    count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
    total = db.scalar(count_statement) or 0
    rows = db.execute(statement.limit(limit).offset(offset)).all()
    return {
        "items": [serializer(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def computer_summary(computer: Computer) -> dict:
    return {
        "id": computer.id,
        "hostname": computer.hostname,
        "domain": computer.domain,
        "first_seen_at": computer.first_seen_at,
        "last_seen_at": computer.last_seen_at,
    }


def device_summary(device: PhysicalDevice) -> dict:
    source = device.representative_device or {}
    storage = source.get("storage") or {}
    usb = ((source.get("pnp") or {}).get("usb") or {})
    return {
        "id": device.id,
        "status": device.status,
        "identity_confidence": device.identity_confidence,
        "hardware_stable_sha256": device.hardware_stable_sha256,
        "first_seen_at": device.first_seen_at,
        "last_seen_at": device.last_seen_at,
        "vendor": storage.get("vendor"),
        "product": storage.get("product"),
        "storage_serial": storage.get("serial"),
        "vid": usb.get("vid"),
        "pid": usb.get("pid"),
    }


def decision_summary(decision: IdentityDecision | None) -> dict | None:
    if decision is None:
        return None
    return {
        "id": decision.id,
        "result": decision.result,
        "confidence": decision.confidence,
        "auto_linked": decision.auto_linked,
        "candidate_physical_device_id": decision.candidate_physical_device_id,
        "assigned_physical_device_id": decision.assigned_physical_device_id,
        "reasons": decision.reasons,
        "decided_at_utc": decision.decided_at_utc,
    }


def observation_summary(observation: Observation, decision: IdentityDecision | None) -> dict:
    return {
        "event_id": observation.event_id,
        "event_type": observation.event_type,
        "observed_at_utc": observation.observed_at_utc,
        "received_at_utc": observation.received_at_utc,
        "hostname": observation.hostname,
        "user_sid": observation.user_sid,
        "computer_id": observation.computer_id,
        "physical_device_id": observation.physical_device_id,
        "media_state_id": observation.media_state_id,
        "hardware_stable_sha256": observation.hardware_stable_sha256,
        "media_identity_sha256": observation.media_identity_sha256,
        "media_state_sha256": observation.media_state_sha256,
        "identity_decision": decision_summary(decision),
    }


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)) -> dict:
    decision_counts = {
        result: count
        for result, count in db.execute(
            select(IdentityDecision.result, func.count())
            .group_by(IdentityDecision.result)
        ).all()
    }
    return {
        "computers": db.scalar(select(func.count()).select_from(Computer)) or 0,
        "physical_devices": db.scalar(select(func.count()).select_from(PhysicalDevice)) or 0,
        "observations": db.scalar(select(func.count()).select_from(Observation)) or 0,
        "media_states": db.scalar(select(func.count()).select_from(MediaState)) or 0,
        "identity_alerts": (
            db.scalar(
                select(func.count())
                .select_from(IdentityDecision)
                .where(IdentityDecision.result.in_(("SERIAL_COLLISION", "CLONE_SUSPECTED")))
            ) or 0
        ),
        "identity_results": decision_counts,
        "latest_observation_at": db.scalar(select(func.max(Observation.observed_at_utc))),
    }


@router.get("/computers")
def list_computers(
    limit: Limit = 50,
    offset: Offset = 0,
    hostname: str | None = None,
    domain: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    statement = select(Computer).order_by(desc(Computer.last_seen_at), Computer.hostname)
    if hostname:
        statement = statement.where(Computer.hostname.ilike("%%%s%%" % hostname.strip()))
    if domain:
        statement = statement.where(Computer.domain.ilike("%%%s%%" % domain.strip()))
    return page(db, statement, limit, offset, lambda row: computer_summary(row[0]))


@router.get("/computers/{computer_id}")
def get_computer(computer_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    computer = db.get(Computer, computer_id)
    if computer is None:
        raise HTTPException(status_code=404, detail="computer not found")
    observations = list(db.execute(
        select(Observation, IdentityDecision)
        .outerjoin(IdentityDecision, IdentityDecision.observation_id == Observation.id)
        .where(Observation.computer_id == computer.id)
        .order_by(desc(Observation.observed_at_utc))
        .limit(100)
    ).all())
    result = computer_summary(computer)
    result["last_host"] = computer.last_host
    result["recent_observations"] = [
        observation_summary(item, decision) for item, decision in observations
    ]
    return result


@router.get("/devices")
def list_devices(
    limit: Limit = 50,
    offset: Offset = 0,
    status: str | None = None,
    confidence: str | None = None,
    hardware_hash: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    statement = select(PhysicalDevice).order_by(desc(PhysicalDevice.last_seen_at))
    if status:
        statement = statement.where(PhysicalDevice.status == status)
    if confidence:
        statement = statement.where(PhysicalDevice.identity_confidence == confidence)
    if hardware_hash:
        statement = statement.where(PhysicalDevice.hardware_stable_sha256 == hardware_hash)
    return page(db, statement, limit, offset, lambda row: device_summary(row[0]))


@router.get("/devices/{device_id}")
def get_device(device_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    device = db.get(PhysicalDevice, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="physical device not found")
    media_states = list(db.scalars(
        select(MediaState)
        .where(MediaState.physical_device_id == device.id)
        .order_by(desc(MediaState.last_seen_at))
    ))
    observations = list(db.execute(
        select(Observation, IdentityDecision)
        .outerjoin(IdentityDecision, IdentityDecision.observation_id == Observation.id)
        .where(Observation.physical_device_id == device.id)
        .order_by(desc(Observation.observed_at_utc))
        .limit(100)
    ).all())
    computers = list(db.scalars(
        select(Computer)
        .join(Observation, Observation.computer_id == Computer.id)
        .where(Observation.physical_device_id == device.id)
        .distinct()
        .order_by(Computer.hostname)
    ))
    user_sids = list(db.scalars(
        select(Observation.user_sid)
        .where(Observation.physical_device_id == device.id)
        .where(Observation.user_sid.is_not(None))
        .distinct()
        .order_by(Observation.user_sid)
    ))
    result = device_summary(device)
    result["representative_device"] = device.representative_device
    result["media_states"] = [
        {
            "id": state.id,
            "media_identity_sha256": state.media_identity_sha256,
            "media_state_sha256": state.media_state_sha256,
            "first_seen_at": state.first_seen_at,
            "last_seen_at": state.last_seen_at,
            "representative_media": state.representative_media,
        }
        for state in media_states
    ]
    result["recent_observations"] = [
        observation_summary(item, decision) for item, decision in observations
    ]
    result["used_on_computers"] = [computer_summary(item) for item in computers]
    result["seen_user_sids"] = user_sids
    return result


@router.get("/observations")
def list_observations(
    limit: Limit = 50,
    offset: Offset = 0,
    computer_id: uuid.UUID | None = None,
    physical_device_id: uuid.UUID | None = None,
    event_type: str | None = None,
    decision: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    statement = (
        select(Observation, IdentityDecision)
        .outerjoin(IdentityDecision, IdentityDecision.observation_id == Observation.id)
        .order_by(desc(Observation.observed_at_utc), desc(Observation.id))
    )
    if computer_id:
        statement = statement.where(Observation.computer_id == computer_id)
    if physical_device_id:
        statement = statement.where(Observation.physical_device_id == physical_device_id)
    if event_type:
        statement = statement.where(Observation.event_type == event_type)
    if decision:
        statement = statement.where(IdentityDecision.result == decision)
    return page(
        db, statement, limit, offset,
        lambda row: observation_summary(row[0], row[1]),
    )


@router.get("/observations/{event_id}")
def get_observation(event_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    row = db.execute(
        select(Observation, IdentityDecision)
        .outerjoin(IdentityDecision, IdentityDecision.observation_id == Observation.id)
        .where(Observation.event_id == event_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="observation not found")
    observation, decision = row
    result = observation_summary(observation, decision)
    result["raw_observation"] = observation.raw_observation
    result["source_ip"] = observation.source_ip
    return result


@router.get("/identity-decisions")
def list_identity_decisions(
    limit: Limit = 50,
    offset: Offset = 0,
    result: str | None = None,
    auto_linked: bool | None = None,
    db: Session = Depends(get_db),
) -> dict:
    statement = (
        select(IdentityDecision, Observation)
        .join(Observation, Observation.id == IdentityDecision.observation_id)
        .order_by(desc(IdentityDecision.decided_at_utc))
    )
    if result:
        statement = statement.where(IdentityDecision.result == result)
    if auto_linked is not None:
        statement = statement.where(IdentityDecision.auto_linked == auto_linked)

    def serialize(row):
        value = decision_summary(row[0])
        value["event_id"] = row[1].event_id
        value["hostname"] = row[1].hostname
        value["observed_at_utc"] = row[1].observed_at_utc
        return value

    return page(db, statement, limit, offset, serialize)


@router.get("/identity-alerts")
def list_identity_alerts(
    limit: Limit = 50,
    offset: Offset = 0,
    db: Session = Depends(get_db),
) -> dict:
    statement = (
        select(IdentityDecision, Observation)
        .join(Observation, Observation.id == IdentityDecision.observation_id)
        .where(IdentityDecision.result.in_(("SERIAL_COLLISION", "CLONE_SUSPECTED")))
        .order_by(desc(IdentityDecision.decided_at_utc))
    )

    def serialize(row):
        value = decision_summary(row[0])
        value["event_id"] = row[1].event_id
        value["hostname"] = row[1].hostname
        value["observed_at_utc"] = row[1].observed_at_utc
        return value

    return page(db, statement, limit, offset, serialize)


@router.get("/audit-log", dependencies=[Depends(require_roles("admin", "security"))])
def list_audit_log(
    limit: Limit = 50,
    offset: Offset = 0,
    action: str | None = None,
    success: bool | None = None,
    db: Session = Depends(get_db),
) -> dict:
    statement = select(AuditLog).order_by(desc(AuditLog.created_at_utc), desc(AuditLog.id))
    if action:
        statement = statement.where(AuditLog.action == action)
    if success is not None:
        statement = statement.where(AuditLog.success == success)

    def serialize(row):
        item = row[0]
        return {
            "id": item.id,
            "username": item.username,
            "action": item.action,
            "success": item.success,
            "source_ip": item.source_ip,
            "details": item.details,
            "created_at_utc": item.created_at_utc,
        }

    return page(db, statement, limit, offset, serialize)
