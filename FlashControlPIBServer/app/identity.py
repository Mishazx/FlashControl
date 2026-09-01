import datetime
import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .models import Computer, IdentityDecision, MediaState, Observation, PhysicalDevice


COLLISION_WINDOW = datetime.timedelta(minutes=10)
RESULT_PRIORITY = {
    "SERIAL_COLLISION": 7,
    "CLONE_SUSPECTED": 6,
    "SAME": 5,
    "LIKELY_SAME": 3,
    "UNKNOWN": 2,
    "DIFFERENT": 0,
}


@dataclass(frozen=True)
class Classification:
    result: str
    confidence: float
    auto_link: bool
    reasons: list[str]


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _latest(left: datetime.datetime, right: datetime.datetime) -> datetime.datetime:
    return left if _utc(left) >= _utc(right) else right


def computer_key(host: dict) -> str:
    hostname = str(host.get("hostname") or host.get("computer_name") or "").strip().lower()
    domain = str(host.get("domain") or host.get("domain_name") or "").strip().lower()
    identity = domain + "\\" + hostname
    if not hostname:
        identity = "missing-hostname:" + json.dumps(
            host, sort_keys=True, separators=(",", ":"), default=str
        )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def strong_identifiers(device: dict) -> set[str]:
    values = set()
    vpd83 = device.get("vpd83") or []
    if isinstance(vpd83, dict):
        vpd83 = vpd83.get("identifiers") or []
    for item in vpd83:
        if isinstance(item, dict):
            value = item.get("value") or item.get("identifier")
        else:
            value = item
        if value:
            values.add("vpd83:" + str(value).strip().lower())
    return values


def serial_identifiers(device: dict) -> set[str]:
    values = set()
    storage = device.get("storage") or {}
    if storage.get("serial"):
        values.add("storage:" + str(storage["serial"]).strip().lower())
    usb = ((device.get("pnp") or {}).get("usb") or {})
    candidate = usb.get("serial_candidate") or {}
    if isinstance(candidate, dict) and candidate.get("value"):
        values.add("usb:" + str(candidate["value"]).strip().lower())
    return values


def classify_pair(current: Observation, previous: Observation) -> Classification:
    current_device = current.device or {}
    previous_device = previous.device or {}
    same_hardware = bool(
        current.hardware_stable_sha256
        and current.hardware_stable_sha256 == previous.hardware_stable_sha256
    )
    same_media = bool(
        current.media_identity_sha256
        and current.media_identity_sha256 == previous.media_identity_sha256
    )
    common_strong = strong_identifiers(current_device) & strong_identifiers(previous_device)
    common_serials = serial_identifiers(current_device) & serial_identifiers(previous_device)

    if common_strong and same_hardware:
        return Classification("SAME", 0.99, True, ["matching_vpd83", "matching_hardware"])
    if same_hardware and same_media and current.computer_id == previous.computer_id:
        return Classification(
            "SAME", 0.95, True,
            ["matching_hardware", "matching_media_identity", "same_computer"],
        )
    if same_hardware and same_media:
        return Classification(
            "LIKELY_SAME", 0.80, False,
            ["matching_hardware", "matching_media_identity", "different_computer"],
        )
    if not same_hardware and same_media:
        return Classification(
            "CLONE_SUSPECTED", 0.20, False,
            ["different_hardware", "matching_media_identity"],
        )
    if not same_hardware and common_serials:
        return Classification(
            "SERIAL_COLLISION", 0.05, False,
            ["different_hardware", "matching_serial_evidence"],
        )
    if same_hardware:
        return Classification(
            "UNKNOWN", 0.45, False,
            ["matching_hardware", "different_or_missing_media_identity"],
        )
    return Classification("DIFFERENT", 0.0, False, ["different_hardware"])


def register_computer(db: Session, observation: Observation) -> Computer:
    key = computer_key(observation.host)
    computer = db.scalar(select(Computer).where(Computer.computer_key == key))
    hostname = str(observation.host.get("hostname") or observation.host.get("computer_name") or "unknown")
    domain = observation.host.get("domain") or observation.host.get("domain_name")
    if computer is None:
        computer = Computer(
            id=uuid.uuid4(), computer_key=key, hostname=hostname, domain=domain,
            first_seen_at=observation.observed_at_utc,
            last_seen_at=observation.observed_at_utc, last_host=observation.host,
        )
        db.add(computer)
        db.flush()
    else:
        computer.hostname = hostname
        computer.domain = domain
        computer.last_seen_at = _latest(computer.last_seen_at, observation.observed_at_utc)
        computer.last_host = observation.host
    observation.computer_id = computer.id
    return computer


def _new_physical_device(observation: Observation) -> PhysicalDevice:
    return PhysicalDevice(
        id=uuid.uuid4(),
        hardware_stable_sha256=observation.hardware_stable_sha256,
        status="provisional", identity_confidence="unknown",
        first_seen_at=observation.observed_at_utc,
        last_seen_at=observation.observed_at_utc,
        representative_device=observation.device,
    )


def _latest_observations(db: Session, observation: Observation) -> list[Observation]:
    return list(db.scalars(
        select(Observation)
        .where(Observation.id != observation.id)
        .where(Observation.physical_device_id.is_not(None))
        .order_by(desc(Observation.observed_at_utc))
        .limit(200)
    ))


def _collision_context(current: Observation, previous: Observation) -> bool:
    if current.computer_id == previous.computer_id:
        return False
    current_time = current.observed_at_utc
    previous_time = previous.observed_at_utc
    return abs(_utc(current_time) - _utc(previous_time)) <= COLLISION_WINDOW


def _media_snapshot(device: dict) -> dict:
    return {
        "layout": device.get("layout"),
        "volumes": device.get("volumes") or [],
    }


def _get_or_create_media_state(db: Session, physical: PhysicalDevice,
                               observation: Observation) -> MediaState:
    state = db.scalar(
        select(MediaState)
        .where(MediaState.physical_device_id == physical.id)
        .where(MediaState.media_identity_sha256 == observation.media_identity_sha256)
        .where(MediaState.media_state_sha256 == observation.media_state_sha256)
    )
    if state is None:
        state = MediaState(
            id=uuid.uuid4(), physical_device_id=physical.id,
            media_identity_sha256=observation.media_identity_sha256,
            media_state_sha256=observation.media_state_sha256,
            first_seen_at=observation.observed_at_utc,
            last_seen_at=observation.observed_at_utc,
            representative_media=_media_snapshot(observation.device),
        )
        db.add(state)
        db.flush()
    else:
        state.last_seen_at = _latest(state.last_seen_at, observation.observed_at_utc)
    return state


def resolve_identity(db: Session, observation: Observation) -> IdentityDecision:
    candidates = _latest_observations(db, observation)
    classification = Classification("UNKNOWN", 0.0, False, ["first_observation"])
    candidate = None

    for previous in candidates:
        pair = classify_pair(observation, previous)
        if _collision_context(observation, previous) and pair.result in (
            "UNKNOWN", "LIKELY_SAME", "SAME"
        ):
            pair = Classification(
                "SERIAL_COLLISION", 0.05, False,
                pair.reasons + ["simultaneous_different_computers"],
            )
        if pair.result != "DIFFERENT" and (
            candidate is None
            or RESULT_PRIORITY[pair.result] > RESULT_PRIORITY[classification.result]
            or (
                RESULT_PRIORITY[pair.result] == RESULT_PRIORITY[classification.result]
                and pair.confidence > classification.confidence
            )
        ):
            candidate = previous
            classification = pair

    if classification.auto_link and candidate is not None:
        physical = db.get(PhysicalDevice, candidate.physical_device_id)
        physical.last_seen_at = _latest(physical.last_seen_at, observation.observed_at_utc)
        physical.identity_confidence = "high" if classification.result == "SAME" else "likely"
    else:
        physical = _new_physical_device(observation)
        db.add(physical)
        db.flush()

    observation.physical_device_id = physical.id
    media_state = _get_or_create_media_state(db, physical, observation)
    observation.media_state_id = media_state.id
    decision = IdentityDecision(
        id=uuid.uuid4(), observation_id=observation.id,
        result=classification.result, confidence=classification.confidence,
        auto_linked=classification.auto_link,
        candidate_physical_device_id=(candidate.physical_device_id if candidate else None),
        assigned_physical_device_id=physical.id,
        reasons=classification.reasons,
    )
    db.add(decision)
    return decision
