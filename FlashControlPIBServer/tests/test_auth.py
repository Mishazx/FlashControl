import os
import subprocess
import sys
import unittest


class PasswordHashTests(unittest.TestCase):
    def test_scrypt_hash_is_salted_and_verifies(self):
        from app.auth import hash_password, verify_password

        first = hash_password("long test password one")
        second = hash_password("long test password one")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("long test password one", first))
        self.assertFalse(verify_password("wrong test password", first))
        self.assertFalse(verify_password("anything", "malformed"))

    def test_short_password_is_rejected(self):
        from app.auth import hash_password

        with self.assertRaises(ValueError):
            hash_password("too-short")


class ProductionConfigurationTests(unittest.TestCase):
    def run_config(self, **values):
        environment = os.environ.copy()
        for name in (
            "FLASHCONTROL_ENVIRONMENT", "FLASHCONTROL_DATABASE_URL", "FLASHCONTROL_LOG_LEVEL",
            "FLASHCONTROL_SESSION_HOURS", "FLASHCONTROL_MACHINE_AUTH_MODE",
            "FLASHCONTROL_DEV_MACHINE_TOKEN", "FLASHCONTROL_TRUSTED_PROXIES",
            "FLASHCONTROL_TRUSTED_MTLS_PROXIES", "FLASHCONTROL_MTLS_IDENTITIES",
            "FLASHCONTROL_ENROLL_NETWORKS",
        ):
            environment.pop(name, None)
        environment.update(values)
        return subprocess.run(
            [sys.executable, "-c", "import app.config"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env=environment,
            capture_output=True,
            text=True,
        )

    def test_production_rejects_sqlite(self):
        result = self.run_config(
            FLASHCONTROL_ENVIRONMENT="production",
            FLASHCONTROL_DATABASE_URL="sqlite:///./flashcontrol-dev.db",
            FLASHCONTROL_MACHINE_AUTH_MODE="mtls",
            FLASHCONTROL_TRUSTED_MTLS_PROXIES="127.0.0.1/32",
            FLASHCONTROL_MTLS_IDENTITIES='{"aabb":"agent:11111111-1111-1111-1111-111111111111"}',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SQLite is not allowed in production", result.stderr)

    def test_production_accepts_postgres_and_mtls(self):
        result = self.run_config(
            FLASHCONTROL_ENVIRONMENT="production",
            FLASHCONTROL_DATABASE_URL="postgresql+psycopg://example",
            FLASHCONTROL_MACHINE_AUTH_MODE="mtls",
            FLASHCONTROL_TRUSTED_MTLS_PROXIES="127.0.0.1/32",
            FLASHCONTROL_MTLS_IDENTITIES='{"aabb":"agent:11111111-1111-1111-1111-111111111111"}',
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
