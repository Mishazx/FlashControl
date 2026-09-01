import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
import uuid


from probe_support import base_record, copy_record, probe


class FingerprintTests(unittest.TestCase):
    def test_hardware_stable_hash_ignores_non_intrinsic_noise(self):
        baseline = copy_record(base_record())
        variant = copy_record(base_record())
        variant["physical_drive"] = 99
        variant["path"] = r"\\.\PhysicalDrive99"
        variant["volumes"][0]["drive_letters"] = ["Z:"]
        variant["volumes"][0]["mount_paths"] = [r"Z:\\"]
        variant["volumes"][0]["volume_guid"] = r"\\?\Volume{99999999-9999-9999-9999-999999999999}\\"
        variant["pnp"]["nodes"][2]["device_instance_id"] = "PCI\\VEN_8086&DEV_9999"
        variant["pnp"]["nodes"][1]["hardware_ids"] = list(reversed(variant["pnp"]["nodes"][1]["hardware_ids"]))
        variant["pnp"]["nodes"][1]["compatible_ids"] = list(reversed(variant["pnp"]["nodes"][1]["compatible_ids"]))
        variant["pnp"]["nodes"][0]["hardware_ids"] = ["USBSTOR\\OTHER"]
        variant["vpd83"] = list(reversed(variant["vpd83"]))

        self.assertEqual(
            probe.hardware_stable_hash(baseline),
            probe.hardware_stable_hash(variant),
        )

    def test_hardware_stable_hash_changes_for_intrinsic_inputs(self):
        baseline = copy_record(base_record())
        baseline_hash = probe.hardware_stable_hash(baseline)

        mutations = [
            ("vid", lambda record: record["pnp"]["usb"].__setitem__("vid", "4321")),
            ("pid", lambda record: record["pnp"]["usb"].__setitem__("pid", "8765")),
            (
                "serial",
                lambda record: record["storage"].__setitem__("serial", "NEWDISK"),
            ),
            (
                "vendor",
                lambda record: record["storage"].__setitem__("vendor", "OtherVendor"),
            ),
            (
                "product",
                lambda record: record["storage"].__setitem__("product", "OtherProduct"),
            ),
            (
                "revision",
                lambda record: record["storage"].__setitem__("revision", "9.99"),
            ),
            (
                "capacity",
                lambda record: record["geometry"].__setitem__("size_bytes", 123),
            ),
            (
                "sector_size",
                lambda record: record["geometry"].__setitem__("bytes_per_sector", 4096),
            ),
            (
                "vpd83",
                lambda record: record["vpd83"][0].__setitem__("value_hex", "deadbeef"),
            ),
        ]

        for name, mutate in mutations:
            with self.subTest(name=name):
                variant = copy_record(base_record())
                mutate(variant)
                self.assertNotEqual(baseline_hash, probe.hardware_stable_hash(variant))

    def test_port_specific_serial_candidate_does_not_change_hardware_stable_hash(self):
        baseline = copy_record(base_record())
        variant = copy_record(base_record())
        baseline["pnp"]["usb"]["serial_candidate"]["likely_port_specific"] = True
        variant["pnp"]["usb"]["serial_candidate"]["likely_port_specific"] = True
        variant["pnp"]["usb"]["serial_candidate"]["value"] = "DIFFERENT"

        self.assertEqual(
            probe.hardware_stable_hash(baseline),
            probe.hardware_stable_hash(variant),
        )

    def test_pnp_observation_hash_ignores_order_and_parent_nodes(self):
        baseline = copy_record(base_record())
        variant = copy_record(base_record())
        variant["pnp"]["nodes"][2]["device_instance_id"] = "PCI\\VEN_8086&DEV_9999"
        variant["pnp"]["nodes"][1]["hardware_ids"] = list(reversed(variant["pnp"]["nodes"][1]["hardware_ids"]))
        variant["pnp"]["nodes"][1]["compatible_ids"] = list(reversed(variant["pnp"]["nodes"][1]["compatible_ids"]))

        self.assertEqual(
            probe.pnp_observation_hash(baseline),
            probe.pnp_observation_hash(variant),
        )

    def test_pnp_observation_hash_changes_for_hardware_ids(self):
        baseline = copy_record(base_record())
        variant = copy_record(base_record())
        variant["pnp"]["nodes"][0]["hardware_ids"] = ["USBSTOR\\OTHER"]

        self.assertNotEqual(
            probe.pnp_observation_hash(baseline),
            probe.pnp_observation_hash(variant),
        )

    def test_media_identity_hash_ignores_state_and_path_noise(self):
        baseline = copy_record(base_record())
        variant = copy_record(base_record())
        variant["volumes"][0]["drive_letters"] = ["X:"]
        variant["volumes"][0]["mount_paths"] = [r"X:\\"]
        variant["volumes"][0]["volume_guid"] = r"\\?\Volume{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}\\"
        variant["volumes"][0]["filesystem"] = "FAT32"
        variant["volumes"][0]["volume_label"] = "RENAMED"
        variant["layout"]["partitions"][0]["name"] = "Other GPT Name"
        variant["layout"]["partitions"] = list(reversed(variant["layout"]["partitions"]))
        variant["volumes"] = list(reversed(variant["volumes"]))

        self.assertEqual(
            probe.media_identity_hash(baseline),
            probe.media_identity_hash(variant),
        )

    def test_media_identity_hash_changes_for_identity_inputs(self):
        baseline = copy_record(base_record())
        baseline_hash = probe.media_identity_hash(baseline)

        mutations = [
            ("mbr_signature", lambda record: record["layout"].__setitem__("mbr_signature", "DEADBEEF")),
            ("gpt_disk_guid", lambda record: record["layout"].__setitem__("gpt_disk_guid", "feedface")),
            ("partition_offset", lambda record: record["layout"]["partitions"][0].__setitem__("offset", 12345)),
            ("partition_length", lambda record: record["layout"]["partitions"][0].__setitem__("length", 54321)),
            ("partition_type", lambda record: record["layout"]["partitions"][0].__setitem__("mbr_type", 99)),
            ("volume_serial", lambda record: record["volumes"][0].__setitem__("volume_serial", "12345678")),
        ]

        for name, mutate in mutations:
            with self.subTest(name=name):
                variant = copy_record(base_record())
                mutate(variant)
                self.assertNotEqual(baseline_hash, probe.media_identity_hash(variant))

    def test_media_state_hash_changes_for_mutable_media_inputs(self):
        baseline = copy_record(base_record())
        baseline_hash = probe.media_state_hash(baseline)

        mutations = [
            ("filesystem", lambda record: record["volumes"][0].__setitem__("filesystem", "FAT32")),
            ("volume_label", lambda record: record["volumes"][0].__setitem__("volume_label", "OTHER")),
            ("partition_name", lambda record: record["layout"]["partitions"][0].__setitem__("name", "Renamed")),
        ]

        for name, mutate in mutations:
            with self.subTest(name=name):
                variant = copy_record(base_record())
                mutate(variant)
                self.assertNotEqual(baseline_hash, probe.media_state_hash(variant))

    def test_media_state_hash_ignores_identity_inputs(self):
        baseline = copy_record(base_record())
        variant = copy_record(base_record())
        variant["layout"]["mbr_signature"] = "DEADBEEF"
        variant["layout"]["gpt_disk_guid"] = "feedface"
        variant["layout"]["partitions"][0]["offset"] = 12345
        variant["volumes"][0]["volume_serial"] = "12345678"

        self.assertEqual(
            probe.media_state_hash(baseline),
            probe.media_state_hash(variant),
        )

    def test_observation_hash_changes_when_any_component_changes(self):
        hardware_stable = probe.hardware_stable_hash(base_record())
        pnp_observation = probe.pnp_observation_hash(base_record())
        media_identity = probe.media_identity_hash(base_record())
        media_state = probe.media_state_hash(base_record())

        baseline = probe.observation_hash(
            hardware_stable,
            pnp_observation,
            media_identity,
            media_state,
        )
        self.assertEqual(
            baseline,
            probe.observation_hash(
                hardware_stable,
                pnp_observation,
                media_identity,
                media_state,
            ),
        )
        self.assertNotEqual(
            baseline,
            probe.observation_hash("a" * 64, pnp_observation, media_identity, media_state),
        )
        self.assertNotEqual(
            baseline,
            probe.observation_hash(hardware_stable, "a" * 64, media_identity, media_state),
        )
        self.assertNotEqual(
            baseline,
            probe.observation_hash(hardware_stable, pnp_observation, "a" * 64, media_state),
        )
        self.assertNotEqual(
            baseline,
            probe.observation_hash(hardware_stable, pnp_observation, media_identity, "a" * 64),
        )


class ObservationAndCapabilityTests(unittest.TestCase):
    def test_summarize_capabilities_aggregates_multiple_devices(self):
        devices = [
            {"capabilities": {"storage_descriptor": True, "geometry": False, "partition_layout": False, "volume_information": False, "pnp_tree": False, "vpd80": False, "vpd83": False}},
            {"capabilities": {"storage_descriptor": False, "geometry": True, "partition_layout": True, "volume_information": False, "pnp_tree": True, "vpd80": False, "vpd83": True}},
        ]
        summary = probe.summarize_capabilities(devices)
        self.assertTrue(summary["storage_descriptor"])
        self.assertTrue(summary["geometry"])
        self.assertTrue(summary["partition_layout"])
        self.assertTrue(summary["pnp_tree"])
        self.assertTrue(summary["vpd83"])
        self.assertFalse(summary["vpd80"])

    def test_collector_error_list_normalizes_and_sorts(self):
        errors = {
            "b": {"message": "two", "status": "unsupported"},
            "a": "one",
            "c": None,
        }
        normalized = probe.collector_error_list(errors)
        self.assertEqual([item["collector"] for item in normalized], ["a", "b"])
        self.assertEqual(normalized[0]["status"], "invalid_data")
        self.assertEqual(normalized[1]["status"], "unsupported")

    def test_build_observation_strips_internal_fields(self):
        record = copy_record(base_record())
        observation = probe.build_observation(
            record,
            host={"hostname": "host-\u2603"},
            session={"session_id": 1, "sid": "S-1-5-21-123"},
            observed_at_utc="2026-09-01T12:00:00.000000Z",
        )

        self.assertEqual(observation["schema_version"], probe.SCHEMA_VERSION)
        self.assertEqual(observation["probe_version"], probe.PROBE_VERSION)
        self.assertEqual(observation["event_type"], "snapshot")
        self.assertEqual(observation["host"]["hostname"], "host-\u2603")
        self.assertEqual(observation["session"]["sid"], "S-1-5-21-123")
        self.assertIn("capabilities", observation)
        self.assertIn("capability_status", observation)
        self.assertIn("collector_errors", observation)
        dumped = json.dumps(observation)
        self.assertNotIn('"drive_letter":', dumped)
        self.assertNotIn('"volume": {', dumped)
        self.assertNotIn('"error":', dumped)

    def test_main_outputs_valid_scan_document(self):
        record = copy_record(base_record())
        device_one = copy_record(record)
        device_two = copy_record(record)
        device_two["physical_drive"] = 8
        device_two["pnp"]["usb"]["vid"] = "4321"
        device_two["pnp"]["usb"]["pid"] = "8765"

        uuid_values = iter([
            uuid.UUID("11111111-1111-1111-1111-111111111111"),
            uuid.UUID("22222222-2222-2222-2222-222222222222"),
            uuid.UUID("33333333-3333-3333-3333-333333333333"),
        ])

        def next_uuid():
            return next(uuid_values)

        with patch.object(probe, "scan_physical_disks", return_value=([device_one, device_two], [])), \
            patch.object(probe, "host_info", return_value={"hostname": "host-\u20ac", "computer_name": "host-\u20ac"}), \
            patch.object(probe, "collect_active_session", return_value={"session_id": 1, "sid": "S-1-5-21-123"}), \
            patch.object(probe, "utc_now_iso", return_value="2026-09-01T12:00:00.000000Z"), \
            patch.object(probe.uuid, "uuid4", side_effect=next_uuid):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                probe.main()

        document = json.loads(buffer.getvalue())
        self.assertEqual(document["schema_version"], probe.SCHEMA_VERSION)
        self.assertEqual(document["probe_version"], probe.PROBE_VERSION)
        self.assertEqual(document["scan_id"], "33333333-3333-3333-3333-333333333333")
        self.assertEqual(document["generated_at_utc"], "2026-09-01T12:00:00.000000Z")
        self.assertEqual(len(document["observations"]), 2)
        self.assertEqual(document["observations"][0]["event_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(document["observations"][1]["event_id"], "22222222-2222-2222-2222-222222222222")
        self.assertNotIn("local_users", document["observations"][0]["host"])
        self.assertEqual(document["scan_errors"], [])
        self.assertTrue(document["scan_capabilities"]["storage_descriptor"])


if __name__ == "__main__":
    unittest.main()
