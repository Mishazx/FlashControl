import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
import uuid


from probe_support import base_record, copy_record, probe


def make_watch_device(interface_path, physical_drive=7, vid="1234", pid="5678"):
    device = copy_record(base_record())
    device["physical_drive"] = physical_drive
    device["path"] = r"\\.\PhysicalDrive%d" % physical_drive
    device["pnp"]["device_interface_path"] = interface_path
    device["pnp"]["usb"]["device_instance_id"] = "USB\\VID_%s&PID_%s\\SERIAL" % (vid, pid)
    device["pnp"]["usb"]["vid"] = vid
    device["pnp"]["usb"]["pid"] = pid
    return device


class WatchHelperTests(unittest.TestCase):
    def test_watch_interval_from_argv_parses_and_clamps(self):
        self.assertEqual(probe.watch_interval_from_argv([]), 2.0)
        self.assertEqual(probe.watch_interval_from_argv(["--watch-interval=5"]), 5.0)
        self.assertEqual(probe.watch_interval_from_argv(["--watch-interval", "3.5"]), 3.5)
        self.assertEqual(probe.watch_interval_from_argv(["--watch-interval=0.1"]), 0.25)

    def test_device_presence_key_prefers_interface_path(self):
        device = make_watch_device(r"\\?\USB#VID_1234&PID_5678#ABCDEF")
        self.assertEqual(
            probe.device_presence_key(device),
            r"\\?\USB#VID_1234&PID_5678#ABCDEF".strip().upper(),
        )
        device["pnp"].pop("device_interface_path")
        self.assertEqual(probe.device_presence_key(device), r"\\.\PHYSICALDRIVE7")

    def test_usb_presence_keys_filters_and_normalizes_paths(self):
        disks = {
            7: {"usb": True, "device_interface_path": r"\\?\USB#VID_1234&PID_5678#ABCDEF"},
            8: {"usb": False, "device_interface_path": r"\\?\USB#VID_DEAD&PID_BEEF#NOPE"},
            9: {"usb": True, "device_interface_path": r"\\?\USB#VID_1234&PID_5678#ABCDEF"},
        }
        with patch.object(probe, "run_collector", return_value=(disks, None)):
            keys, error = probe.usb_presence_keys()

        self.assertIsNone(error)
        self.assertEqual(keys, {r"\\?\USB#VID_1234&PID_5678#ABCDEF".strip().upper()})


class WatchUsbTests(unittest.TestCase):
    def test_watch_usb_emits_snapshot_disconnect_and_connect_events(self):
        initial_device = make_watch_device(r"\\?\USB#VID_1234&PID_5678#A")
        connected_device = make_watch_device(r"\\?\USB#VID_1234&PID_5678#B", physical_drive=8, vid="9999", pid="8888")

        uuid_values = iter([
            uuid.UUID("11111111-1111-1111-1111-111111111111"),
            uuid.UUID("22222222-2222-2222-2222-222222222222"),
            uuid.UUID("33333333-3333-3333-3333-333333333333"),
        ])

        with patch.object(probe, "scan_physical_disks", side_effect=[([initial_device], []), ([connected_device], [])]), \
            patch.object(probe, "usb_presence_keys", side_effect=[({probe.device_presence_key(connected_device)}, None)]), \
            patch.object(probe, "host_info", return_value={"hostname": "host", "computer_name": "host"}), \
            patch.object(probe, "collect_active_session", return_value={"session_id": 1, "sid": "S-1-5-21-123"}), \
            patch.object(probe, "utc_now_iso", return_value="2026-09-01T12:00:00.000000Z"), \
            patch.object(probe.uuid, "uuid4", side_effect=lambda: next(uuid_values)), \
            patch.object(probe.time, "sleep", side_effect=[None, KeyboardInterrupt]):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                probe.watch_usb()

        events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual([event["event"]["type"] for event in events], ["snapshot", "disconnected", "connected"])
        self.assertEqual(events[0]["device"]["vid"], "1234")
        self.assertEqual(events[1]["device"]["vid"], "1234")
        self.assertEqual(events[2]["device"]["vid"], "9999")
        self.assertNotIn("pnp", events[0]["device"])
        self.assertNotIn("event_id", events[0])

    def test_watch_usb_survives_presence_errors(self):
        initial_device = make_watch_device(r"\\?\USB#VID_1234&PID_5678#A")
        uuid_values = iter([
            uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ])

        with patch.object(probe, "scan_physical_disks", return_value=([initial_device], [])), \
            patch.object(probe, "usb_presence_keys", side_effect=[(None, {"message": "boom"})]), \
            patch.object(probe, "host_info", return_value={"hostname": "host", "computer_name": "host"}), \
            patch.object(probe, "collect_active_session", return_value={"session_id": 1, "sid": "S-1-5-21-123"}), \
            patch.object(probe, "utc_now_iso", return_value="2026-09-01T12:00:00.000000Z"), \
            patch.object(probe.uuid, "uuid4", side_effect=lambda: next(uuid_values)), \
            patch.object(probe.time, "sleep", side_effect=[None, KeyboardInterrupt]):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                probe.watch_usb()

        events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual([event["event"]["type"] for event in events], ["snapshot"])
        self.assertIn("USB presence check failed: boom", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
