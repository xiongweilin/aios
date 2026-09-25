from __future__ import annotations

from datetime import UTC, datetime

from administrative_orchestrator.domain import (
    AdministrativeCase,
    AdministrativeRequest,
    FactAuthority,
    FactSnapshot,
)
from administrative_orchestrator.fact_acquisition import (
    AuthoritativeFactRevalidator,
    merge_authoritative_offboarding_facts,
)
from administrative_orchestrator.integrations.authoritative_sources import (
    AuthoritativeRecord,
)
from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.odoo import (
    OdooConnection,
    OdooHRFactSource,
    OdooSourceError,
)
from administrative_orchestrator.persistence import SqlStore


class _Resolver:
    def resolve(self, ref: CredentialRef) -> str:
        return 'secret'


_TERMINATION_FIELDS = {
    'x_administrative_termination_status',
    'x_administrative_termination_effective_at',
    'x_administrative_principal_id',
}


def _odoo_source(*, available_fields: set[str]) -> OdooHRFactSource:
    source = OdooHRFactSource(
        OdooConnection(
            base_url='https://odoo.example.test',
            database='company',
            username='reader',
            reader_credential=CredentialRef('odoo:reader', 'ADMIN_TEST_ODOO_READER'),
        ),
        credentials=_Resolver(),
    )

    def execute(model, method, args, kwargs=None):
        del args
        if model == 'hr.employee' and method == 'fields_get':
            return {name: {'string': name} for name in available_fields}
        if model == 'hr.employee' and method == 'read':
            row = {
                'id': 42,
                'name': 'Alice',
                'department_id': [7, 'Engineering'],
                'parent_id': None,
                'work_email': 'alice@example.test',
                'active': True,
                'write_date': '2026-09-10 09:00:00',
                'x_administrative_termination_status': 'termination_scheduled',
                'x_administrative_termination_effective_at': '2026-10-01T18:00:00Z',
                'x_administrative_principal_id': 'person:departing',
            }
            return [{key: row.get(key) for key in kwargs['fields']}]
        if model == 'hr.contract' and method == 'search_count':
            raise OdooSourceError(
                "Odoo JSON-RPC returned an application error: Object hr.contract does not exist"
            )
        raise AssertionError((model, method))

    source._execute_kw = execute  # type: ignore[method-assign]
    return source


def test_odoo_reader_reads_configured_termination_fields() -> None:
    source = _odoo_source(
        available_fields={
            'id',
            'name',
            'department_id',
            'parent_id',
            'work_email',
            'active',
            'write_date',
            *_TERMINATION_FIELDS,
        }
    )
    record = source.read_employee('odoo:hr.employee:42')
    assert record.value['present'] is True
    assert record.value['termination_status'] == 'termination_scheduled'
    assert record.value['termination_effective_at'] == '2026-10-01T18:00:00Z'
    assert record.value['departing_principal_id'] == 'person:departing'
    assert record.value['department_ref'] == 'odoo:hr.department:7'


def test_odoo_reader_omits_termination_facts_when_fields_are_absent() -> None:
    source = _odoo_source(
        available_fields={
            'id',
            'name',
            'department_id',
            'parent_id',
            'work_email',
            'active',
            'write_date',
        }
    )
    record = source.read_employee('odoo:hr.employee:42')
    assert 'termination_status' not in record.value
    assert 'termination_effective_at' not in record.value


def _offboarding_case_with_claims():
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    request = AdministrativeRequest(
        requester_principal_id="person:test",
        channel="test",
        intent="offboard employee:42",
    )
    snapshot = FactSnapshot(
        source="intake:test",
        owner="person:test",
        authority=FactAuthority.CLAIM,
        source_ref="intake:test/event:1",
        source_version="m7-human-confirmed-v1",
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        facts={
            "employee_ref": "odoo:hr.employee:42",
            "requested_termination_date": "2026-10-01",
        },
    )
    case = AdministrativeCase(
        case_kind="employee-offboarding",
        requester_principal_id="person:test",
        subject_ref="odoo:hr.employee:42",
        fact_snapshot=snapshot,
    )
    store.create_case(request, case)
    return store, case


def _record(*, effective_at: str, status: str = 'termination_scheduled'):
    return AuthoritativeRecord.build(
        source="odoo",
        source_ref="odoo:hr.employee:42",
        source_version="v1",
        value={
            "present": True,
            "employee_ref": "odoo:hr.employee:42",
            "department_ref": "odoo:hr.department:7",
            "termination_status": status,
            "termination_effective_at": effective_at,
            "active": True,
        },
    )


def test_offboarding_merge_overlays_authoritative_termination_facts() -> None:
    _, case = _offboarding_case_with_claims()
    merged = merge_authoritative_offboarding_facts(
        case, _record(effective_at='2026-10-01T18:00:00Z')
    )
    assert merged.source == 'composite:employee-offboarding'
    assert merged.facts['termination_status'] == 'termination_scheduled'
    assert merged.facts['termination_effective_at'] == '2026-10-01T18:00:00Z'
    assert merged.facts['requested_termination_date'] == '2026-10-01'
    assert merged.facts['employee_ref'] == 'odoo:hr.employee:42'
    assert merged.assertions['termination_status'].authority is FactAuthority.AUTHORITATIVE
    assert (
        merged.assertions['requested_termination_date'].authority
        is FactAuthority.CLAIM
    )


def test_offboarding_revalidator_detects_changed_termination_date() -> None:
    _, case = _offboarding_case_with_claims()
    first = _record(effective_at='2026-10-01T18:00:00Z')
    merged = merge_authoritative_offboarding_facts(case, first)
    case = case.model_copy(update={'fact_snapshot': merged})

    class _Source:
        def __init__(self, value):
            self.value = value

        def read_employee(self, employee_ref: str):
            del employee_ref
            return AuthoritativeRecord.build(
                source="odoo",
                source_ref="odoo:hr.employee:42",
                source_version="v2",
                value=dict(self.value),
            )

    unchanged = AuthoritativeFactRevalidator(
        _Source(first.value), max_age_seconds=300
    ).validate(case)
    assert unchanged.valid is True

    changed = AuthoritativeFactRevalidator(
        _Source(_record(effective_at='2026-10-02T18:00:00Z').value),
        max_age_seconds=300,
    ).validate(case)
    assert changed.valid is False
    assert any('termination_effective_at' in reason for reason in changed.reasons)

    cancelled = AuthoritativeFactRevalidator(
        _Source(
            _record(
                effective_at='2026-10-01T18:00:00Z',
                status='termination_cancelled',
            ).value
        ),
        max_age_seconds=300,
    ).validate(case)
    assert cancelled.valid is False
    assert any('termination_status' in reason for reason in cancelled.reasons)


def test_odoo_reader_keeps_base_facts_when_field_introspection_fails() -> None:
    source = _odoo_source(available_fields=set())

    def execute(model, method, args, kwargs=None):
        del args, kwargs
        if model == 'hr.employee' and method == 'fields_get':
            raise OdooSourceError("Odoo JSON-RPC returned an application error: denied")
        if model == 'hr.employee' and method == 'read':
            return [
                {
                    'id': 42,
                    'name': 'Alice',
                    'department_id': [7, 'Engineering'],
                    'parent_id': None,
                    'work_email': 'alice@example.test',
                    'active': True,
                    'write_date': '2026-09-10 09:00:00',
                }
            ]
        if model == 'hr.contract' and method == 'search_count':
            raise OdooSourceError(
                "Odoo JSON-RPC returned an application error: Object hr.contract does not exist"
            )
        raise AssertionError((model, method))

    source._execute_kw = execute  # type: ignore[method-assign]
    record = source.read_employee('odoo:hr.employee:42')
    assert record.value['present'] is True
    assert 'termination_status' not in record.value


def _offboarding_refresh_context(monkeypatch):
    from administrative_orchestrator import operations_api
    from administrative_orchestrator.policy_plane import (
        PolicyRepository,
        default_offboarding_policy_version,
    )
    from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork

    store, case = _offboarding_case_with_claims()
    policies = PolicyRepository(store)
    policies.put_version(default_offboarding_policy_version())
    monkeypatch.setattr(operations_api, "_policies", policies)
    monkeypatch.setattr(operations_api, "_uow", AdministrativeUnitOfWork(store))
    return operations_api, case


def test_apply_authoritative_refresh_advances_offboarding_to_decision(monkeypatch) -> None:
    from administrative_orchestrator.domain import CaseStatus

    operations_api, case = _offboarding_refresh_context(monkeypatch)
    updated = operations_api._apply_authoritative_refresh(
        case, _record(effective_at='2026-10-01T18:00:00Z')
    )
    assert updated.status is CaseStatus.AWAITING_DECISION
    assert updated.fact_snapshot is not None
    assert (
        updated.fact_snapshot.assertions['termination_status'].authority
        is FactAuthority.AUTHORITATIVE
    )


def test_apply_authoritative_refresh_reopens_offboarding_when_cancelled(monkeypatch) -> None:
    from administrative_orchestrator.domain import CaseStatus

    operations_api, case = _offboarding_refresh_context(monkeypatch)
    updated = operations_api._apply_authoritative_refresh(
        case,
        _record(
            effective_at='2026-10-01T18:00:00Z',
            status='termination_cancelled',
        ),
    )
    assert updated.status is CaseStatus.REOPEN_REQUIRED


def test_apply_authoritative_refresh_keeps_onboarding_behavior(monkeypatch) -> None:
    from administrative_orchestrator import operations_api
    from administrative_orchestrator.domain import CaseStatus
    from administrative_orchestrator.policy_plane import (
        PolicyRepository,
        default_onboarding_policy_version,
    )
    from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork

    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    request = AdministrativeRequest(
        requester_principal_id="person:test",
        channel="test",
        intent="onboard employee:42",
    )
    snapshot = FactSnapshot(
        source="intake:test",
        owner="person:test",
        authority=FactAuthority.CLAIM,
        source_ref="intake:test/event:1",
        source_version="m6-human-confirmed-v1",
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        facts={
            "employee_ref": "odoo:hr.employee:42",
            "department_ref": "Engineering",
            "manager_principal_id": "person:manager",
            "start_date": "2026-10-01",
            "employment_type": "full_time",
        },
    )
    case = AdministrativeCase(
        case_kind="employee-onboarding",
        requester_principal_id="person:test",
        subject_ref="odoo:hr.employee:42",
        fact_snapshot=snapshot,
    )
    store.create_case(request, case)
    policies = PolicyRepository(store)
    policies.put_version(default_onboarding_policy_version())
    monkeypatch.setattr(operations_api, '_policies', policies)
    monkeypatch.setattr(operations_api, '_uow', AdministrativeUnitOfWork(store))

    updated = operations_api._apply_authoritative_refresh(
        case,
        _record(effective_at='2026-10-01T18:00:00Z'),
    )
    assert updated.status is CaseStatus.AWAITING_DECISION
