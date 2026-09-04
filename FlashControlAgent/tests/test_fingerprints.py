import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
import uuid


from probe_support import base_record, copy_record, probe


class FingerprintTests(unittest.TestCase):
    def test_hardware_hash_ignores_non_intrinsic_noise(self):
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

        self.assertEqual(
            probe.hardware_hash(baseline),
            probe.hardware_hash(variant),
        )

    def test_hardware_hash_changes_for_intrinsic_inputs(self):
        baseline = copy_record(base_record())
        baseline_hash = probe.hardware_hash(baseline)

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
        ]

        for name, mutate in mutations:
            with self.subTest(name=name):
                variant = copy_record(base_record())
                mutate(variant)
                self.assertNotEqual(baseline_hash, probe.hardware_hash(variant))

    def test_port_specific_serial_candidate_does_not_change_hardware_hash(self):
        baseline = copy_record(base_record())
        variant = copy_record(base_record())
        baseline["pnp"]["usb"]["serial_candidate"]["likely_port_specific"] = True
        variant["pnp"]["usb"]["serial_candidate"]["likely_port_specific"] = True
        variant["pnp"]["usb"]["serial_candidate"]["value"] = "DIFFERENT"

        self.assertEqual(
            probe.hardware_hash(baseline),
            probe.hardware_hash(variant),
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

    def test_software_hash_ignores_path_noise_and_order(self):
        baseline = copy_record(base_record())
        variant = copy_record(base_record())
        variant["volumes"][0]["drive_letters"] = ["X:"]
        variant["volumes"][0]["mount_paths"] = [r"X:\\"]
        variant["volumes"][0]["volume_guid"] = r"\\?\Volume{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}\\"
        variant["layout"]["partitions"] = list(reversed(variant["layout"]["partitions"]))
        variant["volumes"] = list(reversed(variant["volumes"]))

        self.assertEqual(
            probe.software_hash(baseline),
            probe.software_hash(variant),
        )

    def test_software_hash_changes_for_layout_identifiers(self):
        baseline = copy_record(base_record())
        baseline_hash = probe.software_hash(baseline)

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
                self.assertNotEqual(baseline_hash, probe.software_hash(variant))

    def test_software_hash_changes_for_mutable_media_inputs(self):
        baseline = copy_record(base_record())
        baseline_hash = probe.software_hash(baseline)

        mutations = [
            ("filesystem", lambda record: record["volumes"][0].__setitem__("filesystem", "FAT32")),
            ("volume_label", lambda record: record["volumes"][0].__setitem__("volume_label", "OTHER")),
            ("partition_name", lambda record: record["layout"]["partitions"][0].__setitem__("name", "Renamed")),
        ]

        for name, mutate in mutations:
            with self.subTest(name=name):
                variant = copy_record(base_record())
                mutate(variant)
                self.assertNotEqual(baseline_hash, probe.software_hash(variant))

class ObservationAndCapabilityTests(unittest.TestCase):
    def test_summarize_capabilities_aggregates_multiple_devices(self):
        devices = [
            {"capabilities": {"storage_descriptor": True, "geometry": False, "partition_layout": False, "volume_information": False, "pnp_tree": False}},
            {"capabilities": {"storage_descriptor": False, "geometry": True, "partition_layout": True, "volume_information": False, "pnp_tree": True}},
        ]
        summary = probe.summarize_capabilities(devices)
        self.assertTrue(summary["storage_descriptor"])
        self.assertTrue(summary["geometry"])
        self.assertTrue(summary["partition_layout"])
        self.assertTrue(summary["pnp_tree"])

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
        self.assertEqual(observation["event"]["type"], "snapshot")
        self.assertEqual(observation["host"]["hostname"], "host-\u2603")
        self.assertEqual(observation["session"]["sid"], "S-1-5-21-123")
        self.assertNotIn("capabilities", observation)
        self.assertNotIn("event_id", observation)
        dumped = json.dumps(observation)
        self.assertNotIn('"drive_letter":', dumped)
        self.assertNotIn('"volume": {', dumped)
        self.assertNotIn('"error":', dumped)

    def test_build_observation_compacts_payload_without_mutating_source(self):
        record = copy_record(base_record())
        record["storage"]["descriptor_size"] = 123
        record["geometry"]["cylinders"] = 7648
        record["hardware_sha256"] = "aa" * 32
        record["pnp_observation_sha256"] = "bb" * 32
        record["software_sha256"] = "ee" * 32
        record["volumes"][0]["errors"] = {
            "mount_paths": None,
            "open": None,
            "device_number": None,
            "volume_information": None,
        }
        original_nodes = copy_record(record["pnp"]["nodes"])
        original_partitions = copy_record(record["layout"]["partitions"])

        observation = probe.build_observation(
            record,
            host={
                "hostname": "host",
                "ip_addresses": ["10.0.0.1"],
                "workgroup_name": "WORKGROUP",
            },
            session={
                "sid": "S-1-5-21-123",
                "username": "mihail",
                "domain": "host",
                "session_id": 2,
                "errors": {"enumeration": None, "sid": None},
            },
            observed_at_utc="2026-09-01T12:00:00.000000Z",
        )
        device = observation["device"]

        self.assertEqual(record["pnp"]["nodes"], original_nodes)
        self.assertEqual(record["layout"]["partitions"], original_partitions)
        self.assertEqual(observation["event"]["type"], "snapshot")
        self.assertEqual(observation["host"], {"hostname": "host"})
        self.assertEqual(observation["hashes"], {
            "hardware": "aa" * 32,
            "software": "ee" * 32,
        })
        self.assertNotIn("pnp", observation["hashes"])
        self.assertNotIn("hardware_sha256", device)
        self.assertNotIn("pnp", device)
        self.assertNotIn("path", device)
        self.assertNotIn("physical_drive", device)
        self.assertEqual(device["vendor"], "FlashCo")
        self.assertEqual(device["product"], "Probe")
        self.assertEqual(device["serial"], "STOR123")
        self.assertNotIn("revision", device)
        self.assertEqual(device["vid"], "1234")
        self.assertEqual(device["pid"], "5678")
        self.assertEqual(device["usb_serial"], "ABCDEF")
        self.assertNotIn("size_bytes", device)
        self.assertEqual(device["layout"], {
            "style": "MBR",
            "mbr_signature": "A1B2C3D4",
        })
        self.assertNotIn("partitions", device["layout"])
        self.assertEqual(observation["session"], {
            "username": "mihail",
            "sid": "S-1-5-21-123",
        })
        self.assertNotIn("collector_errors", observation)
        self.assertEqual(device["volumes"][0]["filesystem"], "exFAT")
        self.assertEqual(device["volumes"][0]["serial"], "ABCD1234")
        self.assertNotIn("letters", device["volumes"][0])
        self.assertNotIn("label", device["volumes"][0])
        self.assertNotIn("volume_guid", device["volumes"][0])
        self.assertNotIn("mount_paths", device["volumes"][0])

    def test_build_observation_keeps_full_payload_when_not_compact(self):
        record = copy_record(base_record())
        record["storage"]["descriptor_size"] = 123
        record["hardware_sha256"] = "aa" * 32
        observation = probe.build_observation(
            record,
            host={"hostname": "host"},
            session={"sid": "S-1-5-21-123", "errors": {"enumeration": None, "sid": None}},
            observed_at_utc="2026-09-01T12:00:00.000000Z",
            compact=False,
        )
        device = observation["device"]
        self.assertEqual(observation["event"]["type"], "snapshot")
        self.assertEqual(observation["hashes"]["hardware"], "aa" * 32)
        self.assertEqual(device["storage"]["descriptor_size"], 123)
        self.assertEqual(len(device["pnp"]["nodes"]), 3)
        self.assertTrue(any(item.get("is_unused") for item in device["layout"]["partitions"]))
        self.assertEqual(observation["session"]["errors"]["sid"], None)
        self.assertIn("capabilities", observation)

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
        self.assertEqual(document["host"]["hostname"], "host-\u20ac")
        self.assertEqual(document["session"]["sid"], "S-1-5-21-123")
        self.assertNotIn("schema_version", document["observations"][0])
        self.assertNotIn("host", document["observations"][0])
        self.assertNotIn("session", document["observations"][0])
        self.assertEqual(document["scan_id"], "33333333-3333-3333-3333-333333333333")
        self.assertEqual(document["generated_at_utc"], "2026-09-01T12:00:00.000000Z")
        self.assertEqual(len(document["observations"]), 2)
        self.assertEqual(document["observations"][0]["event"]["id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(document["observations"][1]["event"]["id"], "22222222-2222-2222-2222-222222222222")
        self.assertIn("device", document["observations"][0])
        self.assertEqual(document["scan_errors"], [])
        self.assertNotIn("scan_capabilities", document)


if __name__ == "__main__":
    unittest.main()
