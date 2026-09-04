import os
import time
import unittest
from unittest import mock

os.environ.setdefault("FLASHCONTROL_ENVIRONMENT", "test")
os.environ.setdefault("FLASHCONTROL_DEV_MACHINE_TOKEN", "test-machine-token")

from fastapi import HTTPException  # noqa: E402

from app.ratelimit import RateLimiter  # noqa: E402


class FakeClient:
    def __init__(self, host):
        self.host = host


class FakeRequest:
    def __init__(self, host):
        self.client = FakeClient(host)


class RateLimiterTests(unittest.TestCase):
    def test_allows_requests_under_limit(self):
        limiter = RateLimiter(name="t", limit=3, window=10)
        request = FakeRequest("127.0.0.1")
        for _ in range(3):
            limiter.check(request)

    def test_rejects_requests_over_limit(self):
        limiter = RateLimiter(name="t", limit=3, window=10)
        request = FakeRequest("127.0.0.1")
        for _ in range(3):
            limiter.check(request)
        with self.assertRaises(HTTPException) as ctx:
            limiter.check(request)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_keys_are_per_client(self):
        limiter = RateLimiter(name="t", limit=2, window=10)
        limiter.check(FakeRequest("10.0.0.1"))
        limiter.check(FakeRequest("10.0.0.1"))
        with self.assertRaises(HTTPException):
            limiter.check(FakeRequest("10.0.0.1"))
        # A different client has its own independent budget.
        limiter.check(FakeRequest("10.0.0.2"))
        limiter.check(FakeRequest("10.0.0.2"))

    def test_window_expiry_allows_requests_again(self):
        limiter = RateLimiter(name="t", limit=2, window=1)
        request = FakeRequest("127.0.0.1")
        limiter.check(request)
        limiter.check(request)
        with self.assertRaises(HTTPException):
            limiter.check(request)
        time.sleep(1.1)
        limiter.check(request)

    def test_make_limiter_wired_dependency(self):
        from app import ratelimit as ratelimit_module

        dependency = ratelimit_module.make_limiter(name="t", limit=1, window=10)
        request = FakeRequest("127.0.0.1")
        with mock.patch.object(ratelimit_module, "ENVIRONMENT", "production"):
            dependency(request)
            with self.assertRaises(HTTPException) as ctx:
                dependency(request)
            self.assertEqual(ctx.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
