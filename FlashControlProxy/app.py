import asyncio
import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import ssl
import uuid

import httpx
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request

from FlashControlProxy.queue import ProxyQueue, QueueFullError


PROXY_ID = uuid.UUID(os.environ.get("FLASHCONTROL_PROXY_ID", "00000000-0000-0000-0000-000000000001"))
QUEUE_PATH = os.environ.get("FLASHCONTROL_PROXY_QUEUE", "flashcontrol-proxy.db")
QUEUE_MAX_ITEMS = int(os.environ.get("FLASHCONTROL_PROXY_QUEUE_MAX_ITEMS", "100000"))
ALLOWED_NETWORKS = tuple(
    ipaddress.ip_network(item.strip())
    for item in os.environ.get("FLASHCONTROL_PROXY_ALLOWED_NETWORKS", "127.0.0.0/8,::1/128").split(",")
    if item.strip()
)
AGENT_TOKEN = os.environ.get("FLASHCONTROL_PROXY_AGENT_TOKEN", "")
ENROLL_TOKEN = os.environ.get("FLASHCONTROL_PROXY_ENROLL_TOKEN", AGENT_TOKEN)
AUTH_MODE = os.environ.get("FLASHCONTROL_PROXY_AUTH_MODE", "token").lower()
TRUSTED_MTLS_PROXIES = tuple(
    ipaddress.ip_network(item.strip())
    for item in os.environ.get("FLASHCONTROL_PROXY_TRUSTED_MTLS_PROXIES", "").split(",")
    if item.strip()
)
MTLS_AGENTS = {
    key.replace(":", "").lower(): uuid.UUID(value)
    for key, value in json.loads(os.environ.get("FLASHCONTROL_PROXY_MTLS_AGENTS", "{}" )).items()
}
MAIN_TOKEN = os.environ.get("FLASHCONTROL_PROXY_MAIN_TOKEN", "")
MAIN_OBSERVATIONS_URL = os.environ.get("FLASHCONTROL_MAIN_OBSERVATIONS_URL", "").strip()
MAIN_HEARTBEAT_URL = os.environ.get("FLASHCONTROL_MAIN_HEARTBEAT_URL", "").strip()
FORWARD_INTERVAL = max(1, int(os.environ.get("FLASHCONTROL_PROXY_FORWARD_INTERVAL", "5")))
MAIN_CA_FILE = os.environ.get("FLASHCONTROL_PROXY_MAIN_CA_FILE", "")
MAIN_CLIENT_CERT = os.environ.get("FLASHCONTROL_PROXY_MAIN_CLIENT_CERT", "")
MAIN_CLIENT_KEY = os.environ.get("FLASHCONTROL_PROXY_MAIN_CLIENT_KEY", "")


def _hash_token(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def require_agent(
    request: Request,
    machine_id: uuid.UUID = Header(alias="X-FlashControl-Machine-ID"),
    machine_kind: str = Header(default="agent", alias="X-FlashControl-Machine-Kind"),
    machine_token: str = Header(default="", alias="X-FlashControl-Machine-Token"),
) -> uuid.UUID:
    try:
        source = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="invalid source address") from exc
    if not any(source in network for network in ALLOWED_NETWORKS):
        raise HTTPException(status_code=403, detail="source network is not allowed")
    if machine_kind != "agent":
        raise HTTPException(status_code=401, detail="invalid agent credentials")
    if AUTH_MODE == "token":
        if queue.agent_token_matches(machine_id, _hash_token(machine_token)):
            return machine_id
        raise HTTPException(status_code=401, detail="invalid agent credentials")
    if AUTH_MODE != "mtls" or not any(source in network for network in TRUSTED_MTLS_PROXIES):
        raise HTTPException(status_code=401, detail="untrusted mTLS terminator")
    if request.headers.get("X-FlashControl-Client-Verify") != "SUCCESS":
        raise HTTPException(status_code=401, detail="client certificate was not verified")
    fingerprint = request.headers.get("X-FlashControl-Client-Fingerprint", "").replace(":", "").lower()
    enrolled_id = MTLS_AGENTS.get(fingerprint)
    if enrolled_id is None or enrolled_id != machine_id:
        raise HTTPException(status_code=401, detail="client certificate is not enrolled")
    return enrolled_id


queue = ProxyQueue(QUEUE_PATH, QUEUE_MAX_ITEMS)


def main_ssl_context():
    context = ssl.create_default_context(cafile=MAIN_CA_FILE or None)
    if MAIN_CLIENT_CERT:
        context.load_cert_chain(MAIN_CLIENT_CERT, MAIN_CLIENT_KEY or None)
    return context


async def forward_once(client=None):
    if not MAIN_OBSERVATIONS_URL or not MAIN_HEARTBEAT_URL:
        return 0
    delivered = 0
    owned_client = client is None
    if owned_client:
        client = httpx.AsyncClient(timeout=30, verify=main_ssl_context())
    try:
        for item in queue.due():
            url = MAIN_OBSERVATIONS_URL if item["kind"] == "observation" else MAIN_HEARTBEAT_URL
            headers = {
                "X-FlashControl-Machine-ID": str(PROXY_ID),
                "X-FlashControl-Machine-Kind": "proxy",
                "X-FlashControl-Machine-Token": MAIN_TOKEN,
                "X-FlashControl-Forwarded-Agent-ID": item["agent_id"],
            }
            try:
                response = await client.post(url, content=item["payload_json"], headers=headers)
                response.raise_for_status()
                queue.delivered(item["item_key"])
                delivered += 1
            except Exception as exc:
                queue.failed(item["item_key"], exc)
    finally:
        if owned_client:
            await client.aclose()
    return delivered


async def forward_loop():
    while True:
        await forward_once()
        await asyncio.sleep(FORWARD_INTERVAL)


@contextlib.asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(forward_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="FlashControl Proxy Collector", lifespan=lifespan)


@app.post("/api/v1/agents/enroll")
def enroll(request: Request, payload: dict = Body(...)):
    try:
        source = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="invalid source address") from exc
    if not any(source in network for network in ALLOWED_NETWORKS):
        raise HTTPException(status_code=403, detail="source network is not allowed")
    # Enrollment is a privileged operation: network location alone does not
    # prove that a caller is an approved agent.  The bootstrap token is used
    # only here; it never authenticates telemetry after enrollment.
    supplied_token = request.headers.get("X-FlashControl-Enroll-Token", "")
    if AUTH_MODE != "token" or not ENROLL_TOKEN or not hmac.compare_digest(
        _hash_token(supplied_token), _hash_token(ENROLL_TOKEN)
    ):
        raise HTTPException(status_code=401, detail="invalid enrollment credentials")
    try:
        agent_id = uuid.UUID(str(payload.get("agent_id") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="agent_id must be a UUID") from exc
    hostname = str(payload.get("hostname") or "").strip()
    if not hostname:
        raise HTTPException(status_code=422, detail="hostname is required")
    domain = payload.get("domain")
    if domain is not None:
        domain = str(domain).strip() or None
    token = secrets.token_urlsafe(48)
    try:
        queue.issue_agent_token(
            agent_id,
            _hash_token(token),
            hostname,
            domain,
            str(source),
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"agent_id": str(agent_id), "machine_token": token}


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    return {"status": "ok", "queue_size": queue.count()}


@app.post("/api/v1/observations", status_code=202)
def observations(payload: object = Body(...), agent_id: uuid.UUID = Depends(require_agent)):
    try:
        queue.enqueue_observations(agent_id, payload)
    except QueueFullError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "accepted", "queue_size": queue.count()}


@app.post("/api/v1/agents/heartbeat", status_code=202)
def heartbeat(payload: dict = Body(...), agent_id: uuid.UUID = Depends(require_agent)):
    if str(payload.get("agent_id")) != str(agent_id):
        raise HTTPException(status_code=403, detail="agent identity mismatch")
    payload = dict(payload)
    payload["selected_route"] = "proxy"
    payload["proxy_id"] = str(PROXY_ID)
    try:
        queue.enqueue_heartbeat(agent_id, payload)
    except QueueFullError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    return {"status": "accepted", "queue_size": queue.count()}
