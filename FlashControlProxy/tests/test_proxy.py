import os
import json
import shutil
import tempfile
import unittest
import uuid

import httpx
from fastapi.testclient import TestClient


TEST_DIRECTORY = tempfile.mkdtemp(prefix="flashcontrol-proxy-")
os.environ["FLASHCONTROL_PROXY_QUEUE"] = os.path.join(TEST_DIRECTORY, "proxy.db")
os.environ["FLASHCONTROL_PROXY_AGENT_TOKEN"] = "agent-secret"
os.environ["FLASHCONTROL_PROXY_ALLOWED_NETWORKS"] = "127.0.0.0/8"

import FlashControlProxy.app as proxy_module
from FlashControlProxy.app import app, queue


class ProxyApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(app, client=("127.0.0.1", 50000))
        cls.client = cls.context.__enter__()
        cls.agent_id = uuid.uuid4()
        cls.headers = {
            "X-FlashControl-Machine-ID": str(cls.agent_id),
            "X-FlashControl-Machine-Kind": "agent",
            "X-FlashControl-Machine-Token": "agent-secret",
        }

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def test_observation_is_durable_before_accepted(self):
        payload = {"event_id": str(uuid.uuid4()), "schema_version": 1}
        before = queue.count()
        response = self.client.post("/api/v1/observations", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(queue.count(), before + 1)
        duplicate = self.client.post("/api/v1/observations", json=payload, headers=self.headers)
        self.assertEqual(duplicate.status_code, 202)
        self.assertEqual(queue.count(), before + 1)

    def test_shared_observation_envelope_is_expanded(self):
        first = str(uuid.uuid4())
        second = str(uuid.uuid4())
        payload = {
            "schema_version": 1,
            "host": {"hostname": "proxy-host"},
            "session": {"sid": "S-1-5-21-proxy"},
            "observations": [
                {"event": {"id": first}},
                {"event": {"id": second}},
            ],
        }
        before = queue.count()
        response = self.client.post("/api/v1/observations", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(queue.count(), before + 2)
        stored = [
            json.loads(item["payload_json"])
            for item in queue.due()
            if item["kind"] == "observation"
        ]
        matching = [item for item in stored if item.get("event", {}).get("id") in (first, second)]
        self.assertEqual(len(matching), 2)
        self.assertTrue(all(item.get("host", {}).get("hostname") == "proxy-host" for item in matching))

    def test_heartbeat_is_replaced_and_identity_is_checked(self):
        payload = {"agent_id": str(self.agent_id), "queue_size": 2}
        self.assertEqual(
            self.client.post("/api/v1/agents/heartbeat", json=payload, headers=self.headers).status_code,
            202,
        )
        payload["queue_size"] = 1
        self.client.post("/api/v1/agents/heartbeat", json=payload, headers=self.headers)
        heartbeats = [item for item in queue.due() if item["kind"] == "heartbeat"]
        self.assertEqual(len(heartbeats), 1)
        self.assertIn('"queue_size":1', heartbeats[0]["payload_json"])

    def test_invalid_token_is_rejected(self):
        headers = dict(self.headers, **{"X-FlashControl-Machine-Token": "wrong"})
        response = self.client.post(
            "/api/v1/observations", json={"event_id": str(uuid.uuid4())}, headers=headers
        )
        self.assertEqual(response.status_code, 401)


class ProxyForwardingTests(unittest.IsolatedAsyncioTestCase):
    async def test_forwarding_authenticates_proxy_and_acknowledges_only_success(self):
        agent_id = uuid.uuid4()
        event_id = uuid.uuid4()
        queue.enqueue_observations(agent_id, {"event_id": str(event_id)})
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"accepted": 1})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            original_observations = proxy_module.MAIN_OBSERVATIONS_URL
            original_heartbeat = proxy_module.MAIN_HEARTBEAT_URL
            proxy_module.MAIN_OBSERVATIONS_URL = "https://main/api/v1/observations"
            proxy_module.MAIN_HEARTBEAT_URL = "https://main/api/v1/agents/heartbeat"
            try:
                await proxy_module.forward_once(client)
            finally:
                proxy_module.MAIN_OBSERVATIONS_URL = original_observations
                proxy_module.MAIN_HEARTBEAT_URL = original_heartbeat
        matching = [request for request in seen if str(event_id).encode() in request.content]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].headers["X-FlashControl-Machine-Kind"], "proxy")
        self.assertEqual(matching[0].headers["X-FlashControl-Forwarded-Agent-ID"], str(agent_id))


if __name__ == "__main__":
    unittest.main()


def tearDownModule():
    queue.close()
    shutil.rmtree(TEST_DIRECTORY, ignore_errors=True)
