import os
import shutil
import tempfile
import unittest
import uuid


TEST_DIRECTORY = tempfile.mkdtemp(prefix="flashcontrol-server-")
TEST_DATABASE = os.path.join(TEST_DIRECTORY, "test.db")
os.environ["FLASHCONTROL_ENVIRONMENT"] = "test"
os.environ["FLASHCONTROL_DATABASE_URL"] = "sqlite:///" + TEST_DATABASE.replace("\\", "/")

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal, engine
from app.main import app
from app.models import Observation


def observation_payload(event_id):
    return {
        "schema_version": 1,
        "probe_version": "test",
        "event_id": str(event_id),
        "event_type": "snapshot",
        "observed_at_utc": "2026-09-01T12:00:00Z",
        "host": {"hostname": "test-host"},
        "session": {"sid": "S-1-5-21-test"},
        "device": {
            "hardware_stable_sha256": "a" * 64,
            "pnp_observation_sha256": "b" * 64,
            "media_identity_sha256": "c" * 64,
            "media_state_sha256": "d" * 64,
            "observation_sha256": "e" * 64,
        },
        "capabilities": {"storage_descriptor": True},
        "capability_status": {"storage_descriptor": "available"},
        "collector_errors": [],
    }


class SqliteApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        engine.dispose()
        shutil.rmtree(TEST_DIRECTORY, ignore_errors=True)

    def test_health_endpoints(self):
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.assertEqual(self.client.get("/health/ready").status_code, 200)

    def test_duplicate_event_is_idempotent(self):
        event_id = uuid.uuid4()
        payload = observation_payload(event_id)

        first = self.client.post("/api/v1/observations", json=payload)
        second = self.client.post("/api/v1/observations", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["accepted"], 1)
        self.assertEqual(first.json()["duplicates"], 0)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["accepted"], 0)
        self.assertEqual(second.json()["duplicates"], 1)

        with SessionLocal() as session:
            count = session.scalar(select(func.count()).select_from(Observation))
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
