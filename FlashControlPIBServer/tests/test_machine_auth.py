import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request


def request(headers, client="127.0.0.1"):
    return Request({
        "type": "http", "method": "POST", "path": "/", "query_string": b"",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "client": (client, 12345), "server": ("test", 80), "scheme": "http",
    })


class MachineMtlsTests(unittest.TestCase):
    def test_verified_enrolled_certificate_resolves_principal(self):
        from app import machine_auth

        agent_id = "11111111-1111-1111-1111-111111111111"
        headers = {
            "X-FlashControl-Client-Verify": "SUCCESS",
            "X-FlashControl-Client-Fingerprint": "AA:BB:CC",
        }
        with patch.object(machine_auth, "MACHINE_AUTH_MODE", "mtls"), \
             patch.object(machine_auth, "TRUSTED_MTLS_PROXIES", ("127.0.0.1/32",)), \
             patch.object(machine_auth, "MTLS_IDENTITIES", {"aabbcc": "agent:" + agent_id}):
            principal = machine_auth.require_machine(request(headers))
        self.assertEqual(str(principal.id), agent_id)
        self.assertEqual(principal.kind, "agent")

    def test_certificate_headers_from_untrusted_peer_are_rejected(self):
        from app import machine_auth

        headers = {
            "X-FlashControl-Client-Verify": "SUCCESS",
            "X-FlashControl-Client-Fingerprint": "AA:BB:CC",
        }
        with patch.object(machine_auth, "MACHINE_AUTH_MODE", "mtls"), \
             patch.object(machine_auth, "TRUSTED_MTLS_PROXIES", ("127.0.0.1/32",)), \
             patch.object(machine_auth, "MTLS_IDENTITIES", {"aabbcc": "agent:11111111-1111-1111-1111-111111111111"}):
            with self.assertRaises(HTTPException) as caught:
                machine_auth.require_machine(request(headers, "10.0.0.50"))
        self.assertEqual(caught.exception.status_code, 401)


class ClientHostTests(unittest.TestCase):
    def test_untrusted_peer_headers_are_ignored(self):
        from app import machine_auth

        incoming = request(
            {"X-Real-IP": "203.0.113.10", "X-Forwarded-For": "198.51.100.20"},
            "8.8.8.8",
        )
        with patch.object(machine_auth, "TRUSTED_PROXIES", ("172.30.0.0/24",)):
            self.assertEqual(machine_auth.client_host(incoming), "8.8.8.8")
            self.assertEqual(str(machine_auth.source_ip(incoming)), "8.8.8.8")

    def test_trusted_nginx_real_ip_is_used_for_audit(self):
        from app import machine_auth

        incoming = request(
            {
                "X-Real-IP": "203.0.113.10",
                "X-Forwarded-For": "198.51.100.20, 203.0.113.10",
            },
            "172.30.0.4",
        )
        with patch.object(machine_auth, "TRUSTED_PROXIES", ("172.30.0.0/24",)):
            self.assertEqual(machine_auth.client_host(incoming), "203.0.113.10")
            self.assertEqual(str(machine_auth.source_ip(incoming)), "172.30.0.4")

    def test_forwarded_for_skips_trusted_hops(self):
        from app import machine_auth

        incoming = request(
            {"X-Forwarded-For": "198.51.100.20, 203.0.113.10, 172.30.0.4"},
            "172.30.0.4",
        )
        with patch.object(machine_auth, "TRUSTED_PROXIES", ("172.30.0.0/24",)):
            self.assertEqual(machine_auth.client_host(incoming), "203.0.113.10")


if __name__ == "__main__":
    unittest.main()
