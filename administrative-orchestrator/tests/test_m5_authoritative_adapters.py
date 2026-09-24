from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from administrative_orchestrator.auth import Authenticator
from administrative_orchestrator.authority import AuthorityRepository, IdentityBinding
from administrative_orchestrator.config import Settings
from administrative_orchestrator.domain import (
    AdministrativeRequest,
    FactAuthority,
    FactSnapshot,
    Principal,
)
from administrative_orchestrator.fact_acquisition import (
    AuthoritativeFactRevalidator,
    FactAcquisitionError,
    build_hris_source,
    merge_authoritative_onboarding_facts,
)
from administrative_orchestrator.integrations.authoritative_sources import (
    AuthoritativeRecord,
    SourceFreshness,
)
from administrative_orchestrator.integrations.credentials import (
    CredentialRef,
    CredentialResolutionError,
    EnvironmentCredentialResolver,
)
from administrative_orchestrator.integrations.keycloak import (
    KeycloakConnection,
    KeycloakIdentityDirectory,
    KeycloakSourceError,
)
from administrative_orchestrator.integrations.odoo import (
    OdooConnection,
    OdooHRFactSource,
    OdooSourceError,
)
from administrative_orchestrator.oidc import OidcVerificationError
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.service import create_case


class _Resolver:
    def resolve(self, ref: CredentialRef) -> str:
        assert ref.configuration_ref
        return "secret"


def _onboarding_case():
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:42",
    )
    snapshot = FactSnapshot(
        source="ingress:test",
        owner=request.requester_principal_id,
        authority=FactAuthority.CLAIM,
        facts={
            "employee_ref": "employee:42",
            "department_ref": "department:claim",
            "requested_systems": ["iam"],
            "requires_privileged_access": False,
        },
    )
    return create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref="employee:42",
        fact_snapshot=snapshot,
    )


def _authoritative(*, source: str = "odoo", source_ref: str = "odoo:hr.employee:42", **values):
    payload = {
        "present": True,
        "employee_ref": "employee:42",
        "department_ref": "odoo:hr.department:7",
        "active": True,
    }
    payload.update(values)
    return AuthoritativeRecord.build(
        source=source,
        source_ref=source_ref,
        source_version="v1",
        value=payload,
    )


def test_authoritative_record_freshness_and_snapshot_contract() -> None:
    record = _authoritative()
    snapshot = record.as_fact_snapshot(owner="service:test")

    assert record.is_fresh_at(record.observed_at, max_age_seconds=1)
    assert snapshot.authority is FactAuthority.AUTHORITATIVE
    assert snapshot.assertions["department_ref"].source_ref == record.source_ref

    stale = record.model_copy(update={"freshness": SourceFreshness.STALE})
    assert not stale.is_fresh_at(record.observed_at, max_age_seconds=60)
    with pytest.raises(ValueError, match="only current authoritative"):
        stale.as_fact_snapshot(owner="service:test")


def test_authoritative_merge_does_not_erase_claims_with_empty_authoritative_values() -> None:
    case = _onboarding_case()
    record = _authoritative(department_ref=None, start_date=None)

    snapshot = merge_authoritative_onboarding_facts(case, record)

    assert snapshot.facts["department_ref"] == "department:claim"
    assert snapshot.assertions["department_ref"].authority is FactAuthority.CLAIM
    assert "start_date" not in snapshot.facts


def test_fact_acquisition_rejects_missing_absent_and_changed_authoritative_truth() -> None:
    case = _onboarding_case()
    with pytest.raises(FactAcquisitionError, match="no current fact snapshot"):
        merge_authoritative_onboarding_facts(
            case.model_copy(update={"fact_snapshot": None}),
            _authoritative(),
        )
    with pytest.raises(FactAcquisitionError, match="reports employee absent"):
        merge_authoritative_onboarding_facts(
            case,
            _authoritative(present=False),
        )

    no_dependencies = AuthoritativeFactRevalidator(_StaticSource(_authoritative()), max_age_seconds=60)
    result = no_dependencies.validate(case)
    assert result.reasons == ("no authoritative HRIS fact dependencies recorded",)

    merged = case.model_copy(
        update={"fact_snapshot": merge_authoritative_onboarding_facts(case, _authoritative())}
    )
    failed = AuthoritativeFactRevalidator(_FailingSource(), max_age_seconds=60).validate(merged)
    assert failed.valid is False
    assert failed.reasons[0].startswith("authoritative HRIS read failed:")

    absent = AuthoritativeFactRevalidator(
        _StaticSource(_authoritative(present=False)),
        max_age_seconds=60,
    ).validate(merged)
    assert absent.reasons == ("authoritative HRIS reports subject absent",)

    changed_source = AuthoritativeFactRevalidator(
        _StaticSource(_authoritative(source="other-hris")),
        max_age_seconds=60,
    ).validate(merged)
    assert "authoritative source changed for employee_ref" in changed_source.reasons

    rebound = AuthoritativeFactRevalidator(
        _StaticSource(_authoritative(source_ref="odoo:hr.employee:99")),
        max_age_seconds=60,
    ).validate(merged)
    assert "authoritative source identity changed for employee_ref" in rebound.reasons


def test_build_hris_source_disabled_odoo_and_unknown_kind() -> None:
    assert build_hris_source(Settings(hris_source_kind="disabled")) is None
    source = build_hris_source(
        Settings(
            hris_source_kind="odoo",
            odoo_base_url="https://odoo.example.test",
            odoo_database="company",
            odoo_reader_username="reader",
        )
    )
    assert isinstance(source, OdooHRFactSource)

    with pytest.raises(FactAcquisitionError, match="unsupported HRIS source kind"):
        build_hris_source(SimpleNamespace(hris_source_kind="unknown"))  # type: ignore[arg-type]


class _StaticSource:
    def __init__(self, record: AuthoritativeRecord) -> None:
        self.record = record

    def read_employee(self, employee_ref: str) -> AuthoritativeRecord:
        assert employee_ref == "employee:42"
        return self.record

    def read_department(self, department_ref: str) -> AuthoritativeRecord:
        raise AssertionError(department_ref)

    def read_manager(self, employee_ref: str) -> AuthoritativeRecord:
        raise AssertionError(employee_ref)


class _FailingSource(_StaticSource):
    def __init__(self) -> None:
        pass

    def read_employee(self, employee_ref: str) -> AuthoritativeRecord:
        raise RuntimeError(f"offline:{employee_ref}")


def _odoo_source() -> OdooHRFactSource:
    return OdooHRFactSource(
        OdooConnection(
            base_url="https://odoo.example.test",
            database="company",
            username="reader",
            reader_credential=CredentialRef("odoo:reader", "ADMIN_TEST_ODOO_READER"),
        ),
        credentials=_Resolver(),
    )


def test_odoo_authoritative_reader_maps_employee_department_and_manager(monkeypatch) -> None:
    source = _odoo_source()

    def execute(model, method, args, kwargs=None):
        del method, args, kwargs
        if model == "hr.employee":
            return [
                {
                    "id": 42,
                    "name": "Alice",
                    "department_id": [7, "Engineering"],
                    "parent_id": [5, "Manager"],
                    "work_email": "alice@example.test",
                    "active": True,
                    "write_date": "2026-09-09 09:00:00",
                }
            ]
        if model == "hr.contract":
            return [
                {
                    "id": 9,
                    "date_start": "2026-09-15",
                    "state": "open",
                    "contract_type_id": [3, "Employee"],
                    "write_date": "2026-09-09 09:01:00",
                }
            ]
        if model == "hr.department":
            return [
                {
                    "id": 7,
                    "name": "Engineering",
                    "manager_id": 5,
                    "parent_id": [2, "Technology"],
                    "active": True,
                    "write_date": "2026-09-09 09:02:00",
                }
            ]
        raise AssertionError(model)

    monkeypatch.setattr(source, "_execute_kw", execute)

    employee = source.read_employee("odoo:hr.employee:42")
    assert employee.value["department_ref"] == "odoo:hr.department:7"
    assert employee.value["manager_ref"] == "odoo:hr.employee:5"
    assert employee.value["employment_type"] == "Employee"
    assert employee.value["start_date"] == "2026-09-15"
    assert "contract:" in employee.source_version

    department = source.read_department("7")
    assert department.value["manager_ref"] == "odoo:hr.employee:5"
    assert department.value["parent_department_ref"] == "odoo:hr.department:2"

    manager = source.read_manager("42")
    assert manager.value == {
        "employee_ref": "odoo:hr.employee:42",
        "manager_ref": "odoo:hr.employee:5",
        "present": True,
    }


def test_odoo_authoritative_reader_tolerates_absent_contract_model(monkeypatch) -> None:
    source = _odoo_source()

    def execute(model, method, args, kwargs=None):
        del method, args, kwargs
        if model == "hr.contract":
            raise OdooSourceError(
                "Odoo JSON-RPC returned an application error: Object hr.contract does not exist"
            )
        if model == "hr.employee":
            return [
                {
                    "id": 42,
                    "name": "Alice",
                    "department_id": False,
                    "parent_id": False,
                    "work_email": "alice@example.test",
                    "active": True,
                    "write_date": "2026-09-09 09:00:00",
                }
            ]
        raise AssertionError(model)

    monkeypatch.setattr(source, "_execute_kw", execute)

    employee = source.read_employee("odoo:hr.employee:42")
    assert employee.value["present"] is True
    assert employee.value["department_ref"] is None
    assert employee.value["manager_ref"] is None
    assert employee.value["employment_state"] is None
    assert employee.value["employment_type"] is None
    assert employee.value["start_date"] is None
    assert "contract:" not in employee.source_version


def test_odoo_authoritative_reader_absence_validation_and_jsonrpc(monkeypatch) -> None:
    source = _odoo_source()
    monkeypatch.setattr(source, "_execute_kw", lambda *args, **kwargs: [])
    missing = source.read_employee("42")
    assert missing.value["present"] is False
    assert missing.value["model"] == "hr.employee"

    with pytest.raises(OdooSourceError, match="invalid Odoo hr.employee reference"):
        source.read_employee("employee:bad")
    with pytest.raises(ValueError, match="base_url is not permitted"):
        OdooConnection(
            base_url="http://odoo.example.test",
            database="company",
            username="reader",
            reader_credential=CredentialRef("odoo:reader", "SECRET"),
        )
    with pytest.raises(ValueError, match="database and reader username"):
        OdooConnection(
            base_url="https://odoo.example.test",
            database="",
            username="reader",
            reader_credential=CredentialRef("odoo:reader", "SECRET"),
        )

    responses = iter(
        [
            httpx.Response(200, json={"result": 7}),
            httpx.Response(200, json={"result": [{"id": 42}]}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        response = next(responses)
        response.request = request
        return response

    live = OdooHRFactSource(
        source.connection,
        credentials=_Resolver(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    rows = live._execute_kw("hr.employee", "read", [[42]], {})
    assert rows == [{"id": 42}]

    monkeypatch.setattr(live, "_rpc", lambda *args, **kwargs: 0)
    with pytest.raises(OdooSourceError, match="authentication failed"):
        live._execute_kw("hr.employee", "read", [[42]], {})


def test_odoo_jsonrpc_rejects_transport_non_object_and_application_error() -> None:
    connection = _odoo_source().connection

    def assert_error(response: httpx.Response, pattern: str) -> None:
        response.request = httpx.Request("POST", "https://odoo.example.test/jsonrpc")
        client = httpx.Client(transport=httpx.MockTransport(lambda request: response))
        source = OdooHRFactSource(connection, credentials=_Resolver(), client=client)
        with pytest.raises(OdooSourceError, match=pattern):
            source._rpc("common", "authenticate", [])

    assert_error(httpx.Response(503), "authoritative read failed")
    assert_error(httpx.Response(200, json=[1, 2]), "response is invalid")
    assert_error(httpx.Response(200, json={"error": {"message": "denied"}}), "application error")


def _keycloak_directory(*, client=None) -> KeycloakIdentityDirectory:
    return KeycloakIdentityDirectory(
        KeycloakConnection(
            base_url="https://idp.example.test",
            realm="company",
            client_id="reader-client",
            reader_credential=CredentialRef("keycloak:reader", "ADMIN_TEST_KEYCLOAK_READER"),
        ),
        credentials=_Resolver(),
        client=client,
    )


def test_keycloak_authoritative_directory_maps_identity_and_resolution(monkeypatch) -> None:
    directory = _keycloak_directory()

    def get(path: str, *, params=None):
        if path.endswith("/users/user-42"):
            return {
                "id": "user-42",
                "username": "alice",
                "email": "alice@example.test",
                "enabled": True,
                "emailVerified": True,
                "attributes": {"employee_ref": ["employee:42"]},
            }
        if path.endswith("/users/user-42/groups"):
            return [{"path": "/engineering"}, {"name": "fallback"}]
        if path.endswith("/users/user-42/role-mappings/realm/composite"):
            return [{"name": "employee"}, {"name": "reader"}]
        if path.endswith("/users"):
            assert params == {"username": "alice", "exact": "true", "max": "2"}
            return [{"id": "user-42"}]
        raise AssertionError(path)

    monkeypatch.setattr(directory, "_get", get)

    identity = directory.read_identity("keycloak:user:user-42")
    assert identity.value["groups"] == ["/engineering", "fallback"]
    assert identity.value["realm_roles"] == ["employee", "reader"]
    assert identity.value["enabled"] is True

    resolved = directory.resolve_person(" alice ")
    assert resolved.value["present"] is True
    assert resolved.value["external_identity"] == "alice"


def test_keycloak_directory_absence_nonunique_and_invalid_refs(monkeypatch) -> None:
    directory = _keycloak_directory()
    monkeypatch.setattr(directory, "_get", lambda path, **kwargs: None)
    missing = directory.read_identity("user-404")
    assert missing.value["present"] is False

    monkeypatch.setattr(
        directory,
        "_get",
        lambda path, **kwargs: [{"id": "a"}, {"id": "b"}] if path.endswith("/users") else None,
    )
    unresolved = directory.resolve_person("duplicate")
    assert unresolved.value["match_count"] == 2
    assert unresolved.value["present"] is False

    with pytest.raises(KeycloakSourceError, match="external identity is required"):
        directory.resolve_person("   ")
    with pytest.raises(KeycloakSourceError, match="invalid Keycloak user reference"):
        directory.read_identity("keycloak:user:../../etc/passwd")
    with pytest.raises(ValueError, match="base_url is not permitted"):
        KeycloakConnection(
            base_url="http://idp.example.test",
            realm="company",
            client_id="reader",
            reader_credential=CredentialRef("keycloak:reader", "SECRET"),
        )
    with pytest.raises(ValueError, match="realm and client_id"):
        KeycloakConnection(
            base_url="https://idp.example.test",
            realm="",
            client_id="reader",
            reader_credential=CredentialRef("keycloak:reader", "SECRET"),
        )


def test_keycloak_token_and_get_http_contracts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "reader-token"})
        if request.url.path.endswith("/users/missing"):
            return httpx.Response(404)
        return httpx.Response(200, json={"id": "user-42"})

    directory = _keycloak_directory(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert directory._token() == "reader-token"
    assert directory._get("/admin/realms/company/users/missing") is None
    assert directory._get("/admin/realms/company/users/user-42") == {"id": "user-42"}


def test_keycloak_token_and_get_fail_closed() -> None:
    def token_without_access(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    directory = _keycloak_directory(
        client=httpx.Client(transport=httpx.MockTransport(token_without_access))
    )
    with pytest.raises(KeycloakSourceError, match="lacks access_token"):
        directory._token()

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    directory = _keycloak_directory(client=httpx.Client(transport=httpx.MockTransport(server_error)))
    with pytest.raises(KeycloakSourceError, match="authentication failed"):
        directory._token()


def test_environment_credential_resolution(monkeypatch) -> None:
    resolver = EnvironmentCredentialResolver()
    ref = CredentialRef("odoo:reader", "M5_TEST_SECRET")
    monkeypatch.delenv("M5_TEST_SECRET", raising=False)
    with pytest.raises(CredentialResolutionError, match="is unavailable"):
        resolver.resolve(ref)
    monkeypatch.setenv("M5_TEST_SECRET", "secret-value")
    assert resolver.resolve(ref) == "secret-value"


class _OidcStub:
    def __init__(self, claims=None, error: Exception | None = None) -> None:
        self.claims = claims or {"sub": "external:alice"}
        self.error = error

    def verify(self, token: str):
        assert token == "signed-token"
        if self.error is not None:
            raise self.error
        return self.claims


def test_authenticator_oidc_resolves_bound_identity_and_fails_closed() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authority = AuthorityRepository(store)
    principal = Principal(principal_id="person:alice", display_name="Alice")
    authority.put_principal(principal)
    authority.put_identity_binding(
        IdentityBinding(
            provider="https://idp.example.test",
            external_subject="external:alice",
            principal_id=principal.principal_id,
        )
    )
    settings = Settings(
        auth_mode="oidc",
        oidc_issuer="https://idp.example.test/",
        oidc_audience="administrative-orchestrator",
    )
    authenticator = Authenticator(store, settings)
    authenticator._oidc_verifier = _OidcStub()  # type: ignore[assignment]
    request = SimpleNamespace(headers={"Authorization": "Bearer signed-token"})

    authenticated = authenticator.authenticate(request)  # type: ignore[arg-type]
    assert authenticated.principal_id == "person:alice"
    assert authenticated.auth_mode == "oidc"

    authenticator._oidc_verifier = _OidcStub(claims={"sub": "external:missing"})  # type: ignore[assignment]
    with pytest.raises(Exception) as missing:
        authenticator.authenticate(request)  # type: ignore[arg-type]
    assert getattr(missing.value, "status_code", None) == 403

    authenticator._oidc_verifier = _OidcStub(  # type: ignore[assignment]
        error=OidcVerificationError("bad signature")
    )
    with pytest.raises(Exception) as invalid:
        authenticator.authenticate(request)  # type: ignore[arg-type]
    assert getattr(invalid.value, "status_code", None) == 401

    for header in ({}, {"Authorization": "Bearer   "}):
        with pytest.raises(Exception) as bearer:
            authenticator.authenticate(SimpleNamespace(headers=header))  # type: ignore[arg-type]
        assert getattr(bearer.value, "status_code", None) == 401
