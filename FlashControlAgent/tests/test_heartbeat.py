# -*- coding: utf-8 -*-

from __future__ import print_function

import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid

AGENT_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT_DIRECTORY not in sys.path:
    sys.path.insert(0, AGENT_DIRECTORY)

from heartbeat import (
    build_enroll_payload,
    build_heartbeat,
    delivery_credentials_configured,
    enroll_url,
    heartbeat_url,
    host_from_observation,
    load_or_create_agent_id,
    persist_agent_id,
    persist_secret,
)


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

    def test_persist_agent_id_can_override_existing_value(self):
        path = os.path.join(self.folder, "agent.id")
        load_or_create_agent_id(path)
        requested = "11111111-1111-1111-1111-111111111111"
        self.assertEqual(persist_agent_id(path, requested), requested)
        self.assertEqual(load_or_create_agent_id(path), requested)

    def test_delivery_credentials_require_token_or_client_certificate(self):
        self.assertFalse(delivery_credentials_configured({}))
        self.assertTrue(delivery_credentials_configured({"machine_token": "secret"}))
        self.assertTrue(delivery_credentials_configured({"client_cert_file": "agent.pem"}))
        token_path = os.path.join(self.folder, "agent.token")
        persist_secret(token_path, "issued-token")
        self.assertTrue(delivery_credentials_configured({"machine_token_file": token_path}))

    def test_enroll_url_is_derived_from_known_ingest_path(self):
        self.assertEqual(
            enroll_url("https://main/api/v1/observations"),
            "https://main/api/v1/agents/enroll",
        )
        payload = build_enroll_payload(
            "11111111-1111-1111-1111-111111111111",
            "0.4.0",
            {"hostname": "pc-1", "domain_name": "CORP", "ip_addresses": ["10.0.0.1"]},
        )
        self.assertEqual(payload["hostname"], "pc-1")
        self.assertEqual(payload["domain"], "CORP")
        self.assertEqual(payload["current_ips"], ["10.0.0.1"])

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

    def test_host_is_read_from_shared_batch_envelope(self):
        payload = json.dumps({
            "host": {"hostname": "batch-pc", "ip_addresses": ["10.0.0.8"]},
            "observations": [
                {"event": {"id": "11111111-1111-1111-1111-111111111111"}},
            ],
        })
        self.assertEqual(
            host_from_observation(payload)["hostname"],
            "batch-pc",
        )


if __name__ == "__main__":
    unittest.main()
