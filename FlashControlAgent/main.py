# -*- coding: utf-8 -*-
"""
usb_probe_poc.py

PoC для инвентаризации USB-накопителей и физдисков в Windows.

Цели:
- без сторонних зависимостей
- исходник совместим с Python 3.4+
- опрашивать физические диски через Win32 DeviceIoControl
- собирать дескриптор хранилища, VPD page 0x83, геометрию,
  разметку диска, тома, IP-адреса, залогиненных пользователей
  и локальных пользователей
- печатать JSON, удобный для сравнения нескольких флешек

Это исследовательский/диагностический зонд, а не production-агент.
"""

from __future__ import print_function

import ctypes
from ctypes import wintypes
import datetime
import hashlib
import json
import os
import platform
import socket
import struct
import sys
import uuid


# ---- Константы Win32 ---------------------------------------------------------

GENERIC_READ = 0x80000000

FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3

FILE_DEVICE_MASS_STORAGE = 0x0000002D
FILE_DEVICE_DISK = 0x00000007
METHOD_BUFFERED = 0
FILE_ANY_ACCESS = 0

StorageDeviceProperty = 0
StorageDeviceIdProperty = 2
PropertyStandardQuery = 0

BusTypeUsb = 7

PARTITION_STYLE_MBR = 0
PARTITION_STYLE_GPT = 1
PARTITION_STYLE_RAW = 2

ERROR_MORE_DATA = 234
NERR_Success = 0


def ctl_code(device_type, function, method=METHOD_BUFFERED, access=FILE_ANY_ACCESS):
    return (device_type << 16) | (access << 14) | (function << 2) | method


IOCTL_STORAGE_QUERY_PROPERTY = ctl_code(FILE_DEVICE_MASS_STORAGE, 0x0500)
IOCTL_STORAGE_GET_DEVICE_NUMBER = ctl_code(FILE_DEVICE_MASS_STORAGE, 0x0420)
IOCTL_DISK_GET_DRIVE_LAYOUT_EX = ctl_code(FILE_DEVICE_DISK, 0x0014)
IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = ctl_code(FILE_DEVICE_DISK, 0x0028)


# ---- Настройка kernel32 ------------------------------------------------------

if os.name != "nt":
    sys.stderr.write("This probe must be run on Windows.\n")
    sys.exit(2)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
netapi32 = ctypes.WinDLL("netapi32", use_last_error=True)

CreateFileW = kernel32.CreateFileW
CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
CreateFileW.restype = wintypes.HANDLE

DeviceIoControl = kernel32.DeviceIoControl
DeviceIoControl.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
DeviceIoControl.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

GetLogicalDrives = kernel32.GetLogicalDrives
GetLogicalDrives.argtypes = []
GetLogicalDrives.restype = wintypes.DWORD

GetVolumeInformationW = kernel32.GetVolumeInformationW
GetVolumeInformationW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPWSTR,
    wintypes.DWORD,
]
GetVolumeInformationW.restype = wintypes.BOOL

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class WTS_SESSION_INFO(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("pWinStationName", wintypes.LPWSTR),
        ("State", wintypes.DWORD),
    ]


WTSEnumerateSessionsW = wtsapi32.WTSEnumerateSessionsW
WTSEnumerateSessionsW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.POINTER(WTS_SESSION_INFO)),
    ctypes.POINTER(wintypes.DWORD),
]
WTSEnumerateSessionsW.restype = wintypes.BOOL

WTSQuerySessionInformationW = wtsapi32.WTSQuerySessionInformationW
WTSQuerySessionInformationW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.LPVOID),
    ctypes.POINTER(wintypes.DWORD),
]
WTSQuerySessionInformationW.restype = wintypes.BOOL

WTSFreeMemory = wtsapi32.WTSFreeMemory
WTSFreeMemory.argtypes = [wintypes.LPVOID]
WTSFreeMemory.restype = None

WTS_CURRENT_SERVER_HANDLE = wintypes.HANDLE(0)
WTSUserName = 5
WTSDomainName = 7


class USER_INFO_0(ctypes.Structure):
    _fields_ = [("usri0_name", wintypes.LPWSTR)]


NetUserEnum = netapi32.NetUserEnum
NetUserEnum.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.LPVOID),
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
]
NetUserEnum.restype = wintypes.DWORD

NetApiBufferFree = netapi32.NetApiBufferFree
NetApiBufferFree.argtypes = [wintypes.LPVOID]
NetApiBufferFree.restype = wintypes.DWORD

NetGetJoinInformation = netapi32.NetGetJoinInformation
NetGetJoinInformation.argtypes = [
    wintypes.LPCWSTR,
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(wintypes.DWORD),
]
NetGetJoinInformation.restype = wintypes.DWORD

NetApiBufferFree = netapi32.NetApiBufferFree
NetApiBufferFree.argtypes = [wintypes.LPVOID]
NetApiBufferFree.restype = wintypes.DWORD

NetSetupUnknownStatus = 0
NetSetupUnjoined = 1
NetSetupWorkgroupName = 2
NetSetupDomainName = 3


# ---- Вспомогательные функции -------------------------------------------------

def utc_now_iso():
    # Не используем datetime.timezone для максимальной совместимости со старыми версиями Python.
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def clean_ascii(raw):
    if raw is None:
        return None
    if not isinstance(raw, bytearray):
        raw = bytearray(raw)
    raw = bytes(raw).split(b"\x00", 1)[0]
    try:
        text = raw.decode("ascii", "replace")
    except Exception:
        text = repr(raw)
    return text.strip() or None


def c_string_at_offset(buf, offset):
    if not offset:
        return None
    if offset < 0 or offset >= len(buf):
        return None
    end = buf.find(b"\x00", offset)
    if end < 0:
        end = len(buf)
    return clean_ascii(buf[offset:end])


def win_error():
    err = ctypes.get_last_error()
    if not err:
        return "unknown Win32 error"
    try:
        return ctypes.FormatError(err).strip()
    except Exception:
        return "Win32 error %d" % err


def unique_sorted(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return sorted(result)


def stable_hash(parts):
    normalized = "|".join("" if value is None else str(value).strip().upper() for value in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def query_wts_string(session_id, info_class):
    buffer = wintypes.LPVOID()
    bytes_returned = wintypes.DWORD(0)
    ok = WTSQuerySessionInformationW(
        WTS_CURRENT_SERVER_HANDLE,
        session_id,
        info_class,
        ctypes.byref(buffer),
        ctypes.byref(bytes_returned),
    )
    if not ok or not buffer:
        return None
    try:
        return ctypes.wstring_at(buffer).strip() or None
    finally:
        WTSFreeMemory(buffer)


def enumerate_logged_in_users():
    sessions = ctypes.POINTER(WTS_SESSION_INFO)()
    count = wintypes.DWORD(0)
    users = []

    ok = WTSEnumerateSessionsW(
        WTS_CURRENT_SERVER_HANDLE,
        0,
        1,
        ctypes.byref(sessions),
        ctypes.byref(count),
    )
    if not ok:
        return users

    try:
        for index in range(count.value):
            session = sessions[index]
            username = query_wts_string(session.SessionId, WTSUserName)
            if not username:
                continue
            domain = query_wts_string(session.SessionId, WTSDomainName)
            if domain:
                users.append("%s\\%s" % (domain, username))
            else:
                users.append(username)
    finally:
        WTSFreeMemory(sessions)

    return unique_sorted(users)


def enumerate_local_users():
    buffer = wintypes.LPVOID()
    entries_read = wintypes.DWORD(0)
    total_entries = wintypes.DWORD(0)
    resume_handle = wintypes.DWORD(0)
    users = []

    while True:
        status = NetUserEnum(
            None,
            0,
            0,
            ctypes.byref(buffer),
            0xFFFFFFFF,
            ctypes.byref(entries_read),
            ctypes.byref(total_entries),
            ctypes.byref(resume_handle),
        )

        if status not in (NERR_Success, ERROR_MORE_DATA):
            break

        if buffer and entries_read.value:
            array_type = USER_INFO_0 * entries_read.value
            entries = ctypes.cast(buffer, ctypes.POINTER(array_type)).contents
            for index in range(entries_read.value):
                name = entries[index].usri0_name
                if name:
                    users.append(name)

        if buffer:
            NetApiBufferFree(buffer)
            buffer = wintypes.LPVOID()

        if status != ERROR_MORE_DATA:
            break

    return unique_sorted(users)


def enumerate_ip_addresses():
    addresses = []

    try:
        hostname = socket.gethostname()
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            if family == socket.AF_INET:
                addresses.append(sockaddr[0])
            elif family == socket.AF_INET6:
                addresses.append(sockaddr[0].split("%", 1)[0])
    except Exception:
        pass

    for target in ("1.1.1.1", "8.8.8.8"):
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target, 80))
            addresses.append(s.getsockname()[0])
        except Exception:
            pass
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

    return unique_sorted(addresses)


def query_domain_membership():
    name_buffer = wintypes.LPWSTR()
    status = wintypes.DWORD(0)
    result = {
        "is_domain_joined": None,
        "domain_name": None,
        "workgroup_name": None,
        "join_status": None,
    }

    code = NetGetJoinInformation(None, ctypes.byref(name_buffer), ctypes.byref(status))
    if code != NERR_Success:
        return result

    try:
        name = name_buffer.value.strip() if name_buffer and name_buffer.value else None
        join_status = status.value
        result["join_status"] = join_status
        result["is_domain_joined"] = join_status == NetSetupDomainName

        if join_status == NetSetupDomainName:
            result["domain_name"] = name
        elif join_status == NetSetupWorkgroupName:
            result["workgroup_name"] = name
    finally:
        if name_buffer:
            NetApiBufferFree(name_buffer)

    return result


def open_disk(number):
    path = r"\\.\PhysicalDrive%d" % number

    # DesiredAccess=0 достаточно для большинства IOCTL с метаданными и снижает
    # требования к привилегиям. Если на какой-то машине или драйвере не сработает,
    # запусти от администратора.
    handle = CreateFileW(
        path,
        0,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        return None, path, win_error()
    return handle, path, None


def open_volume_letter(letter):
    path = r"\\.\%s:" % letter
    handle = CreateFileW(
        path,
        0,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        return None, path, win_error()
    return handle, path, None


def ioctl(handle, code, in_bytes=None, out_size=4096):
    if in_bytes is None:
        in_bytes = b""

    in_buf = ctypes.create_string_buffer(in_bytes, max(1, len(in_bytes)))
    out_buf = ctypes.create_string_buffer(out_size)
    returned = wintypes.DWORD(0)

    ok = DeviceIoControl(
        handle,
        code,
        ctypes.cast(in_buf, wintypes.LPVOID),
        len(in_bytes),
        ctypes.cast(out_buf, wintypes.LPVOID),
        out_size,
        ctypes.byref(returned),
        None,
    )

    if not ok:
        return None, win_error()

    return out_buf.raw[:returned.value], None


# ---- Сбор данных -------------------------------------------------------------

def query_storage_descriptor(handle):
    # STORAGE_PROPERTY_QUERY:
    # DWORD PropertyId
    # DWORD QueryType
    # BYTE  AdditionalParameters[1]
    # Используем 12 байт, чтобы совпасть с выравниванием структур в Windows.
    query = struct.pack("<II", StorageDeviceProperty, PropertyStandardQuery) + b"\x00\x00\x00\x00"

    data, err = ioctl(handle, IOCTL_STORAGE_QUERY_PROPERTY, query, 8192)
    if data is None:
        return None, err

    # Фиксированный заголовок STORAGE_DEVICE_DESCRIPTOR:
    # DWORD Version
    # DWORD Size
    # BYTE DeviceType
    # BYTE DeviceTypeModifier
    # BOOLEAN RemovableMedia
    # BOOLEAN CommandQueueing
    # DWORD VendorIdOffset
    # DWORD ProductIdOffset
    # DWORD ProductRevisionOffset
    # DWORD SerialNumberOffset
    # STORAGE_BUS_TYPE BusType (DWORD)
    # DWORD RawPropertiesLength
    if len(data) < 36:
        return None, "short STORAGE_DEVICE_DESCRIPTOR (%d bytes)" % len(data)

    version, size = struct.unpack_from("<II", data, 0)
    device_type = data[8] if isinstance(data[8], int) else ord(data[8])
    device_type_modifier = data[9] if isinstance(data[9], int) else ord(data[9])
    removable = bool(data[10] if isinstance(data[10], int) else ord(data[10]))
    command_queueing = bool(data[11] if isinstance(data[11], int) else ord(data[11]))

    vendor_off, product_off, revision_off, serial_off = struct.unpack_from("<IIII", data, 12)
    bus_type, raw_len = struct.unpack_from("<II", data, 28)

    result = {
        "descriptor_version": version,
        "descriptor_size": size,
        "device_type": device_type,
        "device_type_modifier": device_type_modifier,
        "removable_media": removable,
        "command_queueing": command_queueing,
        "vendor": c_string_at_offset(data, vendor_off),
        "product": c_string_at_offset(data, product_off),
        "revision": c_string_at_offset(data, revision_off),
        "serial": c_string_at_offset(data, serial_off),
        "bus_type": bus_type,
        "bus_name": "USB" if bus_type == BusTypeUsb else str(bus_type),
        "raw_properties_length": raw_len,
    }

    return result, None


def query_storage_device_number(handle):
    data, err = ioctl(handle, IOCTL_STORAGE_GET_DEVICE_NUMBER, None, 64)
    if data is None:
        return None, err
    if len(data) < 12:
        return None, "short STORAGE_DEVICE_NUMBER (%d bytes)" % len(data)

    device_type, device_number, partition_number = struct.unpack_from("<III", data, 0)
    return {
        "device_type": device_type,
        "device_number": device_number,
        "partition_number": partition_number,
    }, None


def query_volume_information(root):
    label = ctypes.create_unicode_buffer(261)
    fs_name = ctypes.create_unicode_buffer(261)
    serial = wintypes.DWORD(0)
    max_component = wintypes.DWORD(0)
    fs_flags = wintypes.DWORD(0)

    ok = GetVolumeInformationW(
        root,
        label,
        len(label),
        ctypes.byref(serial),
        ctypes.byref(max_component),
        ctypes.byref(fs_flags),
        fs_name,
        len(fs_name),
    )
    if not ok:
        return None, win_error()

    return {
        "label": label.value or None,
        "filesystem": fs_name.value or None,
        "volume_serial": "%08X" % serial.value,
        "filesystem_flags": fs_flags.value,
        "max_component_length": max_component.value,
    }, None


def enumerate_volumes_by_physical_drive():
    result = {}
    mask = GetLogicalDrives()

    for i in range(26):
        if not (mask & (1 << i)):
            continue

        letter = chr(ord("A") + i)
        handle, _, _ = open_volume_letter(letter)
        if handle is None:
            continue

        try:
            devnum, _ = query_storage_device_number(handle)
        finally:
            CloseHandle(handle)

        if devnum is None:
            continue

        root = "%s:\\" % letter
        vol, vol_err = query_volume_information(root)

        item = {
            "drive_letter": "%s:" % letter,
            "partition_number": devnum["partition_number"],
            "volume": vol,
            "error": vol_err,
        }
        result.setdefault(devnum["device_number"], []).append(item)

    return result


def query_vpd83_identifiers(handle):
    query = struct.pack("<II", StorageDeviceIdProperty, PropertyStandardQuery) + b"\x00\x00\x00\x00"
    data, err = ioctl(handle, IOCTL_STORAGE_QUERY_PROPERTY, query, 16384)
    if data is None:
        return [], err

    if len(data) < 12:
        return [], "short STORAGE_DEVICE_ID_DESCRIPTOR (%d bytes)" % len(data)

    version, size, count = struct.unpack_from("<III", data, 0)
    identifiers = []
    offset = 12

    # Фиксированная часть STORAGE_IDENTIFIER:
    # DWORD CodeSet
    # DWORD Type
    # USHORT IdentifierSize
    # USHORT NextOffset
    # DWORD Association
    # BYTE Identifier[1]
    for _ in range(min(count, 64)):
        if offset + 16 > len(data):
            break

        code_set, ident_type, ident_size, next_offset, association = struct.unpack_from(
            "<IIHHI", data, offset
        )

        start = offset + 16
        end = min(start + ident_size, len(data))
        raw_id = data[start:end]

        printable = None
        try:
            candidate = raw_id.decode("ascii", "strict").strip("\x00 ").strip()
            if candidate and all(31 < ord(ch) < 127 for ch in candidate):
                printable = candidate
        except Exception:
            pass

        identifiers.append({
            "code_set": code_set,
            "type": ident_type,
            "association": association,
            "identifier_size": ident_size,
            "value_ascii": printable,
            "value_hex": raw_id.hex() if hasattr(raw_id, "hex") else "".join("%02x" % (ch if isinstance(ch, int) else ord(ch)) for ch in raw_id),
        })

        if next_offset == 0:
            break
        if next_offset < 16:
            break
        offset += next_offset

    return identifiers, None


def query_geometry(handle):
    data, err = ioctl(handle, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, None, 1024)
    if data is None:
        return None, err

    if len(data) < 32:
        return None, "short DISK_GEOMETRY_EX (%d bytes)" % len(data)

    # DISK_GEOMETRY:
    # LARGE_INTEGER Cylinders @0
    # DWORD MediaType @8
    # DWORD TracksPerCylinder @12
    # DWORD SectorsPerTrack @16
    # DWORD BytesPerSector @20
    # LARGE_INTEGER DiskSize @24
    cylinders = struct.unpack_from("<q", data, 0)[0]
    media_type, tracks, sectors, bytes_per_sector = struct.unpack_from("<IIII", data, 8)
    disk_size = struct.unpack_from("<q", data, 24)[0]

    return {
        "size_bytes": disk_size,
        "bytes_per_sector": bytes_per_sector,
        "cylinders": cylinders,
        "tracks_per_cylinder": tracks,
        "sectors_per_track": sectors,
        "media_type": media_type,
    }, None


def query_drive_layout(handle):
    data, err = ioctl(handle, IOCTL_DISK_GET_DRIVE_LAYOUT_EX, None, 65536)
    if data is None:
        return None, err

    if len(data) < 16:
        return None, "short DRIVE_LAYOUT_INFORMATION_EX (%d bytes)" % len(data)

    style, partition_count = struct.unpack_from("<II", data, 0)

    result = {
        "partition_style": style,
        "partition_count": partition_count,
    }

    if style == PARTITION_STYLE_MBR:
        signature, checksum = struct.unpack_from("<II", data, 8)
        result["partition_style_name"] = "MBR"
        result["mbr_signature"] = "%08X" % signature
        result["mbr_checksum"] = "%08X" % checksum

    elif style == PARTITION_STYLE_GPT:
        # Объединение GPT начинается с офсета 8. GUID занимает первые 16 байт.
        guid_bytes = data[8:24]
        try:
            disk_guid = str(uuid.UUID(bytes_le=guid_bytes))
        except Exception:
            disk_guid = None

        result["partition_style_name"] = "GPT"
        result["gpt_disk_guid"] = disk_guid

        if len(data) >= 44:
            starting_usable = struct.unpack_from("<q", data, 24)[0]
            usable_length = struct.unpack_from("<q", data, 32)[0]
            max_partition_count = struct.unpack_from("<I", data, 40)[0]
            result["starting_usable_offset"] = starting_usable
            result["usable_length"] = usable_length
            result["max_partition_count"] = max_partition_count

    elif style == PARTITION_STYLE_RAW:
        result["partition_style_name"] = "RAW"
    else:
        result["partition_style_name"] = "UNKNOWN"

    return result, None


def hardware_evidence_hash(record):
    storage = record.get("storage") or {}
    geometry = record.get("geometry") or {}
    vpd83 = record.get("vpd83") or []

    parts = [
        storage.get("vendor"),
        storage.get("product"),
        storage.get("revision"),
        storage.get("serial"),
        storage.get("bus_type"),
        geometry.get("size_bytes"),
        geometry.get("bytes_per_sector"),
    ]

    for item in vpd83:
        parts.append(item.get("value_hex"))

    return stable_hash(parts)


def media_evidence_hash(record):
    layout = record.get("layout") or {}
    volumes = record.get("volumes") or []

    parts = [
        layout.get("partition_style_name"),
        layout.get("mbr_signature"),
        layout.get("gpt_disk_guid"),
        layout.get("partition_count"),
    ]

    for item in sorted(volumes, key=lambda x: x.get("drive_letter") or ""):
        volume = item.get("volume") or {}
        parts.extend([
            item.get("partition_number"),
            volume.get("filesystem"),
            volume.get("volume_serial"),
            volume.get("label"),
        ])

    return stable_hash(parts)


def candidate_evidence_hash(record):
    return stable_hash([
        hardware_evidence_hash(record),
        media_evidence_hash(record),
    ])


def scan_physical_disks(max_disks=64, include_non_usb=False):
    devices = []
    errors = []
    volumes_by_disk = enumerate_volumes_by_physical_drive()

    for number in range(max_disks):
        handle, path, open_err = open_disk(number)
        if handle is None:
            # ERROR_FILE_NOT_FOUND и некорректные номера дисков здесь ожидаемы.
            continue

        try:
            storage, storage_err = query_storage_descriptor(handle)
            if storage is None:
                errors.append({
                    "physical_drive": number,
                    "stage": "storage_descriptor",
                    "error": storage_err,
                })
                continue

            if storage.get("bus_type") != BusTypeUsb and not include_non_usb:
                continue

            geometry, geometry_err = query_geometry(handle)
            layout, layout_err = query_drive_layout(handle)
            vpd83, vpd_err = query_vpd83_identifiers(handle)

            record = {
                "physical_drive": number,
                "path": path,
                "storage": storage,
                "geometry": geometry,
                "layout": layout,
                "volumes": volumes_by_disk.get(number, []),
                "vpd83": vpd83,
                "capabilities": {
                    "storage_descriptor": storage is not None,
                    "geometry": geometry is not None,
                    "drive_layout": layout is not None,
                    "volume_information": bool(volumes_by_disk.get(number, [])),
                    "vpd83": vpd_err is None,
                },
                "collector_errors": {
                    "geometry": geometry_err,
                    "drive_layout": layout_err,
                    "vpd83": vpd_err,
                },
            }

            record["hardware_evidence_sha256"] = hardware_evidence_hash(record)
            record["media_evidence_sha256"] = media_evidence_hash(record)
            record["candidate_evidence_sha256"] = candidate_evidence_hash(record)
            devices.append(record)

        finally:
            CloseHandle(handle)

    return devices, errors


def host_info():
    win32 = platform.win32_ver()
    join_info = query_domain_membership()
    return {
        "hostname": socket.gethostname(),
        "computer_name": socket.gethostname(),
        "platform": platform.platform(),
        "windows_release": win32[0],
        "windows_version": win32[1],
        "windows_service_pack": win32[2],
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "is_domain_joined": join_info["is_domain_joined"],
        "domain_name": join_info["domain_name"],
        "workgroup_name": join_info["workgroup_name"],
        "join_status": join_info["join_status"],
        "ip_addresses": enumerate_ip_addresses(),
        "logged_in_users": enumerate_logged_in_users(),
        "local_users": enumerate_local_users(),
    }


def main():
    include_non_usb = "--all-disks" in sys.argv

    devices, errors = scan_physical_disks(
        max_disks=64,
        include_non_usb=include_non_usb,
    )

    result = {
        "schema_version": 1,
        "probe_version": "0.1.0",
        "observed_at_utc": utc_now_iso(),
        "host": host_info(),
        "devices": devices,
        "scan_errors": errors,
    }

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    try:
        print(text)
    except UnicodeEncodeError:
        # Старые консоли Windows могут не поддерживать UTF-8.
        sys.stdout.buffer.write(text.encode("utf-8", "replace"))
        sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
