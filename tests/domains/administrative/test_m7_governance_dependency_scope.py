from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from administrative_orchestrator.authority import ApprovalSatisfaction, AuthorityRepository
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AdministrativeRequest,
    CaseStatus,
    Decision,
    DecisionDisposition,
    FactAuthority,
    FactSnapshot,
    Principal,
    PrincipalKind,
    RoleAssignment,
)
from administrative_orchestrator.fact_acquisition import (
    AuthoritativeFactRevalidator,
    merge_authoritative_offboarding_facts,
)
from administrative_orchestrator.governance import (
    GovernanceBasis,
    GovernanceRepository,
    _digest,
)
from administrative_orchestrator.integrations.authoritative_sources import (
    AuthoritativeRecord,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy_plane import (
    PolicyRepository,
    default_offboarding_policy_version,
)
from administrative_orchestrator.unit_of_work import _expected_governance_change_keys

_FACTS = {
    "employee_ref": "odoo:hr.employee:42",
    "termination_status": "termination_scheduled",
    "termination_effective_at": "2026-10-01T18:00:00Z",
    "active": True,
}


def _snapshot(facts: dict | None = None) -> FactSnapshot:
    return FactSnapshot(
        source="intake:test",
        owner="person:test",
        authority=FactAuthority.CLAIM,
        source_ref="intake:test/event:1",
        source_version="m7-human-confirmed-v1",
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        facts=dict(_FACTS if facts is None else facts),
    )


def _case_and_record():
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    policies = PolicyRepository(store)
    record = default_offboarding_policy_version()
    policies.put_version(record)
    request = AdministrativeRequest(
        requester_principal_id="person:test",
        channel="test",
        intent="offboard employee:42",
    )
    case = AdministrativeCase(
        case_kind="employee-offboarding",
        requester_principal_id="person:test",
        subject_ref="odoo:hr.employee:42",
        policy_ref=record.policy_ref,
        fact_snapshot=_snapshot(),
    )
    store.create_case(request, case)
    return store, case, record


def _basis(case, record, *, dependency_keys, expected_change_keys=('active',)):
    snapshot = case.fact_snapshot
    assert snapshot is not None
    return GovernanceBasis(
        basis_id=uuid4(),
        case_id=case.case_id,
        case_version_at_basis=case.version,
        authority_epoch=case.authority_epoch,
        fact_snapshot_id=snapshot.snapshot_id,
        fact_digest=_digest(snapshot.facts),
        policy_ref=record.policy_ref,
        policy_definition_digest=_digest(record.definition),
        organization_scope="*",
        approval_satisfaction_id=uuid4(),
        qualifications=(),
        authority_digest="test",
        basis_digest="test",
        fact_dependency_keys=dependency_keys,
        fact_dependency_values=(
            {}
            if dependency_keys is None
            else {key: snapshot.facts.get(key) for key in dependency_keys}
        ),
        expected_change_keys=expected_change_keys,
    )


def test_basis_rejects_dependency_that_is_expected_to_change() -> None:
    _, case, record = _case_and_record()
    with pytest.raises(ValueError, match='cannot be governance dependencies'):
        _basis(case, record, dependency_keys=('active',))


def test_dependency_scoped_basis_ignores_expected_self_induced_change() -> None:
    store, case, record = _case_and_record()
    basis = _basis(
        case,
        record,
        dependency_keys=(
            'employee_ref',
            'termination_status',
            'termination_effective_at',
        ),
    )
    repository = GovernanceRepository(store)
    assert repository.revalidate(basis, case).valid is True

    changed = dict(_FACTS)
    changed['active'] = False
    after_expected_change = case.model_copy(update={'fact_snapshot': _snapshot(changed)})
    assert repository.revalidate(basis, after_expected_change).valid is True

    rescheduled = dict(_FACTS)
    rescheduled['termination_effective_at'] = '2026-10-02T18:00:00Z'
    after_real_change = case.model_copy(update={'fact_snapshot': _snapshot(rescheduled)})
    validation = repository.revalidate(basis, after_real_change)
    assert validation.valid is False
    assert any(
        'termination_effective_at' in reason for reason in validation.reasons
    )


def test_legacy_basis_keeps_whole_snapshot_semantics() -> None:
    store, case, record = _case_and_record()
    basis = _basis(case, record, dependency_keys=None, expected_change_keys=())
    repository = GovernanceRepository(store)
    assert repository.revalidate(basis, case).valid is True

    changed = dict(_FACTS)
    changed['active'] = False
    after_change = case.model_copy(update={'fact_snapshot': _snapshot(changed)})
    validation = repository.revalidate(basis, after_change)
    assert validation.valid is False
    assert any('snapshot differs' in reason for reason in validation.reasons)


def test_authoritative_revalidator_can_skip_expected_change() -> None:
    _, case, _ = _case_and_record()
    authoritative = merge_authoritative_offboarding_facts(
        case,
        AuthoritativeRecord.build(
            source='odoo',
            source_ref='odoo:hr.employee:42',
            source_version='v1',
            value={
                'present': True,
                'employee_ref': 'odoo:hr.employee:42',
                'termination_status': 'termination_scheduled',
                'termination_effective_at': '2026-10-01T18:00:00Z',
                'active': True,
            },
        ),
    )
    case = case.model_copy(update={'fact_snapshot': authoritative})

    class _Source:
        def read_employee(self, employee_ref: str):
            del employee_ref
            return AuthoritativeRecord.build(
                source='odoo',
                source_ref='odoo:hr.employee:42',
                source_version='v2',
                value={
                    'present': True,
                    'employee_ref': 'odoo:hr.employee:42',
                    'termination_status': 'termination_scheduled',
                    'termination_effective_at': '2026-10-01T18:00:00Z',
                    'active': False,
                },
            )

    strict = AuthoritativeFactRevalidator(_Source(), max_age_seconds=300).validate(case)
    assert strict.valid is False
    assert any('active' in reason for reason in strict.reasons)

    tolerant = AuthoritativeFactRevalidator(
        _Source(), max_age_seconds=300
    ).validate_with_dependencies(case, expected_change_keys=('active',))
    assert tolerant.valid is True


def test_offboarding_approval_declares_active_as_self_induced_change() -> None:
    _, case, _ = _case_and_record()

    assert _expected_governance_change_keys(case) == ("active",)


def test_non_offboarding_approval_has_no_lifecycle_self_induced_changes() -> None:
    _, case, _ = _case_and_record()
    onboarding = case.model_copy(update={"case_kind": "employee-onboarding"})

    assert _expected_governance_change_keys(onboarding) == ()


def test_decision_transition_persists_offboarding_expected_change_keys() -> None:
    store, case, record = _case_and_record()
    authority = AuthorityRepository(store)
    authority.put_principal(
        Principal(
            principal_id="person:approver",
            kind=PrincipalKind.PERSON,
            display_name="approver",
        )
    )
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:approver",
            role="hr_approver",
            organization_scope="*",
            valid_from=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    decision = Decision(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        principal_id="person:approver",
        decision_role="hr_approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="approved",
        policy_ref=record.policy_ref,
    )
    after = case.model_copy(
        update={"status": CaseStatus.AUTHORIZED, "version": case.version + 1}
    )
    satisfaction = ApprovalSatisfaction(
        satisfaction_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        policy_ref=record.policy_ref,
        decision_ids=(decision.decision_id,),
        satisfied_roles=("hr_approver",),
    )

    from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork

    AdministrativeUnitOfWork(store).apply_decision_transition(
        case,
        after,
        decision,
        organization_scope="*",
        approval_satisfaction=satisfaction,
    )

    basis = GovernanceRepository(store).get_for_approval(satisfaction.satisfaction_id)
    assert basis is not None
    assert basis.expected_change_keys == ("active",)

