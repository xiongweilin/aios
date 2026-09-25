from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class Caller:
    service_identity: str
    purpose: str


def _string_map(name: str) -> dict[str, str]:
    raw = os.getenv(name, "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be valid JSON") from exc
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(secret, str) for key, secret in value.items()
    ):
        raise RuntimeError(f"{name} must be a string-to-string JSON object")
    return value


def _tokens() -> dict[str, str]:
    return _string_map("PERSONAL_WORLD_SERVICE_TOKENS_JSON")


def _workload_secrets() -> dict[str, str]:
    return _string_map("PERSONAL_WORLD_WORKLOAD_HMAC_SECRETS_JSON")


def _admins() -> set[str]:
    raw = os.getenv("PERSONAL_WORLD_ADMIN_SERVICE_IDENTITIES", "administrative-orchestrator")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _auth_mode() -> str:
    mode = os.getenv("PERSONAL_WORLD_AUTH_MODE", "bearer").strip().lower()
    if mode not in {"bearer", "signed-hmac", "insecure-local"}:
        raise RuntimeError("PERSONAL_WORLD_AUTH_MODE must be bearer, signed-hmac, or insecure-local")
    profile = os.getenv("PERSONAL_WORLD_DEPLOYMENT_PROFILE", "local").strip().lower()
    if profile == "production" and mode != "signed-hmac":
        raise RuntimeError("production Personal World requires signed-hmac workload identity")
    if mode == "insecure-local" and os.getenv(
        "PERSONAL_WORLD_ALLOW_INSECURE_LOCAL", ""
    ).lower() != "true":
        raise RuntimeError("insecure-local auth requires PERSONAL_WORLD_ALLOW_INSECURE_LOCAL=true")
    return mode


def workload_signature(
    secret: str,
    *,
    service_identity: str,
    purpose: str,
    timestamp: str,
) -> str:
    payload = f"{service_identity}\n{purpose}\n{timestamp}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _verify_signed_hmac(
    *,
    service_identity: str,
    purpose: str,
    timestamp: str | None,
    signature: str | None,
) -> None:
    secrets = _workload_secrets()
    secret = secrets.get(service_identity)
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unknown workload identity",
        )
    if not timestamp or not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="signed workload identity headers are required",
        )
    try:
        asserted_at = int(timestamp)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid workload timestamp",
        ) from exc
    ttl = max(1, int(os.getenv("PERSONAL_WORLD_WORKLOAD_ASSERTION_TTL_SECONDS", "60")))
    if abs(int(time.time()) - asserted_at) > ttl:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="workload assertion is expired",
        )
    expected = workload_signature(
        secret,
        service_identity=service_identity,
        purpose=purpose,
        timestamp=timestamp,
    )
    presented = signature.removeprefix("sha256=").strip().lower()
    if not hmac.compare_digest(expected, presented):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid workload assertion",
        )


def caller(
    x_service_identity: str = Header(alias="X-Service-Identity"),
    x_purpose: str = Header(alias="X-Purpose"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_workload_timestamp: str | None = Header(default=None, alias="X-Workload-Timestamp"),
    x_workload_signature: str | None = Header(default=None, alias="X-Workload-Signature"),
) -> Caller:
    if not x_purpose.strip():
        raise HTTPException(status_code=400, detail="X-Purpose must not be empty")

    mode = _auth_mode()
    if mode == "signed-hmac":
        _verify_signed_hmac(
            service_identity=x_service_identity,
            purpose=x_purpose,
            timestamp=x_workload_timestamp,
            signature=x_workload_signature,
        )
    elif mode == "bearer":
        configured = _tokens()
        expected = configured.get(x_service_identity)
        presented = ""
        if authorization and authorization.startswith("Bearer "):
            presented = authorization[7:]
        if expected is None or not hmac.compare_digest(expected, presented):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid service credentials",
            )
    else:
        # Explicit local-only mode. Production is rejected by _auth_mode.
        pass

    return Caller(service_identity=x_service_identity, purpose=x_purpose)


def require_admin(value: Caller) -> Caller:
    if value.service_identity not in _admins():
        raise HTTPException(status_code=403, detail="admin service identity required")
    return value
