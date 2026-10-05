from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.effect_common import ConnectorStatus
from administrative_orchestrator.integrations.keycloak_effects import (
    KeycloakEffectConnection,
    KeycloakIdentityDisableConnector,
    KeycloakIdentityDisableVerifier,
    KeycloakIdentityEffectConnector,
    KeycloakSessionRevokeConnector,
    KeycloakSessionVerifier,
)

REALM = "baa-real-keycloak"
WRITER_CLIENT = "baa-writer"
VERIFIER_CLIENT = "baa-verifier"
SESSION_CLIENT = "baa-session-client"
SUBJECT_REF = "employee:baa-real-keycloak"
USERNAME = "baa-real-user"


class KeycloakAdmin:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.client = httpx.Client(timeout=10.0)

    def close(self) -> None:
        self.client.close()

    def wait_ready(self, timeout_seconds: int = 120) -> None:
        deadline = time.monotonic() + timeout_seconds
        last: object = None
        while time.monotonic() < deadline:
            try:
                response = self.client.get(f"{self.base_url}/realms/master")
                if response.status_code == 200:
                    return
                last = (response.status_code, response.text[:200])
            except httpx.HTTPError as exc:
                last = repr(exc)
            time.sleep(1.0)
        raise RuntimeError(f"Keycloak did not become ready: {last!r}")

    def master_token(self) -> str:
        response = self.client.post(
            f"{self.base_url}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": self.username,
                "password": self.password,
            },
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("master admin token missing")
        return token

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json_body: Any | None = None,
        params: dict[str, str] | None = None,
        expected: set[int] | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token or self.master_token()}"}
        response = self.client.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            json=json_body,
            params=params,
        )
        if expected is not None and response.status_code not in expected:
            raise RuntimeError(
                f"Keycloak {method} {path} returned {response.status_code}: "
                f"{response.text[:500]}"
            )
        return response

    def create_realm(self) -> None:
        self.request(
            "POST",
            "/admin/realms",
            json_body={"realm": REALM, "enabled": True},
            expected={201, 409},
        )
        profile = self.request(
            "GET",
            f"/admin/realms/{REALM}/users/profile",
            expected={200},
        ).json()
        if not isinstance(profile, dict):
            raise RuntimeError("Keycloak user profile configuration is not an object")
        profile["unmanagedAttributePolicy"] = "ADMIN_EDIT"
        self.request(
            "PUT",
            f"/admin/realms/{REALM}/users/profile",
            json_body=profile,
            expected={200, 204},
        )

    def configure_user_profile(self) -> None:
        current = self.request(
            "GET",
            f"/admin/realms/{REALM}/users/profile",
            expected={200},
        ).json()
        if not isinstance(current, dict):
            raise RuntimeError("Keycloak user-profile configuration is malformed")
        current["unmanagedAttributePolicy"] = "ADMIN_EDIT"
        updated = self.request(
            "PUT",
            f"/admin/realms/{REALM}/users/profile",
            json_body=current,
            expected={200},
        ).json()
        if not isinstance(updated, dict) or updated.get("unmanagedAttributePolicy") != "ADMIN_EDIT":
            raise RuntimeError("Keycloak user-profile policy update was not retained")

    def _client_rep(self, client_id: str) -> dict[str, Any]:
        response = self.request(
            "GET",
            f"/admin/realms/{REALM}/clients",
            params={"clientId": client_id},
            expected={200},
        )
        rows = response.json()
        if not isinstance(rows, list) or len(rows) != 1:
            raise RuntimeError(f"client lookup for {client_id!r} was not unique")
        return rows[0]

    def create_service_client(self, client_id: str, secret: str) -> dict[str, Any]:
        self.request(
            "POST",
            f"/admin/realms/{REALM}/clients",
            json_body={
                "clientId": client_id,
                "enabled": True,
                "publicClient": False,
                "serviceAccountsEnabled": True,
                "clientAuthenticatorType": "client-secret",
                "secret": secret,
                "standardFlowEnabled": False,
                "directAccessGrantsEnabled": False,
            },
            expected={201, 409},
        )
        return self._client_rep(client_id)

    def create_session_client(self) -> None:
        self.request(
            "POST",
            f"/admin/realms/{REALM}/clients",
            json_body={
                "clientId": SESSION_CLIENT,
                "enabled": True,
                "publicClient": True,
                "standardFlowEnabled": False,
                "directAccessGrantsEnabled": True,
            },
            expected={201, 409},
        )

    def assign_realm_management_roles(
        self,
        client_rep: dict[str, Any],
        role_names: tuple[str, ...],
    ) -> None:
        service_user = self.request(
            "GET",
            f"/admin/realms/{REALM}/clients/{client_rep['id']}/service-account-user",
            expected={200},
        ).json()
        realm_management = self._client_rep("realm-management")
        roles = []
        for name in role_names:
            role = self.request(
                "GET",
                f"/admin/realms/{REALM}/clients/{realm_management['id']}/roles/{name}",
                expected={200},
            ).json()
            roles.append(role)
        self.request(
            "POST",
            f"/admin/realms/{REALM}/users/{service_user['id']}/role-mappings/clients/"
            f"{realm_management['id']}",
            json_body=roles,
            expected={204},
        )

    def create_subject_user(self, password: str) -> str:
        response = self.request(
            "POST",
            f"/admin/realms/{REALM}/users",
            json_body={
                "username": USERNAME,
                "firstName": "BAA",
                "lastName": "Acceptance",
                "email": "baa-real-keycloak@example.test",
                "emailVerified": True,
                "enabled": True,
                "requiredActions": [],
                "attributes": {
                    "administrative_subject_ref": [SUBJECT_REF],
                    "preserve_me": ["yes"],
                },
                "credentials": [
                    {"type": "password", "value": password, "temporary": False}
                ],
            },
            expected={201},
        )
        location = response.headers.get("Location", "")
        user_id = location.rstrip("/").rsplit("/", 1)[-1]
        if not user_id:
            raise RuntimeError("created Keycloak user id missing")
        return user_id

    def create_user_session(self, password: str) -> None:
        response = self.client.post(
            f"{self.base_url}/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": SESSION_CLIENT,
                "username": USERNAME,
                "password": password,
                "scope": "openid",
            },
        )
        if response.status_code != 200:
            detail = response.text[:500]
            raise RuntimeError(
                f"direct grant failed with HTTP {response.status_code}: {detail}"
            )
        if not response.json().get("access_token"):
            raise RuntimeError("direct grant did not create a user session")

    def service_token(self, client_id: str, secret: str) -> str:
        response = self.client.post(
            f"{self.base_url}/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": secret,
            },
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError(f"service token missing for {client_id}")
        return token

    def active_sessions(self, user_id: str) -> int:
        response = self.request(
            "GET",
            f"/admin/realms/{REALM}/users/{user_id}/sessions",
            expected={200},
        )
        rows = response.json()
        return len(rows) if isinstance(rows, list) else -1

    def server_version(self) -> str | None:
        response = self.request("GET", "/admin/serverinfo", expected={200})
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        info = payload.get("systemInfo")
        if isinstance(info, dict):
            version = info.get("version")
            return str(version) if version else None
        return None


async def run_connectors(base_url: str, writer_secret: str, verifier_secret: str) -> dict[str, Any]:
    os.environ["BAA_KEYCLOAK_WRITER_SECRET"] = writer_secret
    os.environ["BAA_KEYCLOAK_VERIFIER_SECRET"] = verifier_secret

    writer = KeycloakIdentityEffectConnector(
        KeycloakEffectConnection(
            base_url=base_url,
            realm=REALM,
            client_id=WRITER_CLIENT,
            credential=CredentialRef(
                "keycloak:baa-writer",
                "BAA_KEYCLOAK_WRITER_SECRET",
            ),
            allow_insecure_http=True,
        )
    )
    verifier = KeycloakIdentityEffectConnector(
        KeycloakEffectConnection(
            base_url=base_url,
            realm=REALM,
            client_id=VERIFIER_CLIENT,
            credential=CredentialRef(
                "keycloak:baa-verifier",
                "BAA_KEYCLOAK_VERIFIER_SECRET",
            ),
            allow_insecure_http=True,
        )
    )

    disable_request = f"request:disable:{uuid4()}"
    disable = await KeycloakIdentityDisableConnector(writer).invoke(
        request_ref=disable_request,
        subject_ref=SUBJECT_REF,
        parameters={},
    )
    if disable.status is not ConnectorStatus.SUCCEEDED:
        raise AssertionError(f"disable failed: {disable}")

    disable_observed = await KeycloakIdentityDisableVerifier(verifier).observe(
        subject_ref=SUBJECT_REF,
        expected_postcondition={"enabled": False},
    )
    if disable_observed.status is not ConnectorStatus.SUCCEEDED:
        raise AssertionError(f"disable read-back unavailable: {disable_observed}")
    if disable_observed.observed_postcondition != {
        "target_system": "iam",
        "operation": "identity.disable",
        "subject_ref": SUBJECT_REF,
        "enabled": False,
    }:
        raise AssertionError(
            f"disable read-back mismatch: {disable_observed.observed_postcondition}"
        )

    disable_reconcile = await KeycloakIdentityDisableConnector(writer).reconcile(
        disable_request
    )
    if disable_reconcile is None or disable_reconcile.status is not ConnectorStatus.SUCCEEDED:
        raise AssertionError(f"disable reconciliation failed: {disable_reconcile}")

    session_request = f"request:sessions:{uuid4()}"
    revoke = await KeycloakSessionRevokeConnector(writer).invoke(
        request_ref=session_request,
        subject_ref=SUBJECT_REF,
        parameters={},
    )
    if revoke.status is not ConnectorStatus.SUCCEEDED:
        raise AssertionError(f"session revoke failed: {revoke}")

    session_observed = await KeycloakSessionVerifier(verifier).observe(
        subject_ref=SUBJECT_REF,
        expected_postcondition={"active_sessions": 0},
    )
    if session_observed.status is not ConnectorStatus.SUCCEEDED:
        raise AssertionError(f"session read-back unavailable: {session_observed}")
    if session_observed.observed_postcondition != {
        "target_system": "iam",
        "operation": "sessions.revoke",
        "subject_ref": SUBJECT_REF,
        "active_sessions": 0,
    }:
        raise AssertionError(
            f"session read-back mismatch: {session_observed.observed_postcondition}"
        )

    session_reconcile = await KeycloakSessionRevokeConnector(writer).reconcile(
        session_request
    )
    if session_reconcile is None or session_reconcile.status is not ConnectorStatus.SUCCEEDED:
        raise AssertionError(f"session reconciliation failed: {session_reconcile}")

    return {
        "disable": {
            "status": disable.status.value,
            "reconciled": bool(disable_reconcile.reconciled),
            "observed": disable_observed.observed_postcondition,
        },
        "session_revoke": {
            "status": revoke.status.value,
            "reconciled": bool(session_reconcile.reconciled),
            "observed": session_observed.observed_postcondition,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:28080")
    parser.add_argument("--evidence-path", required=True)
    args = parser.parse_args()

    admin_user = os.environ["KC_BOOTSTRAP_ADMIN_USERNAME"]
    admin_password = os.environ["KC_BOOTSTRAP_ADMIN_PASSWORD"]
    writer_secret = os.environ["BAA_KEYCLOAK_WRITER_SECRET"]
    verifier_secret = os.environ["BAA_KEYCLOAK_VERIFIER_SECRET"]
    user_password = os.environ["BAA_KEYCLOAK_USER_PASSWORD"]

    admin = KeycloakAdmin(args.base_url, admin_user, admin_password)
    try:
        admin.wait_ready()
        admin.create_realm()
        admin.configure_user_profile()
        writer_client = admin.create_service_client(WRITER_CLIENT, writer_secret)
        verifier_client = admin.create_service_client(VERIFIER_CLIENT, verifier_secret)
        admin.create_session_client()
        admin.assign_realm_management_roles(
            writer_client,
            ("manage-users", "view-users", "query-users"),
        )
        admin.assign_realm_management_roles(
            verifier_client,
            ("view-users", "query-users"),
        )
        user_id = admin.create_subject_user(user_password)
        admin.create_user_session(user_password)
        sessions_before = admin.active_sessions(user_id)
        if sessions_before < 1:
            raise AssertionError("expected at least one active session before offboarding")

        verifier_token = admin.service_token(VERIFIER_CLIENT, verifier_secret)
        forbidden = admin.request(
            "POST",
            f"/admin/realms/{REALM}/users",
            token=verifier_token,
            json_body={
                "username": f"should-not-create-{uuid4()}",
                "enabled": True,
            },
        )
        if forbidden.status_code not in {401, 403}:
            raise AssertionError(
                f"verifier credential unexpectedly acquired write authority: {forbidden.status_code}"
            )

        connector_evidence = asyncio.run(
            run_connectors(args.base_url, writer_secret, verifier_secret)
        )
        sessions_after = admin.active_sessions(user_id)
        if sessions_after != 0:
            raise AssertionError(f"expected zero active sessions after revoke, got {sessions_after}")

        evidence = {
            "status": "passed",
            "generated_at": datetime.now(UTC).isoformat(),
            "qualification": (
                "High-fidelity connector acceptance against a real ephemeral Keycloak "
                "server; not production tenant evidence."
            ),
            "keycloak": {
                "reported_version": admin.server_version(),
                "realm": REALM,
                "writer_client": WRITER_CLIENT,
                "verifier_client": VERIFIER_CLIENT,
                "writer_verifier_separated": WRITER_CLIENT != VERIFIER_CLIENT,
                "verifier_write_status": forbidden.status_code,
                "sessions_before": sessions_before,
                "sessions_after": sessions_after,
            },
            "connectors": connector_evidence,
        }
        path = Path(args.evidence_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(evidence, indent=2, sort_keys=True))
    finally:
        admin.close()
        for name in (
            "BAA_KEYCLOAK_WRITER_SECRET",
            "BAA_KEYCLOAK_VERIFIER_SECRET",
        ):
            os.environ.pop(name, None)


if __name__ == "__main__":
    main()
