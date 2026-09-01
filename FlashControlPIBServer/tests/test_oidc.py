import datetime
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from joserfc import jwk, jwt

class OidcFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorization_url_contains_pkce_state_and_nonce(self):
        from app import oidc

        metadata = {
            "authorization_endpoint": "https://idp.example/authorize",
            "token_endpoint": "https://idp.example/token",
            "jwks_uri": "https://idp.example/keys",
            "issuer": "https://idp.example",
        }
        with patch.object(oidc, "discovery", AsyncMock(return_value=metadata)), \
             patch.object(oidc, "OIDC_CLIENT_ID", "flashcontrol"):
            url = await oidc.authorization_url(
                "state-value", "nonce-value", "v" * 64,
                "https://flash.example/api/v1/auth/oidc/callback",
            )
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["state"], ["state-value"])
        self.assertEqual(query["nonce"], ["nonce-value"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotEqual(query["code_challenge"], ["v" * 64])

    async def test_id_token_signature_and_claims_are_validated(self):
        from app import oidc

        key = jwk.RSAKey.generate_key(2048, auto_kid=True)
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        claims = {
            "iss": "https://idp.example", "sub": "user-1", "aud": "flashcontrol",
            "iat": now, "exp": now + 300, "nonce": "expected-nonce",
        }
        encoded = jwt.encode({"alg": "RS256", "kid": key.kid}, claims, key)
        metadata = {"jwks_uri": "https://idp.example/keys"}
        public_set = {"keys": [key.as_dict(private=False)]}
        with patch.object(oidc, "OIDC_ISSUER", "https://idp.example"), \
             patch.object(oidc, "OIDC_CLIENT_ID", "flashcontrol"), \
             patch.object(oidc, "_jwks_cache", None), \
             patch.object(oidc, "_get_json", AsyncMock(return_value=public_set)):
            result = await oidc.validate_id_token(encoded, "expected-nonce", metadata)
            self.assertEqual(result["sub"], "user-1")
            with self.assertRaises(oidc.OidcError):
                await oidc.validate_id_token(encoded, "wrong-nonce", metadata)


class OidcRoleTests(unittest.TestCase):
    def test_strongest_matching_role_wins_and_unknown_is_denied(self):
        from app.auth import role_for_groups

        with patch("app.auth.OIDC_ADMIN_GROUPS", frozenset({"admins"})), \
             patch("app.auth.OIDC_SECURITY_GROUPS", frozenset({"security"})), \
             patch("app.auth.OIDC_AUDITOR_GROUPS", frozenset({"auditors"})), \
             patch("app.auth.OIDC_DEFAULT_ROLE", ""):
            self.assertEqual(role_for_groups(["AUDITORS", "Admins"]), "admin")
            self.assertIsNone(role_for_groups(["unmapped"]))


if __name__ == "__main__":
    unittest.main()
