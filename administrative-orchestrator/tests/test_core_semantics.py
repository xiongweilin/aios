from datetime import UTC, datetime

import pytest

from administrative_orchestrator.domain import (
    AdministrativeRequest,
    AuthorityClass,
    CaseStatus,
    Decision,
    DecisionDisposition,
    EffectReversibility,
    EvidenceRef,
    FactSnapshot,
    PolicyRef,
    ReopenReason,
)
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy, PolicyDisposition
from administrative_orchestrator.service import (
    TransitionError,
    add_evidence,
    apply_policy_evaluation,
    begin_execution,
    begin_verification,
    create_case,
    explicit_reopen,
    mint_execution_authorization,
    plan_effect,
    record_decision,
    replace_fact_snapshot,
    require_reopen,
    start_policy_evaluation,
    validate_execution_authorization,
)


@pytest.fixture
def policy_ref() -> PolicyRef:
    return PolicyRef(
        policy_id="employee-onboarding",
        version="v0.1",
        owner="test",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _request() -> AdministrativeRequest:
    return AdministrativeRequest(
        requester_principal_id="employee:requester",
        channel="test",
        intent="onboard employee:new",
    )


def _complete_facts() -> OnboardingFacts:
    return OnboardingFacts(
        employee_ref="employee:new",
        department_ref="department:engineering",
        manager_principal_id="person:manager",
        start_date="2026-09-15",
        employment_type="full-time",
        requested_systems=("github", "feishu"),
    )


def _awaiting_decision_case(policy_ref: PolicyRef):
    facts = _complete_facts()
    case = create_case(
        _request(),
        case_kind="employee-onboarding",
        subject_ref="employee:new",
        fact_snapshot=FactSnapshot(
            source="ingress:test",
            owner="administrative-orchestrator",
            facts=facts.model_dump(mode="json"),
        ),
    )
    case = start_policy_evaluation(case)
    evaluation = OnboardingPolicy(policy_ref).evaluate(facts)
    return apply_policy_evaluation(case, evaluation)


def _approve(case, policy_ref: PolicyRef) -> Decision:
    return Decision(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        principal_id="person:hr-approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="current onboarding policy requirements satisfied",
        policy_ref=policy_ref,
    )


def test_missing_facts_do_not_force_reopen(policy_ref: PolicyRef) -> None:
    case = create_case(_request(), case_kind="employee-onboarding", subject_ref="employee:new")
    case = start_policy_evaluation(case)
    evaluation = OnboardingPolicy(policy_ref).evaluate(
        OnboardingFacts(employee_ref="employee:new")
    )

    assert evaluation.disposition == PolicyDisposition.NEED_MORE_FACTS
    updated = apply_policy_evaluation(case, evaluation)
    assert updated.status == CaseStatus.GATHERING_FACTS
    assert updated.reopen_reason is None


def test_complete_onboarding_requires_explicit_decision(policy_ref: PolicyRef) -> None:
    case = _awaiting_decision_case(policy_ref)
    assert case.status == CaseStatus.AWAITING_DECISION
    assert case.policy_ref == policy_ref
    assert case.authority_epoch == 2


def test_approve_then_mint_exact_authorization(policy_ref: PolicyRef) -> None:
    case = _awaiting_decision_case(policy_ref)
    decision = _approve(case, policy_ref)
    case = record_decision(case, decision)

    authorization = mint_execution_authorization(
        case,
        decision,
        issuer_principal_id="service:admin-orchestrator",
        target_system="hris",
        allowed_operations=("employee.create",),
        authority_class=AuthorityClass.EMPLOYMENT,
    )
    effect = plan_effect(
        case,
        authorization,
        operation="employee.create",
        reversibility=EffectReversibility.CORRECTABLE,
    )

    assert case.status == CaseStatus.AUTHORIZED
    assert authorization.subject_ref == case.subject_ref
    assert authorization.authority_epoch == case.authority_epoch
    assert effect.authorization_id == authorization.authorization_id


def test_effect_cannot_exceed_authorization(policy_ref: PolicyRef) -> None:
    case = _awaiting_decision_case(policy_ref)
    decision = _approve(case, policy_ref)
    case = record_decision(case, decision)
    authorization = mint_execution_authorization(
        case,
        decision,
        issuer_principal_id="service:admin-orchestrator",
        target_system="hris",
        allowed_operations=("employee.create",),
        authority_class=AuthorityClass.EMPLOYMENT,
    )

    with pytest.raises(TransitionError, match="outside the authorization scope"):
        plan_effect(
            case,
            authorization,
            operation="employee.terminate",
            reversibility=EffectReversibility.IRREVERSIBLE,
        )


def test_runtime_state_change_does_not_invalidate_authorization(policy_ref: PolicyRef) -> None:
    case = _awaiting_decision_case(policy_ref)
    decision = _approve(case, policy_ref)
    authorized = record_decision(case, decision)
    authorization = mint_execution_authorization(
        authorized,
        decision,
        issuer_principal_id="service:admin-orchestrator",
        target_system="hris",
        allowed_operations=("employee.create",),
        authority_class=AuthorityClass.EMPLOYMENT,
    )

    executing = begin_execution(authorized)
    assert executing.version == authorized.version + 1
    assert executing.authority_epoch == authorized.authority_epoch
    validate_execution_authorization(executing, authorization, operation="employee.create")

    verifying = begin_verification(executing)
    assert verifying.authority_epoch == executing.authority_epoch


def test_authority_relevant_change_invalidates_old_decision_and_authorization(
    policy_ref: PolicyRef,
) -> None:
    case = _awaiting_decision_case(policy_ref)
    decision = _approve(case, policy_ref)
    authorized = record_decision(case, decision)
    authorization = mint_execution_authorization(
        authorized,
        decision,
        issuer_principal_id="service:admin-orchestrator",
        target_system="hris",
        allowed_operations=("employee.create",),
        authority_class=AuthorityClass.EMPLOYMENT,
    )
    changed = add_evidence(
        authorized,
        EvidenceRef(
            source="hris",
            owner="hris",
            observed_at=datetime.now(UTC),
            version="employee-v2",
        ),
    )

    assert changed.authority_epoch == authorized.authority_epoch + 1
    with pytest.raises(TransitionError, match="stale"):
        mint_execution_authorization(
            changed,
            decision,
            issuer_principal_id="service:admin-orchestrator",
            target_system="hris",
            allowed_operations=("employee.create",),
            authority_class=AuthorityClass.EMPLOYMENT,
        )
    with pytest.raises(TransitionError, match="stale"):
        validate_execution_authorization(changed, authorization, operation="employee.create")


def test_replacing_current_facts_invalidates_prior_decision(policy_ref: PolicyRef) -> None:
    case = _awaiting_decision_case(policy_ref)
    decision = _approve(case, policy_ref)
    changed = replace_fact_snapshot(
        case,
        FactSnapshot(
            source="hris",
            owner="hris",
            facts={**_complete_facts().model_dump(mode="json"), "department_ref": "department:finance"},
        ),
    )

    assert changed.version == case.version + 1
    assert changed.authority_epoch == case.authority_epoch + 1
    with pytest.raises(TransitionError, match="current authority epoch"):
        record_decision(changed, decision)


def test_reopen_is_explicit(policy_ref: PolicyRef) -> None:
    case = _awaiting_decision_case(policy_ref)
    previous_epoch = case.authority_epoch
    case = require_reopen(case, ReopenReason.UNKNOWN_RISK_DIMENSION)
    assert case.status == CaseStatus.REOPEN_REQUIRED
    assert case.authority_epoch == previous_epoch + 1

    reopened = explicit_reopen(case)
    assert reopened.status == CaseStatus.GATHERING_FACTS
    assert reopened.reopen_reason is None
    assert reopened.authority_epoch == case.authority_epoch
