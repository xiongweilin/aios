from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.production_effects import (
    ConnectorStatus,
    KeycloakEffectConnection,
    KeycloakIdentityDisableConnector,
    KeycloakIdentityDisableVerifier,
    KeycloakIdentityEffectConnector,
    KeycloakSessionRevokeConnector,
    KeycloakSessionVerifier,
    OdooEffectConnection,
    OdooEmployeeDeactivateConnector,
    OdooEmployeeDeactivateVerifier,
    OdooEmployeeEffectConnector,
    _ApplicationRejected,
    _TransportUnknown,
)


def _odoo() -> OdooEmployeeEffectConnector:
    return OdooEmployeeEffectConnector(
        OdooEffectConnection(
            base_url="https://odoo.example.test",
            database="company",
            username="writer",
            credential=CredentialRef("odoo:writer", "ADMIN_TEST_ODOO_SECRET"),
        )
    )


def _keycloak() -> KeycloakIdentityEffectConnector:
    return KeycloakIdentityEffectConnector(
        KeycloakEffectConnection(
            base_url="https://idp.example.test",
            realm="company",
            client_id="writer",
            credential=CredentialRef("keycloak:writer", "ADMIN_TEST_KEYCLOAK_SECRET"),
        )
    )


@pytest.mark.asyncio
async def test_odoo_deactivate_uses_exact_employee_and_durable_request_ref(
    monkeypatch,
) -> None:
    base = _odoo()
    connector = OdooEmployeeDeactivateConnector(base)
    read = AsyncMock(
        return_value={
            "id": 42,
            "active": True,
            "x_administrative_deactivate_request_ref": False,
        }
    )
    execute = AsyncMock(return_value=True)
    monkeypatch.setattr(connector, "_read", read)
    monkeypatch.setattr(base, "_execute_kw", execute)

    result = await connector.invoke(
        request_ref="request:offboard:1",
        subject_ref="odoo:hr.employee:42",
        parameters={},
    )
    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.external_operation_ref == "odoo:hr.employee:42"
    assert read.await_args.args == (42,)
    assert execute.await_args.args[2] == [
        [42],
        {
            "active": False,
            "x_administrative_deactivate_request_ref": "request:offboard:1",
        },
    ]

    invalid = await connector.invoke(
        request_ref="request:bad", subject_ref="employee:not-exact", parameters={}
    )
    assert invalid.status is ConnectorStatus.FAILED
    assert invalid.error_code == "InvalidOdooEmployeeReference"


@pytest.mark.asyncio
async def test_odoo_deactivate_reconciles_and_verifies_inactive_state(monkeypatch) -> None:
    base = _odoo()
    connector = OdooEmployeeDeactivateConnector(base)
    monkeypatch.setattr(base, "_lookup", AsyncMock(return_value=[{"id": 42}]))
    monkeypatch.setattr(connector, "_read", AsyncMock(return_value={"id": 42, "active": False}))

    result = await connector.reconcile("request:offboard:1")
    assert result is not None
    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.reconciled is True

    observed = await OdooEmployeeDeactivateVerifier(connector).observe(
        subject_ref="employee:42",
        expected_postcondition={"employee_external_ref": "odoo:hr.employee:42"},
    )
    assert observed.observed_postcondition == {
        "target_system": "hris",
        "operation": "employee.deactivate",
        "subject_ref": "employee:42",
        "active": False,
    }

    monkeypatch.setattr(
        connector, "_read", AsyncMock(side_effect=_TransportUnknown("offline"))
    )
    unavailable = await OdooEmployeeDeactivateVerifier(connector).observe(
        subject_ref="employee:42",
        expected_postcondition={"employee_external_ref": "odoo:hr.employee:42"},
    )
    assert unavailable.status is ConnectorStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_keycloak_disable_merges_attributes_and_has_independent_readback(
    monkeypatch,
) -> None:
    base = _keycloak()
    user = {
        "id": "user-1",
        "username": "alice",
        "enabled": True,
        "attributes": {
            "administrative_subject_ref": ["employee:1"],
            "preserve_me": ["yes"],
        },
    }
    monkeypatch.setattr(base, "_find_by_attribute", AsyncMock(return_value=[{"id": "user-1"}]))
    monkeypatch.setattr(base, "_get_user", AsyncMock(return_value=user))
    request = AsyncMock(return_value=httpx.Response(204))
    monkeypatch.setattr(base, "_request", request)

    result = await KeycloakIdentityDisableConnector(base).invoke(
        request_ref="request:disable:1", subject_ref="employee:1", parameters={}
    )
    assert result.status is ConnectorStatus.SUCCEEDED
    body = request.await_args.kwargs["json_body"]
    assert body["enabled"] is False
    assert body["attributes"]["preserve_me"] == ["yes"]
    assert body["attributes"]["administrative_disable_request_ref"] == [
        "request:disable:1"
    ]

    monkeypatch.setattr(base, "_get_user", AsyncMock(return_value={**user, "enabled": False}))
    observed = await KeycloakIdentityDisableVerifier(base).observe(
        subject_ref="employee:1", expected_postcondition={"enabled": False}
    )
    assert observed.observed_postcondition == {
        "target_system": "iam",
        "operation": "identity.disable",
        "subject_ref": "employee:1",
        "enabled": False,
    }


@pytest.mark.asyncio
async def test_keycloak_session_revoke_marks_request_before_logout_and_reconciles(
    monkeypatch,
) -> None:
    base = _keycloak()
    user = {
        "id": "user-1",
        "username": "alice",
        "enabled": False,
        "attributes": {
            "administrative_subject_ref": ["employee:1"],
            "preserve_me": ["yes"],
        },
    }
    monkeypatch.setattr(base, "_find_by_attribute", AsyncMock(return_value=[{"id": "user-1"}]))
    monkeypatch.setattr(base, "_get_user", AsyncMock(return_value=user))
    request = AsyncMock(
        side_effect=[
            httpx.Response(204),
            httpx.Response(200, json=[{"id": "session-1"}]),
            httpx.Response(204),
        ]
    )
    monkeypatch.setattr(base, "_request", request)

    result = await KeycloakSessionRevokeConnector(base).invoke(
        request_ref="request:sessions:1", subject_ref="employee:1", parameters={}
    )
    assert result.status is ConnectorStatus.SUCCEEDED
    assert request.await_args_list[0].args[0] == "PUT"
    marker_body = request.await_args_list[0].kwargs["json_body"]
    assert marker_body["enabled"] is False
    assert marker_body["attributes"]["preserve_me"] == ["yes"]
    assert request.await_args_list[2].args[0] == "POST"
    assert request.await_args_list[2].args[1].endswith("/user-1/logout")

    monkeypatch.setattr(
        base,
        "_find_by_attribute",
        AsyncMock(return_value=[{"id": "user-1"}]),
    )
    monkeypatch.setattr(base, "_request", AsyncMock(return_value=httpx.Response(200, json=[])))
    recovered = await KeycloakSessionRevokeConnector(base).reconcile(
        "request:sessions:1"
    )
    assert recovered is not None
    assert recovered.status is ConnectorStatus.SUCCEEDED
    assert recovered.reconciled is True

    observed = await KeycloakSessionVerifier(base).observe(
        subject_ref="employee:1", expected_postcondition={"active_sessions": 0}
    )
    assert observed.observed_postcondition["active_sessions"] == 0


@pytest.mark.asyncio
async def test_odoo_deactivate_fail_closed_and_unknown_paths(monkeypatch) -> None:
    base = _odoo()
    connector = OdooEmployeeDeactivateConnector(base)
    monkeypatch.setattr(connector, "_read", AsyncMock(return_value={}))
    missing = await connector.invoke(
        request_ref="request:1", subject_ref="odoo:hr.employee:1", parameters={}
    )
    assert missing.error_code == "OdooEmployeeNotFound"

    connector._read = AsyncMock(
        return_value={
            "id": 1,
            "active": False,
            "x_administrative_deactivate_request_ref": "request:other",
        }
    )
    conflict = await connector.invoke(
        request_ref="request:1", subject_ref="odoo:hr.employee:1", parameters={}
    )
    assert conflict.error_code == "ConflictingExternalRequestIdentity"
    connector._read = AsyncMock(
        return_value={
            "id": 1,
            "active": False,
            "x_administrative_deactivate_request_ref": "request:1",
        }
    )
    assert (
        await connector.invoke(
            request_ref="request:1",
            subject_ref="odoo:hr.employee:1",
            parameters={},
        )
    ).reconciled is True

    connector._read = AsyncMock(
        return_value={
            "id": 1,
            "active": True,
            "x_administrative_deactivate_request_ref": False,
        }
    )
    base._execute_kw = AsyncMock(return_value=False)
    rejected = await connector.invoke(
        request_ref="request:1", subject_ref="odoo:hr.employee:1", parameters={}
    )
    assert rejected.error_code == "OdooDeactivateRejected"
    connector._read = AsyncMock(side_effect=_TransportUnknown("offline"))
    assert (
        await connector.invoke(
            request_ref="request:1",
            subject_ref="odoo:hr.employee:1",
            parameters={},
        )
    ).status is ConnectorStatus.UNKNOWN
    connector._read = AsyncMock(side_effect=_ApplicationRejected("denied"))
    assert (
        await connector.invoke(
            request_ref="request:1",
            subject_ref="odoo:hr.employee:1",
            parameters={},
        )
    ).error_code == "OdooApplicationRejected"

    base._lookup = AsyncMock(return_value=[])
    assert await connector.reconcile("request:none") is None
    base._lookup = AsyncMock(return_value=[{"id": 1}, {"id": 2}])
    assert (
        await connector.reconcile("request:duplicate")
    ).error_code == "DuplicateExternalRequestIdentity"
    base._lookup = AsyncMock(return_value=[{"id": 1}])
    connector._read = AsyncMock(return_value={"id": 1, "active": True})
    assert (
        await connector.reconcile("request:1")
    ).status is ConnectorStatus.UNKNOWN


@pytest.mark.asyncio
async def test_keycloak_disable_fail_closed_and_reconciliation_paths(monkeypatch) -> None:
    base = _keycloak()
    connector = KeycloakIdentityDisableConnector(base)
    monkeypatch.setattr(base, "_find_by_attribute", AsyncMock(return_value=[]))
    missing = await connector.invoke(
        request_ref="request:1", subject_ref="employee:1", parameters={}
    )
    assert missing.error_code == "KeycloakSubjectNotUnique"

    user = {
        "id": "user-1",
        "username": "alice",
        "enabled": False,
        "attributes": {
            "administrative_subject_ref": ["employee:1"],
            "administrative_disable_request_ref": ["request:other"],
        },
    }
    base._find_by_attribute = AsyncMock(return_value=[{"id": "user-1"}])
    monkeypatch.setattr(base, "_get_user", AsyncMock(return_value=user))
    conflict = await connector.invoke(
        request_ref="request:1", subject_ref="employee:1", parameters={}
    )
    assert conflict.error_code == "ConflictingExternalRequestIdentity"
    user["attributes"]["administrative_disable_request_ref"] = ["request:1"]
    assert (
        await connector.invoke(
            request_ref="request:1", subject_ref="employee:1", parameters={}
        )
    ).reconciled is True

    base._find_by_attribute = AsyncMock(return_value=[])
    assert await connector.reconcile("request:none") is None
    base._find_by_attribute = AsyncMock(return_value=[{}, {}])
    assert (
        await connector.reconcile("request:duplicate")
    ).error_code == "DuplicateExternalRequestIdentity"
    base._find_by_attribute = AsyncMock(return_value=[{"id": "user-1"}])
    base._get_user = AsyncMock(return_value={**user, "enabled": True})
    assert (
        await connector.reconcile("request:1")
    ).status is ConnectorStatus.UNKNOWN
    base._find_by_attribute = AsyncMock(side_effect=_TransportUnknown("offline"))
    assert (await connector.reconcile("request:1")).reconciled is True
    base._find_by_attribute = AsyncMock(side_effect=_ApplicationRejected("denied"))
    assert (
        await connector.reconcile("request:1")
    ).error_code == "KeycloakApplicationRejected"


@pytest.mark.asyncio
async def test_keycloak_session_unknown_and_active_reconciliation(monkeypatch) -> None:
    base = _keycloak()
    connector = KeycloakSessionRevokeConnector(base)
    user = {
        "id": "user-1",
        "username": "alice",
        "enabled": False,
        "attributes": {
            "administrative_subject_ref": ["employee:1"],
            "administrative_session_revoke_request_ref": ["request:1"],
        },
    }
    monkeypatch.setattr(base, "_find_by_attribute", AsyncMock(return_value=[{"id": "user-1"}]))
    monkeypatch.setattr(base, "_get_user", AsyncMock(return_value=user))
    monkeypatch.setattr(base, "_request", AsyncMock(return_value=httpx.Response(503)))
    result = await connector.invoke(
        request_ref="request:1", subject_ref="employee:1", parameters={}
    )
    assert result.status is ConnectorStatus.UNKNOWN

    base._request = AsyncMock(
        return_value=httpx.Response(200, json=[{"id": "session-1"}])
    )
    unresolved = await connector.reconcile("request:1")
    assert unresolved is not None
    assert unresolved.error_code == "KeycloakSessionsStillActive"
    assert base._request.await_args.args[0] == "GET"

    base._find_by_attribute = AsyncMock(return_value=[])
    empty = await KeycloakSessionVerifier(base).observe(
        subject_ref="employee:none", expected_postcondition={}
    )
    assert empty.observed_postcondition == {}
    base._find_by_attribute = AsyncMock(side_effect=_ApplicationRejected("denied"))
    unavailable = await KeycloakSessionVerifier(base).observe(
        subject_ref="employee:1", expected_postcondition={}
    )
    assert unavailable.status is ConnectorStatus.UNAVAILABLE
