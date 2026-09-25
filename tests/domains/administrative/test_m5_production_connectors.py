from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.production_effects import (
    ConnectorStatus,
    KeycloakEffectConnection,
    KeycloakIdentityEffectConnector,
    KeycloakIdentityVerifier,
    OdooEffectConnection,
    OdooEmployeeEffectConnector,
    _TransportUnknown,
)


def _odoo_connector() -> OdooEmployeeEffectConnector:
    return OdooEmployeeEffectConnector(
        OdooEffectConnection(
            base_url="https://odoo.example.test",
            database="company",
            username="runtime-writer",
            credential=CredentialRef("odoo:writer", "ADMIN_TEST_ODOO_SECRET"),
        )
    )


def _keycloak_connector() -> KeycloakIdentityEffectConnector:
    return KeycloakIdentityEffectConnector(
        KeycloakEffectConnection(
            base_url="https://idp.example.test",
            realm="company",
            client_id="runtime-writer",
            credential=CredentialRef("keycloak:writer", "ADMIN_TEST_KEYCLOAK_SECRET"),
        )
    )


@pytest.mark.asyncio
async def test_odoo_transport_ambiguity_is_unknown_and_requires_reconciliation(monkeypatch):
    connector = _odoo_connector()
    monkeypatch.setattr(connector, "_lookup", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        connector,
        "_execute_kw",
        AsyncMock(side_effect=_TransportUnknown("provider result ambiguous")),
    )

    result = await connector.invoke(
        request_ref="req-1",
        subject_ref="employee:42",
        parameters={"employee_ref": "employee:42"},
    )

    assert result.status is ConnectorStatus.UNKNOWN
    assert result.reconciled is False

    monkeypatch.setattr(connector, "_lookup", AsyncMock(return_value=[{"id": 42}]))
    recovered = await connector.reconcile("req-1")
    assert recovered is not None
    assert recovered.status is ConnectorStatus.SUCCEEDED
    assert recovered.reconciled is True
    assert recovered.external_operation_ref == "odoo:hr.employee:42"


@pytest.mark.asyncio
async def test_odoo_reconciliation_rejects_duplicate_external_request_identity(monkeypatch):
    connector = _odoo_connector()
    monkeypatch.setattr(connector, "_lookup", AsyncMock(return_value=[{"id": 1}, {"id": 2}]))

    result = await connector.reconcile("req-duplicate")

    assert result is not None
    assert result.status is ConnectorStatus.FAILED
    assert result.reconciled is True
    assert result.error_code == "DuplicateExternalRequestIdentity"


@pytest.mark.asyncio
async def test_odoo_invoke_reconciles_employee_created_for_the_same_subject(monkeypatch):
    connector = _odoo_connector()
    monkeypatch.setattr(
        connector,
        "_lookup",
        AsyncMock(side_effect=[[], [{"id": 77}]]),
    )
    execute = AsyncMock()
    monkeypatch.setattr(connector, "_execute_kw", execute)

    result = await connector.invoke(
        request_ref="req-new",
        subject_ref="employee:42",
        parameters={"employee_ref": "employee:42"},
    )

    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.reconciled is True
    assert result.external_operation_ref == "odoo:hr.employee:77"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_odoo_invoke_rejects_duplicate_subject_identity(monkeypatch):
    connector = _odoo_connector()
    monkeypatch.setattr(
        connector,
        "_lookup",
        AsyncMock(side_effect=[[], [{"id": 1}, {"id": 2}]]),
    )

    result = await connector.invoke(
        request_ref="req-dup",
        subject_ref="employee:42",
        parameters={},
    )

    assert result.status is ConnectorStatus.FAILED
    assert result.error_code == "DuplicateExternalSubjectIdentity"


@pytest.mark.asyncio
async def test_keycloak_server_5xx_is_unknown_not_definitive_failure(monkeypatch):
    connector = _keycloak_connector()
    monkeypatch.setattr(connector, "_find_by_attribute", AsyncMock(return_value=[]))
    response = httpx.Response(
        503,
        request=httpx.Request("POST", "https://idp.example.test/admin/realms/company/users"),
    )
    monkeypatch.setattr(connector, "_request", AsyncMock(return_value=response))

    result = await connector.invoke(
        request_ref="req-503",
        subject_ref="employee:42",
        parameters={"employee_ref": "employee:42"},
    )

    assert result.status is ConnectorStatus.UNKNOWN
    assert result.error_code == "KeycloakServerResultAmbiguous"


@pytest.mark.asyncio
async def test_keycloak_invoke_reconciles_identity_created_for_the_same_subject(monkeypatch):
    connector = _keycloak_connector()
    monkeypatch.setattr(
        connector,
        "_find_by_attribute",
        AsyncMock(side_effect=[[], [{"id": "user-77"}]]),
    )
    request = AsyncMock()
    monkeypatch.setattr(connector, "_request", request)

    result = await connector.invoke(
        request_ref="req-new",
        subject_ref="employee:42",
        parameters={"employee_ref": "employee:42"},
    )

    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.reconciled is True
    assert result.external_operation_ref == "keycloak:user:user-77"
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_keycloak_invoke_rejects_duplicate_subject_identity(monkeypatch):
    connector = _keycloak_connector()
    monkeypatch.setattr(
        connector,
        "_find_by_attribute",
        AsyncMock(side_effect=[[], [{"id": "user-1"}, {"id": "user-2"}]]),
    )

    result = await connector.invoke(
        request_ref="req-dup",
        subject_ref="employee:42",
        parameters={"employee_ref": "employee:42"},
    )

    assert result.status is ConnectorStatus.FAILED
    assert result.error_code == "DuplicateExternalSubjectIdentity"


@pytest.mark.asyncio
async def test_keycloak_transport_ambiguity_is_unknown(monkeypatch):
    connector = _keycloak_connector()
    monkeypatch.setattr(
        connector,
        "_find_by_attribute",
        AsyncMock(side_effect=_TransportUnknown("network outcome ambiguous")),
    )

    result = await connector.invoke(
        request_ref="req-timeout",
        subject_ref="employee:42",
        parameters={"employee_ref": "employee:42"},
    )

    assert result.status is ConnectorStatus.UNKNOWN


@pytest.mark.asyncio
async def test_keycloak_reconciliation_uses_durable_request_identity(monkeypatch):
    connector = _keycloak_connector()
    lookup = AsyncMock(return_value=[{"id": "user-42"}])
    monkeypatch.setattr(connector, "_find_by_attribute", lookup)

    result = await connector.reconcile("req-42")

    assert result is not None
    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.reconciled is True
    assert result.external_operation_ref == "keycloak:user:user-42"
    lookup.assert_awaited_once_with("administrative_request_ref", "req-42")


@pytest.mark.asyncio
async def test_keycloak_verifier_reports_observed_reality_instead_of_expected_state(monkeypatch):
    connector = _keycloak_connector()
    monkeypatch.setattr(
        connector,
        "_find_by_attribute",
        AsyncMock(return_value=[{"id": "user-42"}]),
    )
    monkeypatch.setattr(
        connector,
        "_get_user",
        AsyncMock(
            return_value={
                "id": "user-42",
                "enabled": True,
                "attributes": {
                    "administrative_subject_ref": ["employee:42"],
                    "administrative_employee_ref": ["employee:42"],
                    "administrative_department_ref": ["department:actual"],
                },
            }
        ),
    )
    expected = {
        "target_system": "iam",
        "operation": "identity.create",
        "subject_ref": "employee:42",
        "active": True,
        "payload": {
            "employee_ref": "employee:42",
            "department_ref": "department:expected",
        },
    }

    result = await KeycloakIdentityVerifier(connector).observe(
        subject_ref="employee:42",
        expected_postcondition=expected,
    )

    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.observed_postcondition is not None
    assert result.observed_postcondition["payload"]["department_ref"] == "department:actual"
    assert result.observed_postcondition != expected
