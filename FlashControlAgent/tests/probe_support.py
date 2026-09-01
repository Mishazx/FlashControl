import copy
import os
import sys
import struct
import unittest
import uuid


if os.name != "nt":
    raise unittest.SkipTest("Windows-only probe module")


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


from FlashControlAgent import main as probe


def copy_record(value):
    return copy.deepcopy(value)


def make_storage_descriptor(
    vendor=b"VENDOR",
    product=b"PRODUCT",
    revision=b"1.00",
    serial=b"SER123",
    bus_type=None,
    removable=True,
    size=128,
    vendor_off=36,
    product_off=48,
    revision_off=64,
    serial_off=80,
):
    if bus_type is None:
        bus_type = probe.BusTypeUsb

    data = bytearray(size)
    struct.pack_into("<II", data, 0, 1, size)
    data[8] = 0x01
    data[9] = 0x02
    data[10] = 1 if removable else 0
    data[11] = 0
    struct.pack_into(
        "<IIII",
        data,
        12,
        vendor_off,
        product_off,
        revision_off,
        serial_off,
    )
    struct.pack_into("<II", data, 28, bus_type, 0x1234)

    for offset, payload in (
        (vendor_off, vendor),
        (product_off, product),
        (revision_off, revision),
        (serial_off, serial),
    ):
        if offset and offset < len(data):
            data[offset:offset + len(payload)] = payload + b"\x00"

    return bytes(data)


def make_vpd83_buffer(identifiers):
    parts = []
    for index, item in enumerate(identifiers):
        code_set, ident_type, association, value = item[:4]
        next_offset = item[4] if len(item) > 4 else 16 + len(value)
        parts.append(
            struct.pack("<IIHHI", code_set, ident_type, len(value), next_offset, association) +
            value
        )
    payload = b"".join(parts)
    return struct.pack("<III", 1, 12 + len(payload), len(identifiers)) + payload


def make_mbr_layout_buffer(entries, signature=0xA1B2C3D4, checksum=0x01020304):
    entry_size = 144
    data = bytearray(48 + (entry_size * len(entries)))
    struct.pack_into("<II", data, 0, probe.PARTITION_STYLE_MBR, len(entries))
    struct.pack_into("<II", data, 8, signature, checksum)

    for index, entry in enumerate(entries):
        offset = 48 + (index * entry_size)
        struct.pack_into("<I", data, offset, entry.get("style", probe.PARTITION_STYLE_MBR))
        struct.pack_into("<q", data, offset + 8, entry.get("start", 0))
        struct.pack_into("<q", data, offset + 16, entry.get("length", 0))
        struct.pack_into("<I", data, offset + 24, entry.get("number", index + 1))
        data[offset + 28] = 1 if entry.get("rewrite", False) else 0
        data[offset + 29] = 1 if entry.get("service", False) else 0
        data[offset + 32] = entry.get("type", 0)
        data[offset + 33] = 1 if entry.get("boot", False) else 0
        data[offset + 34] = 1 if entry.get("recognized", False) else 0
        struct.pack_into("<I", data, offset + 36, entry.get("hidden_sectors", 0))
        partition_id = entry.get("partition_id", uuid.UUID(int=0).bytes_le)
        data[offset + 40:offset + 56] = partition_id

    return bytes(data)


def make_gpt_layout_buffer(entries, disk_guid=None, usable_offset=0x1000, usable_length=0x2000, max_count=128):
    entry_size = 144
    data = bytearray(48 + (entry_size * len(entries)))
    struct.pack_into("<II", data, 0, probe.PARTITION_STYLE_GPT, len(entries))
    disk_guid = disk_guid or uuid.UUID("12345678-1234-5678-1234-567812345678")
    data[8:24] = disk_guid.bytes_le
    struct.pack_into("<q", data, 24, usable_offset)
    struct.pack_into("<q", data, 32, usable_length)
    struct.pack_into("<I", data, 40, max_count)

    for index, entry in enumerate(entries):
        offset = 48 + (index * entry_size)
        struct.pack_into("<I", data, offset, entry.get("style", probe.PARTITION_STYLE_GPT))
        struct.pack_into("<q", data, offset + 8, entry.get("start", 0))
        struct.pack_into("<q", data, offset + 16, entry.get("length", 0))
        struct.pack_into("<I", data, offset + 24, entry.get("number", index + 1))
        data[offset + 28] = 1 if entry.get("rewrite", False) else 0
        data[offset + 29] = 1 if entry.get("service", False) else 0
        partition_type = entry.get("partition_type", uuid.UUID(int=0))
        partition_guid = entry.get("partition_guid", uuid.UUID(int=0))
        data[offset + 32:offset + 48] = partition_type.bytes_le
        data[offset + 48:offset + 64] = partition_guid.bytes_le
        struct.pack_into("<Q", data, offset + 64, entry.get("attributes", 0))
        name = entry.get("name", "")
        data[offset + 72:offset + 144] = name.encode("utf-16-le")[:72].ljust(72, b"\x00")

    return bytes(data)


def base_record():
    return {
        "physical_drive": 7,
        "path": r"\\.\PhysicalDrive7",
        "storage": {
            "vendor": "FlashCo",
            "product": "Probe",
            "revision": "1.0",
            "serial": "STOR123",
            "bus_type": probe.BusTypeUsb,
            "removable_media": True,
        },
        "geometry": {
            "size_bytes": 64 * 1024 * 1024,
            "bytes_per_sector": 512,
        },
        "layout": {
            "partition_style_name": "MBR",
            "mbr_signature": "A1B2C3D4",
            "gpt_disk_guid": None,
            "partitions": [
                {
                    "entry_index": 1,
                    "partition_style_name": "MBR",
                    "number": 2,
                    "offset": 4096,
                    "length": 8192,
                    "mbr_type": 7,
                    "boot_indicator": False,
                    "recognized_partition": True,
                    "hidden_sectors": 32,
                    "partition_id": "00000000-0000-0000-0000-000000000002",
                    "is_unused": False,
                },
                {
                    "entry_index": 0,
                    "partition_style_name": "MBR",
                    "number": 1,
                    "offset": 0,
                    "length": 0,
                    "mbr_type": 0,
                    "boot_indicator": False,
                    "recognized_partition": False,
                    "hidden_sectors": 0,
                    "partition_id": "00000000-0000-0000-0000-000000000001",
                    "is_unused": True,
                },
            ],
        },
        "volumes": [
            {
                "volume_guid": r"\\?\Volume{11111111-1111-1111-1111-111111111111}\\",
                "drive_letters": ["D:"],
                "mount_paths": ["D:\\"],
                "partition_number": 2,
                "filesystem": "exFAT",
                "volume_label": "FLASH",
                "volume_serial": "ABCD1234",
            },
            {
                "volume_guid": r"\\?\Volume{22222222-2222-2222-2222-222222222222}\\",
                "drive_letters": ["E:"],
                "mount_paths": ["E:\\"],
                "partition_number": 1,
                "filesystem": "NTFS",
                "volume_label": "BACKUP",
                "volume_serial": "EFGH5678",
            },
        ],
        "vpd83": [
            {
                "code_set": 1,
                "type": 3,
                "association": 0,
                "identifier_size": 4,
                "value_ascii": "ABCD",
                "value_hex": "41424344",
            },
            {
                "code_set": 1,
                "type": 3,
                "association": 1,
                "identifier_size": 4,
                "value_ascii": None,
                "value_hex": "31323334",
            },
        ],
        "pnp": {
            "usb": {
                "device_instance_id": "USB\\VID_1234&PID_5678\\ABCDEF",
                "vid": "1234",
                "pid": "5678",
                "serial_candidate": {
                    "value": "ABCDEF",
                    "source": "pnp_usb_instance_id",
                    "likely_port_specific": False,
                },
            },
            "nodes": [
                {
                    "device_instance_id": "USBSTOR\\DISK&VEN_FLASHCO&PROD_PROBE",
                    "hardware_ids": ["USBSTOR\\DISK&VEN_FLASHCO&PROD_PROBE"],
                    "compatible_ids": ["USBSTOR\\DISK", "GENERIC_DISK"],
                    "service": "disk",
                    "class": "DiskDrive",
                },
                {
                    "device_instance_id": "USB\\VID_1234&PID_5678\\ABCDEF",
                    "hardware_ids": ["USB\\VID_1234&PID_5678", "USB\\VID_1234"],
                    "compatible_ids": ["USB\\Class_08", "USB\\Class_08&SubClass_06"],
                    "service": "usbccgp",
                    "class": "USB",
                },
                {
                    "device_instance_id": "PCI\\VEN_8086&DEV_1234",
                    "hardware_ids": ["PCI\\VEN_8086&DEV_1234"],
                    "compatible_ids": ["PCI\\VEN_8086"],
                    "service": "pci",
                    "class": "System",
                },
            ],
        },
        "capabilities": {
            "storage_descriptor": True,
            "geometry": True,
            "partition_layout": True,
            "volume_information": True,
            "pnp_tree": True,
            "vpd80": False,
            "vpd83": True,
        },
        "capability_status": {
            "storage_descriptor": "available",
            "geometry": "available",
            "partition_layout": "available",
            "volume_information": "available",
            "vpd80": "not_implemented",
            "vpd83": "available",
            "pnp_tree": "available",
        },
        "collector_errors": {
            "geometry": None,
            "partition_layout": None,
            "vpd83": None,
        },
    }
