# -*- coding: utf-8 -*-

from __future__ import print_function

import json
import os
import shutil
import sys
import tempfile
import unittest

AGENT_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT_DIRECTORY not in sys.path:
    sys.path.insert(0, AGENT_DIRECTORY)

from delivery_queue import DeliveryQueue, QueueFullError, deliver_due


class ManualClock(object):
    def __init__(self, value=1000):
        self.value = value

    def __call__(self):
        return self.value


class DeliveryQueueTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="flashcontrol-queue-")
        self.path = os.path.join(self.folder, "queue.db")
        self.clock = ManualClock()
        self.queue = DeliveryQueue(self.path, max_items=2, clock=self.clock)

    def tearDown(self):
        self.queue.close()
        shutil.rmtree(self.folder)

    def payload(self, event_id):
        return json.dumps({
            "schema_version": 2,
            "probe_version": "0.4.0",
            "event_id": event_id,
        })

    def test_event_survives_reopen_until_acknowledged(self):
        event_id = "11111111-1111-1111-1111-111111111111"
        self.queue.enqueue_json(self.payload(event_id))
        self.queue.close()
        self.queue = DeliveryQueue(self.path, max_items=2, clock=self.clock)

        self.assertEqual(self.queue.count(), 1)
        self.assertEqual(self.queue.due()[0]["event_id"], event_id)
        self.queue.mark_delivered(event_id)
        self.assertEqual(self.queue.count(), 0)

    def test_duplicate_enqueue_is_idempotent(self):
        event_id = "22222222-2222-2222-2222-222222222222"
        self.queue.enqueue_json(self.payload(event_id))
        self.queue.enqueue_json(self.payload(event_id))
        self.assertEqual(self.queue.count(), 1)

    def test_failed_delivery_uses_exponential_backoff(self):
        event_id = "33333333-3333-3333-3333-333333333333"
        self.queue.enqueue_json(self.payload(event_id))
        self.assertEqual(self.queue.mark_failed(event_id, "offline", 30, 60), 30)
        self.assertEqual(self.queue.due(), [])
        self.clock.value += 30
        self.assertEqual(len(self.queue.due()), 1)
        self.assertEqual(self.queue.mark_failed(event_id, "offline", 30, 60), 60)

    def test_queue_limit_never_evicts_existing_audit_events(self):
        self.queue.enqueue_json(self.payload("44444444-4444-4444-4444-444444444444"))
        self.queue.enqueue_json(self.payload("55555555-5555-5555-5555-555555555555"))
        with self.assertRaises(QueueFullError):
            self.queue.enqueue_json(self.payload("66666666-6666-6666-6666-666666666666"))
        self.assertEqual(self.queue.count(), 2)

    def test_offline_then_online_delivers_same_event_once(self):
        event_id = "77777777-7777-7777-7777-777777777777"
        self.queue.enqueue_json(self.payload(event_id))

        def offline(_payload):
            raise IOError("server unavailable")

        self.assertEqual(deliver_due(self.queue, offline, base_delay=10), 0)
        self.assertEqual(self.queue.count(), 1)

        self.clock.value += 10
        received = []

        def online(payload):
            received.append(json.loads(payload)["event_id"])

        self.assertEqual(deliver_due(self.queue, online, base_delay=10), 1)
        self.assertEqual(received, [event_id])
        self.assertEqual(self.queue.count(), 0)
        self.assertEqual(deliver_due(self.queue, online, base_delay=10), 0)
        self.assertEqual(received, [event_id])


if __name__ == "__main__":
    unittest.main()
