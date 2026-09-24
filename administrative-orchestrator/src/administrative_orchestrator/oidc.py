from __future__ import annotations

import base64
import binascii
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt


class OidcVerificationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OidcMetadata:
    issuer: str
    jwks_uri: str


@dataclass(slots=True)
class _JwksCache:
    keys: dict[str, dict[str, Any]]
    expires_at: float


class OidcVerifier:
    """Fail-closed OIDC/JWKS verifier with bounded key caching.

    Identity-provider group/role claims are intentionally ignored. Successful
    verification establishes only an external subject; Administrative authority
    is resolved separately through IdentityBinding -> Principal -> roles.
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        allowed_algorithms: tuple[str, ...],
        jwks_cache_ttl_seconds: int,
        clock_skew_seconds: int,
        timeout_seconds: float,
        allow_insecure_http: bool = False,
        client: httpx.Client | None = None,
        metadata_url: str = "",
        jwks_url: str = "",
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.allowed_algorithms = allowed_algorithms
        self.metadata_url = metadata_url.strip()
        self.jwks_url = jwks_url.strip()
        self.jwks_cache_ttl_seconds = jwks_cache_ttl_seconds
        self.clock_skew_seconds = clock_skew_seconds
        self.timeout_seconds = timeout_seconds
        self.allow_insecure_http = allow_insecure_http
        self._client = client
        self._metadata: OidcMetadata | None = None
        self._jwks: _JwksCache | None = None

    def verify(self, token: str) -> dict[str, Any]:
        if not token:
            raise OidcVerificationError("OIDC token is empty")
        header = _parse_protected_header(token)

        algorithm = header.get("alg")
        key_id = header.get("kid")
        if algorithm not in self.allowed_algorithms:
            raise OidcVerificationError("OIDC token algorithm is not allowed")
        if not isinstance(key_id, str) or not key_id:
            raise OidcVerificationError("OIDC token kid is required")

        jwk = self._key_for(key_id)
        try:
            key = jwt.PyJWK.from_dict(jwk, algorithm=algorithm).key
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[algorithm],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.clock_skew_seconds,
                options={"require": ["sub", "iat", "exp"]},
            )
        except (jwt.PyJWTError, ValueError) as exc:
            raise OidcVerificationError("OIDC token verification failed") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise OidcVerificationError("OIDC sub is required")
        return claims

    def _key_for(self, key_id: str) -> dict[str, Any]:
        now = time.monotonic()
        if self._jwks is None or self._jwks.expires_at <= now:
            self._refresh_jwks()
        assert self._jwks is not None
        key = self._jwks.keys.get(key_id)
        if key is not None:
            return key

        # Key rotation: force one refresh on an unknown kid. Failure or a second
        # miss is fail-closed; no stale/unknown key is accepted.
        self._refresh_jwks()
        assert self._jwks is not None
        key = self._jwks.keys.get(key_id)
        if key is None:
            raise OidcVerificationError("OIDC token kid is unknown")
        return key

    def _refresh_jwks(self) -> None:
        metadata = self._metadata or self._load_metadata()
        raw = self._get_json(metadata.jwks_uri)
        keys = raw.get("keys")
        if not isinstance(keys, list):
            raise OidcVerificationError("OIDC JWKS keys are missing")
        indexed: dict[str, dict[str, Any]] = {}
        for item in keys:
            if not isinstance(item, dict):
                continue
            kid = item.get("kid")
            if isinstance(kid, str) and kid:
                indexed[kid] = item
        if not indexed:
            raise OidcVerificationError("OIDC JWKS contains no keyed signing material")
        self._jwks = _JwksCache(
            keys=indexed,
            expires_at=time.monotonic() + self.jwks_cache_ttl_seconds,
        )

    def _load_metadata(self) -> OidcMetadata:
        if not self.issuer:
            raise OidcVerificationError("OIDC issuer is not configured")
        self._validate_url(self.issuer)
        metadata_url = self.metadata_url or f"{self.issuer}/.well-known/openid-configuration"
        self._validate_url(metadata_url)
        raw = self._get_json(metadata_url)
        discovered_issuer = raw.get("issuer")
        jwks_uri = raw.get("jwks_uri")
        if not isinstance(discovered_issuer, str) or discovered_issuer.rstrip("/") != self.issuer:
            raise OidcVerificationError("OIDC discovery issuer mismatch")
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise OidcVerificationError("OIDC discovery lacks jwks_uri")
        resolved_jwks_uri = self.jwks_url or jwks_uri
        self._validate_url(resolved_jwks_uri)
        self._metadata = OidcMetadata(issuer=self.issuer, jwks_uri=resolved_jwks_uri)
        return self._metadata

    def _validate_url(self, value: str) -> None:
        parsed = urlparse(value)
        allowed = {"https"} if not self.allow_insecure_http else {"http", "https"}
        if parsed.scheme not in allowed or not parsed.hostname:
            raise OidcVerificationError("OIDC endpoint URL is not permitted")

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            if self._client is not None:
                response = self._client.get(url)
            else:
                response = httpx.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcVerificationError("OIDC endpoint is unavailable or invalid") from exc
        if not isinstance(raw, dict):
            raise OidcVerificationError("OIDC endpoint must return a JSON object")
        return raw


def _parse_protected_header(token: str) -> dict[str, Any]:
    """Parse only the compact-JWS protected header; claims are never decoded here.

    The header is untrusted routing metadata used solely to select an allowed
    algorithm and a candidate key id. Claims are parsed only by `jwt.decode`
    after cryptographic signature verification succeeds.
    """

    parts = token.split(".")
    if len(parts) != 3 or not parts[0]:
        raise OidcVerificationError("OIDC token header is invalid")
    protected = parts[0]
    padding = "=" * (-len(protected) % 4)
    try:
        raw = base64.urlsafe_b64decode((protected + padding).encode("ascii"))
        header = json.loads(raw)
    except (UnicodeEncodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise OidcVerificationError("OIDC token header is invalid") from exc
    if not isinstance(header, dict):
        raise OidcVerificationError("OIDC token header must be a JSON object")
    return header


__all__ = ["OidcMetadata", "OidcVerificationError", "OidcVerifier"]
