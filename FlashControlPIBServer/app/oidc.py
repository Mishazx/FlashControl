import base64
import datetime
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from joserfc import jwk, jwt

from .config import (
    ENVIRONMENT, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_ISSUER,
    OIDC_REDIRECT_URI, OIDC_SCOPES,
)


METADATA_TTL_SECONDS = 300
FLOW_TTL = datetime.timedelta(minutes=10)
ALLOWED_ID_TOKEN_ALGORITHMS = {
    "RS256", "RS384", "RS512", "PS256", "PS384", "PS512",
    "ES256", "ES384", "ES512", "EdDSA",
}
_metadata_cache: tuple[float, dict] | None = None
_jwks_cache: tuple[float, dict] | None = None


class OidcError(RuntimeError):
    pass


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def redirect_uri_for(base_url: str) -> str:
    if OIDC_REDIRECT_URI:
        return OIDC_REDIRECT_URI
    if ENVIRONMENT == "production":
        raise OidcError("OIDC redirect URI is not configured")
    return base_url.rstrip("/") + "/api/v1/auth/oidc/callback"


async def _get_json(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            value = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcError("OIDC provider is unavailable") from exc
    if not isinstance(value, dict):
        raise OidcError("OIDC provider returned invalid JSON")
    return value


async def discovery() -> dict:
    global _metadata_cache
    now = time.monotonic()
    if _metadata_cache and now - _metadata_cache[0] < METADATA_TTL_SECONDS:
        return _metadata_cache[1]
    issuer = OIDC_ISSUER.rstrip("/")
    metadata = await _get_json(issuer + "/.well-known/openid-configuration")
    if metadata.get("issuer", "").rstrip("/") != issuer:
        raise OidcError("OIDC discovery issuer mismatch")
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not isinstance(metadata.get(name), str):
            raise OidcError("OIDC discovery is missing " + name)
        if ENVIRONMENT == "production" and not metadata[name].startswith("https://"):
            raise OidcError("OIDC endpoints must use HTTPS")
    _metadata_cache = (now, metadata)
    return metadata


async def authorization_url(state: str, nonce: str, verifier: str, redirect_uri: str) -> str:
    metadata = await discovery()
    parameters = {
        "client_id": OIDC_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(OIDC_SCOPES),
        "state": state,
        "nonce": nonce,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
    }
    return metadata["authorization_endpoint"] + "?" + urlencode(parameters)


async def exchange_code(code: str, verifier: str, nonce: str, redirect_uri: str) -> dict:
    metadata = await discovery()
    auth_method = "client_secret_basic" if OIDC_CLIENT_SECRET else "none"
    try:
        async with AsyncOAuth2Client(
            client_id=OIDC_CLIENT_ID,
            client_secret=OIDC_CLIENT_SECRET or None,
            redirect_uri=redirect_uri,
            scope=OIDC_SCOPES,
            token_endpoint_auth_method=auth_method,
        ) as client:
            token = await client.fetch_token(
                metadata["token_endpoint"], code=code, code_verifier=verifier,
                grant_type="authorization_code",
            )
    except Exception as exc:
        raise OidcError("OIDC code exchange failed") from exc
    id_token = token.get("id_token")
    if not isinstance(id_token, str):
        raise OidcError("OIDC token response has no ID token")
    return await validate_id_token(id_token, nonce, metadata)


async def validate_id_token(value: str, nonce: str, metadata: dict | None = None) -> dict:
    global _jwks_cache
    metadata = metadata or await discovery()
    now_mono = time.monotonic()
    if not _jwks_cache or now_mono - _jwks_cache[0] >= METADATA_TTL_SECONDS:
        _jwks_cache = (now_mono, await _get_json(metadata["jwks_uri"]))
    try:
        token = jwt.decode(
            value, jwk.KeySet.import_key_set(_jwks_cache[1]),
            algorithms=ALLOWED_ID_TOKEN_ALGORITHMS,
        )
    except Exception:
        # A provider may rotate signing keys before the cache expires.
        _jwks_cache = (time.monotonic(), await _get_json(metadata["jwks_uri"]))
        try:
            token = jwt.decode(
                value, jwk.KeySet.import_key_set(_jwks_cache[1]),
                algorithms=ALLOWED_ID_TOKEN_ALGORITHMS,
            )
        except Exception as exc:
            raise OidcError("OIDC ID token signature is invalid") from exc
    claims = token.claims
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    issuer = OIDC_ISSUER.rstrip("/")
    audience = claims.get("aud")
    audiences = [audience] if isinstance(audience, str) else audience
    valid = (
        isinstance(claims.get("sub"), str)
        and claims.get("iss", "").rstrip("/") == issuer
        and isinstance(audiences, list) and OIDC_CLIENT_ID in audiences
        and isinstance(claims.get("exp"), (int, float)) and claims["exp"] >= now - 60
        and isinstance(claims.get("iat"), (int, float)) and claims["iat"] <= now + 60
        and (
            "nbf" not in claims
            or isinstance(claims["nbf"], (int, float)) and claims["nbf"] <= now + 60
        )
        and isinstance(claims.get("nonce"), str)
        and secrets.compare_digest(claims["nonce"], nonce)
    )
    if len(audiences or []) > 1 and claims.get("azp") != OIDC_CLIENT_ID:
        valid = False
    if not valid:
        raise OidcError("OIDC ID token claims are invalid")
    return dict(claims)
