from __future__ import annotations

from administrative_orchestrator.domain import (
    AdministrativeRequest,
    FactAuthority,
    FactSnapshot,
)
from administrative_orchestrator.fact_acquisition import merge_authoritative_onboarding_facts
from administrative_orchestrator.integrations.authoritative_sources import AuthoritativeRecord
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.production_trust_execution import (
    ProductionTrustOnboardingExecutionEngine,
)
from administrative_orchestrator.service import create_case


class _NoopProvider:
    pass


class _Source:
    def __init__(self, record: AuthoritativeRecord) -> None:
        self.record = record

    def read_employee(self, employee_ref: str) -> AuthoritativeRecord:
        return self.record

    def read_department(self, department_ref: str) -> AuthoritativeRecord:
        raise AssertionError(department_ref)

    def read_manager(self, employee_ref: str) -> AuthoritativeRecord:
        raise AssertionError(employee_ref)


def _record(department: str) -> AuthoritativeRecord:
    return AuthoritativeRecord.build(
        source="odoo",
        source_ref="odoo:hr.employee:42",
        source_version=f"version:{department}",
        value={
            "present": True,
            "employee_ref": "employee:42",
            "department_ref": department,
            "active": True,
        },
    )


def _case(record: AuthoritativeRecord):
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:42",
    )
    initial = FactSnapshot(
        source="ingress:test",
        owner="person:requester",
        authority=FactAuthority.CLAIM,
        facts={
            "employee_ref": "employee:42",
            "department_ref": "department:claim",
            "requested_systems": ["iam"],
            "requires_privileged_access": False,
        },
    )
    case = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref="employee:42",
        fact_snapshot=initial,
    )
    return case.model_copy(update={"fact_snapshot": merge_authoritative_onboarding_facts(case, record)})


def test_production_execution_governance_includes_live_authoritative_truth():
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    recorded = _record("department:engineering")
    case = _case(recorded)
    engine = ProductionTrustOnboardingExecutionEngine(
        store,
        _NoopProvider(),  # type: ignore[arg-type]
        hris_source=_Source(recorded),
        max_fact_age_seconds=300,
    )

    valid = engine._validate_current_governance(case)
    assert valid is not None and valid.valid

    engine.external_facts.source = _Source(_record("department:finance"))
    stale = engine._validate_current_governance(case)
    assert stale is not None and not stale.valid
    assert any("authoritative value changed for department_ref" in reason for reason in stale.reasons)
