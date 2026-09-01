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
            "FLASHCONTROL_ENVIRONMENT", "FLASHCONTROL_DATABASE_URL",
            "FLASHCONTROL_AUTH_PROVIDER", "FLASHCONTROL_OIDC_ISSUER",
            "FLASHCONTROL_OIDC_CLIENT_ID",
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

    def test_production_rejects_local_auth(self):
        result = self.run_config(
            FLASHCONTROL_ENVIRONMENT="production",
            FLASHCONTROL_DATABASE_URL="postgresql+psycopg://example",
            FLASHCONTROL_AUTH_PROVIDER="local",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be oidc", result.stderr)

    def test_production_requires_oidc_settings(self):
        result = self.run_config(
            FLASHCONTROL_ENVIRONMENT="production",
            FLASHCONTROL_DATABASE_URL="postgresql+psycopg://example",
            FLASHCONTROL_AUTH_PROVIDER="oidc",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("issuer and client ID are required", result.stderr)

    def test_production_accepts_explicit_oidc_settings(self):
        result = self.run_config(
            FLASHCONTROL_ENVIRONMENT="production",
            FLASHCONTROL_DATABASE_URL="postgresql+psycopg://example",
            FLASHCONTROL_AUTH_PROVIDER="oidc",
            FLASHCONTROL_OIDC_ISSUER="https://idp.example/tenant",
            FLASHCONTROL_OIDC_CLIENT_ID="flashcontrol",
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
