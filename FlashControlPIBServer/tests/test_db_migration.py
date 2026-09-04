import os
import shutil
import tempfile
import unittest

os.environ.setdefault("FLASHCONTROL_ENVIRONMENT", "test")
os.environ.setdefault("FLASHCONTROL_DEV_MACHINE_TOKEN", "test-machine-token")

from sqlalchemy import create_engine, inspect  # noqa: E402


class SqliteMigrationTests(unittest.TestCase):
    def test_alembic_upgrade_creates_full_schema(self):
        from alembic import command
        from alembic.config import Config
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[1]
        alembic_dir = project_root / "alembic"

        folder = tempfile.mkdtemp(prefix="flashcontrol-migration-")
        path = os.path.join(folder, "migrated.db")
        url = "sqlite:///" + path.replace("\\", "/")
        try:
            cfg = Config(str(project_root / "alembic.ini"))
            cfg.set_main_option("script_location", str(alembic_dir))
            cfg.set_main_option("sqlalchemy.url", url)
            command.upgrade(cfg, "head")

            engine = create_engine(url)
            try:
                inspector = inspect(engine)
                tables = set(inspector.get_table_names())
                self.assertTrue({
                    "observations", "computers", "physical_devices",
                    "media_states", "identity_decisions", "auth_users",
                    "auth_sessions", "audit_log", "agents",
                }.issubset(tables))

                obs_columns = {
                    item["name"] for item in inspector.get_columns("observations")
                }
                self.assertTrue({
                    "computer_id", "physical_device_id", "media_state_id",
                    "agent_id", "proxy_id",
                }.issubset(obs_columns))

                obs_indexes = {item["name"] for item in inspector.get_indexes("observations")}
                self.assertIn("ix_observations_physical_device_seen", obs_indexes)
            finally:
                engine.dispose()
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
