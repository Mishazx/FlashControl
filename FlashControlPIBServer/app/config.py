import os


DATABASE_URL = os.environ.get(
    "FLASHCONTROL_DATABASE_URL",
    "postgresql+psycopg://flashcontrol:flashcontrol@localhost:5432/flashcontrol",
)
LOG_LEVEL = os.environ.get("FLASHCONTROL_LOG_LEVEL", "INFO").upper()

