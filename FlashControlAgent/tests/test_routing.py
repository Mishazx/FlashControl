# -*- coding: utf-8 -*-

import os
import sys
import unittest

AGENT_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT_DIRECTORY not in sys.path:
    sys.path.insert(0, AGENT_DIRECTORY)

from routing import select_proxy


class RoutingTests(unittest.TestCase):
    def test_longest_matching_prefix_wins(self):
        broad = {"id": "broad", "server_url": "https://broad", "networks": ["10.0.0.0/8"]}
        site = {"id": "site", "server_url": "https://site", "networks": ["10.20.0.0/16"]}
        self.assertEqual(select_proxy([broad, site], ["10.20.30.40"])["id"], "site")

    def test_invalid_and_nonmatching_networks_are_ignored(self):
        proxies = [{"id": "bad", "server_url": "https://bad", "networks": ["invalid"]}]
        self.assertIsNone(select_proxy(proxies, ["192.168.1.2", "invalid-ip"]))


if __name__ == "__main__":
    unittest.main()
