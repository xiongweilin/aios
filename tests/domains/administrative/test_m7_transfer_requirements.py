from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from administrative_orchestrator.authority import AuthorityRepository, IdentityBinding
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AdministrativeRequest,
    Delegation,
    FactAuthority,
    FactSnapshot,
    Principal,
    PrincipalKind,
    RoleAssignment,
)
from administrative_orchestrator.obligations import (
    ObligationFulfillmentKind,
    derive_administrative_obligations,
    derive_offboarding_obligations,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import OffboardingFacts
from administrative_orchestrator.policy_plane import (
    compile_offboarding_policy,
    default_offboarding_policy_version,
)
from administrative_orchestrator.transfer import (
    TransferError,
    TransferMode,
    TransferRequirementRepository,
    TransferRequirementStatus,
    derive_transfer_requirements,
)

_NOW = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
_EFFECTIVE = _NOW + timedelta(days=10)


def _setup(*, successor: str | None = None):
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authority = AuthorityRepository(store)
    for principal_id in ("person:departing", "person:successor", "person:outsider"):
        authority.put_principal(
            Principal(
                principal_id=principal_id,
                kind=PrincipalKind.PERSON,
                display_name=principal_id,
            )
        )
    manager = authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:departing",
            role="manager",
            organization_scope="org:finance",
            valid_from=_NOW,
        )
    )
    revoke_only = authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:departing",
            role="hr_approver",
            organization_scope="org:finance",
            valid_from=_NOW,
        )
    )
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:successor",
            role="hr_approver",
            organization_scope="org:finance",
            valid_from=_NOW,
        )
    )
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:outsider",
            role="manager",
            organization_scope="org:legal",
            valid_from=_NOW,
        )
    )
    binding = authority.put_identity_binding(
        IdentityBinding(
            provider="keycloak",
            external_subject="kc:departing",
            principal_id="person:departing",
            valid_from=_NOW,
        )
    )
    delegation = authority.put_delegation(
        Delegation(
            from_principal_id="person:departing",
            to_principal_id="person:successor",
            role="hr_approver",
            organization_scope="org:finance",
            valid_from=_NOW,
            valid_until=_EFFECTIVE + timedelta(days=10),
        )
    )
    record = default_offboarding_policy_version()
    policy = compile_offboarding_policy(record)
    facts = OffboardingFacts(
        employee_ref="employee:1",
        termination_status="termination_scheduled",
        termination_effective_at=_EFFECTIVE.isoformat(),
        departing_principal_id="person:departing",
        successor_principal_id=successor,
    )
    request = AdministrativeRequest(
        requester_principal_id="person:operator",
        channel="test",
        intent="offboard employee:1",
    )
    case = AdministrativeCase(
        case_kind="employee-offboarding",
        requester_principal_id=request.requester_principal_id,
        subject_ref="employee:1",
        policy_ref=record.policy_ref,
        fact_snapshot=FactSnapshot(
            source="test-hris",
            owner="hris",
            authority=FactAuthority.AUTHORITATIVE,
            facts=facts.model_dump(mode="json"),
        ),
    )
    store.create_case(request, case)
    return store, authority, policy, case, manager, revoke_only, binding, delegation


def test_missing_successor_stays_explicit_without_removing_revocation_obligations() -> None:
    store, authority, policy, case, manager, revoke_only, binding, delegation = _setup()
    governance_basis_id = uuid4()
    requirements = derive_transfer_requirements(
        case, policy, authority, governance_basis_id=governance_basis_id
    )
    by_role = {item.role: item for item in requirements}
    assert by_role["manager"].transfer_mode is TransferMode.TRANSFER_REQUIRED
    assert by_role["manager"].status is TransferRequirementStatus.SUCCESSOR_MISSING
    assert by_role["hr_approver"].transfer_mode is TransferMode.REVOKE_ONLY
    assert by_role["hr_approver"].status is TransferRequirementStatus.READY_TO_REVOKE

    evaluation = policy.evaluate(OffboardingFacts.model_validate(case.fact_snapshot.facts))
    obligation_set = derive_offboarding_obligations(
        case,
        evaluation,
        policy,
        authority,
        governance_basis_id=governance_basis_id,
        transfer_requirements=requirements,
    )
    kinds = {item.kind for item in obligation_set.obligations}
    assert {
        "hris.employee.deactivate",
        "iam.identity.disable",
        "iam.sessions.revoke",
        "administrative.identity_binding.expire",
        "administrative.role_assignment.expire",
        "administrative.role_assignment.transfer",
        "administrative.delegation.expire",
        "administrative.principal.deactivate",
    } <= kinds
    external = {
        item.required_operation: item.expected_postcondition
        for item in obligation_set.obligations
        if item.fulfillment_kind
        is ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED
    }
    assert external["identity.disable"]["enabled"] is False
    assert external["sessions.revoke"]["active_sessions"] == 0
    assert external["employee.deactivate"]["active"] is False
    domain_obligations = [
        item
        for item in obligation_set.obligations
        if item.fulfillment_kind is ObligationFulfillmentKind.DOMAIN_STATE_VERIFIED
    ]
    assert any(
        item.expected_postcondition.get("assignment_id") == str(manager.assignment_id)
        for item in domain_obligations
    )
    assert any(
        item.expected_postcondition.get("assignment_id")
        == str(revoke_only.assignment_id)
        for item in domain_obligations
    )
    assert any(
        item.expected_postcondition.get("binding_id") == str(binding.binding_id)
        for item in domain_obligations
    )
    assert any(
        item.expected_postcondition.get("delegation_id") == str(delegation.delegation_id)
        for item in domain_obligations
    )
    transfer = next(
        item
        for item in domain_obligations
        if item.kind == "administrative.role_assignment.transfer"
    )
    assert transfer.expected_postcondition["successor_principal_id"] is None

    repository = TransferRequirementRepository(store)
    assert repository.put_all(requirements) == requirements
    assert repository.put_all(requirements) == requirements
    assert repository.list_for_case(case.case_id, case.authority_epoch) == tuple(
        sorted(requirements, key=lambda item: (item.relationship_kind, item.role, item.relationship_ref))
    )


def test_successor_must_be_active_distinct_and_current_in_scope() -> None:
    store, authority, policy, case, *_ = _setup(successor="person:successor")
    governance_basis_id = uuid4()
    qualified = derive_transfer_requirements(
        case, policy, authority, governance_basis_id=governance_basis_id
    )
    manager = next(item for item in qualified if item.role == "manager")
    assert manager.status is TransferRequirementStatus.SUCCESSOR_QUALIFIED
    repository = TransferRequirementRepository(store)
    repository.put_all(qualified)
    fulfilled = repository.mark_fulfilled(
        manager.requirement_id,
        successor_principal_id="person:successor",
    )
    assert fulfilled.status is TransferRequirementStatus.FULFILLED
    assert (
        repository.mark_fulfilled(
            manager.requirement_id,
            successor_principal_id="person:successor",
        )
        == fulfilled
    )
    with pytest.raises(TransferError, match="does not match"):
        repository.mark_fulfilled(
            manager.requirement_id,
            successor_principal_id="person:outsider",
        )

    _, authority, policy, case, *_ = _setup(successor="person:outsider")
    wrong_scope = derive_transfer_requirements(
        case, policy, authority, governance_basis_id=uuid4()
    )
    manager = next(item for item in wrong_scope if item.role == "manager")
    assert manager.status is TransferRequirementStatus.SUCCESSOR_UNQUALIFIED
    assert "organization scope" in manager.qualification_reason

    _, authority, policy, case, *_ = _setup(successor="person:departing")
    same_subject = derive_transfer_requirements(
        case, policy, authority, governance_basis_id=uuid4()
    )
    manager = next(item for item in same_subject if item.role == "manager")
    assert manager.status is TransferRequirementStatus.SUCCESSOR_UNQUALIFIED


def test_unclassified_current_role_fails_closed_and_dispatch_supports_offboarding() -> None:
    _, authority, policy, case, *_ = _setup(successor="person:successor")
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:departing",
            role="unclassified-role",
            organization_scope="org:finance",
            valid_from=_NOW,
        )
    )
    with pytest.raises(TransferError, match="does not classify"):
        derive_transfer_requirements(case, policy, authority, governance_basis_id=uuid4())

    clean = _setup(successor="person:successor")
    _, authority, policy, case, *_ = clean
    evaluation = policy.evaluate(OffboardingFacts.model_validate(case.fact_snapshot.facts))
    obligations = derive_administrative_obligations(
        case,
        evaluation,
        governance_basis_id=uuid4(),
        offboarding_policy=policy,
        authority_repository=authority,
    )
    assert obligations.obligations
