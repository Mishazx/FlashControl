from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from .config import DATABASE_URL


IS_SQLITE = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


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


def initialize_database():
    if IS_SQLITE:
        initialize_sqlite_database(engine)


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
