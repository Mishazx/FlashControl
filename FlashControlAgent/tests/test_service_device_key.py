import os
import sys
import unittest


AGENT_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT_DIRECTORY not in sys.path:
    sys.path.insert(0, AGENT_DIRECTORY)


try:
    import servicemanager  # noqa: F401
except ImportError:
    raise unittest.SkipTest("requires PyWin32 service modules")

import service


class ServiceDeviceKeyTests(unittest.TestCase):
    def test_prefers_current_hardware_hash(self):
        self.assertEqual(
            service.device_key({"hashes": {"hardware": "current", "hardware_stable": "old"}}),
            "hardware:current",
        )

    def test_accepts_legacy_hardware_hash_for_queued_observations(self):
        self.assertEqual(
            service.device_key({"hashes": {"hardware_stable": "legacy"}}),
            "hardware:legacy",
        )
