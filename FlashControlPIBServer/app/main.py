from contextlib import asynccontextmanager
import datetime
import uuid
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from .db import engine, get_db, initialize_database
from .auth import (
    ALLOWED_ROLES, AuthContext, audit, create_local_user, hash_password,
    optional_auth_context, require_csrf, require_roles, router as auth_router,
)
from .config import ENVIRONMENT
from .enroll import issue_agent_token
from .identity import ensure_computer, presence_host, register_computer, resolve_identity
from .machine_auth import MachinePrincipal, require_machine
from .models import Agent, AuthSession, AuthUser, Computer, IdentityDecision, MediaState, Observation, PhysicalDevice
from .ratelimit import enroll_limiter, heartbeat_limiter, ingest_limiter
from .read_api import router as read_router
from .schemas import AgentEnrollIn, AgentEnrollOut, AgentHeartbeatIn, IngestResult, ObservationIn


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="FlashControl Main Server",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if ENVIRONMENT == "production" else "/docs",
    redoc_url=None if ENVIRONMENT == "production" else "/redoc",
    openapi_url=None if ENVIRONMENT == "production" else "/openapi.json",
)
app.include_router(auth_router)
app.include_router(read_router)
if ENVIRONMENT == "development":
    from .sqladmin_views import mount_development_sqladmin

    mount_development_sqladmin(app)
web_directory = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=web_directory), name="static")


@app.get("/", include_in_schema=False, response_model=None)
def web_ui(
    context: AuthContext | None = Depends(optional_auth_context),
) -> FileResponse | RedirectResponse:
    if context is None:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(web_directory / "index.html")


@app.get("/login", include_in_schema=False, response_model=None)
def login_page() -> FileResponse:
    return FileResponse(web_directory / "login.html")


class UserCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=1024)
    role: str


class UserUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    enabled: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=1024)


def user_summary(user: AuthUser, sessions: int = 0) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "enabled": user.enabled,
        "is_local": user.password_hash is not None,
        "created_at_utc": user.created_at_utc,
        "last_login_at_utc": user.last_login_at_utc,
        "active_sessions": sessions,
    }


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path in ("/", "/login"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
    return response


def idempotent_insert(values: dict):
    if engine.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    return (
        insert(Observation)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[Observation.event_id])
        .returning(Observation.event_id)
    )


SHARED_OBSERVATION_KEYS = ("schema_version", "probe_version", "host", "session")


def unpack_payload(payload: Any) -> list[ObservationIn]:
    if isinstance(payload, dict) and "observations" in payload:
        values = payload.get("observations")
        shared = {
            key: payload[key]
            for key in SHARED_OBSERVATION_KEYS
            if key in payload
        }
    else:
        values = [payload]
        shared = {}
    if not isinstance(values, list) or not values:
        raise ValueError("payload must contain at least one observation")
    observations = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("every observation must be an object")
        merged = dict(shared)
        merged.update(value)
        observations.append(ObservationIn.model_validate(merged))
    return observations


def observation_hash_value(item: ObservationIn, column: str) -> str | None:
    aliases = {
        "hardware_stable_sha256": ("hardware", "hardware_stable_sha256", "hardware_stable"),
        "pnp_observation_sha256": ("pnp_observation_sha256", "pnp"),
        # New agents send the two unambiguous public hashes.  The two legacy
        # columns are populated from software during the migration period.
        "media_identity_sha256": ("software", "media_identity_sha256", "media_identity"),
        "media_state_sha256": ("software", "media_state_sha256", "media_state"),
    }
    hashes = item.hashes or {}
    device = item.device or {}
    for key in aliases[column]:
        value = hashes.get(key)
        if value:
            return str(value)
    value = device.get(column)
    return str(value) if value else None


def observation_values(
    item: ObservationIn, source_ip: str | None,
    agent_id: object, proxy_id: object | None,
) -> dict:
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
        "hardware_stable_sha256": observation_hash_value(item, "hardware_stable_sha256"),
        "pnp_observation_sha256": observation_hash_value(item, "pnp_observation_sha256"),
        "media_identity_sha256": observation_hash_value(item, "media_identity_sha256"),
        "media_state_sha256": observation_hash_value(item, "media_state_sha256"),
        "host": item.host,
        "session": item.session,
        "device": device,
        "capabilities": item.capabilities or {},
        "capability_status": item.capability_status or {},
        "collector_errors": item.collector_errors or [],
        "raw_observation": raw,
        "source_ip": source_ip,
        "agent_id": agent_id,
        "proxy_id": proxy_id,
    }


def clear_device_candidate_refs(db: Session, device_id) -> None:
    for decision in db.scalars(
        select(IdentityDecision).where(IdentityDecision.candidate_physical_device_id == device_id)
    ):
        decision.candidate_physical_device_id = None


def delete_observation_record(db: Session, observation: Observation, prune_device: bool) -> dict[str, int]:
    deleted_decisions = 0
    deleted_media_states = 0
    deleted_devices = 0

    decision = db.scalar(
        select(IdentityDecision).where(IdentityDecision.observation_id == observation.id)
    )
    if decision is not None:
        db.delete(decision)
        deleted_decisions = 1

    media_state_id = observation.media_state_id
    physical_device_id = observation.physical_device_id
    db.delete(observation)
    db.flush()

    if media_state_id is not None:
        media_state = db.get(MediaState, media_state_id)
        if media_state is not None:
            remaining = db.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.media_state_id == media_state_id)
            ) or 0
            if remaining == 0:
                db.delete(media_state)
                deleted_media_states += 1

    if prune_device and physical_device_id is not None:
        physical_device = db.get(PhysicalDevice, physical_device_id)
        if physical_device is not None:
            remaining = db.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.physical_device_id == physical_device_id)
            ) or 0
            if remaining == 0:
                clear_device_candidate_refs(db, physical_device_id)
                for media_state in list(db.scalars(
                    select(MediaState).where(MediaState.physical_device_id == physical_device_id)
                )):
                    db.delete(media_state)
                    deleted_media_states += 1
                db.delete(physical_device)
                deleted_devices = 1

    return {
        "deleted_observations": 1,
        "deleted_decisions": deleted_decisions,
        "deleted_media_states": deleted_media_states,
        "deleted_devices": deleted_devices,
    }


def require_ingest_machine(
    request: Request,
    db: Session = Depends(get_db),
) -> MachinePrincipal:
    return require_machine(request, db)


def optional_machine_auth(
    request: Request,
    db: Session = Depends(get_db),
) -> MachinePrincipal | None:
    """Resolve machine auth when a token is presented, else None.

    Used by the enrollment endpoint so a re-enroll can prove possession of the
    current token while a first-time enroll may proceed without one.
    """
    if not request.headers.get("X-FlashControl-Machine-Token"):
        return None
    return require_machine(request, db)


def require_management_context(
    context: AuthContext = Depends(require_csrf),
) -> AuthContext:
    if context.user.role not in ("admin", "security"):
        raise HTTPException(status_code=403, detail="insufficient role")
    return context


def require_admin_context(
    context: AuthContext = Depends(require_csrf),
) -> AuthContext:
    if context.user.role != "admin":
        raise HTTPException(status_code=403, detail="insufficient role")
    return context


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/v1/users")
def list_users(
    q: str = "",
    _: AuthUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(AuthUser).order_by(AuthUser.username)
    if q.strip():
        statement = statement.where(AuthUser.username.ilike(f"%{q.strip()}%"))
    users = list(db.scalars(statement))
    now = datetime.datetime.now(datetime.timezone.utc)
    session_counts = dict(db.execute(
        select(AuthSession.user_id, func.count(AuthSession.id))
        .where(AuthSession.expires_at_utc > now)
        .group_by(AuthSession.user_id)
    ).all())
    return {"items": [user_summary(user, session_counts.get(user.id, 0)) for user in users], "total": len(users)}


@app.post("/api/v1/users", status_code=201)
def create_user(
    payload: UserCreateIn,
    request: Request,
    context: AuthContext = Depends(require_admin_context),
    db: Session = Depends(get_db),
) -> dict:
    if payload.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=422, detail="invalid role")
    try:
        user = create_local_user(db, payload.username, payload.password, payload.role)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    audit(db, request, "users.create", True, user=context.user, details={"username": user.username, "role": user.role})
    db.commit()
    return user_summary(user)


@app.patch("/api/v1/users/{user_id}")
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateIn,
    request: Request,
    context: AuthContext = Depends(require_admin_context),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(AuthUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if payload.role is not None and payload.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=422, detail="invalid role")
    if user.id == context.user.id and (payload.enabled is False or (payload.role is not None and payload.role != "admin")):
        raise HTTPException(status_code=422, detail="cannot remove own administrator access")

    changes = {}
    if payload.role is not None and payload.role != user.role:
        user.role = payload.role
        changes["role"] = payload.role
    if payload.enabled is not None and payload.enabled != user.enabled:
        user.enabled = payload.enabled
        changes["enabled"] = payload.enabled
    if payload.password is not None:
        if user.password_hash is None:
            raise HTTPException(status_code=422, detail="password cannot be set for a directory user")
        user.password_hash = hash_password(payload.password)
        changes["password_reset"] = True
    if changes:
        if payload.enabled is False or payload.password is not None:
            db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        audit(db, request, "users.update", True, user=context.user, details={"username": user.username, **changes})
        db.commit()
        db.refresh(user)
    return user_summary(user)


@app.post("/api/v1/agents/enroll", response_model=AgentEnrollOut)
def agent_enroll(
    request: Request,
    payload: AgentEnrollIn,
    _: None = Depends(enroll_limiter),
    authenticated: MachinePrincipal | None = Depends(optional_machine_auth),
    db: Session = Depends(get_db),
) -> AgentEnrollOut:
    return issue_agent_token(request, payload, db, authenticated=authenticated)


@app.post("/api/v1/agents/heartbeat", status_code=202)
def agent_heartbeat(
    request: Request,
    payload: AgentHeartbeatIn,
    _: None = Depends(heartbeat_limiter),
    principal: MachinePrincipal = Depends(require_ingest_machine),
    db: Session = Depends(get_db),
) -> dict:
    if principal.kind == "agent":
        if payload.agent_id != principal.id:
            raise HTTPException(status_code=403, detail="agent identity mismatch")
        if payload.proxy_id is not None:
            raise HTTPException(status_code=403, detail="direct agent cannot assert proxy identity")
    elif payload.proxy_id != principal.id:
        raise HTTPException(status_code=403, detail="proxy identity mismatch")
    now = datetime.datetime.now(datetime.timezone.utc)
    computer = ensure_computer(
        db,
        payload.hostname,
        payload.domain,
        now,
        presence_host(payload.hostname, payload.domain, payload.current_ips),
    )
    agent = db.get(Agent, payload.agent_id)
    if agent is None:
        agent = Agent(
            id=payload.agent_id,
            first_seen_at_utc=now,
            last_seen_at_utc=now,
            hostname=payload.hostname,
            domain=payload.domain,
            agent_version=payload.agent_version,
            current_ips=payload.current_ips,
            queue_size=payload.queue_size,
            selected_route=payload.selected_route,
        )
        db.add(agent)
    agent.computer_id = computer.id
    agent.hostname = payload.hostname
    agent.domain = payload.domain
    agent.agent_version = payload.agent_version
    agent.current_ips = payload.current_ips
    agent.queue_size = payload.queue_size
    agent.selected_route = payload.selected_route
    agent.proxy_id = payload.proxy_id
    agent.source_ip = request.client.host if request.client else None
    agent.last_seen_at_utc = now
    db.commit()
    return {"status": "accepted", "agent_id": payload.agent_id}


@app.post("/api/v1/observations", response_model=IngestResult)
def ingest_observations(
    request: Request,
    payload: Any = Body(...),
    forwarded_agent_id: uuid.UUID | None = Header(
        default=None, alias="X-FlashControl-Forwarded-Agent-ID"
    ),
    _: None = Depends(ingest_limiter),
    principal: MachinePrincipal = Depends(require_ingest_machine),
    db: Session = Depends(get_db),
) -> IngestResult:
    if principal.kind == "agent":
        if forwarded_agent_id is not None:
            raise HTTPException(status_code=403, detail="agent cannot forward another agent")
        source_agent_id, source_proxy_id = principal.id, None
    else:
        if forwarded_agent_id is None:
            raise HTTPException(status_code=400, detail="forwarded agent ID is required")
        source_agent_id, source_proxy_id = forwarded_agent_id, principal.id
    try:
        observations = unpack_payload(payload)
    except (ValidationError, ValueError) as exc:
        detail = exc.errors() if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc

    source_ip = request.client.host if request.client else None
    accepted_ids = []
    for item in observations:
        statement = idempotent_insert(observation_values(
            item, source_ip, source_agent_id, source_proxy_id
        ))
        inserted = db.execute(statement).scalar_one_or_none()
        if inserted is not None:
            accepted_ids.append(inserted)
            observation = db.scalar(
                select(Observation).where(Observation.event_id == inserted)
            )
            register_computer(db, observation)
            # An accepted direct-agent observation is authoritative evidence
            # of its computer, even before the next heartbeat arrives.
            if source_proxy_id is None:
                agent = db.get(Agent, source_agent_id)
                if agent is not None:
                    agent.computer_id = observation.computer_id
            resolve_identity(db, observation)
    db.commit()

    accepted = len(accepted_ids)
    return IngestResult(
        received=len(observations),
        accepted=accepted,
        duplicates=len(observations) - accepted,
        event_ids=accepted_ids,
    )


@app.delete("/api/v1/observations/{event_id}")
def delete_observation(
    event_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(require_management_context),
    db: Session = Depends(get_db),
) -> dict:
    observation = db.scalar(select(Observation).where(Observation.event_id == event_id))
    if observation is None:
        raise HTTPException(status_code=404, detail="observation not found")
    details = delete_observation_record(db, observation, prune_device=True)
    audit(
        db,
        request,
        "inventory.delete_observation",
        True,
        user=context.user,
        details={"event_id": str(event_id), **details},
    )
    db.commit()
    return {"status": "deleted", **details}


@app.delete("/api/v1/devices/{device_id}")
def delete_device(
    device_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(require_admin_context),
    db: Session = Depends(get_db),
) -> dict:
    device = db.get(PhysicalDevice, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="physical device not found")

    observations = list(db.scalars(
        select(Observation).where(Observation.physical_device_id == device.id)
    ))
    totals = {
        "deleted_observations": 0,
        "deleted_decisions": 0,
        "deleted_media_states": 0,
        "deleted_devices": 0,
    }
    for observation in observations:
        result = delete_observation_record(db, observation, prune_device=False)
        for key, value in result.items():
            totals[key] += value

    for media_state in list(db.scalars(
        select(MediaState).where(MediaState.physical_device_id == device.id)
    )):
        db.delete(media_state)
        totals["deleted_media_states"] += 1

    clear_device_candidate_refs(db, device.id)
    db.delete(device)
    totals["deleted_devices"] = 1
    audit(
        db,
        request,
        "inventory.delete_device",
        True,
        user=context.user,
        details={"device_id": str(device_id), **totals},
    )
    db.commit()
    return {"status": "deleted", **totals}


@app.delete("/api/v1/computers/{computer_id}")
def delete_computer(
    computer_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(require_admin_context),
    db: Session = Depends(get_db),
) -> dict:
    computer = db.get(Computer, computer_id)
    if computer is None:
        raise HTTPException(status_code=404, detail="computer not found")

    observations = list(db.scalars(
        select(Observation).where(Observation.computer_id == computer.id)
    ))
    totals = {
        "deleted_observations": 0,
        "deleted_decisions": 0,
        "deleted_media_states": 0,
        "deleted_devices": 0,
        "unlinked_agents": 0,
        "deleted_computers": 0,
    }
    for observation in observations:
        result = delete_observation_record(db, observation, prune_device=True)
        for key, value in result.items():
            totals[key] += value

    for agent in list(db.scalars(select(Agent).where(Agent.computer_id == computer.id))):
        agent.computer_id = None
        totals["unlinked_agents"] += 1

    db.delete(computer)
    totals["deleted_computers"] = 1
    audit(
        db,
        request,
        "inventory.delete_computer",
        True,
        user=context.user,
        details={"computer_id": str(computer_id), **totals},
    )
    db.commit()
    return {"status": "deleted", **totals}
