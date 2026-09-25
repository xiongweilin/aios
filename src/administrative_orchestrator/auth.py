from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status

from .authority import AuthorityRepository
from .config import Settings
from .domain import Principal
from .oidc import OidcVerificationError, OidcVerifier
from .persistence import SqlStore


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    principal: Principal
    auth_mode: str
    external_subject: str

    @property
    def principal_id(self) -> str:
        return self.principal.principal_id


class Authenticator:
    def __init__(self, store: SqlStore, settings: Settings) -> None:
        self.repository = AuthorityRepository(store)
        self.settings = settings
        self._oidc_verifier: OidcVerifier | None = None

    def authenticate(self, request: Request) -> AuthenticatedPrincipal:
        mode = self.settings.auth_mode.strip().lower()
        if mode == "development":
            return self._authenticate_development(request)
        if mode == "jwt":
            return self._authenticate_jwt(request)
        if mode == "oidc":
            return self._authenticate_oidc(request)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="unsupported authentication mode",
        )

    def _authenticate_development(self, request: Request) -> AuthenticatedPrincipal:
        principal_id = request.headers.get("X-Principal-ID", "").strip()
        if not principal_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-Principal-ID is required in development auth mode",
            )
        principal = self.repository.get_principal(principal_id)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="development principal is not registered in the authority plane",
            )
        return AuthenticatedPrincipal(
            principal=principal,
            auth_mode="development",
            external_subject=principal_id,
        )

    def _authenticate_oidc(self, request: Request) -> AuthenticatedPrincipal:
        token = self._bearer_token(request)
        if self._oidc_verifier is None:
            self._oidc_verifier = OidcVerifier(
                issuer=self.settings.oidc_issuer,
                audience=self.settings.oidc_audience,
                allowed_algorithms=self.settings.oidc_algorithms,
                metadata_url=self.settings.oidc_metadata_url,
                jwks_url=self.settings.oidc_jwks_url,
                jwks_cache_ttl_seconds=self.settings.oidc_jwks_cache_ttl_seconds,
                clock_skew_seconds=self.settings.oidc_clock_skew_seconds,
                timeout_seconds=self.settings.oidc_http_timeout_seconds,
                allow_insecure_http=self.settings.oidc_allow_insecure_http,
            )
        try:
            claims = self._oidc_verifier.verify(token)
        except OidcVerificationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid OIDC bearer token",
            ) from exc

        subject = str(claims["sub"]).strip()
        principal = self.repository.resolve_identity(
            provider=self.settings.oidc_issuer.rstrip("/"),
            external_subject=subject,
        )
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="authenticated identity is not currently bound to an active principal",
            )
        return AuthenticatedPrincipal(
            principal=principal,
            auth_mode="oidc",
            external_subject=subject,
        )

    def _authenticate_jwt(self, request: Request) -> AuthenticatedPrincipal:
        token = self._bearer_token(request)
        if not self.settings.jwt_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="JWT authentication is not configured",
            )
        try:
            claims = _decode_hs256_jwt(
                token,
                secret=self.settings.jwt_secret,
                issuer=self.settings.jwt_issuer,
                audience=self.settings.jwt_audience,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
            ) from exc

        subject = str(claims["sub"]).strip()
        principal = self.repository.resolve_identity(
            provider=self.settings.jwt_issuer,
            external_subject=subject,
        )
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="authenticated identity is not currently bound to an active principal",
            )
        return AuthenticatedPrincipal(
            principal=principal,
            auth_mode="jwt",
            external_subject=subject,
        )

    @staticmethod
    def _bearer_token(request: Request) -> str:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token is required",
            )
        token = header.removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token is required",
            )
        return token


def _decode_hs256_jwt(
    token: str,
    *,
    secret: str,
    issuer: str,
    audience: str,
) -> dict[str, Any]:
    """Legacy compatibility verifier used only outside the production profile."""

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWT must have three segments")
    encoded_header, encoded_payload, encoded_signature = parts
    header = _decode_json_segment(encoded_header)
    claims = _decode_json_segment(encoded_payload)
    if header.get("alg") != "HS256":
        raise ValueError("only HS256 is accepted by this compatibility profile")

    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    provided = _decode_b64url(encoded_signature)
    if not hmac.compare_digest(expected, provided):
        raise ValueError("invalid JWT signature")

    now = int(time.time())
    subject = claims.get("sub")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    not_before = claims.get("nbf")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("JWT sub is required")
    if not isinstance(issued_at, int) or not isinstance(expires_at, int):
        raise ValueError("JWT iat and exp are required integer timestamps")
    if issued_at > now + 60:
        raise ValueError("JWT iat is in the future")
    if expires_at <= now:
        raise ValueError("JWT has expired")
    if isinstance(not_before, int) and not_before > now + 60:
        raise ValueError("JWT is not yet valid")
    if claims.get("iss") != issuer:
        raise ValueError("JWT issuer mismatch")
    token_audience = claims.get("aud")
    audiences = (
        {token_audience}
        if isinstance(token_audience, str)
        else set(token_audience or [])
        if isinstance(token_audience, list)
        else set()
    )
    if audience not in audiences:
        raise ValueError("JWT audience mismatch")
    return claims


def _decode_json_segment(value: str) -> dict[str, Any]:
    raw = _decode_b64url(value)
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("JWT segment must contain a JSON object")
    return parsed


def _decode_b64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid base64url segment") from exc


__all__ = ["AuthenticatedPrincipal", "Authenticator"]
