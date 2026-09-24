from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from administrative_orchestrator.access_policy import (
    AdministrativeAccessPolicy,
    AdministrativePermission,
)
from administrative_orchestrator.authority import (
    AuthorityRepository,
    RoleAssignmentRow,
    assess_approval_satisfaction,
)
from administrative_orchestrator.completion import assess_onboarding_completion
from administrative_orchestrator.config import Settings
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AdministrativeRequest,
    AuthorityClass,
    CaseStatus,
    ConfirmedOutcome,
    Decision,
    DecisionDisposition,
    EffectRecord,
    EffectReversibility,
    EvidenceRef,
    FactAuthority,
    FactSnapshot,
    Principal,
    RoleAssignment,
)
from administrative_orchestrator.effect_provider import (
    HttpEffectProvider,
    ObservationAvailability,
    ObservationPresence,
)
from administrative_orchestrator.governance import GovernanceRepository
from administrative_orchestrator.obligations import (
    EffectObligationLink,
    derive_onboarding_obligations,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy
from administrative_orchestrator.policy_plane import (
    PolicyPlaneError,
    PolicyRepository,
    PolicyVersionRecord,
    PolicyVersionStatus,
    default_onboarding_policy_version,
)
from administrative_orchestrator.service import (
    apply_policy_evaluation,
    create_case,
    record_decision,
    start_policy_evaluation,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_onboarding_observation,
)


def _store() -> SqlStore:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    return store


def _facts() -> OnboardingFacts:
    return OnboardingFacts(
        employee_ref="employee:new",
        department_ref="department:engineering",
        manager_principal_id="person:manager",
        start_date="2026-09-15",
        employment_type="full-time",
    )


def _case(*, requester: str = "person:requester") -> AdministrativeCase:
    return AdministrativeCase(
        case_kind="employee-onboarding",
        requester_principal_id=requester,
        subject_ref="employee:new",
        fact_snapshot=FactSnapshot(
            source="ingress:test",
            owner=requester,
            authority=FactAuthority.CLAIM,
            facts=_facts().model_dump(mode="json"),
        ),
    )


def test_access_policy_separates_requester_business_and_platform_permissions() -> None:
    store = _store()
    authority = AuthorityRepository(store)
    for principal_id in (
        "person:requester",
        "person:hr",
        "person:auditor",
        "person:platform",
        "person:other",
    ):
        authority.put_principal(Principal(principal_id=principal_id, display_name=principal_id))
    baseline = datetime(2026, 1, 1, tzinfo=UTC)
    for principal_id, role in (
        ("person:hr", "hr_approver"),
        ("person:auditor", "administrative_auditor"),
        ("person:platform", "platform_operator"),
    ):
        authority.put_role_assignment(
            RoleAssignment(
                principal_id=principal_id,
                role=role,
                organization_scope="*",
                valid_from=baseline,
            )
        )

    case = _case()
    access = AdministrativeAccessPolicy(authority)
    assert access.allows("person:requester", AdministrativePermission.CASE_READ, case=case)
    assert not access.allows("person:other", AdministrativePermission.CASE_READ, case=case)
    assert access.allows("person:hr", AdministrativePermission.CASE_READ, case=case)
    assert not access.allows("person:hr", AdministrativePermission.AUDIT_READ, case=case)
    assert access.allows("person:auditor", AdministrativePermission.AUDIT_READ, case=case)
    assert not access.allows(
        "person:auditor",
        AdministrativePermission.DEAD_LETTER_READ,
        organization_scope="*",
    )
    assert access.allows(
        "person:platform",
        AdministrativePermission.DEAD_LETTER_READ,
        organization_scope="*",
    )


def test_governance_basis_detects_role_revocation_without_case_change() -> None:
    store = _store()
    policies = PolicyRepository(store)
    policies.put_version(default_onboarding_policy_version())
    authority = AuthorityRepository(store)
    authority.put_principal(Principal(principal_id="person:requester", display_name="Requester"))
    authority.put_principal(Principal(principal_id="person:hr", display_name="HR"))
    assignment = RoleAssignment(
        principal_id="person:hr",
        role="hr_approver",
        organization_scope="department:engineering",
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    authority.put_role_assignment(assignment)

    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:new",
    )
    original = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref="employee:new",
        fact_snapshot=_case().fact_snapshot,
    )
    uow = AdministrativeUnitOfWork(store)
    uow.create_case(request, original)
    ready = start_policy_evaluation(original)
    policy_record = policies.resolve_current("employee-onboarding")
    evaluation = OnboardingPolicy(policy_record.policy_ref).evaluate(_facts())
    awaiting = apply_policy_evaluation(ready, evaluation)
    uow.apply_policy_transition(original, awaiting, evaluation)

    current = store.get_case(awaiting.case_id)
    assert current is not None
    decision = Decision(
        case_id=current.case_id,
        case_version=current.version,
        authority_epoch=current.authority_epoch,
        principal_id="person:hr",
        decision_role="hr_approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="approved",
        policy_ref=current.policy_ref,
    )
    approval = assess_approval_satisfaction(
        authority,
        case_id=current.case_id,
        authority_epoch=current.authority_epoch,
        policy_ref=current.policy_ref,
        evaluation=evaluation,
        decisions=[decision],
        organization_scope="department:engineering",
    )
    assert approval.satisfaction is not None
    authorized = record_decision(current, decision, approval_complete=True)
    uow.apply_decision_transition(
        current,
        authorized,
        decision,
        organization_scope="department:engineering",
        approval_satisfaction=approval.satisfaction,
    )

    basis = GovernanceRepository(store).get_for_approval(approval.satisfaction.satisfaction_id)
    assert basis is not None
    assert GovernanceRepository(store).revalidate(basis, authorized).valid

    with store.sessions.begin() as db:
        row = db.get(RoleAssignmentRow, assignment.assignment_id)
        assert row is not None
        row.valid_until = datetime.now(UTC) - timedelta(seconds=1)

    unchanged_case = store.get_case(authorized.case_id)
    assert unchanged_case is not None
    validation = GovernanceRepository(store).revalidate(basis, unchanged_case)
    assert not validation.valid
    assert any("no longer qualifies" in reason for reason in validation.reasons)


def test_completion_fails_when_planner_omits_required_obligation() -> None:
    policy_record = default_onboarding_policy_version()
    facts = _facts()
    evaluation = OnboardingPolicy(policy_record.policy_ref).evaluate(facts)
    case = AdministrativeCase(
        case_kind="employee-onboarding",
        requester_principal_id="person:requester",
        subject_ref=facts.employee_ref,
        status=CaseStatus.AUTHORIZED,
        authority_epoch=2,
        policy_ref=policy_record.policy_ref,
        fact_snapshot=FactSnapshot(
            source="test",
            owner="test",
            authority=FactAuthority.ATTESTED,
            facts=facts.model_dump(mode="json"),
        ),
    )
    obligation_set = derive_onboarding_obligations(
        case,
        evaluation,
        governance_basis_id=uuid4(),
    )
    assert len(obligation_set.obligations) == 2
    first = obligation_set.obligations[0]
    effect = EffectRecord(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        authorization_id=uuid4(),
        target_system=first.target_system,
        operation=first.required_operation,
        subject_ref=first.subject_ref,
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=first.authority_class,
    )
    evidence = EvidenceRef(
        source="test",
        owner="test",
        observed_at=datetime.now(UTC),
    )
    outcome = ConfirmedOutcome(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        effect_id=effect.effect_id,
        realization_assessment_id=uuid4(),
        outcome_kind=f"{first.target_system}.{first.required_operation}.verified",
        evidence=[evidence],
    )
    assessment = assess_onboarding_completion(
        obligation_set,
        [effect],
        [outcome],
        links=[
            EffectObligationLink(
                effect_id=effect.effect_id,
                obligation_id=first.obligation_id,
                governance_basis_id=first.governance_basis_id,
            )
        ],
    )
    assert not assessment.satisfied
    assert len(assessment.uncovered_obligation_ids) == 1


def test_reality_404_is_absent_but_timeout_is_unavailable(monkeypatch) -> None:
    effect = EffectRecord(
        case_id=uuid4(),
        case_version=1,
        authority_epoch=1,
        authorization_id=uuid4(),
        target_system="hris",
        operation="employee.create",
        subject_ref="employee:new",
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=AuthorityClass.EMPLOYMENT,
    )
    provider = HttpEffectProvider("http://reality.invalid")

    def not_found(*args, **kwargs):
        request = httpx.Request("GET", "http://reality.invalid/v1/effects/x")
        return httpx.Response(404, request=request)

    monkeypatch.setattr(httpx, "get", not_found)
    absent = provider.observe(effect)
    assert absent.availability == ObservationAvailability.AVAILABLE
    assert absent.presence == ObservationPresence.ABSENT
    assert (
        verify_onboarding_observation(effect, absent, {}).disposition
        == VerificationDisposition.ABSENT
    )

    def timed_out(*args, **kwargs):
        request = httpx.Request("GET", "http://reality.invalid/v1/effects/x")
        raise httpx.ReadTimeout("timeout", request=request)

    monkeypatch.setattr(httpx, "get", timed_out)
    unavailable = provider.observe(effect)
    assert unavailable.availability == ObservationAvailability.UNAVAILABLE
    assert unavailable.presence == ObservationPresence.UNKNOWN
    assert (
        verify_onboarding_observation(effect, unavailable, {}).disposition
        == VerificationDisposition.UNAVAILABLE
    )


def test_policy_activation_rejects_overlap_and_records_lifecycle() -> None:
    store = _store()
    policies = PolicyRepository(store)
    policies.put_version(default_onboarding_policy_version())
    v2 = PolicyVersionRecord(
        policy_id="employee-onboarding",
        version="v2",
        owner="administrative-orchestrator",
        status=PolicyVersionStatus.DRAFT,
        effective_from=datetime(2026, 6, 1, tzinfo=UTC),
        definition=OnboardingPolicy.default_definition(),
    )
    policies.create_draft(v2)
    with pytest.raises(PolicyPlaneError, match="overlap"):
        policies.activate(
            "employee-onboarding",
            "v2",
            actor_principal_id="person:policy-owner",
            reason="replace baseline",
        )

    policies.retire(
        "employee-onboarding",
        "v1",
        actor_principal_id="person:policy-owner",
        reason="superseded",
    )
    activated = policies.activate(
        "employee-onboarding",
        "v2",
        actor_principal_id="person:policy-owner",
        reason="approved replacement",
    )
    assert activated.status == PolicyVersionStatus.ACTIVE
    events = policies.list_lifecycle_events("employee-onboarding")
    assert [(item.action, item.actor_principal_id) for item in events] == [
        ("retire", "person:policy-owner"),
        ("activate", "person:policy-owner"),
    ]


def test_governed_profile_cannot_disable_authority_enforcement() -> None:
    settings = Settings(
        runtime_profile="governed",
        authority_enforcement_enabled=False,
    )
    assert settings.authority_enforcement_enabled is True
