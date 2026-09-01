import datetime
import unittest

from app.identity import classify_pair


class FakeObservation(object):
    def __init__(self, hardware, media, computer, device=None):
        self.hardware_stable_sha256 = hardware
        self.media_identity_sha256 = media
        self.computer_id = computer
        self.device = device or {}


class IdentityRuleTests(unittest.TestCase):
    def test_same_host_hardware_and_media_is_same(self):
        left = FakeObservation("hardware-a", "media-a", "computer-a")
        right = FakeObservation("hardware-a", "media-a", "computer-a")
        result = classify_pair(left, right)
        self.assertEqual(result.result, "SAME")
        self.assertTrue(result.auto_link)

    def test_same_media_with_different_hardware_is_clone_suspected(self):
        left = FakeObservation("hardware-a", "media-a", "computer-a")
        right = FakeObservation("hardware-b", "media-a", "computer-a")
        result = classify_pair(left, right)
        self.assertEqual(result.result, "CLONE_SUSPECTED")
        self.assertFalse(result.auto_link)

    def test_matching_evidence_on_different_computer_is_only_likely(self):
        left = FakeObservation("hardware-a", "media-a", "computer-a")
        right = FakeObservation("hardware-a", "media-a", "computer-b")
        result = classify_pair(left, right)
        self.assertEqual(result.result, "LIKELY_SAME")
        self.assertFalse(result.auto_link)

    def test_matching_serial_with_different_hardware_is_collision(self):
        device_a = {"storage": {"serial": "CHEAP-SERIAL"}}
        device_b = {"storage": {"serial": "CHEAP-SERIAL"}}
        left = FakeObservation("hardware-a", "media-a", "computer-a", device_a)
        right = FakeObservation("hardware-b", "media-b", "computer-b", device_b)
        result = classify_pair(left, right)
        self.assertEqual(result.result, "SERIAL_COLLISION")
        self.assertFalse(result.auto_link)

    def test_matching_hardware_with_changed_media_stays_unknown(self):
        left = FakeObservation("hardware-a", "media-a", "computer-a")
        right = FakeObservation("hardware-a", "media-b", "computer-a")
        result = classify_pair(left, right)
        self.assertEqual(result.result, "UNKNOWN")
        self.assertFalse(result.auto_link)

    def test_vpd83_match_requires_consistent_hardware(self):
        device = {"vpd83": [{"value": "naa.1234"}]}
        left = FakeObservation("hardware-a", "media-a", "computer-a", device)
        right = FakeObservation("hardware-b", "media-a", "computer-a", device)
        result = classify_pair(left, right)
        self.assertNotEqual(result.result, "SAME")
        self.assertFalse(result.auto_link)


if __name__ == "__main__":
    unittest.main()
