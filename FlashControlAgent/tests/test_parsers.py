import struct
import unittest
from unittest.mock import patch
import uuid


from probe_support import (
    base_record,
    copy_record,
    make_gpt_layout_buffer,
    make_mbr_layout_buffer,
    make_storage_descriptor,
    make_vpd83_buffer,
    probe,
)


class StorageDescriptorTests(unittest.TestCase):
    def test_query_storage_descriptor_parses_offsets_and_bus_type(self):
        data = make_storage_descriptor(
            vendor=b"ACME",
            product=b"USB DRIVE",
            revision=b"2.10",
            serial=b"SERIAL123",
            bus_type=probe.BusTypeUsb,
            removable=True,
        )
        with patch.object(probe, "ioctl", return_value=(data, None)):
            result, error = probe.query_storage_descriptor(object())

        self.assertIsNone(error)
        self.assertEqual(result["vendor"], "ACME")
        self.assertEqual(result["product"], "USB DRIVE")
        self.assertEqual(result["revision"], "2.10")
        self.assertEqual(result["serial"], "SERIAL123")
        self.assertEqual(result["bus_type"], probe.BusTypeUsb)
        self.assertEqual(result["bus_name"], "USB")
        self.assertTrue(result["removable_media"])

    def test_query_storage_descriptor_handles_out_of_range_serial_offset(self):
        data = make_storage_descriptor(serial_off=4096)
        with patch.object(probe, "ioctl", return_value=(data, None)):
            result, error = probe.query_storage_descriptor(object())

        self.assertIsNone(error)
        self.assertIsNone(result["serial"])

    def test_query_storage_descriptor_returns_error_for_short_buffer(self):
        with patch.object(probe, "ioctl", return_value=(b"\x00" * 35, None)):
            result, error = probe.query_storage_descriptor(object())

        self.assertIsNone(result)
        self.assertIn("short STORAGE_DEVICE_DESCRIPTOR", error)

    def test_query_storage_descriptor_handles_missing_serial(self):
        data = make_storage_descriptor(serial=b"", serial_off=0)
        with patch.object(probe, "ioctl", return_value=(data, None)):
            result, error = probe.query_storage_descriptor(object())

        self.assertIsNone(error)
        self.assertIsNone(result["serial"])


class Vpd83ParserTests(unittest.TestCase):
    def test_query_vpd83_identifiers_parses_ascii_and_binary_values(self):
        data = make_vpd83_buffer([
            (1, 3, 0, b"SN1234"),
            (1, 3, 1, b"\x00\x01\xfe\xff", 0),
        ])
        with patch.object(probe, "ioctl", return_value=(data, None)):
            identifiers, error = probe.query_vpd83_identifiers(object())

        self.assertIsNone(error)
        self.assertEqual(len(identifiers), 2)
        self.assertEqual(identifiers[0]["value_ascii"], "SN1234")
        self.assertEqual(identifiers[0]["value_hex"], "534e31323334")
        self.assertIsNone(identifiers[1]["value_ascii"])
        self.assertEqual(identifiers[1]["value_hex"], "0001feff")

    def test_query_vpd83_identifiers_stops_on_zero_next_offset(self):
        data = make_vpd83_buffer([
            (1, 3, 0, b"FIRST", 0),
            (1, 3, 1, b"SECOND"),
        ])
        with patch.object(probe, "ioctl", return_value=(data, None)):
            identifiers, error = probe.query_vpd83_identifiers(object())

        self.assertIsNone(error)
        self.assertEqual(len(identifiers), 1)
        self.assertEqual(identifiers[0]["value_ascii"], "FIRST")

    def test_query_vpd83_identifiers_handles_small_next_offset_safely(self):
        data = make_vpd83_buffer([
            (1, 3, 0, b"ONE", 8),
            (1, 3, 0, b"TWO"),
        ])
        with patch.object(probe, "ioctl", return_value=(data, None)):
            identifiers, error = probe.query_vpd83_identifiers(object())

        self.assertIsNone(error)
        self.assertEqual(len(identifiers), 1)
        self.assertEqual(identifiers[0]["value_ascii"], "ONE")

    def test_query_vpd83_identifiers_limits_identifier_to_buffer(self):
        payload = bytearray(make_vpd83_buffer([(1, 3, 0, b"ABCD")]))
        struct.pack_into("<III", payload, 0, 1, len(payload), 5)
        struct.pack_into("<H", payload, 12 + 8, 32)
        with patch.object(probe, "ioctl", return_value=(bytes(payload), None)):
            identifiers, error = probe.query_vpd83_identifiers(object())

        self.assertIsNone(error)
        self.assertEqual(len(identifiers), 1)
        self.assertEqual(identifiers[0]["value_hex"], "41424344")

    def test_query_vpd83_identifiers_returns_short_buffer_error(self):
        with patch.object(probe, "ioctl", return_value=(b"\x00" * 11, None)):
            identifiers, error = probe.query_vpd83_identifiers(object())

        self.assertEqual(identifiers, [])
        self.assertIn("short STORAGE_DEVICE_ID_DESCRIPTOR", error)

    def test_error_status_classifies_invalid_parameter_for_vpd83(self):
        self.assertEqual(
            probe.error_status(probe.ERROR_INVALID_PARAMETER),
            "unsupported_or_invalid",
        )


class PartitionLayoutTests(unittest.TestCase):
    def test_query_drive_layout_parses_mbr_entries(self):
        data = make_mbr_layout_buffer([
            {
                "start": 4096,
                "length": 8192,
                "number": 2,
                "type": 7,
                "boot": True,
                "recognized": True,
                "hidden_sectors": 64,
                "partition_id": bytes.fromhex("11223344556677889900aabbccddeeff"),
            },
            {
                "start": 0,
                "length": 0,
                "number": 1,
                "type": 0,
                "partition_id": bytes.fromhex("ffeeddccbbaa00998877665544332211"),
            },
        ])
        with patch.object(probe, "ioctl", return_value=(data, None)):
            result, error = probe.query_drive_layout(object())

        self.assertIsNone(error)
        self.assertEqual(result["partition_style_name"], "MBR")
        self.assertEqual(result["mbr_signature"], "A1B2C3D4")
        self.assertEqual(result["partition_count"], 2)
        self.assertEqual(result["partitions"][0]["number"], 2)
        self.assertEqual(result["partitions"][0]["offset"], 4096)
        self.assertEqual(result["partitions"][0]["length"], 8192)
        self.assertTrue(result["partitions"][0]["boot_indicator"])
        self.assertTrue(result["partitions"][0]["recognized_partition"])
        self.assertEqual(result["partitions"][0]["hidden_sectors"], 64)
        self.assertFalse(result["partitions"][0]["is_unused"])
        self.assertTrue(result["partitions"][1]["is_unused"])

    def test_query_drive_layout_returns_error_for_short_buffer(self):
        with patch.object(probe, "ioctl", return_value=(b"\x00" * 15, None)):
            result, error = probe.query_drive_layout(object())

        self.assertIsNone(result)
        self.assertIn("short DRIVE_LAYOUT_INFORMATION_EX", error)

    def test_query_drive_layout_rejects_unreasonable_partition_count(self):
        data = bytearray(make_mbr_layout_buffer([]))
        struct.pack_into("<I", data, 4, 4096)
        with patch.object(probe, "ioctl", return_value=(bytes(data), None)):
            result, error = probe.query_drive_layout(object())

        self.assertIsNone(result)
        self.assertIn("unreasonable partition count", error)

    def test_query_drive_layout_parses_gpt_entries(self):
        data = make_gpt_layout_buffer([
            {
                "number": 7,
                "start": 2048,
                "length": 4096,
                "partition_type": uuid.UUID("e3c9e316-0b5c-4db8-817d-f92df00215ae"),
                "partition_guid": uuid.UUID("12345678-1234-1234-1234-1234567890ab"),
                "attributes": 0x1234,
                "name": "DATA",
            },
            {
                "number": 8,
                "start": 6144,
                "length": 0,
                "partition_type": uuid.UUID(int=0),
                "partition_guid": uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                "attributes": 0,
                "name": "",
            },
        ])
        with patch.object(probe, "ioctl", return_value=(data, None)):
            result, error = probe.query_drive_layout(object())

        self.assertIsNone(error)
        self.assertEqual(result["partition_style_name"], "GPT")
        self.assertEqual(result["gpt_disk_guid"], "12345678-1234-5678-1234-567812345678")
        self.assertEqual(result["starting_usable_offset"], 0x1000)
        self.assertEqual(result["usable_length"], 0x2000)
        self.assertEqual(result["max_partition_count"], 128)
        self.assertEqual(result["partitions"][0]["partition_type_guid"], "e3c9e316-0b5c-4db8-817d-f92df00215ae")
        self.assertEqual(result["partitions"][0]["partition_guid"], "12345678-1234-1234-1234-1234567890ab")
        self.assertEqual(result["partitions"][0]["attributes"], 0x1234)
        self.assertEqual(result["partitions"][0]["name"], "DATA")
        self.assertFalse(result["partitions"][0]["is_unused"])
        self.assertTrue(result["partitions"][1]["is_unused"])


class UsbEvidenceTests(unittest.TestCase):
    def test_usb_evidence_prefers_actual_usb_node(self):
        nodes = [
            {
                "device_instance_id": "USBSTOR\\DISK&VEN_FLASH&PROD_PROBE",
            },
            {
                "device_instance_id": "USB\\VID_1234&PID_5678\\AB&CD",
            },
            {
                "device_instance_id": "USB\\ROOT_HUB30\\0000",
            },
        ]
        evidence = probe.usb_evidence_from_chain(nodes)
        self.assertEqual(evidence["vid"], "1234")
        self.assertEqual(evidence["pid"], "5678")
        self.assertEqual(evidence["serial_candidate"]["value"], "AB&CD")
        self.assertTrue(evidence["serial_candidate"]["likely_port_specific"])

    def test_usb_evidence_returns_none_without_usb_node(self):
        self.assertIsNone(probe.usb_evidence_from_chain([
            {"device_instance_id": "PCI\\VEN_8086&DEV_1234"},
            {"device_instance_id": "ACPI\\PNP0A08"},
        ]))

    def test_hardware_and_compatible_ids_are_sorted_in_pnp_observation(self):
        record = copy_record(base_record())
        record["pnp"]["nodes"][0]["hardware_ids"] = ["B", "A"]
        record["pnp"]["nodes"][0]["compatible_ids"] = ["Y", "X"]
        record["pnp"]["nodes"][1]["hardware_ids"] = ["D", "C"]
        record["pnp"]["nodes"][1]["compatible_ids"] = ["Q", "P"]

        evidence = probe.pnp_observation_evidence(record)
        self.assertEqual(evidence["pnp_device_nodes"][0]["hardware_ids"], ["A", "B"])
        self.assertEqual(evidence["pnp_device_nodes"][0]["compatible_ids"], ["X", "Y"])
        self.assertEqual(evidence["pnp_device_nodes"][1]["hardware_ids"], ["C", "D"])
        self.assertEqual(evidence["pnp_device_nodes"][1]["compatible_ids"], ["P", "Q"])


if __name__ == "__main__":
    unittest.main()
