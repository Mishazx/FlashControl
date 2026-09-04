import hashlib
import hmac
import ipaddress
import secrets
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from .config import (
    DEV_MACHINE_TOKEN,
    ENROLL_NETWORKS,
    ENVIRONMENT,
    MACHINE_AUTH_MODE,
    MTLS_IDENTITIES,
    TRUSTED_MTLS_PROXIES,
    TRUSTED_PROXIES,
)
from .models import Agent


@dataclass(frozen=True)
class MachinePrincipal:
    id: uuid.UUID
    kind: str
    certificate_fingerprint: str | None = None


def hash_machine_token(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def new_machine_token() -> str:
    return secrets.token_urlsafe(48)


def _normalized_fingerprint(value: str) -> str:
    return value.replace(":", "").strip().lower()


def _parse_ip(value: str | None) -> ipaddress._BaseAddress | None:
    if not value:
        return None
    host = value.strip()
    if host.startswith("["):
        host = host.split("]", 1)[0][1:]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _in_networks(address: ipaddress._BaseAddress | None, networks: tuple[str, ...]) -> bool:
    if address is None or not networks:
        return False
    try:
        return any(address in ipaddress.ip_network(item) for item in networks)
    except ValueError:
        return False


def source_ip(request: Request) -> ipaddress._BaseAddress | None:
    if not request.client:
        return None
    return _parse_ip(request.client.host)


def client_host(request: Request) -> str | None:
    """Original client address for audit and sessions.

    The TCP peer stays in ``request.client`` so mTLS terminator checks keep
    seeing Nginx, not the browser. Forwarded headers are used only when that
    peer is in ``TRUSTED_PROXIES``.
    """
    raw_peer = request.client.host if request.client else None
    peer = _parse_ip(raw_peer)
    if not _in_networks(peer, TRUSTED_PROXIES):
        return raw_peer
    real = _parse_ip(request.headers.get("x-real-ip"))
    if real is not None:
        return str(real)
    forwarded = [
        parsed
        for parsed in (
            _parse_ip(part)
            for part in request.headers.get("x-forwarded-for", "").split(",")
        )
        if parsed is not None
    ]
    for candidate in reversed(forwarded):
        if not _in_networks(candidate, TRUSTED_PROXIES):
            return str(candidate)
    if forwarded:
        return str(forwarded[0])
    return raw_peer


def source_in_networks(request: Request, networks: tuple[str, ...]) -> bool:
    peer = source_ip(request)
    if peer is None:
        return False
    try:
        return any(peer in ipaddress.ip_network(value) for value in networks)
    except ValueError:
        return False


def _peer_is_trusted(request: Request) -> bool:
    return source_in_networks(request, TRUSTED_MTLS_PROXIES)


def enroll_source_allowed(request: Request) -> bool:
    if MACHINE_AUTH_MODE != "token":
        return False
    if not ENROLL_NETWORKS:
        return ENVIRONMENT in ("development", "test")
    return source_in_networks(request, ENROLL_NETWORKS)


def _shared_token_matches(supplied: str) -> bool:
    if not DEV_MACHINE_TOKEN or not supplied:
        return False
    return hmac.compare_digest(
        hashlib.sha256(supplied.encode()).digest(),
        hashlib.sha256(DEV_MACHINE_TOKEN.encode()).digest(),
    )


def _issued_agent_token_matches(db: Session | None, agent_id: uuid.UUID, supplied: str) -> bool:
    if db is None or not supplied:
        return False
    agent = db.get(Agent, agent_id)
    stored = getattr(agent, "token_hash", None) if agent is not None else None
    if not stored:
        return False
    return hmac.compare_digest(hash_machine_token(supplied), stored)


def require_machine(request: Request, db: Session | None = None) -> MachinePrincipal:
    if MACHINE_AUTH_MODE == "token":
        supplied = request.headers.get("X-FlashControl-Machine-Token", "")
        machine_id = request.headers.get("X-FlashControl-Machine-ID", "")
        kind = request.headers.get("X-FlashControl-Machine-Kind", "agent").lower()
        if kind not in ("agent", "proxy"):
            raise HTTPException(status_code=401, detail="invalid machine credentials")
        try:
            principal_id = uuid.UUID(machine_id)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="invalid machine identity") from exc
        if kind == "agent" and _issued_agent_token_matches(db, principal_id, supplied):
            return MachinePrincipal(principal_id, kind)
        # The shared dev/test token is a convenience for local tooling only. It
        # must never act as a fallback in production, where machines are
        # authenticated by enrolled certificate identity (mTLS).
        if ENVIRONMENT in ("development", "test") and _shared_token_matches(supplied):
            return MachinePrincipal(principal_id, kind)
        raise HTTPException(status_code=401, detail="invalid machine credentials")

    if not _peer_is_trusted(request):
        raise HTTPException(status_code=401, detail="untrusted mTLS terminator")
    if request.headers.get("X-FlashControl-Client-Verify", "") != "SUCCESS":
        raise HTTPException(status_code=401, detail="client certificate was not verified")
    fingerprint = _normalized_fingerprint(
        request.headers.get("X-FlashControl-Client-Fingerprint", "")
    )
    configured = {
        _normalized_fingerprint(key): value for key, value in MTLS_IDENTITIES.items()
    }.get(fingerprint)
    if not configured or ":" not in configured:
        raise HTTPException(status_code=401, detail="client certificate is not enrolled")
    kind, raw_id = configured.split(":", 1)
    if kind not in ("agent", "proxy"):
        raise HTTPException(status_code=401, detail="invalid certificate enrollment")
    try:
        return MachinePrincipal(uuid.UUID(raw_id), kind, fingerprint)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid certificate enrollment") from exc
