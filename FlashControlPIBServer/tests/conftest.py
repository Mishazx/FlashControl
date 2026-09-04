"""Bootstrap environment variables before any test module is imported.

conftest.py is loaded by pytest before test module collection, so env vars
set here are visible when app.config / app.db are first imported by any
test module (alphabetically, test_ratelimit imports app.ratelimit → app.config
before test_sqlite gets to set its own vars). Setting them here ensures a
consistent DATABASE_URL across the entire suite.
"""

import os
import tempfile

TEST_DIRECTORY = tempfile.mkdtemp(prefix="flashcontrol-server-")
TEST_DATABASE = os.path.join(TEST_DIRECTORY, "test.db")

os.environ.setdefault("FLASHCONTROL_ENVIRONMENT", "test")
os.environ.setdefault("FLASHCONTROL_DEV_MACHINE_TOKEN", "test-machine-token")
os.environ["FLASHCONTROL_DATABASE_URL"] = "sqlite:///" + TEST_DATABASE.replace("\\", "/")
