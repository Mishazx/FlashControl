import os
import shutil
import tempfile
import unittest

from sqlalchemy import create_engine, inspect, text

class SqliteMigrationTests(unittest.TestCase):
    def test_existing_observations_table_gets_identity_columns(self):
        from app.db import initialize_sqlite_database

        folder = tempfile.mkdtemp(prefix="flashcontrol-migration-")
        path = os.path.join(folder, "legacy.db")
        test_engine = create_engine("sqlite:///" + path.replace("\\", "/"))
        try:
            with test_engine.begin() as connection:
                connection.execute(text(
                    "CREATE TABLE observations (id INTEGER PRIMARY KEY)"
                ))
            initialize_sqlite_database(test_engine)
            columns = {
                item["name"] for item in inspect(test_engine).get_columns("observations")
            }
            self.assertTrue({
                "computer_id", "physical_device_id", "media_state_id"
            }.issubset(columns))
        finally:
            test_engine.dispose()
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
