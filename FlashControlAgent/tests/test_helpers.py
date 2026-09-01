import unittest


from probe_support import probe


class HelperTests(unittest.TestCase):
    def test_clean_ascii_handles_nul_and_empty_values(self):
        self.assertEqual(probe.clean_ascii(b"FLASH\x00TRAIL"), "FLASH")
        self.assertIsNone(probe.clean_ascii(b""))
        self.assertIsNone(probe.clean_ascii(None))

    def test_clean_ascii_replaces_non_ascii_bytes(self):
        self.assertEqual(probe.clean_ascii(b"\xff"), "\ufffd")

    def test_c_string_at_offset_handles_valid_and_invalid_offsets(self):
        buf = b"\x00VENDOR\x00PRODUCT\x00"
        self.assertIsNone(probe.c_string_at_offset(buf, 0))
        self.assertEqual(probe.c_string_at_offset(buf, 1), "VENDOR")
        self.assertIsNone(probe.c_string_at_offset(buf, -1))
        self.assertIsNone(probe.c_string_at_offset(buf, len(buf)))

    def test_unique_sorted_deduplicates_and_drops_empty_values(self):
        self.assertEqual(
            probe.unique_sorted(["beta", "", "alpha", "beta", None, "gamma", "alpha"]),
            ["alpha", "beta", "gamma"],
        )

    def test_error_status_classifies_win32_codes(self):
        self.assertEqual(probe.error_status(probe.ERROR_FILE_NOT_FOUND), "not_found")
        self.assertEqual(probe.error_status(probe.ERROR_PATH_NOT_FOUND), "not_found")
        self.assertEqual(probe.error_status(probe.ERROR_ACCESS_DENIED), "access_denied")
        self.assertEqual(probe.error_status(probe.ERROR_NOT_SUPPORTED), "unsupported")
        self.assertEqual(
            probe.error_status(probe.ERROR_INVALID_PARAMETER),
            "unsupported_or_invalid",
        )
        self.assertEqual(probe.error_status(123456), "collector_failed")

    def test_normalize_collector_error_preserves_details_and_collector(self):
        error = {
            "winerror": 87,
            "message": "bad parameter",
            "status": "unsupported_or_invalid",
        }
        normalized = probe.normalize_collector_error("vpd83", error)
        self.assertEqual(normalized["collector"], "vpd83")
        self.assertEqual(normalized["winerror"], 87)
        self.assertEqual(normalized["message"], "bad parameter")
        self.assertEqual(normalized["status"], "unsupported_or_invalid")

    def test_normalize_collector_error_wraps_plain_values(self):
        normalized = probe.normalize_collector_error("storage", "boom")
        self.assertEqual(normalized["collector"], "storage")
        self.assertEqual(normalized["message"], "boom")
        self.assertEqual(normalized["status"], "invalid_data")

    def test_run_collector_turns_exception_into_structured_error(self):
        def boom():
            raise ValueError("kaboom")

        data, error = probe.run_collector("geometry", boom)
        self.assertIsNone(data)
        self.assertEqual(error["collector"], "geometry")
        self.assertEqual(error["status"], "collector_failed")
        self.assertIn("ValueError", error["message"])


if __name__ == "__main__":
    unittest.main()
