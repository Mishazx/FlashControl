#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор raw-образов USB-носителей для тестов FlashControl probe в QEMU/Proxmox.

Требования на Linux-хосте (Proxmox):
  qemu-img, sgdisk, parted, losetup, mkfs.vfat, mkfs.ntfs (ntfs-3g), mkfs.exfat (опционально)

Примеры:
  sudo ./generate.py --list
  sudo ./generate.py baseline_mbr_fat32
  sudo ./generate.py --all
  sudo ./generate.py profiles/custom.json -o output/custom.img
"""

from __future__ import print_function

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import uuid


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")

GPT_BASIC_DATA = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"
MBR_SIGNATURE_OFFSET = 0x1B8


def eprint(*args):
    print(*args, file=sys.stderr)


def require_root():
    if os.name != "posix":
        eprint("error: generate.py запускается на Linux-хосте Proxmox")
        sys.exit(1)
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        eprint("error: нужен root (losetup/mkfs), запусти через sudo")
        sys.exit(1)


def run(cmd, check=True):
    eprint("+", " ".join(cmd))
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and result.returncode != 0:
        eprint(result.stdout)
        eprint(result.stderr)
        raise RuntimeError("command failed: %s" % " ".join(cmd))
    return result


def require_tool(name):
    if shutil.which(name) is None:
        raise RuntimeError("не найден инструмент: %s" % name)


def check_dependencies():
    for tool in ("qemu-img", "sgdisk", "parted", "losetup", "mkfs.vfat", "mkfs.ntfs"):
        require_tool(tool)


def normalize_hex(value, width):
    text = str(value).strip().lower().replace("0x", "")
    if not re.fullmatch(r"[0-9a-f]+", text):
        raise ValueError("invalid hex value: %s" % value)
    if len(text) > width:
        raise ValueError("hex value too long: %s" % value)
    return text.zfill(width)


def load_profile(path):
    with open(path, "r", encoding="utf-8") as handle:
        profile = json.load(handle)
    if "name" not in profile:
        profile["name"] = os.path.splitext(os.path.basename(path))[0]
    if "size_mb" not in profile:
        raise ValueError("profile must define size_mb")
    if "partition_style" not in profile:
        raise ValueError("profile must define partition_style")
    style = profile["partition_style"].lower()
    if style == "raw":
        profile.setdefault("partitions", [])
    elif not profile.get("partitions"):
        raise ValueError("profile must define at least one partition")
    return profile


def list_profiles():
    if not os.path.isdir(PROFILES_DIR):
        return []
    result = []
    for name in sorted(os.listdir(PROFILES_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(PROFILES_DIR, name)
        profile = load_profile(path)
        result.append((profile["name"], profile.get("description", ""), path))
    return result


def create_empty_image(path, size_mb):
    if os.path.exists(path):
        raise RuntimeError("output already exists: %s" % path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    run(["qemu-img", "create", "-f", "raw", path, "%dM" % int(size_mb)])


def patch_mbr_signature(path, signature):
    value = int(normalize_hex(signature, 8), 16)
    with open(path, "r+b") as handle:
        handle.seek(MBR_SIGNATURE_OFFSET)
        handle.write(struct.pack("<I", value))


def partition_gpt(path, profile):
    cmd = ["sgdisk", "--clear", "--set-alignment=1"]
    disk_guid = profile.get("gpt_disk_guid")
    if disk_guid:
        cmd.extend(["--disk-guid", str(disk_guid)])
    partitions = profile["partitions"]
    for index, part in enumerate(partitions, start=1):
        size_mb = part.get("size_mb")
        if size_mb:
            spec = "%d:0:+%dM" % (index, int(size_mb))
        else:
            spec = "%d:0:0" % index
        cmd.extend(["--new", spec])
        part_type = part.get("partition_type", GPT_BASIC_DATA)
        cmd.extend(["--typecode", "%d:%s" % (index, part_type)])
        gpt_name = part.get("gpt_name") or part.get("label") or ("part%d" % index)
        cmd.extend(["--change-name", "%d:%s" % (index, gpt_name)])
        part_guid = part.get("partition_guid")
        if part_guid:
            cmd.extend(["--partition-guid", "%d:%s" % (index, part_guid)])
    cmd.append(path)
    run(cmd)


def partition_mbr(path, profile):
    partitions = profile["partitions"]
    run(["parted", "-s", path, "mklabel", "msdos"])
    start_mb = 1
    for index, part in enumerate(partitions, start=1):
        size_mb = int(part.get("size_mb") or 0)
        if size_mb > 0:
            end_mb = start_mb + size_mb
            run([
                "parted", "-s", path, "mkpart", "primary",
                "%dMiB" % start_mb, "%dMiB" % end_mb,
            ])
            start_mb = end_mb
        else:
            run([
                "parted", "-s", path, "mkpart", "primary",
                "%dMiB" % start_mb, "100%",
            ])
        if part.get("bootable"):
            run(["parted", "-s", path, "set", str(index), "boot", "on"])
    signature = profile.get("mbr_signature")
    if signature:
        patch_mbr_signature(path, signature)


def should_format_partition(part):
    filesystem = (part.get("filesystem") or "fat32").lower()
    return filesystem not in ("none", "unformatted", "raw", "skip")


def setup_loop(path):
    result = run(["losetup", "-f", "--show", "-P", path])
    loop = result.stdout.strip()
    if not loop:
        raise RuntimeError("losetup did not return a loop device")
    return loop


def teardown_loop(loop):
    run(["losetup", "-d", loop])


def partition_device(loop, number):
    return "%sp%d" % (loop, int(number))


def format_partition(part, device):
    filesystem = (part.get("filesystem") or "fat32").lower()
    label = part.get("label") or "FLASHGEN"
    if filesystem in ("fat32", "vfat", "fat"):
        cmd = ["mkfs.vfat", "-F", "32", "-n", label, device]
        volume_serial = part.get("volume_serial")
        if volume_serial:
            cmd[1:1] = ["-i", normalize_hex(volume_serial, 8)]
        run(cmd)
        return
    if filesystem == "ntfs":
        cmd = ["mkfs.ntfs", "-f", "-L", label, device]
        run(cmd)
        return
    if filesystem == "exfat":
        if shutil.which("mkfs.exfat") is None:
            raise RuntimeError("mkfs.exfat не найден, установи exfatprogs")
        run(["mkfs.exfat", "-n", label, device])
        return
    raise ValueError("unsupported filesystem: %s" % filesystem)


def generate_image(profile, output_path):
    create_empty_image(output_path, profile["size_mb"])
    style = profile["partition_style"].lower()
    if style == "raw":
        return output_path
    if style == "gpt":
        partition_gpt(output_path, profile)
    elif style == "mbr":
        partition_mbr(output_path, profile)
    else:
        raise ValueError("unsupported partition_style: %s" % style)

    format_targets = [part for part in profile["partitions"] if should_format_partition(part)]
    if not format_targets:
        return output_path

    loop = setup_loop(output_path)
    try:
        for part in format_targets:
            number = int(part.get("number") or 1)
            device = partition_device(loop, number)
            if not os.path.exists(device):
                raise RuntimeError("partition device not found: %s" % device)
            format_partition(part, device)
    finally:
        teardown_loop(loop)

    return output_path


def resolve_profile_arg(value):
    if os.path.isfile(value):
        return load_profile(value)
    json_path = os.path.join(PROFILES_DIR, value + ".json")
    if os.path.isfile(json_path):
        return load_profile(json_path)
    raise RuntimeError("profile not found: %s" % value)


def default_output_path(profile):
    return os.path.join(OUTPUT_DIR, "%s.img" % profile["name"])


def write_manifest(profile, output_path):
    manifest = {
        "profile": profile["name"],
        "description": profile.get("description"),
        "image": os.path.abspath(output_path),
        "partition_style": profile.get("partition_style"),
        "gpt_disk_guid": profile.get("gpt_disk_guid"),
        "mbr_signature": profile.get("mbr_signature"),
        "partitions": profile.get("partitions"),
        "expect": profile.get("expect"),
        "qemu_attach": profile.get("qemu_attach"),
    }
    manifest_path = output_path + ".json"
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest_path


def main():
    parser = argparse.ArgumentParser(description="Generate raw USB media images for FlashControl VM tests")
    parser.add_argument("profile", nargs="?", help="profile name (without .json) or path to profile json")
    parser.add_argument("-o", "--output", help="output image path")
    parser.add_argument("--all", action="store_true", help="generate all profiles from profiles/")
    parser.add_argument("--list", action="store_true", help="list available profiles")
    parser.add_argument("--force", action="store_true", help="overwrite existing output image")
    args = parser.parse_args()

    if args.list:
        for name, description, path in list_profiles():
            print("%-24s %s" % (name, description))
            print("  %s" % path)
        return 0

    if not args.profile and not args.all:
        parser.print_help()
        return 1

    require_root()
    check_dependencies()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    profiles = []
    if args.all:
        for _, _, path in list_profiles():
            profiles.append(load_profile(path))
    else:
        profiles.append(resolve_profile_arg(args.profile))

    generated = []
    for profile in profiles:
        output_path = args.output if args.output and len(profiles) == 1 else default_output_path(profile)
        if os.path.exists(output_path):
            if not args.force:
                raise RuntimeError("output exists (use --force): %s" % output_path)
            os.remove(output_path)
            manifest_path = output_path + ".json"
            if os.path.exists(manifest_path):
                os.remove(manifest_path)
        image_path = generate_image(profile, output_path)
        manifest_path = write_manifest(profile, image_path)
        generated.append((image_path, manifest_path))

    print("")
    print("Generated:")
    for image_path, manifest_path in generated:
        print("  image:    %s" % image_path)
        print("  manifest: %s" % manifest_path)
    print("")
    print("Attach to Windows VM 5000:")
    print("  sudo ./attach.sh %s" % generated[-1][0])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        eprint("error:", exc)
        sys.exit(1)
