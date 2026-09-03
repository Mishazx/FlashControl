# -*- coding: utf-8 -*-

from __future__ import print_function

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import patch


AGENT_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
for path in (TESTS_DIRECTORY, AGENT_DIRECTORY):
    if path not in sys.path:
        sys.path.insert(0, path)

from probe_support import base_record, probe
import dump


class DumpTests(unittest.TestCase):
    def _run_dump(self, argv, devices, errors=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.object(probe, "scan_physical_disks", return_value=(devices, errors or [])))
            stack.enter_context(patch.object(probe, "host_info", return_value={"hostname": "TEST-PC"}))
            stack.enter_context(patch.object(probe, "collect_active_session", return_value={"sid": "S-1-5-21-test"}))
            stack.enter_context(patch.object(probe, "utc_now_iso", return_value="2026-09-03T10:00:00Z"))
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            status = dump.main(argv)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_dump_writes_observation_payload_file(self):
        out_dir = tempfile.mkdtemp(prefix="flashcontrol-dump-")
        out_path = os.path.join(out_dir, "payload.json")
        try:
            status, stdout, stderr = self._run_dump(
                ["--out", out_path, "--no-pause"],
                [base_record()],
            )
            self.assertEqual(status, 0)
            with open(out_path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
            self.assertEqual(document["host"]["hostname"], "TEST-PC")
            self.assertEqual(document["session"]["sid"], "S-1-5-21-test")
            self.assertEqual(document["device"]["serial"], "STOR123")
            self.assertEqual(document["schema_version"], 1)
            self.assertIn("event", document)
            self.assertNotIn("observations", document)
            self.assertNotIn("scan_id", document)
            self.assertIn("STOR123", stderr)
            self.assertNotIn("hostname", stdout)
            self.assertNotIn("STOR123", stdout)
        finally:
            try:
                os.remove(out_path)
                os.rmdir(out_dir)
            except OSError:
                pass

    def test_dump_empty_scan_still_writes_file(self):
        out_dir = tempfile.mkdtemp(prefix="flashcontrol-dump-empty-")
        out_path = os.path.join(out_dir, "payload.json")
        try:
            status, _stdout, stderr = self._run_dump(
                ["--out", out_path, "--no-pause"],
                [],
            )
            self.assertEqual(status, 0)
            with open(out_path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
            self.assertEqual(document["observations"], [])
            self.assertIn("No USB flash drives found", stderr)
        finally:
            try:
                os.remove(out_path)
                os.rmdir(out_dir)
            except OSError:
                pass

    def test_dump_two_devices_hoists_shared_host_context(self):
        out_dir = tempfile.mkdtemp(prefix="flashcontrol-dump-two-")
        out_path = os.path.join(out_dir, "payload.json")
        second = base_record()
        second["physical_drive"] = 8
        second["storage"] = dict(second["storage"], serial="STOR456")
        second["pnp"]["usb"]["vid"] = "125F"
        try:
            status, _stdout, stderr = self._run_dump(
                ["--out", out_path, "--no-pause"],
                [base_record(), second],
            )
            self.assertEqual(status, 0)
            with open(out_path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
            self.assertEqual(document["schema_version"], 1)
            self.assertEqual(document["host"]["hostname"], "TEST-PC")
            self.assertEqual(document["session"]["sid"], "S-1-5-21-test")
            self.assertEqual(len(document["observations"]), 2)
            self.assertNotIn("host", document["observations"][0])
            self.assertNotIn("session", document["observations"][0])
            self.assertNotIn("schema_version", document["observations"][0])
            self.assertEqual(document["observations"][0]["device"]["serial"], "STOR123")
            self.assertEqual(document["observations"][1]["device"]["serial"], "STOR456")
            self.assertIn("STOR123", stderr)
            self.assertIn("STOR456", stderr)
        finally:
            try:
                os.remove(out_path)
                os.rmdir(out_dir)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
