# -*- coding: utf-8 -*-

from __future__ import print_function

import os
import sys
import unittest


AGENT_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT_DIRECTORY not in sys.path:
    sys.path.insert(0, AGENT_DIRECTORY)

from observation_payload import expand_observations, pack_observation_payload


class ObservationPayloadTests(unittest.TestCase):
    def test_single_observation_stays_self_contained(self):
        observation = {
            "schema_version": 1,
            "probe_version": "0.4.0",
            "host": {"hostname": "PC"},
            "session": {"sid": "S-1-5-21-x"},
            "event": {"id": "1"},
            "device": {"serial": "A"},
        }
        self.assertEqual(pack_observation_payload([observation]), observation)

    def test_batch_hoists_identical_host_context(self):
        first = {
            "schema_version": 1,
            "probe_version": "0.4.0",
            "host": {"hostname": "PC"},
            "session": {"sid": "S-1-5-21-x"},
            "event": {"id": "1"},
            "device": {"serial": "A"},
        }
        second = dict(first)
        second["event"] = {"id": "2"}
        second["device"] = {"serial": "B"}
        packed = pack_observation_payload([first, second])
        self.assertEqual(packed["host"]["hostname"], "PC")
        self.assertEqual(packed["session"]["sid"], "S-1-5-21-x")
        self.assertNotIn("host", packed["observations"][0])
        self.assertEqual(packed["observations"][0]["device"]["serial"], "A")
        self.assertEqual(packed["observations"][1]["device"]["serial"], "B")
        expanded = expand_observations(packed)
        self.assertEqual(expanded[0]["host"], first["host"])
        self.assertEqual(expanded[1]["device"]["serial"], "B")
        self.assertEqual(expanded[1]["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
