#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка QEMU monitor команд для usb-storage с опциональной hardware-identity.

Источники (по приоритету):
  1. переменные окружения QEMU_*
  2. manifest <image>.json -> qemu_attach
  3. defaults
"""

from __future__ import print_function

import json
import hashlib
import os
import re
import sys


def normalize_hex_id(value):
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not re.fullmatch(r"[0-9a-f]{1,4}", text):
        raise ValueError("invalid usb id: %r" % value)
    return "0x" + text.zfill(4)


def env_or_none(name):
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value


def load_manifest_qemu_attach(image_path):
    manifest_path = image_path + ".json"
    if not os.path.isfile(manifest_path):
        return {}
    with open(manifest_path, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    attach = document.get("qemu_attach")
    return attach if isinstance(attach, dict) else {}


def merge_qemu_attach(image_path):
    attach = dict(load_manifest_qemu_attach(image_path))

    env_map = {
        "usb_serial": "QEMU_USB_SERIAL",
        "drive_serial": "QEMU_DRIVE_SERIAL",
        "vendor_id": "QEMU_VENDOR_ID",
        "product_id": "QEMU_PRODUCT_ID",
        "removable": "QEMU_REMOVABLE",
    }
    for key, env_name in env_map.items():
        value = env_or_none(env_name)
        if value is not None:
            attach[key] = value

    # Keep QEMU's virtual hardware identity stable for a generated image even
    # when its profile did not specify one explicitly.  QEMU otherwise derives
    # a transient serial from the attachment slot, which looks like a new USB
    # device after every detach/attach.
    image_name = os.path.basename(image_path).encode("utf-8")
    identity = hashlib.sha256(image_name).hexdigest()[:16].upper()
    attach.setdefault("usb_serial", "FG-" + identity)
    attach.setdefault("drive_serial", "STOR-" + identity)

    return attach


def parse_removable(value):
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ValueError("invalid removable value: %r" % value)


def qemu_monitor_quote(value):
    text = str(value)
    return text.replace("\\", "\\\\").replace(",", "\\,")


def build_drive_add(drive_id, image_path, attach):
    parts = [
        "file=%s" % qemu_monitor_quote(image_path),
        "if=none",
        "id=%s" % drive_id,
        "format=raw",
        "readonly=off",
    ]
    drive_serial = attach.get("drive_serial")
    if drive_serial:
        parts.append("serial=%s" % qemu_monitor_quote(drive_serial))
    return "drive_add 0 " + ",".join(parts)


def build_device_add_variants(dev_id, drive_id, bus, attach):
    removable = parse_removable(attach.get("removable", True))
    base = {
        "id": dev_id,
        "drive": drive_id,
        "bus": bus,
        "removable": "on" if removable else "off",
    }
    optional = {}
    if attach.get("usb_serial"):
        optional["serial"] = attach["usb_serial"]
    vendor_id = attach.get("vendor_id")
    product_id = attach.get("product_id")
    if vendor_id:
        optional["vendorid"] = normalize_hex_id(vendor_id)
    if product_id:
        optional["productid"] = normalize_hex_id(product_id)

    variants = []
    # Сначала полный набор, затем откаты без неподдерживаемых свойств.
    if optional:
        full = dict(base)
        full.update(optional)
        variants.append(full)
        if "vendorid" in optional or "productid" in optional:
            without_vid = dict(base)
            without_vid.update({k: v for k, v in optional.items() if k not in ("vendorid", "productid")})
            variants.append(without_vid)
    variants.append(base)

    commands = []
    seen = set()
    for item in variants:
        parts = ["device_add usb-storage"]
        for key in ("drive", "bus", "id", "serial", "vendorid", "productid", "removable"):
            if key not in item:
                continue
            parts.append("%s=%s" % (key, qemu_monitor_quote(item[key])))
        command = ",".join(parts)
        if command not in seen:
            seen.add(command)
            commands.append(command)
    return commands


def main():
    if len(sys.argv) < 5:
        print("usage: qemu_attach.py <image> <drive_id> <dev_id> <bus>", file=sys.stderr)
        return 2

    image_path = sys.argv[1]
    drive_id = sys.argv[2]
    dev_id = sys.argv[3]
    bus = sys.argv[4]

    attach = merge_qemu_attach(image_path)
    drive_cmd = build_drive_add(drive_id, image_path, attach)
    device_cmds = build_device_add_variants(dev_id, drive_id, bus, attach)

    print(json.dumps({
        "qemu_attach": attach,
        "drive_add": drive_cmd,
        "device_add_variants": device_cmds,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
