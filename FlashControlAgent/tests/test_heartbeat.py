# -*- coding: utf-8 -*-

from __future__ import print_function

import os
import shutil
import sys
import tempfile
import unittest
import uuid

AGENT_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT_DIRECTORY not in sys.path:
    sys.path.insert(0, AGENT_DIRECTORY)

from heartbeat import build_heartbeat, heartbeat_url, load_or_create_agent_id


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="flashcontrol-agent-id-")

    def tearDown(self):
        shutil.rmtree(self.folder)

    def test_agent_id_is_generated_once_and_persisted(self):
        path = os.path.join(self.folder, "agent.id")
        first = load_or_create_agent_id(path)
        second = load_or_create_agent_id(path)
        self.assertEqual(first, second)
        self.assertEqual(str(uuid.UUID(first)), first)

    def test_heartbeat_url_is_derived_only_from_known_ingest_path(self):
        self.assertEqual(
            heartbeat_url("https://main/api/v1/observations"),
            "https://main/api/v1/agents/heartbeat",
        )
        self.assertEqual(heartbeat_url("https://main/custom"), "")

    def test_heartbeat_contains_health_and_host_data(self):
        result = build_heartbeat(
            str(uuid.uuid4()), "0.4.0", 7,
            {"hostname": "pc-1", "domain_name": "CORP", "ip_addresses": ["10.0.0.1"]},
        )
        self.assertEqual(result["hostname"], "pc-1")
        self.assertEqual(result["domain"], "CORP")
        self.assertEqual(result["current_ips"], ["10.0.0.1"])
        self.assertEqual(result["queue_size"], 7)


if __name__ == "__main__":
    unittest.main()
