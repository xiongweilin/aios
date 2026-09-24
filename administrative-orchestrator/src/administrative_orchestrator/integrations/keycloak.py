from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from .authoritative_sources import AuthoritativeRecord
from .credentials import CredentialRef, CredentialResolver, EnvironmentCredentialResolver


class KeycloakSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KeycloakConnection:
    base_url: str
    realm: str
    client_id: str
    reader_credential: CredentialRef
    timeout_seconds: float = 10.0
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        allowed = {"https"} if not self.allow_insecure_http else {"http", "https"}
        if parsed.scheme not in allowed or not parsed.hostname:
            raise ValueError("Keycloak base_url is not permitted")
        if not self.realm.strip() or not self.client_id.strip():
            raise ValueError("Keycloak realm and client_id are required")


class KeycloakIdentityDirectory:
    """Read-only authoritative identity adapter for Keycloak Admin REST.

    It does not create users or mutate roles. Kernel deployment providers own
    write and independent verification capabilities.
    """

    def __init__(
        self,
        connection: KeycloakConnection,
        *,
        credentials: CredentialResolver | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.connection = connection
        self.credentials = credentials or EnvironmentCredentialResolver()
        self._client = client

    def read_identity(self, identity_ref: str) -> AuthoritativeRecord:
        user_id = _user_id(identity_ref)
        user = self._get(f"/admin/realms/{self.connection.realm}/users/{user_id}")
        if user is None:
            return AuthoritativeRecord.build(
                source="keycloak",
                source_ref=f"keycloak:user:{user_id}",
                source_version="absent",
                value={"present": False, "identity_ref": f"keycloak:user:{user_id}"},
            )
        groups = self._get(f"/admin/realms/{self.connection.realm}/users/{user_id}/groups") or []
        roles = self._get(
            f"/admin/realms/{self.connection.realm}/users/{user_id}/role-mappings/realm/composite"
        ) or []
        value = {
            "present": True,
            "identity_ref": f"keycloak:user:{user_id}",
            "username": user.get("username"),
            "email": user.get("email"),
            "enabled": bool(user.get("enabled", False)),
            "email_verified": bool(user.get("emailVerified", False)),
            "groups": sorted(
                item.get("path") or item.get("name")
                for item in groups
                if isinstance(item, dict) and (item.get("path") or item.get("name"))
            ),
            "realm_roles": sorted(
                item.get("name") for item in roles if isinstance(item, dict) and item.get("name")
            ),
            "attributes": user.get("attributes") or {},
        }
        version = _content_version(value)
        return AuthoritativeRecord.build(
            source="keycloak",
            source_ref=f"keycloak:user:{user_id}",
            source_version=version,
            value=value,
        )

    def resolve_person(self, external_identity: str) -> AuthoritativeRecord:
        token = external_identity.strip()
        if not token:
            raise KeycloakSourceError("external identity is required")
        users = self._get(
            f"/admin/realms/{self.connection.realm}/users",
            params={"username": token, "exact": "true", "max": "2"},
        )
        rows = users if isinstance(users, list) else []
        if len(rows) != 1 or not isinstance(rows[0], dict) or not rows[0].get("id"):
            return AuthoritativeRecord.build(
                source="keycloak",
                source_ref=f"keycloak:resolve:{token}",
                source_version=_content_version(rows),
                value={"present": False, "external_identity": token, "match_count": len(rows)},
            )
        user_id = str(rows[0]["id"])
        identity = self.read_identity(user_id)
        value = dict(identity.value)
        value["external_identity"] = token
        return AuthoritativeRecord.build(
            source="keycloak",
            source_ref=f"keycloak:resolve:{token}",
            source_version=identity.source_version,
            observed_at=identity.observed_at,
            value=value,
        )

    def _token(self) -> str:
        secret = self.credentials.resolve(self.connection.reader_credential)
        url = f"{self.connection.base_url.rstrip('/')}/realms/{self.connection.realm}/protocol/openid-connect/token"
        try:
            if self._client is not None:
                response = self._client.post(
                    url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.connection.client_id,
                        "client_secret": secret,
                    },
                )
            else:
                response = httpx.post(
                    url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.connection.client_id,
                        "client_secret": secret,
                    },
                    timeout=self.connection.timeout_seconds,
                )
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KeycloakSourceError("Keycloak reader authentication failed") from exc
        access_token = raw.get("access_token") if isinstance(raw, dict) else None
        if not isinstance(access_token, str) or not access_token:
            raise KeycloakSourceError("Keycloak token response lacks access_token")
        return access_token

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        url = f"{self.connection.base_url.rstrip('/')}{path}"
        headers = {"Authorization": f"Bearer {self._token()}"}
        try:
            if self._client is not None:
                response = self._client.get(url, params=params, headers=headers)
            else:
                response = httpx.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.connection.timeout_seconds,
                )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KeycloakSourceError("Keycloak authoritative read failed") from exc


def _user_id(ref: str) -> str:
    value = ref.strip()
    prefix = "keycloak:user:"
    if value.startswith(prefix):
        value = value[len(prefix) :]
    if not value or "/" in value or ".." in value:
        raise KeycloakSourceError("invalid Keycloak user reference")
    return value


def _content_version(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = ["KeycloakConnection", "KeycloakIdentityDirectory", "KeycloakSourceError"]
