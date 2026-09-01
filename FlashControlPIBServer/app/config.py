import os


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
SESSION_HOURS = max(1, int(os.environ.get("FLASHCONTROL_SESSION_HOURS", "8")))

if ENVIRONMENT == "production" and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError("SQLite is not allowed in production")
if ENVIRONMENT == "production" and AUTH_PROVIDER != "oidc":
    raise RuntimeError("production authentication provider must be oidc")
if ENVIRONMENT == "production" and (not OIDC_ISSUER or not OIDC_CLIENT_ID):
    raise RuntimeError("production OIDC issuer and client ID are required")
if AUTH_PROVIDER not in ("local", "oidc"):
    raise RuntimeError("unsupported authentication provider: %s" % AUTH_PROVIDER)
