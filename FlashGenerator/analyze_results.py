#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка JSON-результатов FlashControl probe для synthetic USB профилей.

Примеры:
  python analyze_results.py results/
  python analyze_results.py results/ --suite test_suite.json
  python analyze_results.py results/baseline_mbr_fat32.json
"""

from __future__ import print_function

import argparse
import glob
import json
import os
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SUITE = os.path.join(SCRIPT_DIR, "test_suite.json")
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")

HASH_FIELDS = (
    "hardware_stable_sha256",
    "pnp_observation_sha256",
    "media_identity_sha256",
    "media_state_sha256",
    "observation_sha256",
)


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def profile_expectation(profile_name):
    profile_path = os.path.join(PROFILES_DIR, profile_name + ".json")
    if os.path.isfile(profile_path):
        profile = load_json(profile_path)
        return profile.get("expect") or {}
    manifest_path = os.path.join(OUTPUT_DIR, profile_name + ".img.json")
    if os.path.isfile(manifest_path):
        manifest = load_json(manifest_path)
        return manifest.get("expect") or {}
    return {}


def iter_result_files(path):
    if os.path.isfile(path):
        return [path]
    patterns = [
        os.path.join(path, "*.json"),
        os.path.join(path, "**", "*.json"),
    ]
    files = set()
    for pattern in patterns:
        files.update(glob.glob(pattern, recursive=True))
    return sorted(
        item for item in files
        if not item.endswith(".img.json")
        and os.path.basename(item) not in ("test_suite.json", "suite_summary.json")
    )


def profile_name_from_path(path):
    base = os.path.basename(path)
    if base.endswith(".json"):
        base = base[:-5]
    for prefix in ("scan_", "result_", "probe_"):
        if base.startswith(prefix):
            base = base[len(prefix):]
    return base


def usb_observations(document):
    observations = document.get("observations") or []
    usb_items = []
    for observation in observations:
        device = observation.get("device") or {}
        storage = device.get("storage") or {}
        bus_type = storage.get("bus_type")
        if bus_type == 7:
            usb_items.append(observation)
            continue
        pnp = device.get("pnp") or {}
        if pnp.get("usb"):
            usb_items.append(observation)
    return usb_items if usb_items else observations


def pick_primary_device(document):
    observations = usb_observations(document)
    if not observations:
        return None, []
    observation = observations[0]
    return observation.get("device") or {}, observations


def normalize_filesystem(value):
    return (value or "").strip().upper()


def check_expectation(profile_name, device, observation):
    expect = profile_expectation(profile_name)
    errors = []
    warnings = []

    if expect.get("manual_followup"):
        warnings.append("manual follow-up: %s" % expect["manual_followup"])

    if expect.get("usb_required"):
        storage = device.get("storage") or {}
        if storage.get("bus_type") != 7:
            errors.append("expected BusTypeUsb (7), got %r" % storage.get("bus_type"))

    layout = device.get("layout") or {}
    style = layout.get("partition_style_name")
    expected_style = expect.get("partition_style")
    if expected_style and style != expected_style:
        errors.append("expected partition_style %s, got %s" % (expected_style, style))

    partitions = layout.get("partitions") or []
    volumes = device.get("volumes") or []

    min_partitions = expect.get("min_partitions")
    if min_partitions is not None and len(partitions) < int(min_partitions):
        errors.append("expected >= %d partitions, got %d" % (min_partitions, len(partitions)))

    max_volumes = expect.get("max_volumes")
    if max_volumes is not None and len(volumes) > int(max_volumes):
        errors.append("expected <= %d volumes, got %d" % (max_volumes, len(volumes)))

    min_volumes = expect.get("min_volumes")
    if min_volumes is not None and len(volumes) < int(min_volumes):
        errors.append("expected >= %d volumes, got %d" % (min_volumes, len(volumes)))

    volume_status = ((observation.get("capability_status") or {}).get("volume_information"))
    allowed_status = expect.get("volume_status_in")
    if allowed_status and volume_status not in allowed_status:
        errors.append(
            "expected volume_information in %r, got %r" % (allowed_status, volume_status)
        )

    bootable_min = expect.get("bootable_partitions_min")
    if bootable_min is not None:
        bootable = sum(1 for part in partitions if part.get("boot_indicator"))
        if bootable < int(bootable_min):
            errors.append("expected >= %d bootable partitions, got %d" % (bootable_min, bootable))

    min_size = expect.get("min_size_bytes")
    if min_size is not None:
        geometry = device.get("geometry") or {}
        size_bytes = geometry.get("size_bytes") or 0
        if size_bytes < int(min_size):
            errors.append("expected size_bytes >= %d, got %d" % (min_size, size_bytes))

    expected_filesystems = expect.get("filesystems_contain") or []
    if expected_filesystems:
        actual = {normalize_filesystem(item.get("filesystem")) for item in volumes}
        for filesystem in expected_filesystems:
            if normalize_filesystem(filesystem) not in actual:
                errors.append("expected filesystem %s in %r" % (filesystem, sorted(actual)))

    for field in HASH_FIELDS:
        if field not in device:
            errors.append("missing hash field: %s" % field)

    if device.get("fingerprint_version") != 2:
        errors.append("expected fingerprint_version=2, got %r" % device.get("fingerprint_version"))

    return errors, warnings


def load_profile_results(results_dir, suite):
    profile_names = suite.get("profiles") or []
    mapping = {}
    for path in iter_result_files(results_dir):
        name = profile_name_from_path(path)
        if name in profile_names or len(profile_names) == 0:
            mapping[name] = path
    return mapping


def compare_profiles(mapping, comparison):
    errors = []
    profiles = comparison.get("profiles") or []
    devices = {}
    for profile_name in profiles:
        path = mapping.get(profile_name)
        if not path:
            errors.append("missing result for comparison profile: %s" % profile_name)
            continue
        document = load_json(path)
        device, _ = pick_primary_device(document)
        if device is None:
            errors.append("no device in result: %s" % profile_name)
            continue
        devices[profile_name] = device

    for field in comparison.get("same_hashes") or []:
        values = [devices[name].get(field) for name in profiles if name in devices]
        if values and len(set(values)) != 1:
            errors.append(
                "comparison %s expected same %s, got %r"
                % (comparison.get("name"), field, values)
            )

    for field in comparison.get("different_hashes") or []:
        values = [devices[name].get(field) for name in profiles if name in devices]
        if values and len(set(values)) < 2:
            errors.append(
                "comparison %s expected different %s, got %r"
                % (comparison.get("name"), field, values)
            )

    return errors


def check_repeatability(mapping, profile_name):
    path = mapping.get(profile_name)
    if not path:
        return ["missing repeatability result: %s" % profile_name]
    document = load_json(path)
    observations = usb_observations(document)
    if len(observations) < 2:
        return ["repeatability profile %s needs >= 2 observations in one scan file" % profile_name]
    first = observations[0].get("device") or {}
    second = observations[1].get("device") or {}
    errors = []
    for field in HASH_FIELDS:
        if first.get(field) != second.get(field):
            errors.append(
                "repeatability %s: %s differs (%s vs %s)"
                % (profile_name, field, first.get(field), second.get(field))
            )
    return errors


def analyze_file(path):
    profile_name = profile_name_from_path(path)
    document = load_json(path)
    device, observations = pick_primary_device(document)
    if device is None:
        return profile_name, ["no observations/device in %s" % path], []

    errors, warnings = check_expectation(profile_name, device, observations[0])
    if not device.get("hardware_stable_sha256"):
        errors.append("probe output looks incomplete")
    return profile_name, errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Analyze FlashControl probe results for FlashGenerator profiles")
    parser.add_argument("path", help="result file or directory")
    parser.add_argument("--suite", default=DEFAULT_SUITE, help="path to test_suite.json")
    args = parser.parse_args()

    suite = load_json(args.suite) if os.path.isfile(args.suite) else {"profiles": [], "comparisons": []}

    if os.path.isfile(args.path):
        files = [args.path]
    else:
        files = iter_result_files(args.path)

    if not files:
        print("No result files found in %s" % args.path)
        return 1

    total_errors = []
    total_warnings = []
    checked = 0

    print("Analyzing %d result file(s)" % len(files))
    print("")

    for path in files:
        profile_name, errors, warnings = analyze_file(path)
        checked += 1
        status = "OK" if not errors else "FAIL"
        print("[%s] %s (%s)" % (status, profile_name, path))
        for warning in warnings:
            print("  warn:", warning)
            total_warnings.append("%s: %s" % (profile_name, warning))
        for error in errors:
            print("  error:", error)
            total_errors.append("%s: %s" % (profile_name, error))

    if os.path.isdir(args.path):
        mapping = load_profile_results(args.path, suite)
        missing = [
            name for name in (suite.get("profiles") or [])
            if name not in mapping and name not in (suite.get("manual_profiles") or [])
        ]
        for profile_name in missing:
            msg = "missing automated result for profile: %s" % profile_name
            print("[FAIL] %s" % msg)
            total_errors.append(msg)

        for comparison in suite.get("comparisons") or []:
            comparison_errors = compare_profiles(mapping, comparison)
            name = comparison.get("name") or "comparison"
            if comparison_errors:
                print("[FAIL] comparison %s" % name)
                for error in comparison_errors:
                    print("  error:", error)
                    total_errors.append("%s: %s" % (name, error))
            else:
                print("[OK] comparison %s" % name)

        for profile_name in suite.get("repeatability_profiles") or []:
            repeat_path = mapping.get(profile_name)
            if repeat_path:
                repeat_errors = check_repeatability(mapping, profile_name)
                if repeat_errors:
                    print("[FAIL] repeatability %s" % profile_name)
                    for error in repeat_errors:
                        print("  error:", error)
                        total_errors.append(error)
                else:
                    print("[OK] repeatability %s" % profile_name)

    print("")
    print("Checked files: %d" % checked)
    print("Warnings: %d" % len(total_warnings))
    print("Errors: %d" % len(total_errors))
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
