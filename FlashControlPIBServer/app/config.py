import os
import json


def _csv_set(name: str) -> frozenset[str]:
    return frozenset(
        item.strip().casefold()
        for item in os.environ.get(name, "").split(",")
        if item.strip()
    )


ENVIRONMENT = os.environ.get("FLASHCONTROL_ENVIRONMENT", "development").lower()
DATABASE_URL = os.environ.get(
    "FLASHCONTROL_DATABASE_URL",
    "sqlite:///./flashcontrol-dev.db",
)
LOG_LEVEL = os.environ.get("FLASHCONTROL_LOG_LEVEL", "INFO").upper()
AUTH_PROVIDER = os.environ.get(
    "FLASHCONTROL_AUTH_PROVIDER",
    "oidc" if ENVIRONMENT == "production" else "local",
).lower()
OIDC_ISSUER = os.environ.get("FLASHCONTROL_OIDC_ISSUER", "").strip()
OIDC_CLIENT_ID = os.environ.get("FLASHCONTROL_OIDC_CLIENT_ID", "").strip()
OIDC_CLIENT_SECRET = os.environ.get("FLASHCONTROL_OIDC_CLIENT_SECRET", "").strip()
OIDC_REDIRECT_URI = os.environ.get("FLASHCONTROL_OIDC_REDIRECT_URI", "").strip()
OIDC_SCOPES = os.environ.get(
    "FLASHCONTROL_OIDC_SCOPES", "openid profile email groups"
).split()
OIDC_GROUP_CLAIM = os.environ.get("FLASHCONTROL_OIDC_GROUP_CLAIM", "groups").strip()
OIDC_ADMIN_GROUPS = _csv_set("FLASHCONTROL_OIDC_ADMIN_GROUPS")
OIDC_SECURITY_GROUPS = _csv_set("FLASHCONTROL_OIDC_SECURITY_GROUPS")
OIDC_AUDITOR_GROUPS = _csv_set("FLASHCONTROL_OIDC_AUDITOR_GROUPS")
OIDC_DEFAULT_ROLE = os.environ.get("FLASHCONTROL_OIDC_DEFAULT_ROLE", "").strip().lower()
SESSION_HOURS = max(1, int(os.environ.get("FLASHCONTROL_SESSION_HOURS", "8")))
MACHINE_AUTH_MODE = os.environ.get(
    "FLASHCONTROL_MACHINE_AUTH_MODE",
    "mtls" if ENVIRONMENT == "production" else "token",
).lower()
DEV_MACHINE_TOKEN = os.environ.get("FLASHCONTROL_DEV_MACHINE_TOKEN", "").strip()
TRUSTED_MTLS_PROXIES = tuple(
    item.strip() for item in os.environ.get("FLASHCONTROL_TRUSTED_MTLS_PROXIES", "").split(",")
    if item.strip()
)
try:
    MTLS_IDENTITIES = json.loads(os.environ.get("FLASHCONTROL_MTLS_IDENTITIES", "{}"))
except ValueError as exc:
    raise RuntimeError("FLASHCONTROL_MTLS_IDENTITIES must be valid JSON") from exc

if ENVIRONMENT == "production" and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError("SQLite is not allowed in production")
if ENVIRONMENT == "production" and AUTH_PROVIDER != "oidc":
    raise RuntimeError("production authentication provider must be oidc")
if AUTH_PROVIDER == "oidc" and (not OIDC_ISSUER or not OIDC_CLIENT_ID):
    raise RuntimeError("OIDC issuer and client ID are required")
if ENVIRONMENT == "production" and not OIDC_REDIRECT_URI:
    raise RuntimeError("production OIDC redirect URI is required")
if ENVIRONMENT == "production" and not OIDC_ISSUER.startswith("https://"):
    raise RuntimeError("production OIDC issuer must use HTTPS")
if ENVIRONMENT == "production" and not OIDC_REDIRECT_URI.startswith("https://"):
    raise RuntimeError("production OIDC redirect URI must use HTTPS")
if OIDC_DEFAULT_ROLE not in ("", "admin", "security", "auditor"):
    raise RuntimeError("OIDC default role must be admin, security, auditor, or empty")
if AUTH_PROVIDER == "oidc" and not (
    OIDC_ADMIN_GROUPS or OIDC_SECURITY_GROUPS or OIDC_AUDITOR_GROUPS or OIDC_DEFAULT_ROLE
):
    raise RuntimeError("OIDC requires at least one group mapping or an explicit default role")
if AUTH_PROVIDER not in ("local", "oidc"):
    raise RuntimeError("unsupported authentication provider: %s" % AUTH_PROVIDER)
if MACHINE_AUTH_MODE not in ("token", "mtls"):
    raise RuntimeError("machine authentication mode must be token or mtls")
if MACHINE_AUTH_MODE == "token" and not DEV_MACHINE_TOKEN and ENVIRONMENT != "test":
    raise RuntimeError("development machine token is required")
if ENVIRONMENT == "production" and MACHINE_AUTH_MODE != "mtls":
    raise RuntimeError("production machine authentication must use mtls")
if MACHINE_AUTH_MODE == "mtls" and (not TRUSTED_MTLS_PROXIES or not MTLS_IDENTITIES):
    raise RuntimeError("mTLS requires trusted proxy CIDRs and certificate identities")
