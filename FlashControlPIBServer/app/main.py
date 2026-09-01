from contextlib import asynccontextmanager
import datetime
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import engine, get_db, initialize_database
from .auth import AUTH_PROVIDER, AuthContext, optional_auth_context, router as auth_router
from .config import ENVIRONMENT
from .identity import register_computer, resolve_identity
from .models import Agent, Computer, Observation
from .read_api import router as read_router
from .schemas import AgentHeartbeatIn, IngestResult, ObservationIn


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
web_directory = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=web_directory), name="static")


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


@app.get("/", include_in_schema=False, response_model=None)
def web_ui(
    context: AuthContext | None = Depends(optional_auth_context),
) -> FileResponse | RedirectResponse:
    if context is None:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(web_directory / "index.html")


@app.get("/login", include_in_schema=False, response_model=None)
def login_page() -> FileResponse | RedirectResponse:
    if AUTH_PROVIDER != "local":
        return RedirectResponse("/api/v1/auth/oidc/start", status_code=303)
    return FileResponse(web_directory / "login.html")


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
        "hardware_stable_sha256": device.get("hardware_stable_sha256"),
        "pnp_observation_sha256": device.get("pnp_observation_sha256"),
        "media_identity_sha256": device.get("media_identity_sha256"),
        "media_state_sha256": device.get("media_state_sha256"),
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


@app.post("/api/v1/agents/heartbeat", status_code=202)
def agent_heartbeat(
    request: Request,
    payload: AgentHeartbeatIn,
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    agent = db.get(Agent, payload.agent_id)
    if agent is None:
        agent = Agent(id=payload.agent_id, first_seen_at_utc=now, last_seen_at_utc=now)
        db.add(agent)
    computer = db.scalar(
        select(Computer)
        .where(Computer.hostname == payload.hostname)
        .where(Computer.domain == payload.domain)
    )
    agent.computer_id = computer.id if computer else None
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
        statement = idempotent_insert(observation_values(item, source_ip))
        inserted = db.execute(statement).scalar_one_or_none()
        if inserted is not None:
            accepted_ids.append(inserted)
            observation = db.scalar(
                select(Observation).where(Observation.event_id == inserted)
            )
            register_computer(db, observation)
            resolve_identity(db, observation)
    db.commit()

    accepted = len(accepted_ids)
    return IngestResult(
        received=len(observations),
        accepted=accepted,
        duplicates=len(observations) - accepted,
        event_ids=accepted_ids,
    )
