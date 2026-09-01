import os


ENVIRONMENT = os.environ.get("FLASHCONTROL_ENVIRONMENT", "development").lower()
DATABASE_URL = os.environ.get(
    "FLASHCONTROL_DATABASE_URL",
    "sqlite:///./flashcontrol-dev.db",
)
LOG_LEVEL = os.environ.get("FLASHCONTROL_LOG_LEVEL", "INFO").upper()

if ENVIRONMENT == "production" and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError("SQLite is not allowed in production")
