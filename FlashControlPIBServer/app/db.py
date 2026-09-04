from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import DATABASE_URL


IS_SQLITE = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"


def run_migrations() -> None:
    """Apply pending schema migrations with Alembic."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(ALEMBIC_DIR.parent / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    if DATABASE_URL:
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")


def initialize_database():
    run_migrations()



def initialize_sqlite_database(target_engine):
    from .models import Base

    Base.metadata.create_all(bind=target_engine)
    columns = {
        item["name"] for item in inspect(target_engine).get_columns("observations")
    }
    additions = {
        "computer_id": "CHAR(32) REFERENCES computers (id)",
        "physical_device_id": "CHAR(32) REFERENCES physical_devices (id)",
        "media_state_id": "CHAR(32) REFERENCES media_states (id)",
        "agent_id": "CHAR(32)",
        "proxy_id": "CHAR(32)",
    }
    with target_engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(
                    "ALTER TABLE observations ADD COLUMN %s %s" % (name, definition)
                ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_observations_computer_id "
            "ON observations (computer_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_observations_physical_device_id "
            "ON observations (physical_device_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_observations_agent_id ON observations (agent_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_observations_proxy_id ON observations (proxy_id)"
        ))
        agent_columns = set()
        if inspect(target_engine).has_table("agents"):
            agent_columns = {
                item["name"] for item in inspect(target_engine).get_columns("agents")
            }
        agent_additions = {
            "token_hash": "VARCHAR(64)",
            "enroll_source_ip": "VARCHAR(128)",
            "enrolled_at_utc": "DATETIME",
        }
        for name, definition in agent_additions.items():
            if name not in agent_columns:
                connection.execute(text(
                    "ALTER TABLE agents ADD COLUMN %s %s" % (name, definition)
                ))


def initialize_database():
    if IS_SQLITE:
        initialize_sqlite_database(engine)


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
