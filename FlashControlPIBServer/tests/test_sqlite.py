import os
import shutil
import tempfile
import unittest
import uuid


TEST_DIRECTORY = tempfile.mkdtemp(prefix="flashcontrol-server-")
TEST_DATABASE = os.path.join(TEST_DIRECTORY, "test.db")
os.environ["FLASHCONTROL_ENVIRONMENT"] = "test"
os.environ["FLASHCONTROL_DATABASE_URL"] = "sqlite:///" + TEST_DATABASE.replace("\\", "/")
os.environ["FLASHCONTROL_DEV_MACHINE_TOKEN"] = "test-machine-token"

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal, engine
from app.auth import create_local_user
from app.main import app
from app.models import Agent, Computer, IdentityDecision, MediaState, Observation, PhysicalDevice


def observation_payload(event_id, hostname="test-host", hardware="a", media="c", state="d"):
    return {
        "schema_version": 1,
        "probe_version": "test",
        "event": {
            "id": str(event_id),
            "type": "snapshot",
            "observed_at_utc": "2026-09-01T12:00:00Z",
        },
        "host": {"hostname": hostname},
        "session": {"sid": "S-1-5-21-test"},
        "device": {"vendor": "FlashCo", "product": "Probe", "vid": "1234", "pid": "5678"},
        "hashes": {
            "hardware_stable": hardware * 64,
            "pnp": "b" * 64,
            "media_identity": media * 64,
            "media_state": state * 64,
            "observation": "e" * 64,
        },
    }


def payload_event_id(payload):
    return payload.get("event_id") or payload["event"]["id"]


class SqliteApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        cls.agent_id = uuid.uuid4()
        cls.client.headers.update({
            "X-FlashControl-Machine-Token": "test-machine-token",
            "X-FlashControl-Machine-ID": str(cls.agent_id),
            "X-FlashControl-Machine-Kind": "agent",
        })
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

    def test_agent_heartbeat_is_upserted_and_visible(self):
        agent_id = self.agent_id
        payload = {
            "agent_id": str(agent_id),
            "agent_version": "0.4.0",
            "hostname": "heartbeat-host",
            "domain": "CORP",
            "current_ips": ["10.20.30.40"],
            "queue_size": 3,
            "selected_route": "direct",
            "proxy_id": None,
        }
        first = self.client.post("/api/v1/agents/heartbeat", json=payload)
        payload["queue_size"] = 0
        second = self.client.post("/api/v1/agents/heartbeat", json=payload)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)

        with SessionLocal() as session:
            self.assertEqual(session.get(Agent, agent_id).queue_size, 0)

        listing = self.client.get(
            "/api/v1/agents", params={"status": "online", "hostname": "heartbeat-host"}
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["total"], 1)
        self.assertEqual(listing.json()["items"][0]["status"], "online")
        self.assertEqual(
            self.client.post(
                "/api/v1/agents/heartbeat", json=dict(payload, current_ips=["bad-ip"])
            ).status_code,
            422,
        )

    def test_agent_can_enroll_from_allowed_network_and_use_issued_token(self):
        guest = TestClient(app)
        agent_id = uuid.uuid4()
        enrolled = guest.post(
            "/api/v1/agents/enroll",
            json={
                "agent_id": str(agent_id),
                "agent_version": "0.4.0",
                "hostname": "enroll-pc",
                "domain": "CORP",
                "current_ips": ["10.20.30.40"],
            },
        )
        self.assertEqual(enrolled.status_code, 200)
        token = enrolled.json()["machine_token"]
        self.assertTrue(token)
        headers = {
            "X-FlashControl-Machine-Token": token,
            "X-FlashControl-Machine-ID": str(agent_id),
            "X-FlashControl-Machine-Kind": "agent",
        }
        event_id = uuid.uuid4()
        ingested = guest.post(
            "/api/v1/observations",
            json=observation_payload(event_id, hostname="enroll-pc"),
            headers=headers,
        )
        self.assertEqual(ingested.status_code, 200)
        self.assertEqual(ingested.json()["accepted"], 1)
        stolen = guest.post(
            "/api/v1/agents/enroll",
            json={
                "agent_id": str(agent_id),
                "agent_version": "0.4.0",
                "hostname": "other-pc",
                "domain": "CORP",
                "current_ips": ["10.20.30.41"],
            },
        )
        self.assertEqual(stolen.status_code, 403)
        guest.close()

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
        self.assertIn("confidenceColumnHint", script.text)
        self.assertIn("identityConfidenceHints", script.text)
        self.assertIn(".hint { cursor: help; }", styles.text)
        self.assertIn("tbody tr.clickable .hint { cursor: help; }", styles.text)

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

    def test_legacy_flat_observation_still_ingests(self):
        event_id = uuid.uuid4()
        payload = {
            "schema_version": 1,
            "probe_version": "test",
            "event_id": str(event_id),
            "event_type": "snapshot",
            "observed_at_utc": "2026-09-01T12:00:00Z",
            "host": {"hostname": "legacy-host"},
            "session": {"sid": "S-1-5-21-legacy"},
            "device": {"hardware_stable_sha256": "9" * 64, "serial": "LEGACY"},
            "capabilities": {"storage_descriptor": True},
            "capability_status": {"storage_descriptor": "available"},
            "collector_errors": [],
        }
        response = self.client.post("/api/v1/observations", json=payload)
        self.assertEqual(response.status_code, 200)
        with SessionLocal() as session:
            observation = session.scalar(
                select(Observation).where(Observation.event_id == event_id)
            )
            self.assertEqual(observation.hardware_stable_sha256, "9" * 64)
            self.assertEqual(observation.hostname, "legacy-host")

    def test_shared_batch_envelope_is_applied_to_each_observation(self):
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()
        payload = {
            "schema_version": 1,
            "probe_version": "test",
            "host": {"hostname": "batch-host"},
            "session": {"sid": "S-1-5-21-batch"},
            "observations": [
                {
                    "event": {
                        "id": str(first_id),
                        "type": "snapshot",
                        "observed_at_utc": "2026-09-01T12:00:00Z",
                    },
                    "device": {"serial": "ONE"},
                    "hashes": {"hardware_stable": "a" * 64, "media_identity": "c" * 64},
                },
                {
                    "event": {
                        "id": str(second_id),
                        "type": "snapshot",
                        "observed_at_utc": "2026-09-01T12:00:00Z",
                    },
                    "device": {"serial": "TWO"},
                    "hashes": {"hardware_stable": "b" * 64, "media_identity": "d" * 64},
                },
            ],
        }
        response = self.client.post("/api/v1/observations", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accepted"], 2)
        with SessionLocal() as session:
            first = session.scalar(select(Observation).where(Observation.event_id == first_id))
            second = session.scalar(select(Observation).where(Observation.event_id == second_id))
            self.assertEqual(first.hostname, "batch-host")
            self.assertEqual(second.hostname, "batch-host")
            self.assertEqual(first.device["serial"], "ONE")
            self.assertEqual(second.device["serial"], "TWO")

    def test_ingest_registers_computer_device_media_and_decision(self):
        payload = observation_payload(uuid.uuid4(), hardware="1", media="2", state="3")
        response = self.client.post("/api/v1/observations", json=payload)
        self.assertEqual(response.status_code, 200)

        with SessionLocal() as session:
            observation = session.scalar(
                select(Observation).where(Observation.event_id == uuid.UUID(payload_event_id(payload)))
            )
            decision = session.scalar(
                select(IdentityDecision).where(IdentityDecision.observation_id == observation.id)
            )
            self.assertIsNotNone(session.get(Computer, observation.computer_id))
            self.assertEqual(observation.agent_id, self.agent_id)
            self.assertIsNone(observation.proxy_id)
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
        self.assertIn(payload_event_id(second_payload), matching_ids)
        detail = self.client.get("/api/v1/observations/" + payload_event_id(second_payload))
        self.assertEqual(detail.status_code, 200)
        raw = detail.json()["raw_observation"]
        self.assertEqual(payload_event_id(raw), payload_event_id(second_payload))

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

    def test_cleanup_endpoints_delete_events_and_devices(self):
        single_event_id = uuid.uuid4()
        single_response = self.client.post(
            "/api/v1/observations",
            json=observation_payload(
                single_event_id,
                hostname="cleanup-event-host",
                hardware="c",
                media="d",
                state="e",
            ),
        )
        self.assertEqual(single_response.status_code, 200)
        with SessionLocal() as session:
            single_observation = session.scalar(
                select(Observation).where(Observation.event_id == single_event_id)
            )
            single_device_id = single_observation.physical_device_id

        csrf = self.client.cookies.get("flashcontrol_csrf")
        deleted_event = self.client.delete(
            "/api/v1/observations/" + str(single_event_id),
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(deleted_event.status_code, 200)
        self.assertEqual(deleted_event.json()["deleted_observations"], 1)
        with SessionLocal() as session:
            self.assertIsNone(session.scalar(select(Observation).where(Observation.event_id == single_event_id)))
            self.assertIsNone(session.get(PhysicalDevice, single_device_id))

        first_event_id = uuid.uuid4()
        second_event_id = uuid.uuid4()
        first_multi = self.client.post(
            "/api/v1/observations",
            json=observation_payload(
                first_event_id,
                hostname="cleanup-device-host",
                hardware="g",
                media="h",
                state="i",
            ),
        )
        second_multi = self.client.post(
            "/api/v1/observations",
            json=observation_payload(
                second_event_id,
                hostname="cleanup-device-host",
                hardware="g",
                media="h",
                state="i",
            ),
        )
        self.assertEqual(first_multi.status_code, 200)
        self.assertEqual(second_multi.status_code, 200)
        with SessionLocal() as session:
            device_id = session.scalar(
                select(PhysicalDevice.id)
                .join(Observation, Observation.physical_device_id == PhysicalDevice.id)
                .where(Observation.event_id == first_event_id)
            )

        deleted_device = self.client.delete(
            "/api/v1/devices/" + str(device_id),
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(deleted_device.status_code, 200)
        self.assertEqual(deleted_device.json()["deleted_devices"], 1)
        with SessionLocal() as session:
            self.assertIsNone(session.get(PhysicalDevice, device_id))
            remaining = session.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.event_id.in_((first_event_id, second_event_id)))
            )
        self.assertEqual(remaining, 0)

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

    def test_ldap_login_creates_directory_user_and_assigns_role(self):
        from unittest.mock import patch

        from app.ldap_auth import LdapLoginOutcome
        from app.models import AuthUser

        guest = TestClient(app)
        outcome = LdapLoginOutcome(True, "ivan", role="security", display_name="Ivan")
        try:
            with patch("app.auth.ldap_configured", return_value=True), \
                patch("app.auth.perform_ldap_login", return_value=outcome):
                login = guest.post(
                    "/api/v1/auth/login",
                    json={"username": r"MOSMETRO\Ivan", "password": "domain password"},
                )
            self.assertEqual(login.status_code, 200)
            self.assertEqual(login.json(), {"username": "ivan", "role": "security"})
            self.assertEqual(guest.get("/api/v1/computers").status_code, 200)
            with SessionLocal() as session:
                user = session.scalar(select(AuthUser).where(AuthUser.username == "ivan"))
                self.assertIsNotNone(user)
                self.assertIsNone(user.password_hash)
                self.assertEqual(user.role, "security")
        finally:
            guest.close()

    def test_ldap_login_without_group_is_forbidden(self):
        from unittest.mock import patch

        from app.ldap_auth import LdapLoginOutcome

        guest = TestClient(app)
        outcome = LdapLoginOutcome(False, "ivan", failure="not_in_group")
        try:
            with patch("app.auth.ldap_configured", return_value=True), \
                patch("app.auth.perform_ldap_login", return_value=outcome):
                response = guest.post(
                    "/api/v1/auth/login",
                    json={"username": "ivan", "password": "domain password"},
                )
            self.assertEqual(response.status_code, 403)
        finally:
            guest.close()

    def test_machine_credentials_and_identity_are_required(self):
        payload = observation_payload(uuid.uuid4())
        guest = TestClient(app)
        self.assertEqual(guest.post("/api/v1/observations", json=payload).status_code, 401)
        wrong_headers = {
            "X-FlashControl-Machine-Token": "test-machine-token",
            "X-FlashControl-Machine-ID": str(uuid.uuid4()),
            "X-FlashControl-Machine-Kind": "agent",
        }
        heartbeat = {
            "agent_id": str(self.agent_id), "agent_version": "0.4.0",
            "hostname": "host", "domain": None, "current_ips": [],
            "queue_size": 0, "selected_route": "direct", "proxy_id": None,
        }
        self.assertEqual(
            guest.post("/api/v1/agents/heartbeat", json=heartbeat, headers=wrong_headers).status_code,
            403,
        )
        guest.close()

    def test_authenticated_proxy_can_forward_for_agent(self):
        event_id = uuid.uuid4()
        proxy_id = uuid.uuid4()
        source_agent_id = uuid.uuid4()
        headers = {
            "X-FlashControl-Machine-Token": "test-machine-token",
            "X-FlashControl-Machine-ID": str(proxy_id),
            "X-FlashControl-Machine-Kind": "proxy",
            "X-FlashControl-Forwarded-Agent-ID": str(source_agent_id),
        }
        response = self.client.post(
            "/api/v1/observations", json=observation_payload(event_id), headers=headers
        )
        self.assertEqual(response.status_code, 200)
        with SessionLocal() as session:
            observation = session.scalar(
                select(Observation).where(Observation.event_id == event_id)
            )
            self.assertEqual(observation.agent_id, source_agent_id)
            self.assertEqual(observation.proxy_id, proxy_id)

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

    def test_login_audit_uses_forwarded_client_ip_from_trusted_proxy(self):
        from unittest.mock import patch

        from app import machine_auth
        from app.models import AuditLog

        guest = TestClient(app, client=("172.30.0.4", 50000))
        with patch.object(machine_auth, "TRUSTED_PROXIES", ("172.30.0.0/24",)):
            response = guest.post(
                "/api/v1/auth/login",
                json={"username": "test-admin", "password": "wrong password value"},
                headers={
                    "X-Real-IP": "203.0.113.77",
                    "X-Forwarded-For": "198.51.100.20, 203.0.113.77",
                },
            )
        self.assertEqual(response.status_code, 401)
        with SessionLocal() as session:
            entry = session.scalar(
                select(AuditLog)
                .where(AuditLog.action == "auth.login")
                .where(AuditLog.success.is_(False))
                .where(AuditLog.username == "test-admin")
                .where(AuditLog.source_ip == "203.0.113.77")
                .order_by(AuditLog.created_at_utc.desc())
            )
        self.assertIsNotNone(entry)
        guest.close()


if __name__ == "__main__":
    unittest.main()
