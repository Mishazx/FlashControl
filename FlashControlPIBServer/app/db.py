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
    """Apply pending schema migrations with Alembic.

    Uses the same database URL that the application engine is bound to so
    migrations and runtime queries always target the same database.
    """
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(ALEMBIC_DIR.parent / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")


def initialize_database():
    run_migrations()


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
