import json
import os


ENVIRONMENT = os.environ.get("FLASHCONTROL_ENVIRONMENT", "development").lower()
DATABASE_URL = os.environ.get(
    "FLASHCONTROL_DATABASE_URL",
    "sqlite:///./flashcontrol-dev.db",
)
LOG_LEVEL = os.environ.get("FLASHCONTROL_LOG_LEVEL", "INFO").upper()
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
TRUSTED_PROXIES = tuple(
    item.strip() for item in os.environ.get("FLASHCONTROL_TRUSTED_PROXIES", "").split(",")
    if item.strip()
) or TRUSTED_MTLS_PROXIES
try:
    MTLS_IDENTITIES = json.loads(os.environ.get("FLASHCONTROL_MTLS_IDENTITIES", "{}"))
except ValueError as exc:
    raise RuntimeError("FLASHCONTROL_MTLS_IDENTITIES must be valid JSON") from exc
ENROLL_NETWORKS = tuple(
    item.strip() for item in os.environ.get("FLASHCONTROL_ENROLL_NETWORKS", "").split(",")
    if item.strip()
)


def _csv_set(name: str) -> frozenset[str]:
    return frozenset(
        item.strip().casefold()
        for item in os.environ.get(name, "").split(",")
        if item.strip()
    )


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


LDAP_SERVER_URI = os.environ.get("FLASHCONTROL_LDAP_SERVER_URI", "").strip()
LDAP_START_TLS = _env_bool("FLASHCONTROL_LDAP_START_TLS", False)
LDAP_TLS_CERT_POLICY = os.environ.get("FLASHCONTROL_LDAP_TLS_CERT_POLICY", "demand").strip().lower()
LDAP_BASE_DN = os.environ.get("FLASHCONTROL_LDAP_BASE_DN", "").strip()
LDAP_DOMAIN_NAME = os.environ.get("FLASHCONTROL_LDAP_DOMAIN_NAME", "").strip()
LDAP_GROUP_PARENT_DN = os.environ.get("FLASHCONTROL_LDAP_GROUP_PARENT_DN", "").strip()
LDAP_ACCESS_GROUP = os.environ.get("FLASHCONTROL_LDAP_ACCESS_GROUP", "").strip()
LDAP_ADMIN_GROUPS = _csv_set("FLASHCONTROL_LDAP_ADMIN_GROUPS")
LDAP_SECURITY_GROUPS = _csv_set("FLASHCONTROL_LDAP_SECURITY_GROUPS")
LDAP_AUDITOR_GROUPS = _csv_set("FLASHCONTROL_LDAP_AUDITOR_GROUPS")
LDAP_DEFAULT_ROLE = os.environ.get("FLASHCONTROL_LDAP_DEFAULT_ROLE", "").strip().lower()
LDAP_NETWORK_TIMEOUT = max(1, int(os.environ.get("FLASHCONTROL_LDAP_NETWORK_TIMEOUT", "5")))
LDAP_TIMEOUT = max(1, int(os.environ.get("FLASHCONTROL_LDAP_TIMEOUT", "5")))

if ENVIRONMENT == "production" and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError("SQLite is not allowed in production")
if MACHINE_AUTH_MODE not in ("token", "mtls"):
    raise RuntimeError("machine authentication mode must be token or mtls")
if MACHINE_AUTH_MODE == "token" and not DEV_MACHINE_TOKEN and ENVIRONMENT != "test":
    raise RuntimeError("development machine token is required")
if ENVIRONMENT == "production" and MACHINE_AUTH_MODE != "mtls":
    raise RuntimeError("production machine authentication must use mtls")
if MACHINE_AUTH_MODE == "mtls" and (not TRUSTED_MTLS_PROXIES or not MTLS_IDENTITIES):
    raise RuntimeError("mTLS requires trusted proxy CIDRs and certificate identities")
if LDAP_TLS_CERT_POLICY not in ("demand", "allow", "never", "none", "0", "1"):
    raise RuntimeError("LDAP TLS cert policy must be demand, allow, or never")
if LDAP_DEFAULT_ROLE not in ("", "admin", "security", "auditor"):
    raise RuntimeError("LDAP default role must be admin, security, auditor, or empty")
if LDAP_SERVER_URI:
    if not LDAP_BASE_DN or not LDAP_DOMAIN_NAME:
        raise RuntimeError("LDAP base DN and domain name are required")
    if not (
        LDAP_ADMIN_GROUPS or LDAP_SECURITY_GROUPS or LDAP_AUDITOR_GROUPS or LDAP_DEFAULT_ROLE
    ):
        raise RuntimeError("LDAP requires at least one group mapping or an explicit default role")
