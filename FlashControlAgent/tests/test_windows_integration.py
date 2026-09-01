import os
import unittest


from probe_support import probe


RUN_INTEGRATION = os.environ.get("FLASHCONTROL_INTEGRATION") == "1"


@unittest.skipUnless(os.name == "nt" and RUN_INTEGRATION, "integration tests are disabled")
class WindowsIntegrationTests(unittest.TestCase):
    def test_scan_physical_disks_runs_read_only(self):
        devices, errors = probe.scan_physical_disks(max_disks=2, include_non_usb=True)
        self.assertIsInstance(devices, list)
        self.assertIsInstance(errors, list)

    def test_host_info_runs_without_local_users(self):
        info = probe.host_info(include_diagnostics=False)
        self.assertIn("hostname", info)
        self.assertNotIn("local_users", info)


if __name__ == "__main__":
    unittest.main()
