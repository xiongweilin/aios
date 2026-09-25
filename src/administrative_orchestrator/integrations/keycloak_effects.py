from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .credentials import CredentialRef, CredentialResolver, EnvironmentCredentialResolver
from .effect_common import (
    ConnectorConfigurationError,
    ConnectorResult,
    ConnectorStatus,
    _ApplicationRejected,
    _TransportUnknown,
    _unavailable_result,
    _unknown_result,
    _validate_base_url,
)


@dataclass(frozen=True, slots=True)
class KeycloakEffectConnection:
    base_url: str
    realm: str
    client_id: str
    credential: CredentialRef
    request_ref_attribute: str = "administrative_request_ref"
    disable_request_ref_attribute: str = "administrative_disable_request_ref"
    session_revoke_request_ref_attribute: str = (
        "administrative_session_revoke_request_ref"
    )
    subject_ref_attribute: str = "administrative_subject_ref"
    timeout_seconds: float = 10.0
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        _validate_base_url(self.base_url, allow_insecure_http=self.allow_insecure_http)
        if not self.realm.strip() or not self.client_id.strip():
            raise ConnectorConfigurationError("Keycloak realm and client_id are required")


class KeycloakIdentityEffectConnector:
    def __init__(
        self,
        connection: KeycloakEffectConnection,
        *,
        credentials: CredentialResolver | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.connection = connection
        self.credentials = credentials or EnvironmentCredentialResolver()
        self._client = client

    async def invoke(
        self,
        *,
        request_ref: str,
        subject_ref: str,
        parameters: dict[str, Any],
    ) -> ConnectorResult:
        try:
            existing = await self._find_by_attribute(self.connection.request_ref_attribute, request_ref)
            if len(existing) > 1:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="DuplicateExternalRequestIdentity",
                    error_message="multiple Keycloak users share the same request_ref",
                )
            if existing:
                return ConnectorResult(
                    ConnectorStatus.SUCCEEDED,
                    external_operation_ref=f"keycloak:user:{existing[0]['id']}",
                    reconciled=True,
                )

            by_subject = await self._find_by_attribute(
                self.connection.subject_ref_attribute,
                subject_ref,
            )
            if len(by_subject) > 1:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="DuplicateExternalSubjectIdentity",
                    error_message="multiple Keycloak users share the same subject_ref",
                )
            if by_subject:
                return ConnectorResult(
                    ConnectorStatus.SUCCEEDED,
                    external_operation_ref=f"keycloak:user:{by_subject[0]['id']}",
                    reconciled=True,
                )

            username = str(
                parameters.get("username")
                or parameters.get("work_email")
                or parameters.get("employee_ref")
                or subject_ref
            )
            attributes = {
                self.connection.request_ref_attribute: [request_ref],
                self.connection.subject_ref_attribute: [subject_ref],
            }
            for key in (
                "employee_ref",
                "department_ref",
                "manager_principal_id",
                "start_date",
                "employment_type",
            ):
                value = parameters.get(key)
                if value is not None:
                    attributes[f"administrative_{key}"] = [str(value)]
            body = {
                "username": username,
                "email": parameters.get("work_email") or None,
                "enabled": True,
                "attributes": attributes,
            }
            response = await self._request(
                "POST",
                f"/admin/realms/{self.connection.realm}/users",
                json_body=body,
            )
            if response.status_code >= 500:
                return ConnectorResult(
                    ConnectorStatus.UNKNOWN,
                    error_code="KeycloakServerResultAmbiguous",
                    error_message=f"Keycloak create returned HTTP {response.status_code}",
                )
            if response.status_code not in {201, 204}:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="KeycloakCreateRejected",
                    error_message=f"Keycloak create returned HTTP {response.status_code}",
                )
            location = response.headers.get("Location", "")
            user_id = location.rstrip("/").rsplit("/", 1)[-1] if location else ""
            if not user_id:
                found = await self._find_by_attribute(self.connection.request_ref_attribute, request_ref)
                if len(found) == 1:
                    user_id = str(found[0]["id"])
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED,
                external_operation_ref=(f"keycloak:user:{user_id}" if user_id else None),
            )
        except _TransportUnknown as exc:
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
            )

    async def reconcile(self, request_ref: str) -> ConnectorResult | None:
        try:
            rows = await self._find_by_attribute(self.connection.request_ref_attribute, request_ref)
        except _TransportUnknown as exc:
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
                reconciled=True,
            )
        if not rows:
            return None
        if len(rows) != 1:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="DuplicateExternalRequestIdentity",
                error_message="reconciliation found multiple Keycloak users",
                reconciled=True,
            )
        return ConnectorResult(
            ConnectorStatus.SUCCEEDED,
            external_operation_ref=f"keycloak:user:{rows[0]['id']}",
            reconciled=True,
        )

    async def _find_by_attribute(self, name: str, value: str) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            f"/admin/realms/{self.connection.realm}/users",
            params={"q": f"{name}:{value}", "max": "2"},
        )
        if response.status_code >= 500:
            raise _TransportUnknown(f"Keycloak search returned HTTP {response.status_code}")
        if response.status_code != 200:
            raise _ApplicationRejected(f"Keycloak search rejected HTTP {response.status_code}")
        try:
            raw = response.json()
        except ValueError as exc:
            raise _TransportUnknown("Keycloak search returned invalid JSON") from exc
        return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    async def _get_user(self, user_id: str) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"/admin/realms/{self.connection.realm}/users/{user_id}",
        )
        if response.status_code >= 500:
            raise _TransportUnknown(f"Keycloak user read returned HTTP {response.status_code}")
        if response.status_code != 200:
            raise _ApplicationRejected(f"Keycloak user read rejected HTTP {response.status_code}")
        try:
            raw = response.json()
        except ValueError as exc:
            raise _TransportUnknown("Keycloak user read returned invalid JSON") from exc
        if not isinstance(raw, dict):
            raise _TransportUnknown("Keycloak user read returned invalid representation")
        return raw

    async def _token(self) -> str:
        secret = self.credentials.resolve(self.connection.credential)
        url = (
            f"{self.connection.base_url.rstrip('/')}/realms/{self.connection.realm}"
            "/protocol/openid-connect/token"
        )
        data = {
            "grant_type": "client_credentials",
            "client_id": self.connection.client_id,
            "client_secret": secret,
        }
        try:
            if self._client is not None:
                response = await self._client.post(url, data=data)
            else:
                async with httpx.AsyncClient(timeout=self.connection.timeout_seconds) as client:
                    response = await client.post(url, data=data)
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise _TransportUnknown("Keycloak client-credential authentication is ambiguous") from exc
        token = raw.get("access_token") if isinstance(raw, dict) else None
        if not isinstance(token, str) or not token:
            raise _TransportUnknown("Keycloak token response lacks access_token")
        return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        token = await self._token()
        url = f"{self.connection.base_url.rstrip('/')}{path}"
        try:
            if self._client is not None:
                return await self._client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
            async with httpx.AsyncClient(timeout=self.connection.timeout_seconds) as client:
                return await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            raise _TransportUnknown("Keycloak transport/result is ambiguous") from exc


class KeycloakIdentityDisableConnector:
    def __init__(self, connector: KeycloakIdentityEffectConnector) -> None:
        self.connector = connector

    async def invoke(
        self,
        *,
        request_ref: str,
        subject_ref: str,
        parameters: dict[str, Any],
    ) -> ConnectorResult:
        del parameters
        try:
            user = await _keycloak_subject_user(self.connector, subject_ref)
            if user is None:
                return _keycloak_subject_failure(subject_ref)
            user_id = str(user["id"])
            marker = self.connector.connection.disable_request_ref_attribute
            recorded = _first_attribute(_user_attributes(user), marker)
            if recorded and recorded != request_ref:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="ConflictingExternalRequestIdentity",
                    error_message="Keycloak user records a different disable request",
                )
            if recorded == request_ref and user.get("enabled") is False:
                return _keycloak_success(user_id, reconciled=True)
            response = await self.connector._request(
                "PUT",
                f"/admin/realms/{self.connector.connection.realm}/users/{user_id}",
                json_body=_keycloak_user_update(user, marker, request_ref, enabled=False),
            )
            return _keycloak_write_result(response, user_id, operation="disable")
        except _TransportUnknown as exc:
            return _unknown_result(exc)
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="KeycloakApplicationRejected",
                error_message=str(exc),
            )

    async def reconcile(self, request_ref: str) -> ConnectorResult | None:
        try:
            rows = await self.connector._find_by_attribute(
                self.connector.connection.disable_request_ref_attribute, request_ref
            )
            if not rows:
                return None
            if len(rows) != 1 or not rows[0].get("id"):
                return _keycloak_duplicate_request("disable")
            user = await self.connector._get_user(str(rows[0]["id"]))
            if user.get("enabled") is False:
                return _keycloak_success(str(user["id"]), reconciled=True)
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                external_operation_ref=f"keycloak:user:{user['id']}",
                error_code="KeycloakDisableNotObserved",
                error_message="disable request identity exists but enabled=false is not observed",
                reconciled=True,
            )
        except _TransportUnknown as exc:
            return _unknown_result(exc, reconciled=True)
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="KeycloakApplicationRejected",
                error_message=str(exc),
                reconciled=True,
            )


class KeycloakIdentityDisableVerifier:
    def __init__(self, connector: KeycloakIdentityEffectConnector) -> None:
        self.connector = connector

    async def observe(
        self,
        *,
        subject_ref: str,
        expected_postcondition: dict[str, Any],
    ) -> ConnectorResult:
        del expected_postcondition
        try:
            user = await _keycloak_subject_user(self.connector, subject_ref)
            observed = (
                {
                    "target_system": "iam",
                    "operation": "identity.disable",
                    "subject_ref": subject_ref,
                    "enabled": bool(user.get("enabled", True)),
                }
                if user is not None
                else {}
            )
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED, observed_postcondition=observed
            )
        except (_TransportUnknown, _ApplicationRejected) as exc:
            return _unavailable_result(exc)


class KeycloakSessionRevokeConnector:
    def __init__(self, connector: KeycloakIdentityEffectConnector) -> None:
        self.connector = connector

    async def invoke(
        self,
        *,
        request_ref: str,
        subject_ref: str,
        parameters: dict[str, Any],
    ) -> ConnectorResult:
        del parameters
        try:
            user = await _keycloak_subject_user(self.connector, subject_ref)
            if user is None:
                return _keycloak_subject_failure(subject_ref)
            user_id = str(user["id"])
            marker = self.connector.connection.session_revoke_request_ref_attribute
            recorded = _first_attribute(_user_attributes(user), marker)
            if recorded and recorded != request_ref:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="ConflictingExternalRequestIdentity",
                    error_message="Keycloak user records a different session revoke request",
                )
            if recorded != request_ref:
                marker_response = await self.connector._request(
                    "PUT",
                    f"/admin/realms/{self.connector.connection.realm}/users/{user_id}",
                    json_body=_keycloak_user_update(user, marker, request_ref),
                )
                marker_result = _keycloak_write_result(
                    marker_response, user_id, operation="session marker"
                )
                if marker_result.status is not ConnectorStatus.SUCCEEDED:
                    return marker_result
            sessions = await _keycloak_sessions(self.connector, user_id)
            if not sessions:
                return _keycloak_success(user_id, reconciled=True)
            response = await self.connector._request(
                "POST",
                f"/admin/realms/{self.connector.connection.realm}/users/{user_id}/logout",
            )
            return _keycloak_write_result(response, user_id, operation="session revoke")
        except _TransportUnknown as exc:
            return _unknown_result(exc)
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="KeycloakApplicationRejected",
                error_message=str(exc),
            )

    async def reconcile(self, request_ref: str) -> ConnectorResult | None:
        try:
            rows = await self.connector._find_by_attribute(
                self.connector.connection.session_revoke_request_ref_attribute,
                request_ref,
            )
            if not rows:
                return None
            if len(rows) != 1 or not rows[0].get("id"):
                return _keycloak_duplicate_request("session revoke")
            user_id = str(rows[0]["id"])
            sessions = await _keycloak_sessions(self.connector, user_id)
            if not sessions:
                return _keycloak_success(user_id, reconciled=True)
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                external_operation_ref=f"keycloak:user:{user_id}",
                error_code="KeycloakSessionsStillActive",
                error_message="session revoke request exists but active sessions remain",
                reconciled=True,
            )
        except _TransportUnknown as exc:
            return _unknown_result(exc, reconciled=True)
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="KeycloakApplicationRejected",
                error_message=str(exc),
                reconciled=True,
            )


class KeycloakSessionVerifier:
    def __init__(self, connector: KeycloakIdentityEffectConnector) -> None:
        self.connector = connector

    async def observe(
        self,
        *,
        subject_ref: str,
        expected_postcondition: dict[str, Any],
    ) -> ConnectorResult:
        del expected_postcondition
        try:
            user = await _keycloak_subject_user(self.connector, subject_ref)
            if user is None:
                observed: dict[str, Any] = {}
            else:
                sessions = await _keycloak_sessions(self.connector, str(user["id"]))
                observed = {
                    "target_system": "iam",
                    "operation": "sessions.revoke",
                    "subject_ref": subject_ref,
                    "active_sessions": len(sessions),
                }
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED, observed_postcondition=observed
            )
        except (_TransportUnknown, _ApplicationRejected) as exc:
            return _unavailable_result(exc)


class KeycloakIdentityVerifier:
    def __init__(self, connector: KeycloakIdentityEffectConnector) -> None:
        self.connector = connector

    async def observe(
        self,
        *,
        subject_ref: str,
        expected_postcondition: dict[str, Any],
    ) -> ConnectorResult:
        try:
            users = await self.connector._find_by_attribute(
                self.connector.connection.subject_ref_attribute,
                subject_ref,
            )
            if len(users) != 1 or not users[0].get("id"):
                observed: dict[str, Any] = {}
            else:
                user = await self.connector._get_user(str(users[0]["id"]))
                attributes = (
                    user.get("attributes") if isinstance(user.get("attributes"), dict) else {}
                )
                expected_payload = expected_postcondition.get("payload")
                expected_payload = expected_payload if isinstance(expected_payload, dict) else {}
                payload: dict[str, Any] = {}
                for key in expected_payload:
                    if key == "employee_ref":
                        payload[key] = (
                            _first_attribute(attributes, "administrative_employee_ref")
                            or subject_ref
                        )
                    else:
                        payload[key] = _first_attribute(attributes, f"administrative_{key}")
                observed = {
                    "target_system": "iam",
                    "operation": "identity.create",
                    "subject_ref": subject_ref,
                    "active": bool(user.get("enabled", False)),
                    "payload": payload,
                }
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED,
                observed_postcondition=observed,
            )
        except (_TransportUnknown, _ApplicationRejected) as exc:
            return ConnectorResult(
                ConnectorStatus.UNAVAILABLE,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
            )


def _first_attribute(attributes: dict[str, Any], name: str) -> str | None:
    value = attributes.get(name)
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    if isinstance(value, str):
        return value
    return None


def _user_attributes(user: dict[str, Any]) -> dict[str, Any]:
    attributes = user.get("attributes")
    return dict(attributes) if isinstance(attributes, dict) else {}


def _keycloak_user_update(
    user: dict[str, Any],
    marker: str,
    request_ref: str,
    *,
    enabled: bool | None = None,
) -> dict[str, Any]:
    attributes = _user_attributes(user)
    attributes[marker] = [request_ref]
    body: dict[str, Any] = {
        "username": user.get("username"),
        "enabled": bool(user.get("enabled", True)) if enabled is None else enabled,
        "attributes": attributes,
    }
    for key in ("email", "firstName", "lastName"):
        if key in user:
            body[key] = user[key]
    return body


async def _keycloak_subject_user(
    connector: KeycloakIdentityEffectConnector, subject_ref: str
) -> dict[str, Any] | None:
    rows = await connector._find_by_attribute(
        connector.connection.subject_ref_attribute, subject_ref
    )
    if len(rows) != 1 or not rows[0].get("id"):
        return None
    return await connector._get_user(str(rows[0]["id"]))


async def _keycloak_sessions(
    connector: KeycloakIdentityEffectConnector, user_id: str
) -> list[dict[str, Any]]:
    response = await connector._request(
        "GET", f"/admin/realms/{connector.connection.realm}/users/{user_id}/sessions"
    )
    if response.status_code >= 500:
        raise _TransportUnknown(
            f"Keycloak session read returned HTTP {response.status_code}"
        )
    if response.status_code != 200:
        raise _ApplicationRejected(
            f"Keycloak session read rejected HTTP {response.status_code}"
        )
    try:
        raw = response.json()
    except ValueError as exc:
        raise _TransportUnknown("Keycloak session read returned invalid JSON") from exc
    if not isinstance(raw, list):
        raise _TransportUnknown("Keycloak session read returned invalid representation")
    return [item for item in raw if isinstance(item, dict)]


def _keycloak_write_result(
    response: httpx.Response, user_id: str, *, operation: str
) -> ConnectorResult:
    if response.status_code >= 500:
        return ConnectorResult(
            ConnectorStatus.UNKNOWN,
            external_operation_ref=f"keycloak:user:{user_id}",
            error_code="KeycloakServerResultAmbiguous",
            error_message=f"Keycloak {operation} returned HTTP {response.status_code}",
        )
    if response.status_code not in {200, 204}:
        return ConnectorResult(
            ConnectorStatus.FAILED,
            external_operation_ref=f"keycloak:user:{user_id}",
            error_code="KeycloakOperationRejected",
            error_message=f"Keycloak {operation} returned HTTP {response.status_code}",
        )
    return _keycloak_success(user_id)


def _keycloak_success(user_id: str, *, reconciled: bool = False) -> ConnectorResult:
    return ConnectorResult(
        ConnectorStatus.SUCCEEDED,
        external_operation_ref=f"keycloak:user:{user_id}",
        reconciled=reconciled,
    )


def _keycloak_subject_failure(subject_ref: str) -> ConnectorResult:
    return ConnectorResult(
        ConnectorStatus.FAILED,
        error_code="KeycloakSubjectNotUnique",
        error_message=f"Keycloak subject is absent or ambiguous: {subject_ref}",
    )


def _keycloak_duplicate_request(operation: str) -> ConnectorResult:
    return ConnectorResult(
        ConnectorStatus.FAILED,
        error_code="DuplicateExternalRequestIdentity",
        error_message=f"multiple Keycloak users share the {operation} request_ref",
        reconciled=True,
    )


__all__ = [
    "KeycloakEffectConnection",
    "KeycloakIdentityDisableConnector",
    "KeycloakIdentityDisableVerifier",
    "KeycloakIdentityEffectConnector",
    "KeycloakIdentityVerifier",
    "KeycloakSessionRevokeConnector",
    "KeycloakSessionVerifier",
]
