import datetime
import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.identity import (
    Classification,
    _collision_context,
    _get_or_create_media_state,
    _latest_observations,
    _new_physical_device,
    classify_pair,
    computer_key,
    ensure_computer,
    presence_host,
    register_computer,
    resolve_identity,
    serial_identifiers,
)
from app.models import Base, Computer, IdentityDecision, MediaState, Observation, PhysicalDevice


class FakeObservation:
    def __init__(
        self,
        hardware,
        media,
        media_state,
        computer,
        device=None,
        observation_id=None,
        observed_at=None,
    ):
        self.id = observation_id or uuid.uuid4().int & ((1 << 63) - 1)
        self.hardware_stable_sha256 = hardware
        self.media_identity_sha256 = media
        self.media_state_sha256 = media_state
        self.computer_id = computer
        self.device = device or {}
        self.observed_at_utc = observed_at or datetime.datetime.now(datetime.timezone.utc)
        self.physical_device_id = None
        self.media_state_id = None


class IdentityUnitTests(unittest.TestCase):
    """Pure unit tests without database."""

    def test_computer_key_with_hostname_and_domain(self):
        host = {"hostname": "PC-001", "domain": "CORP"}
        key = computer_key(host)
        self.assertEqual(len(key), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in key))

    def test_computer_key_without_hostname(self):
        host = {"domain": "CORP"}
        key = computer_key(host)
        self.assertEqual(len(key), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in key))

    def test_computer_key_case_insensitive(self):
        key1 = computer_key({"hostname": "PC-001", "domain": "CORP"})
        key2 = computer_key({"hostname": "pc-001", "domain": "corp"})
        self.assertEqual(key1, key2)

    def test_computer_key_whitespace_trimmed(self):
        key1 = computer_key({"hostname": "  PC-001  ", "domain": "  CORP  "})
        key2 = computer_key({"hostname": "PC-001", "domain": "CORP"})
        self.assertEqual(key1, key2)

    def test_presence_host_includes_domain_and_ips(self):
        host = presence_host("PC-001", "CORP", ["10.0.0.1", "10.0.0.1"])
        self.assertEqual(host["hostname"], "PC-001")
        self.assertEqual(host["domain"], "CORP")
        self.assertEqual(host["domain_name"], "CORP")
        self.assertEqual(host["ip_addresses"], ["10.0.0.1", "10.0.0.1"])

    def test_presence_host_omits_empty_domain(self):
        host = presence_host("PC-001", None)
        self.assertNotIn("domain", host)
        self.assertEqual(host["ip_addresses"], [])

    def test_serial_identifiers_storage_serial(self):
        device = {"storage": {"serial": "STOR-12345"}}
        serials = serial_identifiers(device)
        self.assertIn("storage:stor-12345", serials)

    def test_serial_identifiers_usb_serial_candidate(self):
        device = {"usb": {"serial_candidate": {"value": "USB-ABCDEF"}}}
        serials = serial_identifiers(device)
        self.assertIn("usb:usb-abcdef", serials)

    def test_serial_identifiers_usb_serial_direct(self):
        device = {"usb": {"serial": "USB-DIRECT-789"}}
        serials = serial_identifiers(device)
        self.assertIn("usb:usb-direct-789", serials)

    def test_serial_identifiers_pnp_usb_fallback(self):
        device = {"pnp": {"usb": {"serial_candidate": {"value": "PNP-USB-111"}}}}
        serials = serial_identifiers(device)
        self.assertIn("usb:pnp-usb-111", serials)

    def test_serial_identifiers_multiple(self):
        device = {
            "storage": {"serial": "STOR-123"},
            "usb": {"serial_candidate": {"value": "USB-456"}},
        }
        serials = serial_identifiers(device)
        self.assertEqual(len(serials), 2)

    def test_serial_identifiers_empty_device(self):
        device = {}
        serials = serial_identifiers(device)
        self.assertEqual(serials, set())

    def test_classify_pair_same_host_same_hardware_same_media(self):
        left = FakeObservation("hw-a", "media-a", "ms-a", "comp-a")
        right = FakeObservation("hw-a", "media-a", "ms-a", "comp-a")
        result = classify_pair(left, right)
        self.assertEqual(result.result, "SAME")
        self.assertEqual(result.confidence, 0.95)
        self.assertTrue(result.auto_link)
        self.assertIn("matching_hardware", result.reasons)
        self.assertIn("matching_media_identity", result.reasons)
        self.assertIn("same_computer", result.reasons)

    def test_classify_pair_different_computer_same_hardware_same_media(self):
        left = FakeObservation("hw-a", "media-a", "ms-a", "comp-a")
        right = FakeObservation("hw-a", "media-a", "ms-a", "comp-b")
        result = classify_pair(left, right)
        self.assertEqual(result.result, "LIKELY_SAME")
        self.assertEqual(result.confidence, 0.80)
        self.assertFalse(result.auto_link)
        self.assertIn("different_computer", result.reasons)

    def test_classify_pair_same_media_different_hardware(self):
        left = FakeObservation("hw-a", "media-a", "ms-a", "comp-a")
        right = FakeObservation("hw-b", "media-a", "ms-a", "comp-a")
        result = classify_pair(left, right)
        self.assertEqual(result.result, "CLONE_SUSPECTED")
        self.assertEqual(result.confidence, 0.20)
        self.assertFalse(result.auto_link)
        self.assertIn("different_hardware", result.reasons)
        self.assertIn("matching_media_identity", result.reasons)

    def test_classify_pair_matching_serial_different_hardware(self):
        device_a = {"storage": {"serial": "CHEAP-SERIAL"}}
        device_b = {"serial": "CHEAP-SERIAL", "vid": "1234"}
        left = FakeObservation("hw-a", "media-a", "ms-a", "comp-a", device_a)
        right = FakeObservation("hw-b", "media-b", "ms-b", "comp-b", device_b)
        result = classify_pair(left, right)
        self.assertEqual(result.result, "SERIAL_COLLISION")
        self.assertEqual(result.confidence, 0.05)
        self.assertFalse(result.auto_link)
        self.assertIn("matching_serial_evidence", result.reasons)

    def test_classify_pair_same_hardware_changed_media(self):
        left = FakeObservation("hw-a", "media-a", "ms-a", "comp-a")
        right = FakeObservation("hw-a", "media-b", "ms-b", "comp-a")
        result = classify_pair(left, right)
        self.assertEqual(result.result, "UNKNOWN")
        self.assertEqual(result.confidence, 0.45)
        self.assertFalse(result.auto_link)
        self.assertIn("matching_hardware", result.reasons)
        self.assertIn("different_or_missing_media_identity", result.reasons)

    def test_classify_pair_completely_different(self):
        left = FakeObservation("hw-a", "media-a", "ms-a", "comp-a")
        right = FakeObservation("hw-b", "media-b", "ms-b", "comp-b")
        result = classify_pair(left, right)
        self.assertEqual(result.result, "DIFFERENT")
        self.assertEqual(result.confidence, 0.0)
        self.assertFalse(result.auto_link)
        self.assertIn("different_hardware", result.reasons)

    def test_classify_pair_none_hardware_hash(self):
        left = FakeObservation(None, "media-a", "ms-a", "comp-a")
        right = FakeObservation("hw-b", "media-a", "ms-a", "comp-a")
        result = classify_pair(left, right)
        self.assertEqual(result.result, "CLONE_SUSPECTED")

    def test_classify_pair_none_media_hash(self):
        left = FakeObservation("hw-a", None, "ms-a", "comp-a")
        right = FakeObservation("hw-a", "media-a", "ms-a", "comp-a")
        result = classify_pair(left, right)
        self.assertEqual(result.result, "UNKNOWN")

    def test_collision_context_same_computer_false(self):
        current = FakeObservation("hw-a", "media-a", "ms-a", "comp-a",
                                  observed_at=datetime.datetime(2024, 1, 1, 10, 0, tzinfo=datetime.timezone.utc))
        previous = FakeObservation("hw-b", "media-b", "ms-b", "comp-a",
                                   observed_at=datetime.datetime(2024, 1, 1, 10, 5, tzinfo=datetime.timezone.utc))
        self.assertFalse(_collision_context(current, previous))

    def test_collision_context_different_computer_within_window(self):
        current = FakeObservation("hw-a", "media-a", "ms-a", "comp-a",
                                  observed_at=datetime.datetime(2024, 1, 1, 10, 0, tzinfo=datetime.timezone.utc))
        previous = FakeObservation("hw-b", "media-b", "ms-b", "comp-b",
                                   observed_at=datetime.datetime(2024, 1, 1, 10, 5, tzinfo=datetime.timezone.utc))
        self.assertTrue(_collision_context(current, previous))

    def test_collision_context_different_computer_outside_window(self):
        current = FakeObservation("hw-a", "media-a", "ms-a", "comp-a",
                                  observed_at=datetime.datetime(2024, 1, 1, 10, 0, tzinfo=datetime.timezone.utc))
        previous = FakeObservation("hw-b", "media-b", "ms-b", "comp-b",
                                   observed_at=datetime.datetime(2024, 1, 1, 10, 15, tzinfo=datetime.timezone.utc))
        self.assertFalse(_collision_context(current, previous))

    def test_collision_context_exact_window_boundary(self):
        current = FakeObservation("hw-a", "media-a", "ms-a", "comp-a",
                                  observed_at=datetime.datetime(2024, 1, 1, 10, 0, tzinfo=datetime.timezone.utc))
        previous = FakeObservation("hw-b", "media-b", "ms-b", "comp-b",
                                   observed_at=datetime.datetime(2024, 1, 1, 10, 10, tzinfo=datetime.timezone.utc))
        self.assertTrue(_collision_context(current, previous))

    def test_collision_context_naive_datetime_handling(self):
        current = FakeObservation("hw-a", "media-a", "ms-a", "comp-a",
                                  observed_at=datetime.datetime(2024, 1, 1, 10, 0))
        previous = FakeObservation("hw-b", "media-b", "ms-b", "comp-b",
                                   observed_at=datetime.datetime(2024, 1, 1, 10, 5))
        self.assertTrue(_collision_context(current, previous))


class IdentityIntegrationTests(unittest.TestCase):
    """Integration tests with real SQLite database."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def _make_obs(self, hardware, media, media_state, comp_suffix, device=None, observed_at=None):
        hostname = f"test-pc-{comp_suffix}"
        domain = f"test-{comp_suffix}"
        comp_key_val = computer_key({"hostname": hostname, "domain": domain})

        existing = self.db.scalar(
            select(Computer).where(Computer.computer_key == comp_key_val)
        )
        if existing is not None:
            comp_id = existing.id
        else:
            comp_id = uuid.uuid4()
            comp = Computer(
                id=comp_id,
                computer_key=comp_key_val,
                hostname=hostname,
                domain=domain,
                first_seen_at=observed_at or datetime.datetime.now(datetime.timezone.utc),
                last_seen_at=observed_at or datetime.datetime.now(datetime.timezone.utc),
                last_host={"hostname": hostname, "domain": domain},
            )
            self.db.add(comp)
            self.db.flush()

        obs = Observation(
            event_id=uuid.uuid4(),
            schema_version=1,
            probe_version="0.5.0",
            event_type="snapshot",
            observed_at_utc=observed_at or datetime.datetime.now(datetime.timezone.utc),
            hostname=hostname,
            hardware_stable_sha256=hardware,
            media_identity_sha256=media,
            media_state_sha256=media_state,
            host={"hostname": hostname, "domain": domain},
            session={"sid": f"S-1-5-21-test-{comp_suffix}"},
            device=device or {},
            capabilities={},
            capability_status={},
            collector_errors=[],
            raw_observation={},
            computer_id=comp_id,
        )
        return obs

    def test_ensure_computer_creates_and_reuses_by_key(self):
        now = datetime.datetime(2026, 9, 4, 8, 0, tzinfo=datetime.timezone.utc)
        first = ensure_computer(
            self.db, "Presence-PC", "CORP", now,
            presence_host("Presence-PC", "CORP", ["10.0.0.8"]),
        )
        self.db.flush()
        later = datetime.datetime(2026, 9, 4, 9, 0, tzinfo=datetime.timezone.utc)
        second = ensure_computer(
            self.db, "presence-pc", "corp", later,
            presence_host("presence-pc", "corp", ["10.0.0.9"]),
        )
        self.db.flush()
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.hostname, "presence-pc")
        self.assertEqual(second.last_seen_at, later)
        self.assertEqual(second.last_host["ip_addresses"], ["10.0.0.9"])

    def test_ensure_computer_keeps_observation_host_fields(self):
        now = datetime.datetime(2026, 9, 4, 8, 0, tzinfo=datetime.timezone.utc)
        computer = ensure_computer(
            self.db, "merge-pc", None, now,
            {"hostname": "merge-pc", "os": "Windows", "ip_addresses": ["10.0.0.1"]},
        )
        self.db.flush()
        ensure_computer(
            self.db, "merge-pc", None, now,
            presence_host("merge-pc", None, ["10.0.0.2"]),
        )
        self.db.flush()
        self.assertEqual(computer.last_host["os"], "Windows")
        self.assertEqual(computer.last_host["ip_addresses"], ["10.0.0.2"])

    def test_register_computer_reuses_presence_computer(self):
        now = datetime.datetime(2026, 9, 4, 8, 0, tzinfo=datetime.timezone.utc)
        presence = ensure_computer(self.db, "test-pc-reg-presence", "test-reg-presence", now)
        self.db.flush()
        obs = self._make_obs("hw-1", "media-1", "ms-1", "reg-presence")
        computer = register_computer(self.db, obs)
        self.db.flush()
        self.assertEqual(presence.id, computer.id)
        self.assertEqual(obs.computer_id, presence.id)

    def test_register_computer_creates_new(self):
        obs = self._make_obs("hw-1", "media-1", "ms-1", "reg-new")
        computer = register_computer(self.db, obs)
        self.db.flush()
        self.assertIsNotNone(computer.id)
        self.assertEqual(computer.hostname, "test-pc-reg-new")
        self.assertEqual(computer.domain, "test-reg-new")
        self.assertEqual(obs.computer_id, computer.id)

    def test_register_computer_updates_existing(self):
        obs1 = self._make_obs("hw-1", "media-1", "ms-1", "reg-upd")
        comp1 = register_computer(self.db, obs1)
        self.db.flush()

        obs2 = self._make_obs("hw-2", "media-2", "ms-2", "reg-upd")
        comp2 = register_computer(self.db, obs2)
        self.db.flush()

        self.assertEqual(comp1.id, comp2.id)
        self.assertEqual(obs2.computer_id, comp1.id)

    def test_resolve_identity_first_observation_creates_new_device(self):
        obs = self._make_obs("hw-first", "media-first", "ms-first", "ri-first")
        self.db.add(obs)
        self.db.flush()

        decision = resolve_identity(self.db, obs)
        self.db.commit()

        self.assertEqual(decision.result, "UNKNOWN")
        self.assertEqual(decision.confidence, 0.0)
        self.assertFalse(decision.auto_linked)
        self.assertIn("first_observation", decision.reasons)
        self.assertIsNotNone(obs.physical_device_id)
        self.assertIsNotNone(obs.media_state_id)

        physical = self.db.get(PhysicalDevice, obs.physical_device_id)
        self.assertEqual(physical.hardware_stable_sha256, "hw-first")
        self.assertEqual(physical.status, "provisional")
        self.assertEqual(physical.identity_confidence, "unknown")

    def test_resolve_identity_same_hardware_same_media_same_computer_auto_links(self):
        obs1 = self._make_obs("hw-same", "media-same", "ms-same", "ri-same")
        self.db.add(obs1)
        self.db.flush()
        resolve_identity(self.db, obs1)
        self.db.commit()

        obs2 = self._make_obs("hw-same", "media-same", "ms-same", "ri-same")
        self.db.add(obs2)
        self.db.flush()
        decision = resolve_identity(self.db, obs2)
        self.db.commit()

        self.assertEqual(decision.result, "SAME")
        self.assertTrue(decision.auto_linked)
        self.assertEqual(obs2.physical_device_id, obs1.physical_device_id)
        self.assertEqual(obs2.media_state_id, obs1.media_state_id)

        physical = self.db.get(PhysicalDevice, obs1.physical_device_id)
        self.assertEqual(physical.identity_confidence, "high")

    def test_resolve_identity_same_hardware_same_media_different_computer_likely_same(self):
        now = datetime.datetime.now(datetime.timezone.utc)

        obs1 = self._make_obs("hw-likely", "media-likely", "ms-likely", "ri-likely-a",
                               observed_at=now)
        self.db.add(obs1)
        self.db.flush()
        resolve_identity(self.db, obs1)
        self.db.commit()

        obs2 = self._make_obs("hw-likely", "media-likely", "ms-likely", "ri-likely-b",
                               observed_at=now + datetime.timedelta(minutes=20))
        self.db.add(obs2)
        self.db.flush()
        decision = resolve_identity(self.db, obs2)
        self.db.commit()

        self.assertEqual(decision.result, "LIKELY_SAME")
        self.assertFalse(decision.auto_linked)
        self.assertNotEqual(obs2.physical_device_id, obs1.physical_device_id)

        physical = self.db.get(PhysicalDevice, obs2.physical_device_id)
        self.assertEqual(physical.identity_confidence, "unknown")

    def test_resolve_identity_clone_suspected(self):
        now = datetime.datetime.now(datetime.timezone.utc)

        obs1 = self._make_obs("hw-a", "media-clone", "ms-clone", "ri-clone-a",
                               observed_at=now)
        self.db.add(obs1)
        self.db.flush()
        resolve_identity(self.db, obs1)
        self.db.commit()

        obs2 = self._make_obs("hw-b", "media-clone", "ms-clone", "ri-clone-b",
                               observed_at=now + datetime.timedelta(minutes=20))
        self.db.add(obs2)
        self.db.flush()
        decision = resolve_identity(self.db, obs2)
        self.db.commit()

        self.assertEqual(decision.result, "CLONE_SUSPECTED")
        self.assertFalse(decision.auto_linked)

    def test_resolve_identity_serial_collision(self):
        device_a = {"storage": {"serial": "COLLISION-123"}}
        device_b = {"serial": "COLLISION-123"}

        obs1 = self._make_obs("hw-a", "media-a", "ms-a", "ri-coll-a", device_a)
        self.db.add(obs1)
        self.db.flush()
        resolve_identity(self.db, obs1)
        self.db.commit()

        obs2 = self._make_obs("hw-b", "media-b", "ms-b", "ri-coll-b", device_b)
        self.db.add(obs2)
        self.db.flush()
        decision = resolve_identity(self.db, obs2)
        self.db.commit()

        self.assertEqual(decision.result, "SERIAL_COLLISION")

    def test_resolve_identity_simultaneous_different_computers_becomes_collision(self):
        now = datetime.datetime.now(datetime.timezone.utc)

        obs1 = self._make_obs("hw-a", "media-a", "ms-a", "ri-sim-a",
                               observed_at=now)
        self.db.add(obs1)
        self.db.flush()
        resolve_identity(self.db, obs1)
        self.db.commit()

        obs2 = self._make_obs("hw-a", "media-a", "ms-a", "ri-sim-b",
                               observed_at=now + datetime.timedelta(minutes=5))
        self.db.add(obs2)
        self.db.flush()
        decision = resolve_identity(self.db, obs2)
        self.db.commit()

        self.assertEqual(decision.result, "SERIAL_COLLISION")
        self.assertIn("simultaneous_different_computers", decision.reasons)

    def test_resolve_identity_unknown_hardware_match_different_media(self):
        now = datetime.datetime.now(datetime.timezone.utc)

        obs1 = self._make_obs("hw-unknown", "media-a", "ms-a", "ri-unk-a",
                               observed_at=now)
        self.db.add(obs1)
        self.db.flush()
        resolve_identity(self.db, obs1)
        self.db.commit()

        obs2 = self._make_obs("hw-unknown", "media-b", "ms-b", "ri-unk-b",
                               observed_at=now + datetime.timedelta(minutes=20))
        self.db.add(obs2)
        self.db.flush()
        decision = resolve_identity(self.db, obs2)
        self.db.commit()

        self.assertEqual(decision.result, "UNKNOWN")
        self.assertFalse(decision.auto_linked)

    def test_media_state_created_per_unique_media_identity(self):
        obs1 = self._make_obs("hw-ms1", "media-a", "ms-a", "ri-ms1")
        self.db.add(obs1)
        self.db.flush()
        resolve_identity(self.db, obs1)
        self.db.commit()

        obs2 = self._make_obs("hw-ms1", "media-a", "ms-b", "ri-ms1")
        self.db.add(obs2)
        self.db.flush()
        resolve_identity(self.db, obs2)
        self.db.commit()

        self.assertEqual(obs1.physical_device_id, obs2.physical_device_id)
        self.assertNotEqual(obs1.media_state_id, obs2.media_state_id)

        media_states = list(self.db.scalars(
            select(MediaState).where(MediaState.physical_device_id == obs1.physical_device_id)
        ))
        self.assertEqual(len(media_states), 2)

    def test_media_state_reused_for_same_identity_and_state(self):
        obs1 = self._make_obs("hw-ms2", "media-a", "ms-a", "ri-ms2")
        self.db.add(obs1)
        self.db.flush()
        resolve_identity(self.db, obs1)
        self.db.commit()

        obs2 = self._make_obs("hw-ms2", "media-a", "ms-a", "ri-ms2")
        self.db.add(obs2)
        self.db.flush()
        resolve_identity(self.db, obs2)
        self.db.commit()

        self.assertEqual(obs1.media_state_id, obs2.media_state_id)

    def test_same_computer_changing_media_reuses_provisional_device(self):
        # Same computer + same hardware but changing media no longer spawns an
        # unbounded set of provisional devices; a single provisional device is
        # reused per (computer, hardware).
        first = self._make_obs("hw-reuse", "media-a", "ms-a", "ri-reuse")
        self.db.add(first)
        self.db.flush()
        resolve_identity(self.db, first)
        self.db.commit()

        second = self._make_obs("hw-reuse", "media-b", "ms-b", "ri-reuse")
        self.db.add(second)
        self.db.flush()
        resolve_identity(self.db, second)
        self.db.commit()

        self.assertEqual(second.physical_device_id, first.physical_device_id)
        self.assertNotEqual(second.media_state_id, first.media_state_id)

    def test_different_computer_changing_media_keeps_separate_devices(self):
        first = self._make_obs("hw-reuse2", "media-a", "ms-a", "ri-reuse2-a")
        self.db.add(first)
        self.db.flush()
        resolve_identity(self.db, first)
        self.db.commit()

        second = self._make_obs("hw-reuse2", "media-a", "ms-b", "ri-reuse2-b")
        self.db.add(second)
        self.db.flush()
        resolve_identity(self.db, second)
        self.db.commit()

        self.assertNotEqual(second.physical_device_id, first.physical_device_id)

    def test_latest_observations_limit_200(self):
        for i in range(250):
            obs = self._make_obs(f"hw-lim-{i}", f"media-lim-{i}", f"ms-lim-{i}",
                                 f"ri-lim-{i}")
            obs.physical_device_id = uuid.uuid4()
            self.db.add(obs)
        self.db.commit()

        latest_obs = self._make_obs("hw-latest", "media-latest", "ms-latest", "ri-latest")
        self.db.add(latest_obs)
        self.db.flush()

        candidates = _latest_observations(self.db, latest_obs)
        self.assertEqual(len(candidates), 200)

    def test_priority_resolution_picks_highest_priority(self):
        now = datetime.datetime.now(datetime.timezone.utc)

        obs_a = self._make_obs("hw-pri-a", "media-a", "ms-a", "ri-pri-a",
                                observed_at=now)
        self.db.add(obs_a)
        self.db.flush()
        resolve_identity(self.db, obs_a)
        self.db.commit()

        obs_b = self._make_obs("hw-pri-b", "media-a", "ms-a", "ri-pri-b",
                                observed_at=now + datetime.timedelta(minutes=20))
        self.db.add(obs_b)
        self.db.flush()
        resolve_identity(self.db, obs_b)
        self.db.commit()

        obs_c = self._make_obs("hw-pri-c", "media-a", "ms-a", "ri-pri-c",
                                observed_at=now + datetime.timedelta(minutes=40))
        obs_c.device = {"storage": {"serial": "SAME-SERIAL"}}
        obs_a.device = {"storage": {"serial": "SAME-SERIAL"}}
        self.db.add(obs_c)
        self.db.flush()
        decision = resolve_identity(self.db, obs_c)
        self.db.commit()

        self.assertEqual(decision.result, "CLONE_SUSPECTED")

    def test_new_physical_device_sets_correct_fields(self):
        obs = self._make_obs("hw-npd", "media-npd", "ms-npd", "ri-npd")
        physical = _new_physical_device(obs)
        self.assertEqual(physical.hardware_stable_sha256, "hw-npd")
        self.assertEqual(physical.status, "provisional")
        self.assertEqual(physical.identity_confidence, "unknown")
        self.assertEqual(physical.representative_device, obs.device)

    def test_get_or_create_media_state_creates_new(self):
        physical = PhysicalDevice(
            id=uuid.uuid4(),
            hardware_stable_sha256="hw-goc",
            status="provisional",
            identity_confidence="unknown",
            first_seen_at=datetime.datetime.now(datetime.timezone.utc),
            last_seen_at=datetime.datetime.now(datetime.timezone.utc),
            representative_device={},
        )
        self.db.add(physical)
        self.db.flush()

        obs = self._make_obs("hw-goc", "media-a", "ms-a", "ri-goc")
        state = _get_or_create_media_state(self.db, physical, obs)
        self.db.commit()

        self.assertEqual(state.media_identity_sha256, "media-a")
        self.assertEqual(state.media_state_sha256, "ms-a")
        self.assertEqual(state.physical_device_id, physical.id)

    def test_get_or_create_media_state_reuses_existing(self):
        physical = PhysicalDevice(
            id=uuid.uuid4(),
            hardware_stable_sha256="hw-gocr",
            status="provisional",
            identity_confidence="unknown",
            first_seen_at=datetime.datetime.now(datetime.timezone.utc),
            last_seen_at=datetime.datetime.now(datetime.timezone.utc),
            representative_device={},
        )
        self.db.add(physical)
        self.db.flush()

        obs1 = self._make_obs("hw-gocr", "media-a", "ms-a", "ri-gocr")
        state1 = _get_or_create_media_state(self.db, physical, obs1)
        self.db.commit()

        obs2 = self._make_obs("hw-gocr", "media-a", "ms-a", "ri-gocr")
        state2 = _get_or_create_media_state(self.db, physical, obs2)
        self.db.commit()

        self.assertEqual(state1.id, state2.id)

    def test_identity_decision_stored_with_correct_fields(self):
        obs = self._make_obs("hw-dec", "media-dec", "ms-dec", "ri-dec")
        self.db.add(obs)
        self.db.flush()
        decision = resolve_identity(self.db, obs)
        self.db.commit()

        stored = self.db.get(IdentityDecision, decision.id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.observation_id, obs.id)
        self.assertEqual(stored.result, "UNKNOWN")
        self.assertEqual(stored.confidence, 0.0)
        self.assertFalse(stored.auto_linked)
        self.assertEqual(stored.assigned_physical_device_id, obs.physical_device_id)
        self.assertEqual(stored.reasons, ["first_observation"])


class IdentityEdgeCaseTests(unittest.TestCase):
    """Edge cases and error handling."""

    def test_classify_pair_with_empty_device_dicts(self):
        left = FakeObservation("hw-a", "media-a", "ms-a", "comp-a", {})
        right = FakeObservation("hw-a", "media-a", "ms-a", "comp-a", {})
        result = classify_pair(left, right)
        self.assertEqual(result.result, "SAME")

    def test_classify_pair_with_none_device(self):
        left = FakeObservation("hw-a", "media-a", "ms-a", "comp-a", None)
        right = FakeObservation("hw-a", "media-a", "ms-a", "comp-a", None)
        result = classify_pair(left, right)
        self.assertEqual(result.result, "SAME")

    def test_serial_identifiers_with_non_dict_storage(self):
        device = {"storage": "not-a-dict"}
        serials = serial_identifiers(device)
        self.assertEqual(serials, set())

    def test_serial_identifiers_with_non_dict_usb(self):
        device = {"usb": "not-a-dict"}
        serials = serial_identifiers(device)
        self.assertEqual(serials, set())

    def test_serial_identifiers_case_insensitive(self):
        device_a = {"storage": {"serial": "ABC-123"}}
        device_b = {"storage": {"serial": "abc-123"}}
        serials_a = serial_identifiers(device_a)
        serials_b = serial_identifiers(device_b)
        self.assertEqual(serials_a, serials_b)


if __name__ == "__main__":
    unittest.main()
