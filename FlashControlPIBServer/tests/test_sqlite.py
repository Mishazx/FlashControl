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
from app.auth import create_local_user
from app.main import app
from app.models import Computer, IdentityDecision, MediaState, Observation, PhysicalDevice


def observation_payload(event_id, hostname="test-host", hardware="a", media="c", state="d"):
    return {
        "schema_version": 1,
        "probe_version": "test",
        "event_id": str(event_id),
        "event_type": "snapshot",
        "observed_at_utc": "2026-09-01T12:00:00Z",
        "host": {"hostname": hostname},
        "session": {"sid": "S-1-5-21-test"},
        "device": {
            "hardware_stable_sha256": hardware * 64,
            "pnp_observation_sha256": "b" * 64,
            "media_identity_sha256": media * 64,
            "media_state_sha256": state * 64,
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
        with SessionLocal() as session:
            create_local_user(session, "test-admin", "correct horse battery staple", "admin")
            create_local_user(session, "test-auditor", "auditor password for tests", "auditor")
        login = cls.client.post(
            "/api/v1/auth/login",
            json={"username": "test-admin", "password": "correct horse battery staple"},
        )
        if login.status_code != 200:
            raise RuntimeError("test login failed: %s" % login.text)

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        engine.dispose()
        shutil.rmtree(TEST_DIRECTORY, ignore_errors=True)

    def test_health_endpoints(self):
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.assertEqual(self.client.get("/health/ready").status_code, 200)
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_web_ui_and_assets_are_served(self):
        page = self.client.get("/")
        styles = self.client.get("/static/app.css")
        script = self.client.get("/static/app.js")
        self.assertEqual(page.status_code, 200)
        self.assertIn("text/html", page.headers["content-type"])
        self.assertIn("FlashControl", page.text)
        self.assertEqual(page.headers["x-frame-options"], "DENY")
        self.assertIn("default-src 'self'", page.headers["content-security-policy"])
        self.assertEqual(styles.status_code, 200)
        self.assertIn("text/css", styles.headers["content-type"])
        self.assertEqual(script.status_code, 200)
        self.assertIn("javascript", script.headers["content-type"])
        self.assertIn('const API = "/api/v1"', script.text)

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
            count = session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.event_id == event_id)
            )
        self.assertEqual(count, 1)

    def test_ingest_registers_computer_device_media_and_decision(self):
        payload = observation_payload(uuid.uuid4(), hardware="1", media="2", state="3")
        response = self.client.post("/api/v1/observations", json=payload)
        self.assertEqual(response.status_code, 200)

        with SessionLocal() as session:
            observation = session.scalar(
                select(Observation).where(Observation.event_id == uuid.UUID(payload["event_id"]))
            )
            decision = session.scalar(
                select(IdentityDecision).where(IdentityDecision.observation_id == observation.id)
            )
            self.assertIsNotNone(session.get(Computer, observation.computer_id))
            self.assertIsNotNone(session.get(PhysicalDevice, observation.physical_device_id))
            self.assertIsNotNone(session.get(MediaState, observation.media_state_id))
            self.assertEqual(decision.result, "UNKNOWN")
            self.assertFalse(decision.auto_linked)
            self.assertEqual(decision.reasons, ["first_observation"])

    def test_repeat_observation_links_same_physical_device(self):
        first_payload = observation_payload(uuid.uuid4(), hardware="4", media="5", state="6")
        second_payload = observation_payload(uuid.uuid4(), hardware="4", media="5", state="6")
        self.client.post("/api/v1/observations", json=first_payload)
        self.client.post("/api/v1/observations", json=second_payload)

        with SessionLocal() as session:
            observations = list(session.scalars(
                select(Observation)
                .where(Observation.hardware_stable_sha256 == "4" * 64)
                .order_by(Observation.id)
            ))
            decision = session.scalar(
                select(IdentityDecision).where(IdentityDecision.observation_id == observations[1].id)
            )
            self.assertEqual(observations[0].physical_device_id, observations[1].physical_device_id)
            self.assertEqual(decision.result, "SAME")
            self.assertTrue(decision.auto_linked)

    def test_media_state_change_does_not_create_physical_device(self):
        first_payload = observation_payload(uuid.uuid4(), hardware="7", media="8", state="9")
        second_payload = observation_payload(uuid.uuid4(), hardware="7", media="8", state="0")
        self.client.post("/api/v1/observations", json=first_payload)
        self.client.post("/api/v1/observations", json=second_payload)

        with SessionLocal() as session:
            observations = list(session.scalars(
                select(Observation)
                .where(Observation.hardware_stable_sha256 == "7" * 64)
                .order_by(Observation.id)
            ))
            self.assertEqual(observations[0].physical_device_id, observations[1].physical_device_id)
            self.assertNotEqual(observations[0].media_state_id, observations[1].media_state_id)

    def test_simultaneous_matching_evidence_on_other_host_is_not_merged(self):
        first_payload = observation_payload(
            uuid.uuid4(), hostname="host-a", hardware="b", media="e", state="f"
        )
        second_payload = observation_payload(
            uuid.uuid4(), hostname="host-b", hardware="b", media="e", state="f"
        )
        self.client.post("/api/v1/observations", json=first_payload)
        self.client.post("/api/v1/observations", json=second_payload)

        with SessionLocal() as session:
            observations = list(session.scalars(
                select(Observation)
                .where(Observation.hardware_stable_sha256 == "b" * 64)
                .order_by(Observation.id)
            ))
            decision = session.scalar(
                select(IdentityDecision).where(IdentityDecision.observation_id == observations[1].id)
            )
            self.assertNotEqual(observations[0].physical_device_id, observations[1].physical_device_id)
            self.assertEqual(decision.result, "SERIAL_COLLISION")
            self.assertFalse(decision.auto_linked)

    def test_read_api_lists_filters_and_returns_details(self):
        first_payload = observation_payload(
            uuid.uuid4(), hostname="api-host-a", hardware="f", media="1", state="2"
        )
        second_payload = observation_payload(
            uuid.uuid4(), hostname="api-host-b", hardware="f", media="1", state="2"
        )
        self.assertEqual(
            self.client.post("/api/v1/observations", json=first_payload).status_code, 200
        )
        self.assertEqual(
            self.client.post("/api/v1/observations", json=second_payload).status_code, 200
        )

        computers = self.client.get("/api/v1/computers", params={"hostname": "api-host"})
        self.assertEqual(computers.status_code, 200)
        self.assertEqual(computers.json()["total"], 2)
        self.assertEqual(len(computers.json()["items"]), 2)
        computer_id = computers.json()["items"][0]["id"]
        computer = self.client.get("/api/v1/computers/" + computer_id)
        self.assertEqual(computer.status_code, 200)
        self.assertTrue(computer.json()["recent_observations"])

        devices = self.client.get(
            "/api/v1/devices", params={"hardware_hash": "f" * 64, "limit": 1}
        )
        self.assertEqual(devices.status_code, 200)
        self.assertEqual(devices.json()["total"], 2)
        self.assertEqual(len(devices.json()["items"]), 1)
        device_id = devices.json()["items"][0]["id"]
        device = self.client.get("/api/v1/devices/" + device_id)
        self.assertEqual(device.status_code, 200)
        self.assertTrue(device.json()["media_states"])
        self.assertTrue(device.json()["used_on_computers"])
        self.assertEqual(device.json()["seen_user_sids"], ["S-1-5-21-test"])

        observations = self.client.get(
            "/api/v1/observations", params={"decision": "SERIAL_COLLISION"}
        )
        self.assertEqual(observations.status_code, 200)
        matching_ids = {str(item["event_id"]) for item in observations.json()["items"]}
        self.assertIn(second_payload["event_id"], matching_ids)
        detail = self.client.get("/api/v1/observations/" + second_payload["event_id"])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["raw_observation"]["event_id"], second_payload["event_id"])

        decisions = self.client.get(
            "/api/v1/identity-decisions", params={"result": "SERIAL_COLLISION"}
        )
        alerts = self.client.get("/api/v1/identity-alerts")
        self.assertEqual(decisions.status_code, 200)
        self.assertGreaterEqual(decisions.json()["total"], 1)
        self.assertEqual(alerts.status_code, 200)
        self.assertGreaterEqual(alerts.json()["total"], 1)

        dashboard = self.client.get("/api/v1/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertGreaterEqual(dashboard.json()["computers"], 2)
        self.assertGreaterEqual(dashboard.json()["identity_alerts"], 1)
        self.assertGreaterEqual(
            dashboard.json()["identity_results"]["SERIAL_COLLISION"], 1
        )

        self.assertEqual(
            self.client.get("/api/v1/observations", params={"limit": 201}).status_code,
            422,
        )
        self.assertEqual(
            self.client.get("/api/v1/devices/" + str(uuid.uuid4())).status_code,
            404,
        )

    def test_authentication_session_csrf_and_roles(self):
        guest = TestClient(app)
        self.assertEqual(
            guest.get("/", follow_redirects=False).status_code, 303
        )
        self.assertEqual(guest.get("/login").status_code, 200)
        self.assertEqual(guest.get("/api/v1/computers").status_code, 401)
        failed = guest.post(
            "/api/v1/auth/login",
            json={"username": "test-admin", "password": "wrong-password"},
        )
        self.assertEqual(failed.status_code, 401)

        login = guest.post(
            "/api/v1/auth/login",
            json={"username": "test-auditor", "password": "auditor password for tests"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("HttpOnly", login.headers.get("set-cookie", ""))
        self.assertEqual(guest.get("/api/v1/auth/me").json()["role"], "auditor")
        self.assertEqual(guest.get("/api/v1/computers").status_code, 200)
        self.assertEqual(guest.get("/api/v1/audit-log").status_code, 403)
        self.assertEqual(guest.post("/api/v1/auth/logout").status_code, 403)
        csrf = guest.cookies.get("flashcontrol_csrf")
        logout = guest.post(
            "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(guest.get("/api/v1/computers").status_code, 401)
        guest.close()

        self.assertEqual(self.client.get("/api/v1/audit-log").status_code, 200)

    def test_login_attempts_are_rate_limited_and_audited(self):
        guest = TestClient(app)
        for _index in range(5):
            response = guest.post(
                "/api/v1/auth/login",
                json={"username": "missing-user", "password": "incorrect password value"},
            )
            self.assertEqual(response.status_code, 401)
        blocked = guest.post(
            "/api/v1/auth/login",
            json={"username": "missing-user", "password": "incorrect password value"},
        )
        self.assertEqual(blocked.status_code, 429)
        audit_response = self.client.get(
            "/api/v1/audit-log",
            params={"action": "auth.login", "success": False},
        )
        self.assertEqual(audit_response.status_code, 200)
        self.assertGreaterEqual(audit_response.json()["total"], 5)
        guest.close()


if __name__ == "__main__":
    unittest.main()
