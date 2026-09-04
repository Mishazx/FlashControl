# -*- coding: utf-8 -*-
"""
usb_probe_poc.py

PoC для инвентаризации USB-накопителей и физдисков в Windows.

Цели:
- без сторонних зависимостей
- исходник совместим с Python 3.4+
- опрашивать физические диски через Win32 DeviceIoControl
- собирать дескриптор хранилища, геометрию,
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
import time
import uuid

try:
    from FlashControlAgent.observation_payload import pack_observation_payload
except ImportError:
    from observation_payload import pack_observation_payload


SCHEMA_VERSION = 1
AGENT_VERSION = "1.0.0"
PROBE_VERSION = "1.0.0"


# ---- Константы Win32 ---------------------------------------------------------

FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3

FILE_DEVICE_MASS_STORAGE = 0x0000002D
FILE_DEVICE_DISK = 0x00000007
METHOD_BUFFERED = 0
FILE_ANY_ACCESS = 0

StorageDeviceProperty = 0
PropertyStandardQuery = 0

BusTypeUsb = 7

PARTITION_STYLE_MBR = 0
PARTITION_STYLE_GPT = 1
PARTITION_STYLE_RAW = 2

ERROR_MORE_DATA = 234
ERROR_INVALID_FUNCTION = 1
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_ACCESS_DENIED = 5
ERROR_NOT_SUPPORTED = 50
ERROR_INVALID_PARAMETER = 87
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
setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
cfgmgr32 = ctypes.WinDLL("cfgmgr32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def guid_from_string(value):
    raw = uuid.UUID(value).bytes_le
    result = GUID()
    result.Data1, result.Data2, result.Data3 = struct.unpack_from("<IHH", raw, 0)
    for index in range(8):
        result.Data4[index] = raw[8 + index]
    return result


GUID_DEVINTERFACE_DISK = guid_from_string("53f56307-b6bf-11d0-94f2-00a0c91efb8b")
DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010
ERROR_NO_MORE_ITEMS = 259
ERROR_NO_MORE_FILES = 18
CR_SUCCESS = 0

CM_DRP_DEVICEDESC = 0x00000001
CM_DRP_HARDWAREID = 0x00000002
CM_DRP_COMPATIBLEIDS = 0x00000003
CM_DRP_SERVICE = 0x00000005
CM_DRP_CLASS = 0x00000008
CM_DRP_MFG = 0x0000000C
CM_DRP_FRIENDLYNAME = 0x0000000D


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


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

FindFirstVolumeW = kernel32.FindFirstVolumeW
FindFirstVolumeW.argtypes = [wintypes.LPWSTR, wintypes.DWORD]
FindFirstVolumeW.restype = wintypes.HANDLE

FindNextVolumeW = kernel32.FindNextVolumeW
FindNextVolumeW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD]
FindNextVolumeW.restype = wintypes.BOOL

FindVolumeClose = kernel32.FindVolumeClose
FindVolumeClose.argtypes = [wintypes.HANDLE]
FindVolumeClose.restype = wintypes.BOOL

GetVolumePathNamesForVolumeNameW = kernel32.GetVolumePathNamesForVolumeNameW
GetVolumePathNamesForVolumeNameW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
GetVolumePathNamesForVolumeNameW.restype = wintypes.BOOL

LookupAccountNameW = advapi32.LookupAccountNameW
LookupAccountNameW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
]
LookupAccountNameW.restype = wintypes.BOOL

ConvertSidToStringSidW = advapi32.ConvertSidToStringSidW
ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
ConvertSidToStringSidW.restype = wintypes.BOOL

LocalFree = kernel32.LocalFree
LocalFree.argtypes = [wintypes.HANDLE]
LocalFree.restype = wintypes.HANDLE

WTSGetActiveConsoleSessionId = getattr(kernel32, "WTSGetActiveConsoleSessionId", None)
if WTSGetActiveConsoleSessionId is not None:
    WTSGetActiveConsoleSessionId.argtypes = []
    WTSGetActiveConsoleSessionId.restype = wintypes.DWORD

SetupDiGetClassDevsW = setupapi.SetupDiGetClassDevsW
SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD,
]
SetupDiGetClassDevsW.restype = wintypes.HANDLE

SetupDiEnumDeviceInterfaces = setupapi.SetupDiEnumDeviceInterfaces
SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(SP_DEVINFO_DATA),
    ctypes.POINTER(GUID),
    wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
]
SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL

SetupDiGetDeviceInterfaceDetailW = setupapi.SetupDiGetDeviceInterfaceDetailW
SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(SP_DEVINFO_DATA),
]
SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL

SetupDiDestroyDeviceInfoList = setupapi.SetupDiDestroyDeviceInfoList
SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

CM_Get_Parent = cfgmgr32.CM_Get_Parent
CM_Get_Parent.argtypes = [
    ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.ULONG,
]
CM_Get_Parent.restype = wintypes.DWORD

CM_Get_Device_IDW = cfgmgr32.CM_Get_Device_IDW
CM_Get_Device_IDW.argtypes = [
    wintypes.DWORD, wintypes.LPWSTR, wintypes.ULONG, wintypes.ULONG,
]
CM_Get_Device_IDW.restype = wintypes.DWORD

CM_Get_DevNode_Registry_PropertyW = cfgmgr32.CM_Get_DevNode_Registry_PropertyW
CM_Get_DevNode_Registry_PropertyW.argtypes = [
    wintypes.DWORD,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.ULONG),
    wintypes.ULONG,
]
CM_Get_DevNode_Registry_PropertyW.restype = wintypes.DWORD

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
WTSActive = 0

WTS_STATE_NAMES = {
    0: "Active",
    1: "Connected",
    2: "ConnectQuery",
    3: "Shadow",
    4: "Disconnected",
    5: "Idle",
    6: "Listen",
    7: "Reset",
    8: "Down",
    9: "Init",
}


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
    # timezone доступен в Python 3.2+, поэтому этот вариант
    # совместим с целевым Python 3.4 и не использует deprecated utcnow().
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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


def error_status(winerror):
    if winerror == ERROR_INVALID_FUNCTION:
        return "unsupported"
    if winerror in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
        return "not_found"
    if winerror == ERROR_ACCESS_DENIED:
        return "access_denied"
    if winerror == ERROR_NOT_SUPPORTED:
        return "unsupported"
    if winerror == ERROR_INVALID_PARAMETER:
        return "unsupported_or_invalid"
    return "collector_failed"


def structured_error(collector, message, winerror=None, status=None):
    return {
        "collector": collector,
        "winerror": winerror,
        "message": message,
        "status": status or error_status(winerror),
    }


def win_error(collector=None):
    err = ctypes.get_last_error()
    try:
        message = ctypes.FormatError(err).strip() if err else "unknown Win32 error"
    except Exception:
        message = "Win32 error %d" % err
    return structured_error(collector, message, err or None)


def normalize_collector_error(collector, error):
    if error is None:
        return None
    if isinstance(error, dict):
        result = dict(error)
        if not result.get("collector"):
            result["collector"] = collector
        return result
    return structured_error(collector, str(error), status="invalid_data")


def run_collector(collector, function, *args):
    try:
        data, error = function(*args)
        return data, normalize_collector_error(collector, error)
    except Exception as exc:
        return None, structured_error(
            collector,
            "%s: %s" % (exc.__class__.__name__, exc),
            status="collector_failed",
        )


def unique_sorted(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return sorted(result)


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


def lookup_account_sid(domain, username):
    account_name = "%s\\%s" % (domain, username) if domain else username
    sid_size = wintypes.DWORD(0)
    domain_size = wintypes.DWORD(0)
    sid_use = wintypes.DWORD(0)

    LookupAccountNameW(
        None,
        account_name,
        None,
        ctypes.byref(sid_size),
        None,
        ctypes.byref(domain_size),
        ctypes.byref(sid_use),
    )
    if not sid_size.value:
        return None, win_error("session_sid")

    sid_buffer = ctypes.create_string_buffer(sid_size.value)
    domain_buffer = ctypes.create_unicode_buffer(max(1, domain_size.value))
    ok = LookupAccountNameW(
        None,
        account_name,
        ctypes.cast(sid_buffer, wintypes.LPVOID),
        ctypes.byref(sid_size),
        domain_buffer,
        ctypes.byref(domain_size),
        ctypes.byref(sid_use),
    )
    if not ok:
        return None, win_error("session_sid")

    string_sid = wintypes.LPWSTR()
    ok = ConvertSidToStringSidW(
        ctypes.cast(sid_buffer, wintypes.LPVOID),
        ctypes.byref(string_sid),
    )
    if not ok:
        return None, win_error("session_sid")
    try:
        return string_sid.value, None
    finally:
        LocalFree(string_sid)


def enumerate_user_sessions():
    sessions = ctypes.POINTER(WTS_SESSION_INFO)()
    count = wintypes.DWORD(0)
    result = []
    ok = WTSEnumerateSessionsW(
        WTS_CURRENT_SERVER_HANDLE,
        0,
        1,
        ctypes.byref(sessions),
        ctypes.byref(count),
    )
    if not ok:
        return None, win_error("session_enumerator")

    try:
        for index in range(count.value):
            item = sessions[index]
            username = query_wts_string(item.SessionId, WTSUserName)
            if not username:
                continue
            domain = query_wts_string(item.SessionId, WTSDomainName)
            result.append({
                "session_id": item.SessionId,
                "username": username,
                "domain": domain,
                "state": WTS_STATE_NAMES.get(item.State, "Unknown"),
                "state_code": item.State,
                "station_name": item.pWinStationName or None,
            })
    finally:
        WTSFreeMemory(sessions)
    return result, None


def collect_active_session():
    sessions, sessions_error = run_collector(
        "session_enumerator",
        enumerate_user_sessions,
    )
    if not sessions:
        return {
            "session_id": None,
            "username": None,
            "domain": None,
            "sid": None,
            "state": None,
            "errors": {"enumeration": sessions_error, "sid": None},
        }

    console_session_id = 0xFFFFFFFF
    if WTSGetActiveConsoleSessionId is not None:
        console_session_id = WTSGetActiveConsoleSessionId()

    selected = None
    for session in sessions:
        if session["session_id"] == console_session_id and session["state_code"] == WTSActive:
            selected = session
            break
    if selected is None:
        for session in sessions:
            if session["state_code"] == WTSActive:
                selected = session
                break
    if selected is None:
        selected = sessions[0]

    sid, sid_error = lookup_account_sid(selected["domain"], selected["username"])
    result = dict(selected)
    result.pop("state_code", None)
    result["sid"] = sid
    result["errors"] = {"enumeration": sessions_error, "sid": sid_error}
    return result


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
            if buffer:
                NetApiBufferFree(buffer)
                buffer = wintypes.LPVOID()
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


def open_handle(path, access=0, collector=None):
    handle = CreateFileW(
        path,
        access,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        return None, win_error(collector)
    return handle, None


def open_disk(number):
    # DesiredAccess=0 достаточно для большинства IOCTL с метаданными и снижает
    # требования к привилегиям.
    path = r"\\.\PhysicalDrive%d" % number
    handle, error = open_handle(path)
    return handle, path, error


def open_device_path(path):
    return open_handle(path, collector="setupapi_disk_open")


def cm_device_id(devinst):
    buffer = ctypes.create_unicode_buffer(4096)
    result = CM_Get_Device_IDW(devinst, buffer, len(buffer), 0)
    if result != CR_SUCCESS:
        return None
    return buffer.value or None


def decode_registry_strings(raw):
    if not raw:
        return []
    text = raw.decode("utf-16-le", "replace").rstrip("\x00")
    return [value for value in text.split("\x00") if value]


def cm_registry_property(devinst, property_code, multiple=False):
    buffer = ctypes.create_string_buffer(65536)
    size = wintypes.ULONG(len(buffer))
    data_type = wintypes.ULONG(0)
    result = CM_Get_DevNode_Registry_PropertyW(
        devinst,
        property_code,
        ctypes.byref(data_type),
        ctypes.cast(buffer, wintypes.LPVOID),
        ctypes.byref(size),
        0,
    )
    if result != CR_SUCCESS:
        return [] if multiple else None
    values = decode_registry_strings(buffer.raw[:size.value])
    if multiple:
        return values
    return values[0] if values else None


def pnp_node(devinst):
    return {
        "device_instance_id": cm_device_id(devinst),
        "hardware_ids": cm_registry_property(devinst, CM_DRP_HARDWAREID, True),
        "compatible_ids": cm_registry_property(devinst, CM_DRP_COMPATIBLEIDS, True),
        "manufacturer": cm_registry_property(devinst, CM_DRP_MFG),
        "friendly_name": cm_registry_property(devinst, CM_DRP_FRIENDLYNAME),
        "service": cm_registry_property(devinst, CM_DRP_SERVICE),
        "class": cm_registry_property(devinst, CM_DRP_CLASS),
    }


def pnp_parent_chain(devinst, max_depth=8):
    nodes = []
    current = devinst
    for _ in range(max_depth):
        node = pnp_node(current)
        node["depth"] = len(nodes)
        nodes.append(node)
        instance_id = (node.get("device_instance_id") or "").upper()
        if instance_id.startswith("USB\\VID_"):
            break
        parent = wintypes.DWORD(0)
        if CM_Get_Parent(ctypes.byref(parent), current, 0) != CR_SUCCESS:
            break
        current = parent.value
    return nodes


def usb_evidence_from_chain(nodes):
    for node in nodes:
        instance_id = node.get("device_instance_id") or ""
        upper = instance_id.upper()
        if not upper.startswith("USB\\"):
            continue
        vid = None
        pid = None
        for part in upper.split("\\", 1)[0:1] + upper.split("\\")[1:2]:
            for token in part.split("&"):
                if token.startswith("VID_"):
                    vid = token[4:]
                elif token.startswith("PID_"):
                    pid = token[4:]
        serial_candidate = instance_id.rsplit("\\", 1)[-1] if "\\" in instance_id else None
        likely_port_specific = bool(serial_candidate and "&" in serial_candidate)
        return {
            "device_instance_id": instance_id,
            "vid": vid,
            "pid": pid,
            "serial_candidate": {
                "value": serial_candidate,
                "source": "pnp_usb_instance_id",
                "likely_port_specific": likely_port_specific,
            } if serial_candidate else None,
        }
    return None


def enumerate_setupapi_disks():
    by_number = {}
    info_set = SetupDiGetClassDevsW(
        ctypes.byref(GUID_DEVINTERFACE_DISK),
        None,
        None,
        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
    )
    if info_set == INVALID_HANDLE_VALUE:
        return None, win_error("setupapi_enumerator")

    try:
        index = 0
        while True:
            interface = SP_DEVICE_INTERFACE_DATA()
            interface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            ok = SetupDiEnumDeviceInterfaces(
                info_set,
                None,
                ctypes.byref(GUID_DEVINTERFACE_DISK),
                index,
                ctypes.byref(interface),
            )
            if not ok:
                error = ctypes.get_last_error()
                if error == ERROR_NO_MORE_ITEMS:
                    break
                return None, win_error("setupapi_enumerator")

            required = wintypes.DWORD(0)
            devinfo = SP_DEVINFO_DATA()
            devinfo.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            SetupDiGetDeviceInterfaceDetailW(
                info_set,
                ctypes.byref(interface),
                None,
                0,
                ctypes.byref(required),
                ctypes.byref(devinfo),
            )
            if not required.value:
                index += 1
                continue

            detail = ctypes.create_string_buffer(required.value)
            ctypes.cast(detail, ctypes.POINTER(wintypes.DWORD)).contents.value = (
                8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            )
            ok = SetupDiGetDeviceInterfaceDetailW(
                info_set,
                ctypes.byref(interface),
                ctypes.cast(detail, wintypes.LPVOID),
                required.value,
                ctypes.byref(required),
                ctypes.byref(devinfo),
            )
            if not ok:
                index += 1
                continue

            device_path = ctypes.wstring_at(ctypes.addressof(detail) + 4)
            handle, _ = open_device_path(device_path)
            if handle is not None:
                try:
                    device_number, _ = query_storage_device_number(handle)
                finally:
                    CloseHandle(handle)
                if device_number is not None:
                    chain = pnp_parent_chain(devinfo.DevInst)
                    by_number[device_number["device_number"]] = {
                        "device_interface_path": device_path,
                        "disk_instance_id": chain[0].get("device_instance_id") if chain else None,
                        "nodes": chain,
                        "usb": usb_evidence_from_chain(chain),
                    }
            index += 1
    finally:
        SetupDiDestroyDeviceInfoList(info_set)

    return by_number, None


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


def volume_mount_paths(volume_guid):
    size = 1024
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        required = wintypes.DWORD(0)
        ok = GetVolumePathNamesForVolumeNameW(
            volume_guid,
            buffer,
            size,
            ctypes.byref(required),
        )
        if ok:
            text = "".join(buffer[:required.value])
            return [value for value in text.split("\x00") if value], None
        error = ctypes.get_last_error()
        if error == ERROR_MORE_DATA and required.value > size:
            size = required.value
            continue
        return [], win_error("volume_mount_paths")


def open_volume_guid(volume_guid):
    # CreateFile expects the volume GUID path without its trailing backslash.
    path = volume_guid[:-1] if volume_guid.endswith("\\") else volume_guid
    return open_handle(path, collector="volume_open")


def enumerate_volumes_by_physical_drive():
    result = {}
    name_buffer = ctypes.create_unicode_buffer(1024)
    search_handle = FindFirstVolumeW(name_buffer, len(name_buffer))
    if search_handle == INVALID_HANDLE_VALUE:
        raise RuntimeError(win_error("volume_enumerator"))

    try:
        while True:
            volume_guid = name_buffer.value
            mount_paths, mount_error = volume_mount_paths(volume_guid)
            drive_letters = unique_sorted([
                path[:2]
                for path in mount_paths
                if len(path) >= 3 and path[1:3] == ":\\"
            ])

            handle, open_error = open_volume_guid(volume_guid)
            device_number = None
            device_number_error = None
            if handle is not None:
                try:
                    device_number, device_number_error = run_collector(
                        "volume_device_number",
                        query_storage_device_number,
                        handle,
                    )
                finally:
                    CloseHandle(handle)

            volume, volume_error = run_collector(
                "volume_information",
                query_volume_information,
                volume_guid,
            )

            if device_number is not None:
                item = {
                    "volume_guid": volume_guid,
                    "drive_letters": drive_letters,
                    "mount_paths": mount_paths,
                    "partition_number": device_number["partition_number"],
                    "filesystem": volume.get("filesystem") if volume else None,
                    "volume_label": volume.get("label") if volume else None,
                    "volume_serial": volume.get("volume_serial") if volume else None,
                    "errors": {
                        "mount_paths": mount_error,
                        "open": open_error,
                        "device_number": device_number_error,
                        "volume_information": volume_error,
                    },
                }
                result.setdefault(device_number["device_number"], []).append(item)

            ok = FindNextVolumeW(search_handle, name_buffer, len(name_buffer))
            if ok:
                continue
            error = ctypes.get_last_error()
            if error == ERROR_NO_MORE_FILES:
                break
            raise RuntimeError(win_error("volume_enumerator"))
    finally:
        FindVolumeClose(search_handle)

    return result


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
        "partitions": [],
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

    # DRIVE_LAYOUT_INFORMATION_EX contains a 40-byte MBR/GPT union after its
    # 8-byte header. PARTITION_INFORMATION_EX entries therefore start at 48.
    # Each entry is 144 bytes with the normal Windows packing used by winioctl.h.
    entry_offset = 48
    entry_size = 144
    required_size = entry_offset + (partition_count * entry_size)
    if partition_count > 1024:
        return None, "unreasonable partition count (%d)" % partition_count
    if partition_count and len(data) < required_size:
        return None, (
            "short DRIVE_LAYOUT_INFORMATION_EX for %d entries (%d of %d bytes)"
            % (partition_count, len(data), required_size)
        )

    for index in range(partition_count):
        offset = entry_offset + (index * entry_size)
        entry_style = struct.unpack_from("<I", data, offset)[0]
        starting_offset = struct.unpack_from("<q", data, offset + 8)[0]
        partition_length = struct.unpack_from("<q", data, offset + 16)[0]
        partition_number = struct.unpack_from("<I", data, offset + 24)[0]
        rewrite_partition = bool(data[offset + 28])
        service_partition = bool(data[offset + 29])

        entry = {
            "entry_index": index,
            "partition_style": entry_style,
            "number": partition_number,
            "offset": starting_offset,
            "length": partition_length,
            "rewrite_partition": rewrite_partition,
            "service_partition": service_partition,
        }

        if entry_style == PARTITION_STYLE_MBR:
            partition_type = data[offset + 32]
            partition_id_bytes = data[offset + 40:offset + 56]
            entry.update({
                "partition_style_name": "MBR",
                "mbr_type": partition_type,
                "boot_indicator": bool(data[offset + 33]),
                "recognized_partition": bool(data[offset + 34]),
                "hidden_sectors": struct.unpack_from("<I", data, offset + 36)[0],
                "partition_id": str(uuid.UUID(bytes_le=partition_id_bytes)),
                "is_unused": partition_type == 0,
            })
        elif entry_style == PARTITION_STYLE_GPT:
            partition_type_bytes = data[offset + 32:offset + 48]
            partition_id_bytes = data[offset + 48:offset + 64]
            name_bytes = data[offset + 72:offset + 144]
            name = name_bytes.decode("utf-16-le", "replace").split("\x00", 1)[0]
            partition_type_guid = str(uuid.UUID(bytes_le=partition_type_bytes))
            entry.update({
                "partition_style_name": "GPT",
                "partition_type_guid": partition_type_guid,
                "partition_guid": str(uuid.UUID(bytes_le=partition_id_bytes)),
                "attributes": struct.unpack_from("<Q", data, offset + 64)[0],
                "name": name or None,
                "is_unused": partition_type_guid == "00000000-0000-0000-0000-000000000000",
            })
        elif entry_style == PARTITION_STYLE_RAW:
            entry["partition_style_name"] = "RAW"
            entry["is_unused"] = partition_length == 0
        else:
            entry["partition_style_name"] = "UNKNOWN"
            entry["is_unused"] = partition_length == 0

        result["partitions"].append(entry)

    return result, None


def canonical_sha256(value):
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def partition_sort_key(partition):
    return (
        partition.get("number") if partition.get("number") is not None else -1,
        partition.get("offset") if partition.get("offset") is not None else -1,
        partition.get("entry_index") if partition.get("entry_index") is not None else -1,
    )


def volume_sort_key(volume):
    return (
        volume.get("partition_number") if volume.get("partition_number") is not None else -1,
    )


def hardware_evidence(record):
    storage = record.get("storage") or {}
    geometry = record.get("geometry") or {}
    pnp = record.get("pnp") or {}
    usb = pnp.get("usb") or {}
    serial_candidate = usb.get("serial_candidate") or {}

    return {
        "usb": {
            "vid": usb.get("vid"),
            "pid": usb.get("pid"),
            "serial_candidate": (
                serial_candidate.get("value")
                if not serial_candidate.get("likely_port_specific")
                else None
            ),
        },
        "storage": {
            "vendor": storage.get("vendor"),
            "product": storage.get("product"),
            "revision": storage.get("revision"),
            "serial": storage.get("serial"),
            "bus_type": storage.get("bus_type"),
            "removable_media": storage.get("removable_media"),
        },
        "geometry": {
            "size_bytes": geometry.get("size_bytes"),
            "bytes_per_sector": geometry.get("bytes_per_sector"),
        },
    }


def pnp_observation_evidence(record):
    nodes = (record.get("pnp") or {}).get("nodes") or []
    device_nodes = []
    # Only the disk and actual USB device nodes are PnP evidence. Parents
    # above them identify the host controller and port.
    for node in nodes[:2]:
        device_nodes.append({
            "hardware_ids": sorted(node.get("hardware_ids") or []),
            "compatible_ids": sorted(node.get("compatible_ids") or []),
            "service": node.get("service"),
            "class": node.get("class"),
        })
    return {
        "pnp_device_nodes": device_nodes,
    }


def media_identity_evidence(record):
    layout = record.get("layout") or {}
    volumes = record.get("volumes") or []
    partitions = layout.get("partitions") or []

    normalized_partitions = []
    for partition in sorted(partitions, key=partition_sort_key):
        normalized_partitions.append({
            "style": partition.get("partition_style_name"),
            "number": partition.get("number"),
            "offset": partition.get("offset"),
            "length": partition.get("length"),
            "mbr_type": partition.get("mbr_type"),
            "boot_indicator": partition.get("boot_indicator"),
            "recognized_partition": partition.get("recognized_partition"),
            "hidden_sectors": partition.get("hidden_sectors"),
            "partition_type_guid": partition.get("partition_type_guid"),
            "partition_guid": partition.get("partition_guid"),
            "attributes": partition.get("attributes"),
            "is_unused": partition.get("is_unused"),
        })

    normalized_volumes = []
    for item in sorted(volumes, key=volume_sort_key):
        normalized_volumes.append({
            "partition_number": item.get("partition_number"),
            "volume_serial": item.get("volume_serial"),
        })

    return {
        "disk": {
            "partition_style": layout.get("partition_style_name"),
            "mbr_signature": layout.get("mbr_signature"),
            "gpt_disk_guid": layout.get("gpt_disk_guid"),
        },
        "partitions": normalized_partitions,
        "volumes": normalized_volumes,
    }


def media_state_evidence(record):
    layout = record.get("layout") or {}
    volumes = record.get("volumes") or []
    partitions = layout.get("partitions") or []

    normalized_partitions = []
    for partition in sorted(partitions, key=partition_sort_key):
        normalized_partitions.append({
            "number": partition.get("number"),
            "name": partition.get("name"),
        })

    normalized_volumes = []
    for item in sorted(volumes, key=volume_sort_key):
        normalized_volumes.append({
            "partition_number": item.get("partition_number"),
            "filesystem": item.get("filesystem"),
            "volume_label": item.get("volume_label"),
        })

    return {
        "partitions": normalized_partitions,
        "volumes": normalized_volumes,
    }


def software_evidence(record):
    """Return the mutable, on-media configuration of a USB device.

    This intentionally includes both the disk layout identifiers and the
    user-visible filesystem metadata.  It is the counterpart to the hardware
    fingerprint, not a second, ambiguously named media fingerprint.
    """
    return {
        "layout": media_identity_evidence(record),
        "filesystem": media_state_evidence(record),
    }


def hardware_hash(record):
    return canonical_sha256(hardware_evidence(record))


def pnp_observation_hash(record):
    return canonical_sha256(pnp_observation_evidence(record))


def software_hash(record):
    return canonical_sha256(software_evidence(record))


def scan_physical_disks(max_disks=64):
    devices = []
    errors = []
    pnp_by_disk, pnp_collector_error = run_collector(
        "setupapi_enumerator",
        enumerate_setupapi_disks,
    )
    if pnp_by_disk is None:
        pnp_by_disk = {}
    if pnp_collector_error is not None:
        errors.append(pnp_collector_error)
    volume_collector_error = None
    try:
        volumes_by_disk = enumerate_volumes_by_physical_drive()
    except Exception as exc:
        volumes_by_disk = {}
        volume_collector_error = structured_error(
            "volume_enumerator",
            "%s: %s" % (exc.__class__.__name__, exc),
            status="collector_failed",
        )
        errors.append(volume_collector_error)

    for number in range(max_disks):
        handle, path, open_err = open_disk(number)
        if handle is None:
            # Отсутствующие номера дисков здесь ожидаемы. Остальные
            # ошибки, включая access denied, не должны пропадать.
            open_err = normalize_collector_error("disk_open", open_err)
            if open_err.get("status") != "not_found":
                open_err["physical_drive"] = number
                open_err["path"] = path
                errors.append(open_err)
            continue

        try:
            storage, storage_err = run_collector(
                "storage_descriptor",
                query_storage_descriptor,
                handle,
            )
            if storage is None:
                errors.append({
                    "physical_drive": number,
                    "error": storage_err,
                })
                continue

            if storage.get("bus_type") != BusTypeUsb:
                continue

            geometry, geometry_err = run_collector("geometry", query_geometry, handle)
            layout, layout_err = run_collector("drive_layout", query_drive_layout, handle)
            record = {
                "physical_drive": number,
                "path": path,
                "storage": storage,
                "geometry": geometry,
                "layout": layout,
                "volumes": volumes_by_disk.get(number, []),
                "pnp": pnp_by_disk.get(number),
                "capabilities": {
                    "storage_descriptor": storage is not None,
                    "geometry": geometry is not None,
                    "partition_layout": layout is not None,
                    "volume_information": volume_collector_error is None,
                    "pnp_tree": pnp_collector_error is None,
                },
                "capability_status": {
                    "storage_descriptor": "available",
                    "geometry": "available" if geometry_err is None else geometry_err["status"],
                    "partition_layout": "available" if layout_err is None else layout_err["status"],
                    "volume_information": (
                        "available" if volumes_by_disk.get(number, [])
                        else "no_volumes" if volume_collector_error is None
                        else volume_collector_error["status"]
                    ),
                    "pnp_tree": (
                        "available" if pnp_by_disk.get(number) is not None
                        else "not_found" if pnp_collector_error is None
                        else pnp_collector_error["status"]
                    ),
                },
                "collector_errors": {
                    "geometry": geometry_err,
                    "partition_layout": layout_err,
                },
            }

            hardware = hardware_hash(record)
            pnp_observation = pnp_observation_hash(record)
            software = software_hash(record)
            record["hardware_sha256"] = hardware
            record["software_sha256"] = software
            record["pnp_observation_sha256"] = pnp_observation
            devices.append(record)

        finally:
            CloseHandle(handle)

    return devices, errors


def host_ip_addresses(include_link_local=False):
    addresses = []
    for address in enumerate_ip_addresses():
        if not include_link_local and address.lower().startswith("fe80:"):
            continue
        addresses.append(address)
    return addresses


def host_info(include_diagnostics=False):
    join_info = query_domain_membership()
    result = {
        "hostname": socket.gethostname(),
        "ip_addresses": host_ip_addresses(include_link_local=include_diagnostics),
    }
    if join_info["domain_name"]:
        result["domain_name"] = join_info["domain_name"]
    if include_diagnostics:
        win32 = platform.win32_ver()
        result["computer_name"] = result["hostname"]
        result["platform"] = platform.platform()
        result["windows_release"] = win32[0]
        result["windows_version"] = win32[1]
        result["windows_service_pack"] = win32[2]
        result["architecture"] = platform.machine()
        result["python_version"] = platform.python_version()
        result["join_status"] = join_info["join_status"]
        result["is_domain_joined"] = join_info["is_domain_joined"]
        result["domain_name"] = join_info["domain_name"]
        result["workgroup_name"] = join_info["workgroup_name"]
        result["local_users"] = enumerate_local_users()
    return result


def summarize_capabilities(devices):
    names = (
        "storage_descriptor",
        "geometry",
        "partition_layout",
        "volume_information",
        "pnp_tree",
    )
    summary = {}
    for name in names:
        summary[name] = any(
            bool((device.get("capabilities") or {}).get(name))
            for device in devices
        )
    return summary


def collector_error_list(error_map):
    result = []
    for name in sorted(error_map):
        error = error_map.get(name)
        if error is None:
            continue
        normalized = normalize_collector_error(name, error)
        result.append(normalized)
    return result


STORAGE_PAYLOAD_KEYS = (
    "vendor",
    "product",
    "serial",
)

SESSION_PAYLOAD_KEYS = (
    "username",
    "domain",
    "sid",
)

HASH_FIELDS = (
    ("hardware", "hardware_sha256"),
    ("software", "software_sha256"),
)

DEBUG_HASH_FIELDS = HASH_FIELDS + (
    ("pnp", "pnp_observation_sha256"),
)

HOST_PAYLOAD_KEYS = (
    "hostname",
    "domain_name",
)

DEVICE_HASH_KEYS = (
    "hardware_sha256",
    "software_sha256",
    "pnp_observation_sha256",
)


def compact_mapping(value, keys):
    result = {}
    for key in keys:
        if key not in value:
            continue
        item = value[key]
        if item is None:
            continue
        result[key] = item
    return result


def compact_usb(pnp):
    usb = (pnp or {}).get("usb") or {}
    if not isinstance(usb, dict):
        return {}
    result = compact_mapping(usb, ("vid", "pid"))
    candidate = usb.get("serial_candidate") or {}
    if isinstance(candidate, dict) and candidate.get("value"):
        result["serial"] = candidate["value"]
    return result


def compact_layout(layout):
    result = {}
    style = layout.get("partition_style_name") or layout.get("style")
    if style:
        result["style"] = style
    if layout.get("mbr_signature"):
        result["mbr_signature"] = layout["mbr_signature"]
    if layout.get("gpt_disk_guid"):
        result["gpt_disk_guid"] = layout["gpt_disk_guid"]
    return result


def compact_volume(volume):
    result = {}
    if volume.get("filesystem"):
        result["filesystem"] = volume["filesystem"]
    serial = volume.get("serial") or volume.get("volume_serial")
    if serial:
        result["serial"] = serial
    return result


def compact_host(host):
    if not isinstance(host, dict):
        return host
    return compact_mapping(host, HOST_PAYLOAD_KEYS)


def compact_session(session, host=None):
    if not isinstance(session, dict):
        return session
    result = compact_mapping(session, SESSION_PAYLOAD_KEYS)
    hostname = str((host or {}).get("hostname") or "").strip().lower()
    domain = str(result.get("domain") or "").strip().lower()
    if domain and hostname and domain == hostname:
        result.pop("domain", None)
    return result


def observation_hashes(device_record, compact=True):
    result = {}
    fields = HASH_FIELDS if compact else DEBUG_HASH_FIELDS
    for short_name, full_name in fields:
        value = device_record.get(full_name)
        if value:
            result[short_name] = value
    return result


def compact_device_payload(device):
    result = compact_mapping(device.get("storage") or {}, STORAGE_PAYLOAD_KEYS)
    usb = compact_usb(device.get("pnp") or {})
    if usb.get("vid"):
        result["vid"] = usb["vid"]
    if usb.get("pid"):
        result["pid"] = usb["pid"]
    usb_serial = usb.get("serial")
    if usb_serial and usb_serial != result.get("serial"):
        result["usb_serial"] = usb_serial
    layout = device.get("layout")
    if isinstance(layout, dict):
        compacted_layout = compact_layout(layout)
        if compacted_layout:
            result["layout"] = compacted_layout
    volumes = []
    for item in device.get("volumes") or []:
        if not isinstance(item, dict):
            continue
        compacted = compact_volume(item)
        if compacted:
            volumes.append(compacted)
    if volumes:
        result["volumes"] = volumes
    return result


def build_observation(
    device_record,
    host,
    session,
    observed_at_utc,
    event_type="snapshot",
    compact=True,
):
    device = dict(device_record)
    hashes = observation_hashes(device, compact=compact)
    capabilities = device.pop("capabilities", {})
    capability_status = device.pop("capability_status", {})
    collector_errors = collector_error_list(device.pop("collector_errors", {}))
    for key in DEVICE_HASH_KEYS:
        device.pop(key, None)
    if compact:
        device = compact_device_payload(device)
        session = compact_session(session, host)
        host = compact_host(host)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "probe_version": PROBE_VERSION,
        "event": {
            "id": str(uuid.uuid4()),
            "type": event_type,
            "observed_at_utc": observed_at_utc,
        },
        "host": host,
        "session": session,
        "device": device,
    }
    if hashes:
        payload["hashes"] = hashes
    if not compact:
        payload["capabilities"] = capabilities
        payload["capability_status"] = capability_status
        if collector_errors:
            payload["collector_errors"] = collector_errors
    return payload


def write_json_stdout(value, compact=False):
    options = {
        "ensure_ascii": False,
    }
    if compact:
        options["separators"] = (",", ":")
    else:
        options["indent"] = 2
    text = json.dumps(value, **options)
    binary_stdout = getattr(sys.stdout, "buffer", None)
    if binary_stdout is not None:
        binary_stdout.write(text.encode("utf-8"))
        binary_stdout.write(b"\n")
        binary_stdout.flush()
        return
    # Windows Service captures stdout with io.StringIO, which has no buffer.
    sys.stdout.write(text)
    sys.stdout.write("\n")
    sys.stdout.flush()


def device_presence_key(device):
    pnp = device.get("pnp") or {}
    interface_path = pnp.get("device_interface_path")
    if interface_path:
        return interface_path.strip().upper()
    path = device.get("path")
    return path.strip().upper() if path else None


def usb_presence_keys():
    disks, error = run_collector(
        "setupapi_enumerator",
        enumerate_setupapi_disks,
    )
    if error is not None:
        return None, error
    keys = set()
    for item in (disks or {}).values():
        if not item.get("usb"):
            continue
        path = item.get("device_interface_path")
        if path:
            keys.add(path.strip().upper())
    return keys, None


def watch_interval_from_argv(argv):
    value = 2.0
    for index, argument in enumerate(argv):
        if argument.startswith("--watch-interval="):
            value = float(argument.split("=", 1)[1])
        elif argument == "--watch-interval" and index + 1 < len(argv):
            value = float(argv[index + 1])
    if value < 0.25:
        value = 0.25
    return value


def watch_usb(include_diagnostics=False, interval_seconds=2.0):
    devices, scan_errors = scan_physical_disks(
        max_disks=64,
    )
    observed_at = utc_now_iso()
    host = host_info(include_diagnostics=include_diagnostics)
    session = collect_active_session()
    cache = {}

    for device in devices:
        key = device_presence_key(device)
        if key:
            cache[key] = device
        write_json_stdout(
            build_observation(
                device,
                host,
                session,
                observed_at,
                "snapshot",
                compact=not include_diagnostics,
            ),
            compact=True,
        )

    if scan_errors:
        sys.stderr.write("Initial watch scan completed with %d error(s).\n" % len(scan_errors))

    while True:
        try:
            time.sleep(interval_seconds)
            current_keys, presence_error = usb_presence_keys()
            if presence_error is not None:
                sys.stderr.write(
                    "USB presence check failed: %s\n" % presence_error.get("message")
                )
                continue

            previous_keys = set(cache)
            added_keys = current_keys - previous_keys
            removed_keys = previous_keys - current_keys
            if not added_keys and not removed_keys:
                continue

            # A full rescan is intentional: a device notification is only a
            # trigger, while the Observation must contain fresh complete facts.
            current_devices, current_errors = scan_physical_disks(
                max_disks=64,
            )
            current_by_key = {}
            for device in current_devices:
                key = device_presence_key(device)
                if key:
                    current_by_key[key] = device

            event_time = utc_now_iso()
            event_host = host_info(include_diagnostics=include_diagnostics)
            event_session = collect_active_session()

            for key in sorted(removed_keys):
                device = cache.pop(key, None)
                if device is None:
                    continue
                write_json_stdout(
                    build_observation(
                        device,
                        event_host,
                        event_session,
                        event_time,
                        "disconnected",
                        compact=not include_diagnostics,
                    ),
                    compact=True,
                )

            for key in sorted(added_keys):
                device = current_by_key.get(key)
                if device is None:
                    # The interface can appear before storage IOCTLs are ready.
                    # Do not cache it yet; the next poll will retry collection.
                    continue
                cache[key] = device
                write_json_stdout(
                    build_observation(
                        device,
                        event_host,
                        event_session,
                        event_time,
                        "connected",
                        compact=not include_diagnostics,
                    ),
                    compact=True,
                )

            # Refresh evidence for devices that remained connected across the
            # rescan without emitting duplicate events.
            for key in current_keys & set(cache):
                if key in current_by_key:
                    cache[key] = current_by_key[key]

            if current_errors:
                sys.stderr.write(
                    "Watch rescan completed with %d error(s).\n" % len(current_errors)
                )
        except KeyboardInterrupt:
            return


def main():
    include_diagnostics = "--debug" in sys.argv or "--diagnostics" in sys.argv

    if "--watch" in sys.argv:
        try:
            interval_seconds = watch_interval_from_argv(sys.argv[1:])
        except (TypeError, ValueError):
            sys.stderr.write("--watch-interval must be a number.\n")
            return 2
        watch_usb(
            include_diagnostics=include_diagnostics,
            interval_seconds=interval_seconds,
        )
        return 0

    devices, errors = scan_physical_disks(
        max_disks=64,
    )

    observed_at_utc = utc_now_iso()
    host = host_info(include_diagnostics=include_diagnostics)
    session = collect_active_session()
    observations = [
        build_observation(
            device,
            host,
            session,
            observed_at_utc,
            compact=not include_diagnostics,
        )
        for device in devices
    ]

    extra = {
        "scan_id": str(uuid.uuid4()),
        "generated_at_utc": observed_at_utc,
        "scan_errors": errors,
    }
    if include_diagnostics:
        extra["scan_capabilities"] = summarize_capabilities(devices)
    result = pack_observation_payload(observations, extra=extra)
    if "schema_version" not in result:
        result["schema_version"] = SCHEMA_VERSION
        result["probe_version"] = PROBE_VERSION

    write_json_stdout(result)


if __name__ == "__main__":
    sys.exit(main() or 0)
