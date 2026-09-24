from __future__ import annotations

import base64
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from administrative_orchestrator.config import Settings
from administrative_orchestrator.oidc import OidcVerificationError, OidcVerifier

ISSUER = "https://id.example.test"
AUDIENCE = "administrative-orchestrator"


def _material(kid: str):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return private, jwk


def _token(private, kid: str, *, issuer: str = ISSUER, audience: str = AUDIENCE):
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "external:alice",
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + 300,
            "groups": ["hr-admin"],
        },
        private,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _verifier(*, client: httpx.Client | None = None) -> OidcVerifier:
    return OidcVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        allowed_algorithms=("RS256", "ES256"),
        jwks_cache_ttl_seconds=300,
        clock_skew_seconds=30,
        timeout_seconds=1,
        client=client,
    )


def _compact_header(value) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    protected = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{protected}.e30.signature"


def test_oidc_verifies_asymmetric_token_and_ignores_authority_claims() -> None:
    private, public_jwk = _material("kid-1")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"})
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [public_jwk]})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verifier = _verifier(client=client)

    claims = verifier.verify(_token(private, "kid-1"))
    assert claims["sub"] == "external:alice"
    assert claims["groups"] == ["hr-admin"]
    # The verifier returns identity claims only; no Administrative role is
    # materialized by OIDC verification itself.
    assert "decision_role" not in claims


def test_oidc_protected_header_parsing_fails_closed_before_claims_are_decoded() -> None:
    verifier = _verifier()

    for malformed in ("", "not-a-jwt", "@@@.e30.signature", _compact_header(["RS256", "kid"])):
        with pytest.raises(OidcVerificationError, match="token (header|is empty)"):
            verifier.verify(malformed)

    with pytest.raises(OidcVerificationError, match="algorithm is not allowed"):
        verifier.verify(_compact_header({"alg": "none", "kid": "kid-1"}))
    with pytest.raises(OidcVerificationError, match="kid is required"):
        verifier.verify(_compact_header({"alg": "RS256"}))


def test_unknown_kid_forces_one_jwks_refresh_for_rotation() -> None:
    old_private, old_jwk = _material("old")
    new_private, new_jwk = _material("new")
    jwks_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal jwks_calls
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"})
        if request.url.path == "/jwks":
            jwks_calls += 1
            keys = [old_jwk] if jwks_calls == 1 else [old_jwk, new_jwk]
            return httpx.Response(200, json={"keys": keys})
        return httpx.Response(404)

    verifier = OidcVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        allowed_algorithms=("RS256",),
        jwks_cache_ttl_seconds=300,
        clock_skew_seconds=30,
        timeout_seconds=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert verifier.verify(_token(old_private, "old"))["sub"] == "external:alice"
    assert verifier.verify(_token(new_private, "new"))["sub"] == "external:alice"
    assert jwks_calls == 2


def test_oidc_can_use_internal_metadata_and_jwks_endpoints_for_external_issuer() -> None:
    private, public_jwk = _material("internal-path")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "keycloak" and request.url.path.endswith(
            "/.well-known/openid-configuration"
        ):
            return httpx.Response(
                200,
                json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"},
            )
        if request.url.host == "keycloak" and request.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [public_jwk]})
        return httpx.Response(404)

    verifier = OidcVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        allowed_algorithms=("RS256",),
        metadata_url="http://keycloak/realms/m7/.well-known/openid-configuration",
        jwks_url="http://keycloak/realms/m7/protocol/openid-connect/certs",
        jwks_cache_ttl_seconds=300,
        clock_skew_seconds=30,
        timeout_seconds=1,
        allow_insecure_http=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert verifier.verify(_token(private, "internal-path"))["iss"] == ISSUER


def test_oidc_rejects_issuer_audience_and_unknown_kid() -> None:
    private, public_jwk = _material("known")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"})
        return httpx.Response(200, json={"keys": [public_jwk]})

    verifier = OidcVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        allowed_algorithms=("RS256",),
        jwks_cache_ttl_seconds=300,
        clock_skew_seconds=0,
        timeout_seconds=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(OidcVerificationError):
        verifier.verify(_token(private, "known", issuer="https://wrong.example"))
    with pytest.raises(OidcVerificationError):
        verifier.verify(_token(private, "known", audience="wrong-audience"))

    other_private, _ = _material("unknown")
    with pytest.raises(OidcVerificationError):
        verifier.verify(_token(other_private, "unknown"))


def test_production_profile_requires_https_oidc_and_asymmetric_algorithms() -> None:
    with pytest.raises(ValueError):
        Settings(runtime_profile="production", auth_mode="jwt")
    with pytest.raises(ValueError):
        Settings(
            runtime_profile="production",
            auth_mode="oidc",
            oidc_issuer="http://id.example.test",
            oidc_audience=AUDIENCE,
        )
    with pytest.raises(ValueError):
        Settings(
            runtime_profile="production",
            auth_mode="oidc",
            oidc_issuer=ISSUER,
            oidc_audience=AUDIENCE,
            oidc_allowed_algorithms="HS256",
        )

    settings = Settings(
        runtime_profile="production",
        auth_mode="oidc",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_allowed_algorithms="RS256,ES256",
    )
    assert settings.authority_enforcement_enabled is True


def test_staging_profile_requires_oidc_and_allows_explicit_local_http() -> None:
    settings = Settings(
        runtime_profile="staging",
        auth_mode="oidc",
        oidc_issuer="http://keycloak:8080/realms/m6",
        oidc_audience=AUDIENCE,
        oidc_allow_insecure_http=True,
    )
    assert settings.authority_enforcement_enabled is True

    with pytest.raises(ValueError, match="HTTP requires"):
        Settings(
            runtime_profile="staging",
            auth_mode="oidc",
            oidc_issuer="http://keycloak:8080/realms/m6",
            oidc_audience=AUDIENCE,
        )

    with pytest.raises(ValueError, match="requires ADMIN_AUTH_MODE=oidc"):
        Settings(runtime_profile="staging", auth_mode="jwt")
    with pytest.raises(ValueError, match="issuer and audience are required"):
        Settings(runtime_profile="staging", auth_mode="oidc", oidc_issuer="")
    with pytest.raises(ValueError, match="cannot allow insecure HTTP"):
        Settings(
            runtime_profile="production",
            auth_mode="oidc",
            oidc_issuer=ISSUER,
            oidc_audience=AUDIENCE,
            oidc_allow_insecure_http=True,
        )
