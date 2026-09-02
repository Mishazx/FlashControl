import hashlib
import hmac
import ipaddress
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request

from .config import (
    DEV_MACHINE_TOKEN, MACHINE_AUTH_MODE, MTLS_IDENTITIES, TRUSTED_MTLS_PROXIES,
)


@dataclass(frozen=True)
class MachinePrincipal:
    id: uuid.UUID
    kind: str
    certificate_fingerprint: str | None = None


def _normalized_fingerprint(value: str) -> str:
    return value.replace(":", "").strip().lower()


def _peer_is_trusted(request: Request) -> bool:
    if not request.client:
        return False
    try:
        peer = ipaddress.ip_address(request.client.host)
        return any(peer in ipaddress.ip_network(value) for value in TRUSTED_MTLS_PROXIES)
    except ValueError:
        return False


def require_machine(request: Request) -> MachinePrincipal:
    if MACHINE_AUTH_MODE == "token":
        supplied = request.headers.get("X-FlashControl-Machine-Token", "")
        machine_id = request.headers.get("X-FlashControl-Machine-ID", "")
        kind = request.headers.get("X-FlashControl-Machine-Kind", "agent").lower()
        if (
            not DEV_MACHINE_TOKEN or not supplied
            or not hmac.compare_digest(
                hashlib.sha256(supplied.encode()).digest(),
                hashlib.sha256(DEV_MACHINE_TOKEN.encode()).digest(),
            )
            or kind not in ("agent", "proxy")
        ):
            raise HTTPException(status_code=401, detail="invalid machine credentials")
        try:
            return MachinePrincipal(uuid.UUID(machine_id), kind)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="invalid machine identity") from exc

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
