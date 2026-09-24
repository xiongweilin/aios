from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.production_effects import (
    ConnectorConfigurationError,
    ConnectorStatus,
    KeycloakEffectConnection,
    KeycloakIdentityEffectConnector,
    KeycloakIdentityVerifier,
    OdooEffectConnection,
    OdooEmployeeEffectConnector,
    OdooEmployeeVerifier,
    _ApplicationRejected,
    _TransportUnknown,
)


class _Resolver:
    def resolve(self, ref: CredentialRef) -> str:
        assert ref.configuration_ref
        return "secret"


def _odoo_connector(*, client=None) -> OdooEmployeeEffectConnector:
    return OdooEmployeeEffectConnector(
        OdooEffectConnection(
            base_url="https://odoo.example.test",
            database="company",
            username="writer",
            credential=CredentialRef("odoo:writer", "ADMIN_TEST_ODOO_WRITER"),
        ),
        credentials=_Resolver(),
        client=client,
    )


def _keycloak_connector(*, client=None) -> KeycloakIdentityEffectConnector:
    return KeycloakIdentityEffectConnector(
        KeycloakEffectConnection(
            base_url="https://idp.example.test",
            realm="company",
            client_id="writer-client",
            credential=CredentialRef("keycloak:writer", "ADMIN_TEST_KEYCLOAK_WRITER"),
        ),
        credentials=_Resolver(),
        client=client,
    )


@pytest.mark.asyncio
async def test_odoo_invoke_duplicate_existing_and_created_payload(monkeypatch) -> None:
    connector = _odoo_connector()
    monkeypatch.setattr(
        connector,
        "_lookup",
        AsyncMock(return_value=[{"id": 1}, {"id": 2}]),
    )
    duplicate = await connector.invoke(
        request_ref="request:1",
        subject_ref="employee:42",
        parameters={},
    )
    assert duplicate.status is ConnectorStatus.FAILED
    assert duplicate.error_code == "DuplicateExternalRequestIdentity"

    connector = _odoo_connector()
    monkeypatch.setattr(connector, "_lookup", AsyncMock(return_value=[{"id": 42}]))
    existing = await connector.invoke(
        request_ref="request:1",
        subject_ref="employee:42",
        parameters={},
    )
    assert existing.status is ConnectorStatus.SUCCEEDED
    assert existing.reconciled is True
    assert existing.external_operation_ref == "odoo:hr.employee:42"

    connector = _odoo_connector()
    lookup = AsyncMock(return_value=[])
    execute = AsyncMock(return_value=43)
    monkeypatch.setattr(connector, "_lookup", lookup)
    monkeypatch.setattr(connector, "_execute_kw", execute)
    created = await connector.invoke(
        request_ref="request:2",
        subject_ref="employee:43",
        parameters={
            "name": "Alice",
            "work_email": "alice@example.test",
            "department_ref": "odoo:hr.department:7",
            "manager_ref": "odoo:hr.employee:5",
            "manager_principal_id": "person:manager",
            "employment_type": "employee",
            "start_date": "2026-09-15",
        },
    )
    assert created.status is ConnectorStatus.SUCCEEDED
    assert created.external_operation_ref == "odoo:hr.employee:43"
    values = execute.await_args.args[2][0]
    assert values["department_id"] == 7
    assert values["parent_id"] == 5
    assert values["x_administrative_manager_principal_id"] == "person:manager"
    assert values["x_administrative_employment_type"] == "employee"
    assert values["x_administrative_start_date"] == "2026-09-15"


@pytest.mark.asyncio
async def test_odoo_invoke_and_reconcile_failure_semantics(monkeypatch) -> None:
    connector = _odoo_connector()
    monkeypatch.setattr(connector, "_lookup", AsyncMock(return_value=[]))
    monkeypatch.setattr(connector, "_execute_kw", AsyncMock(return_value="not-an-id"))
    invalid = await connector.invoke(
        request_ref="request:invalid",
        subject_ref="employee:invalid",
        parameters={"employee_ref": "employee:invalid"},
    )
    assert invalid.status is ConnectorStatus.FAILED
    assert invalid.error_code == "InvalidOdooCreateResult"

    monkeypatch.setattr(
        connector,
        "_lookup",
        AsyncMock(side_effect=_TransportUnknown("ambiguous")),
    )
    unknown = await connector.invoke(
        request_ref="request:unknown",
        subject_ref="employee:unknown",
        parameters={},
    )
    assert unknown.status is ConnectorStatus.UNKNOWN

    monkeypatch.setattr(
        connector,
        "_lookup",
        AsyncMock(side_effect=_ApplicationRejected("denied")),
    )
    rejected = await connector.invoke(
        request_ref="request:rejected",
        subject_ref="employee:rejected",
        parameters={},
    )
    assert rejected.status is ConnectorStatus.FAILED
    assert rejected.error_code == "OdooApplicationRejected"

    connector = _odoo_connector()
    monkeypatch.setattr(connector, "_lookup", AsyncMock(return_value=[]))
    assert await connector.reconcile("request:none") is None

    monkeypatch.setattr(
        connector,
        "_lookup",
        AsyncMock(return_value=[{"id": 1}, {"id": 2}]),
    )
    duplicate = await connector.reconcile("request:duplicate")
    assert duplicate is not None
    assert duplicate.status is ConnectorStatus.FAILED
    assert duplicate.reconciled is True

    monkeypatch.setattr(
        connector,
        "_lookup",
        AsyncMock(side_effect=_TransportUnknown("offline")),
    )
    ambiguous = await connector.reconcile("request:ambiguous")
    assert ambiguous is not None
    assert ambiguous.status is ConnectorStatus.UNKNOWN
    assert ambiguous.reconciled is True

    monkeypatch.setattr(
        connector,
        "_lookup",
        AsyncMock(side_effect=_ApplicationRejected("denied")),
    )
    failed = await connector.reconcile("request:failed")
    assert failed is not None
    assert failed.error_code == "OdooApplicationRejected"


@pytest.mark.asyncio
async def test_odoo_rpc_execution_and_verifier_branches(monkeypatch) -> None:
    responses = iter(
        [
            httpx.Response(200, json={"result": 9}),
            httpx.Response(200, json={"result": 55}),
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        response = next(responses)
        response.request = request
        return response

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = _odoo_connector(client=client)
    result = await connector._execute_kw("hr.employee", "create", [{"name": "Alice"}], {})
    assert result == 55
    await client.aclose()

    connector = _odoo_connector()
    monkeypatch.setattr(connector, "_rpc", AsyncMock(return_value=0))
    with pytest.raises(_ApplicationRejected, match="authentication rejected"):
        await connector._execute_kw("hr.employee", "read", [[1]], {})

    verifier_connector = _odoo_connector()
    monkeypatch.setattr(
        verifier_connector,
        "_lookup",
        AsyncMock(return_value=[{"id": 42}]),
    )
    monkeypatch.setattr(
        verifier_connector,
        "_execute_kw",
        AsyncMock(
            return_value=[
                {
                    "id": 42,
                    "department_id": [7, "Engineering"],
                    "parent_id": [5, "Manager"],
                    "active": True,
                    "x_administrative_manager_principal_id": "person:manager",
                    "x_administrative_employment_type": "employee",
                    "x_administrative_start_date": "2026-09-15",
                }
            ]
        ),
    )
    observed = await OdooEmployeeVerifier(verifier_connector).observe(
        subject_ref="employee:42",
        expected_postcondition={
            "payload": {
                "employee_ref": "employee:42",
                "department_ref": "odoo:hr.department:7",
                "manager_principal_id": "person:manager",
                "employment_type": "employee",
                "start_date": "2026-09-15",
                "opaque_expected_field": "same",
            }
        },
    )
    assert observed.status is ConnectorStatus.SUCCEEDED
    assert observed.observed_postcondition == {
        "target_system": "hris",
        "operation": "employee.create",
        "subject_ref": "employee:42",
        "active": True,
        "payload": {
            "employee_ref": "employee:42",
            "department_ref": "odoo:hr.department:7",
            "manager_principal_id": "person:manager",
            "employment_type": "employee",
            "start_date": "2026-09-15",
            "opaque_expected_field": "same",
        },
    }

    monkeypatch.setattr(verifier_connector, "_lookup", AsyncMock(return_value=[]))
    empty = await OdooEmployeeVerifier(verifier_connector).observe(
        subject_ref="employee:none",
        expected_postcondition={"payload": {}},
    )
    assert empty.observed_postcondition == {}

    monkeypatch.setattr(
        verifier_connector,
        "_lookup",
        AsyncMock(side_effect=_TransportUnknown("offline")),
    )
    unavailable = await OdooEmployeeVerifier(verifier_connector).observe(
        subject_ref="employee:offline",
        expected_postcondition={},
    )
    assert unavailable.status is ConnectorStatus.UNAVAILABLE

    monkeypatch.setattr(
        verifier_connector,
        "_lookup",
        AsyncMock(side_effect=_ApplicationRejected("denied")),
    )
    rejected = await OdooEmployeeVerifier(verifier_connector).observe(
        subject_ref="employee:denied",
        expected_postcondition={},
    )
    assert rejected.status is ConnectorStatus.UNAVAILABLE
    assert rejected.error_code == "OdooVerificationRejected"


@pytest.mark.asyncio
async def test_odoo_rpc_transport_and_configuration_fail_closed() -> None:
    with pytest.raises(ConnectorConfigurationError, match="custom x_ fields"):
        OdooEffectConnection(
            base_url="https://odoo.example.test",
            database="company",
            username="writer",
            credential=CredentialRef("odoo:writer", "SECRET"),
            request_ref_field="request_ref",
        )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["invalid"], request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = _odoo_connector(client=client)
    with pytest.raises(_ApplicationRejected, match="non-object"):
        await connector._rpc("common", "authenticate", [])
    await client.aclose()

    async def application_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"message": "denied"}}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(application_error))
    connector = _odoo_connector(client=client)
    with pytest.raises(_ApplicationRejected, match="rejected"):
        await connector._rpc("object", "execute_kw", [])
    await client.aclose()

    async def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(server_error))
    connector = _odoo_connector(client=client)
    with pytest.raises(_TransportUnknown, match="ambiguous"):
        await connector._rpc("object", "execute_kw", [])
    await client.aclose()


@pytest.mark.asyncio
async def test_keycloak_invoke_existing_create_and_rejection_paths(monkeypatch) -> None:
    connector = _keycloak_connector()
    monkeypatch.setattr(
        connector,
        "_find_by_attribute",
        AsyncMock(return_value=[{"id": "a"}, {"id": "b"}]),
    )
    duplicate = await connector.invoke(
        request_ref="request:1",
        subject_ref="employee:42",
        parameters={},
    )
    assert duplicate.status is ConnectorStatus.FAILED
    assert duplicate.error_code == "DuplicateExternalRequestIdentity"

    monkeypatch.setattr(
        connector,
        "_find_by_attribute",
        AsyncMock(return_value=[{"id": "user-42"}]),
    )
    existing = await connector.invoke(
        request_ref="request:1",
        subject_ref="employee:42",
        parameters={},
    )
    assert existing.reconciled is True
    assert existing.external_operation_ref == "keycloak:user:user-42"

    connector = _keycloak_connector()
    find = AsyncMock(side_effect=[[], [], [{"id": "user-created"}]])
    request = AsyncMock(return_value=httpx.Response(201))
    monkeypatch.setattr(connector, "_find_by_attribute", find)
    monkeypatch.setattr(connector, "_request", request)
    created = await connector.invoke(
        request_ref="request:2",
        subject_ref="employee:43",
        parameters={
            "work_email": "alice@example.test",
            "employee_ref": "employee:43",
            "department_ref": "department:7",
            "manager_principal_id": "person:manager",
            "start_date": "2026-09-15",
            "employment_type": "employee",
        },
    )
    assert created.status is ConnectorStatus.SUCCEEDED
    assert created.external_operation_ref == "keycloak:user:user-created"
    body = request.await_args.kwargs["json_body"]
    assert body["username"] == "alice@example.test"
    assert body["attributes"]["administrative_employee_ref"] == ["employee:43"]
    assert body["attributes"]["administrative_department_ref"] == ["department:7"]

    connector = _keycloak_connector()
    monkeypatch.setattr(connector, "_find_by_attribute", AsyncMock(return_value=[]))
    monkeypatch.setattr(connector, "_request", AsyncMock(return_value=httpx.Response(503)))
    ambiguous = await connector.invoke(
        request_ref="request:3",
        subject_ref="employee:44",
        parameters={},
    )
    assert ambiguous.status is ConnectorStatus.UNKNOWN
    assert ambiguous.error_code == "KeycloakServerResultAmbiguous"

    monkeypatch.setattr(connector, "_request", AsyncMock(return_value=httpx.Response(400)))
    rejected = await connector.invoke(
        request_ref="request:4",
        subject_ref="employee:45",
        parameters={},
    )
    assert rejected.status is ConnectorStatus.FAILED
    assert rejected.error_code == "KeycloakCreateRejected"

    monkeypatch.setattr(
        connector,
        "_find_by_attribute",
        AsyncMock(side_effect=_TransportUnknown("offline")),
    )
    unknown = await connector.invoke(
        request_ref="request:5",
        subject_ref="employee:46",
        parameters={},
    )
    assert unknown.status is ConnectorStatus.UNKNOWN


@pytest.mark.asyncio
async def test_keycloak_location_reconcile_and_search_user_contracts(monkeypatch) -> None:
    connector = _keycloak_connector()
    monkeypatch.setattr(connector, "_find_by_attribute", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        connector,
        "_request",
        AsyncMock(
            return_value=httpx.Response(
                201,
                headers={"Location": "https://idp.example.test/admin/realms/company/users/u-1"},
            )
        ),
    )
    created = await connector.invoke(
        request_ref="request:location",
        subject_ref="employee:location",
        parameters={"username": "alice"},
    )
    assert created.external_operation_ref == "keycloak:user:u-1"

    connector = _keycloak_connector()
    monkeypatch.setattr(connector, "_find_by_attribute", AsyncMock(return_value=[]))
    assert await connector.reconcile("request:none") is None

    monkeypatch.setattr(
        connector,
        "_find_by_attribute",
        AsyncMock(return_value=[{"id": "a"}, {"id": "b"}]),
    )
    duplicate = await connector.reconcile("request:duplicate")
    assert duplicate is not None
    assert duplicate.status is ConnectorStatus.FAILED
    assert duplicate.reconciled is True

    monkeypatch.setattr(
        connector,
        "_find_by_attribute",
        AsyncMock(return_value=[{"id": "u-2"}]),
    )
    success = await connector.reconcile("request:ok")
    assert success is not None
    assert success.external_operation_ref == "keycloak:user:u-2"

    monkeypatch.setattr(
        connector,
        "_find_by_attribute",
        AsyncMock(side_effect=_TransportUnknown("offline")),
    )
    unknown = await connector.reconcile("request:offline")
    assert unknown is not None
    assert unknown.status is ConnectorStatus.UNKNOWN

    connector = _keycloak_connector()
    monkeypatch.setattr(connector, "_request", AsyncMock(return_value=httpx.Response(503)))
    with pytest.raises(_TransportUnknown, match="search returned HTTP 503"):
        await connector._find_by_attribute("administrative_request_ref", "request:1")

    monkeypatch.setattr(connector, "_request", AsyncMock(return_value=httpx.Response(403)))
    with pytest.raises(_ApplicationRejected, match="search rejected"):
        await connector._find_by_attribute("administrative_request_ref", "request:1")

    monkeypatch.setattr(
        connector,
        "_request",
        AsyncMock(return_value=httpx.Response(200, content=b"not-json")),
    )
    with pytest.raises(_TransportUnknown, match="invalid JSON"):
        await connector._find_by_attribute("administrative_request_ref", "request:1")

    monkeypatch.setattr(
        connector,
        "_request",
        AsyncMock(return_value=httpx.Response(200, json=[{"id": "u"}, "skip"])),
    )
    assert await connector._find_by_attribute("administrative_request_ref", "request:1") == [
        {"id": "u"}
    ]


@pytest.mark.asyncio
async def test_keycloak_token_request_user_and_verifier_fail_closed(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "writer-token"}, request=request)
        return httpx.Response(200, json={"id": "u-1"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = _keycloak_connector(client=client)
    assert await connector._token() == "writer-token"
    response = await connector._request("GET", "/admin/realms/company/users/u-1")
    assert response.status_code == 200
    await client.aclose()

    connector = _keycloak_connector()
    monkeypatch.setattr(connector, "_request", AsyncMock(return_value=httpx.Response(503)))
    with pytest.raises(_TransportUnknown, match="user read returned HTTP 503"):
        await connector._get_user("u-1")

    monkeypatch.setattr(connector, "_request", AsyncMock(return_value=httpx.Response(403)))
    with pytest.raises(_ApplicationRejected, match="user read rejected"):
        await connector._get_user("u-1")

    monkeypatch.setattr(
        connector,
        "_request",
        AsyncMock(return_value=httpx.Response(200, content=b"not-json")),
    )
    with pytest.raises(_TransportUnknown, match="invalid JSON"):
        await connector._get_user("u-1")

    monkeypatch.setattr(
        connector,
        "_request",
        AsyncMock(return_value=httpx.Response(200, json=["wrong-shape"])),
    )
    with pytest.raises(_TransportUnknown, match="invalid representation"):
        await connector._get_user("u-1")

    verifier_connector = _keycloak_connector()
    monkeypatch.setattr(
        verifier_connector,
        "_find_by_attribute",
        AsyncMock(return_value=[]),
    )
    empty = await KeycloakIdentityVerifier(verifier_connector).observe(
        subject_ref="employee:none",
        expected_postcondition={"payload": {}},
    )
    assert empty.status is ConnectorStatus.SUCCEEDED
    assert empty.observed_postcondition == {}

    monkeypatch.setattr(
        verifier_connector,
        "_find_by_attribute",
        AsyncMock(side_effect=_TransportUnknown("offline")),
    )
    unavailable = await KeycloakIdentityVerifier(verifier_connector).observe(
        subject_ref="employee:offline",
        expected_postcondition={},
    )
    assert unavailable.status is ConnectorStatus.UNAVAILABLE

    monkeypatch.setattr(
        verifier_connector,
        "_find_by_attribute",
        AsyncMock(side_effect=_ApplicationRejected("denied")),
    )
    rejected = await KeycloakIdentityVerifier(verifier_connector).observe(
        subject_ref="employee:denied",
        expected_postcondition={},
    )
    assert rejected.status is ConnectorStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_keycloak_missing_token_and_configuration_validation() -> None:
    async def no_token(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(no_token))
    connector = _keycloak_connector(client=client)
    with pytest.raises(_TransportUnknown, match="lacks access_token"):
        await connector._token()
    await client.aclose()

    with pytest.raises(ConnectorConfigurationError, match="realm and client_id"):
        KeycloakEffectConnection(
            base_url="https://idp.example.test",
            realm="",
            client_id="writer",
            credential=CredentialRef("keycloak:writer", "SECRET"),
        )
    with pytest.raises(ConnectorConfigurationError, match="base URL"):
        KeycloakEffectConnection(
            base_url="http://idp.example.test",
            realm="company",
            client_id="writer",
            credential=CredentialRef("keycloak:writer", "SECRET"),
        )
