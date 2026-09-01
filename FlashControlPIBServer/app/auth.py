import datetime
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import (
    AUTH_PROVIDER, ENVIRONMENT, OIDC_ADMIN_GROUPS, OIDC_AUDITOR_GROUPS,
    OIDC_DEFAULT_ROLE, OIDC_GROUP_CLAIM, OIDC_ISSUER, OIDC_SECURITY_GROUPS,
    SESSION_HOURS,
)
from .db import get_db
from .models import AuditLog, AuthSession, AuthUser, OidcIdentity, OidcTransaction
from .oidc import FLOW_TTL, OidcError, authorization_url, exchange_code, redirect_uri_for


SESSION_COOKIE = "flashcontrol_session"
CSRF_COOKIE = "flashcontrol_csrf"
OIDC_FLOW_COOKIE = "flashcontrol_oidc_flow"
ALLOWED_ROLES = ("admin", "security", "auditor")
READ_ROLES = frozenset(ALLOWED_ROLES)
PASSWORD_N = 2 ** 14
PASSWORD_R = 8
PASSWORD_P = 1
LOGIN_WINDOW = datetime.timedelta(minutes=5)
LOGIN_FAILURE_LIMIT = 5
DUMMY_PASSWORD_HASH = (
    "scrypt$16384$8$1$00000000000000000000000000000000$"
    "cfcf41dd616a7d1da01df9dff8142141be5a408b029e68a13118fd27839a8dda"
)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


@dataclass(frozen=True)
class AuthContext:
    user: AuthUser
    session: AuthSession


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def as_utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not username or len(username) > 128:
        raise ValueError("invalid username")
    return username


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=PASSWORD_N, r=PASSWORD_R, p=PASSWORD_P, dklen=32,
    )
    return "scrypt${}${}${}${}${}".format(
        PASSWORD_N, PASSWORD_R, PASSWORD_P, salt.hex(), derived.hex()
    )


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(expected)),
        )
        return hmac.compare_digest(derived.hex(), expected)
    except (ValueError, TypeError):
        return False


def create_local_user(db: Session, username: str, password: str, role: str) -> AuthUser:
    if AUTH_PROVIDER != "local":
        raise RuntimeError("local users are disabled for the configured auth provider")
    normalized = normalize_username(username)
    if role not in ALLOWED_ROLES:
        raise ValueError("role must be one of: %s" % ", ".join(ALLOWED_ROLES))
    existing = db.scalar(select(AuthUser).where(AuthUser.username == normalized))
    if existing is not None:
        raise ValueError("user already exists")
    user = AuthUser(
        id=uuid.uuid4(), username=normalized, password_hash=hash_password(password),
        role=role, enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def audit(db: Session, request: Request, action: str, success: bool,
          user: AuthUser | None = None, username: str | None = None,
          details: dict | None = None) -> None:
    db.add(AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else username,
        action=action,
        success=success,
        source_ip=request.client.host if request.client else None,
        details=details or {},
    ))


def _session_from_request(request: Request, db: Session) -> AuthContext | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    auth_session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_secret(token))
    )
    if auth_session is None:
        return None
    if as_utc(auth_session.expires_at_utc) <= utcnow():
        db.delete(auth_session)
        db.commit()
        return None
    user = db.get(AuthUser, auth_session.user_id)
    if user is None or not user.enabled:
        return None
    auth_session.last_seen_at_utc = utcnow()
    return AuthContext(user=user, session=auth_session)


def optional_auth_context(
    request: Request, db: Session = Depends(get_db)
) -> AuthContext | None:
    return _session_from_request(request, db)


def require_auth_context(
    request: Request, db: Session = Depends(get_db)
) -> AuthContext:
    context = _session_from_request(request, db)
    if context is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return context


def require_read_user(context: AuthContext = Depends(require_auth_context)) -> AuthUser:
    if context.user.role not in READ_ROLES:
        raise HTTPException(status_code=403, detail="insufficient role")
    return context.user


def require_roles(*roles: str):
    allowed = frozenset(roles)

    def dependency(context: AuthContext = Depends(require_auth_context)) -> AuthUser:
        if context.user.role not in allowed:
            raise HTTPException(status_code=403, detail="insufficient role")
        return context.user

    return dependency


def require_csrf(
    request: Request,
    context: AuthContext = Depends(require_auth_context),
) -> AuthContext:
    supplied = request.headers.get("X-CSRF-Token", "")
    cookie_value = request.cookies.get(CSRF_COOKIE, "")
    if (
        not supplied
        or not cookie_value
        or not hmac.compare_digest(supplied, cookie_value)
        or not hmac.compare_digest(hash_secret(supplied), context.session.csrf_hash)
    ):
        raise HTTPException(status_code=403, detail="invalid CSRF token")
    return context


def _set_auth_cookies(response: Response, token: str, csrf_token: str) -> None:
    secure = ENVIRONMENT == "production"
    max_age = SESSION_HOURS * 3600
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True,
        secure=secure, samesite="strict", path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, max_age=max_age, httponly=False,
        secure=secure, samesite="strict", path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _create_session(db: Session, request: Request, user: AuthUser) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = utcnow()
    db.execute(delete(AuthSession).where(AuthSession.expires_at_utc <= now))
    db.add(AuthSession(
        id=uuid.uuid4(), user_id=user.id, token_hash=hash_secret(token),
        csrf_hash=hash_secret(csrf_token), created_at_utc=now,
        expires_at_utc=now + datetime.timedelta(hours=SESSION_HOURS),
        last_seen_at_utc=now,
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:512],
    ))
    user.last_login_at_utc = now
    return token, csrf_token


def role_for_groups(groups: list[str]) -> str | None:
    normalized = {item.casefold() for item in groups}
    for role, allowed in (
        ("admin", OIDC_ADMIN_GROUPS),
        ("security", OIDC_SECURITY_GROUPS),
        ("auditor", OIDC_AUDITOR_GROUPS),
    ):
        if normalized & allowed:
            return role
    return OIDC_DEFAULT_ROLE or None


def _claim_groups(claims: dict) -> list[str]:
    value = claims.get(OIDC_GROUP_CLAIM, [])
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(dict.fromkeys(value))
    raise OidcError("OIDC group claim has an invalid format")


def _oidc_username(claims: dict) -> str:
    for name in ("preferred_username", "upn", "email"):
        value = claims.get(name)
        if isinstance(value, str):
            try:
                return normalize_username(value)
            except ValueError:
                pass
    return "oidc-" + hashlib.sha256(claims["sub"].encode()).hexdigest()[:16]


def _upsert_oidc_user(db: Session, claims: dict, role: str, groups: list[str]) -> AuthUser:
    subject = claims["sub"]
    identity = db.scalar(select(OidcIdentity).where(
        OidcIdentity.issuer == OIDC_ISSUER.rstrip("/"),
        OidcIdentity.subject == subject,
    ))
    now = utcnow()
    if identity is not None:
        user = db.get(AuthUser, identity.user_id)
        if user is None:
            raise OidcError("OIDC identity references a missing user")
        identity.groups = groups
        identity.last_seen_at_utc = now
        user.role = role
        return user

    username = _oidc_username(claims)
    if db.scalar(select(AuthUser).where(AuthUser.username == username)) is not None:
        suffix = hashlib.sha256((OIDC_ISSUER + subject).encode()).hexdigest()[:8]
        username = (username[:119] + "~" + suffix)
    user = AuthUser(
        id=uuid.uuid4(), username=username, password_hash=None, role=role, enabled=True,
    )
    db.add(user)
    db.flush()
    db.add(OidcIdentity(
        id=uuid.uuid4(), user_id=user.id, issuer=OIDC_ISSUER.rstrip("/"),
        subject=subject, groups=groups, created_at_utc=now, last_seen_at_utc=now,
    ))
    return user


router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response,
          db: Session = Depends(get_db)) -> dict:
    if AUTH_PROVIDER != "local":
        raise HTTPException(status_code=501, detail="OIDC login is not implemented")
    try:
        username = normalize_username(payload.username)
    except ValueError:
        username = "invalid"
    source_ip = request.client.host if request.client else None
    since = utcnow() - LOGIN_WINDOW
    failed_count = db.scalar(
        select(func.count()).select_from(AuditLog)
        .where(AuditLog.action == "auth.login")
        .where(AuditLog.success.is_(False))
        .where(AuditLog.username == username)
        .where(AuditLog.source_ip == source_ip)
        .where(AuditLog.created_at_utc >= since)
    ) or 0
    if failed_count >= LOGIN_FAILURE_LIMIT:
        raise HTTPException(status_code=429, detail="too many login attempts")

    user = db.scalar(select(AuthUser).where(AuthUser.username == username))
    password_hash = user.password_hash if user and user.password_hash else DUMMY_PASSWORD_HASH
    password_valid = verify_password(payload.password, password_hash)
    valid = bool(user and user.enabled and password_valid)
    if not valid:
        audit(db, request, "auth.login", False, username=username, details={"reason": "invalid_credentials"})
        db.commit()
        raise HTTPException(status_code=401, detail="invalid username or password")

    token, csrf_token = _create_session(db, request, user)
    audit(db, request, "auth.login", True, user=user, details={"role": user.role})
    db.commit()
    _set_auth_cookies(response, token, csrf_token)
    return {"username": user.username, "role": user.role}


@router.get("/oidc/start", include_in_schema=False)
async def oidc_start(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    if AUTH_PROVIDER != "oidc":
        raise HTTPException(status_code=404, detail="OIDC authentication is disabled")
    state = secrets.token_urlsafe(32)
    browser_secret = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    now = utcnow()
    db.execute(delete(OidcTransaction).where(OidcTransaction.expires_at_utc <= now))
    db.add(OidcTransaction(
        id=uuid.uuid4(), state_hash=hash_secret(state),
        browser_hash=hash_secret(browser_secret), nonce=nonce,
        code_verifier=verifier, created_at_utc=now, expires_at_utc=now + FLOW_TTL,
    ))
    db.commit()
    try:
        target = await authorization_url(
            state, nonce, verifier, redirect_uri_for(str(request.base_url))
        )
    except OidcError as exc:
        audit(db, request, "auth.oidc.start", False, details={"reason": str(exc)})
        db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        OIDC_FLOW_COOKIE, browser_secret, max_age=int(FLOW_TTL.total_seconds()),
        httponly=True, secure=ENVIRONMENT == "production", samesite="lax", path="/",
    )
    return response


@router.get("/oidc/callback", include_in_schema=False)
async def oidc_callback(
    request: Request,
    code: str | None = Query(default=None, max_length=4096),
    state: str | None = Query(default=None, max_length=512),
    error: str | None = Query(default=None, max_length=256),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if AUTH_PROVIDER != "oidc":
        raise HTTPException(status_code=404, detail="OIDC authentication is disabled")
    if error or not code or not state:
        audit(db, request, "auth.login", False, details={"reason": "provider_rejected"})
        db.commit()
        raise HTTPException(status_code=401, detail="OIDC authentication was rejected")
    transaction = db.scalar(select(OidcTransaction).where(
        OidcTransaction.state_hash == hash_secret(state)
    ))
    browser_secret = request.cookies.get(OIDC_FLOW_COOKIE, "")
    browser_matches = bool(
        transaction and browser_secret and hmac.compare_digest(
            transaction.browser_hash, hash_secret(browser_secret)
        )
    )
    if (
        transaction is None
        or as_utc(transaction.expires_at_utc) <= utcnow()
        or not browser_matches
    ):
        audit(db, request, "auth.login", False, details={
            "provider": "oidc", "reason": "invalid_or_expired_state",
        })
        db.commit()
        raise HTTPException(status_code=401, detail="OIDC state is invalid or expired")
    nonce, verifier = transaction.nonce, transaction.code_verifier
    db.delete(transaction)
    db.commit()  # Consume state before the external token request; callbacks are one-shot.
    try:
        claims = await exchange_code(
            code, verifier, nonce, redirect_uri_for(str(request.base_url))
        )
        groups = _claim_groups(claims)
        role = role_for_groups(groups)
        if role is None:
            raise OidcError("OIDC account is not assigned to a FlashControl role")
        user = _upsert_oidc_user(db, claims, role, groups)
        if not user.enabled:
            raise OidcError("OIDC account is disabled")
        token, csrf_token = _create_session(db, request, user)
        audit(db, request, "auth.login", True, user=user, details={
            "provider": "oidc", "role": role,
        })
        db.commit()
    except OidcError as exc:
        db.rollback()
        audit(db, request, "auth.login", False, details={
            "provider": "oidc", "reason": str(exc),
        })
        db.commit()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    response = RedirectResponse("/", status_code=303)
    _set_auth_cookies(response, token, csrf_token)
    response.delete_cookie(OIDC_FLOW_COOKIE, path="/")
    return response


@router.get("/me")
def me(context: AuthContext = Depends(require_auth_context)) -> dict:
    return {"username": context.user.username, "role": context.user.role}


@router.post("/logout")
def logout(request: Request, response: Response,
           context: AuthContext = Depends(require_csrf),
           db: Session = Depends(get_db)) -> dict:
    audit(db, request, "auth.logout", True, user=context.user)
    db.delete(context.session)
    db.commit()
    clear_auth_cookies(response)
    return {"status": "ok"}
