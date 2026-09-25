from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from administrative_orchestrator.completion import assess_onboarding_completion
from administrative_orchestrator.domain import (
    AdministrativeRequest,
    AuthorityClass,
    ConfirmedOutcome,
    EffectRecord,
    EffectReversibility,
    EffectStatus,
    FactSnapshot,
    PolicyRef,
)
from administrative_orchestrator.effect_provider import RealityObservation
from administrative_orchestrator.fact_history import list_fact_snapshots
from administrative_orchestrator.fact_transitions import replace_facts_for_reevaluation
from administrative_orchestrator.ingress import DuplicateIngressEvent, get_ingress_receipt
from administrative_orchestrator.messaging import (
    claim_outbox,
    emit_outbox,
    list_failed_outbox,
    mark_retry,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy
from administrative_orchestrator.service import (
    apply_policy_evaluation,
    create_case,
    start_policy_evaluation,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_onboarding_observation,
)


def _policy_ref() -> PolicyRef:
    return PolicyRef(
        policy_id="employee-onboarding",
        version="v0.1",
        owner="test",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _facts(*, department: str = "department:engineering") -> OnboardingFacts:
    return OnboardingFacts(
        employee_ref="employee:new",
        department_ref=department,
        manager_principal_id="person:manager",
        start_date="2026-09-15",
        employment_type="full-time",
    )


def test_ingress_receipt_prevents_duplicate_case_and_keeps_initial_fact_history() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    uow = AdministrativeUnitOfWork(store)

    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:new",
        source_ref="evt-1",
    )
    case = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref="employee:new",
        fact_snapshot=FactSnapshot(
            source="ingress:test",
            owner="test",
            facts=_facts().model_dump(mode="json"),
        ),
    )
    uow.create_case(request, case, source_event_id="evt-1")

    receipt = get_ingress_receipt(store, "evt-1")
    assert receipt is not None
    assert receipt.case_id == case.case_id
    history = list_fact_snapshots(store, case.case_id)
    assert [item.snapshot_id for item in history] == [case.fact_snapshot.snapshot_id]

    duplicate_request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="duplicate",
    )
    duplicate_case = create_case(
        duplicate_request,
        case_kind="employee-onboarding",
        subject_ref="employee:new",
    )
    with pytest.raises(DuplicateIngressEvent):
        uow.create_case(duplicate_request, duplicate_case, source_event_id="evt-1")


def test_replacing_facts_preserves_immutable_history_and_re_evaluates_policy() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    uow = AdministrativeUnitOfWork(store)
    policy = OnboardingPolicy(_policy_ref())

    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:new",
    )
    initial = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref="employee:new",
        fact_snapshot=FactSnapshot(
            source="ingress:test",
            owner="test",
            facts=_facts().model_dump(mode="json"),
        ),
    )
    uow.create_case(request, initial)
    ready = start_policy_evaluation(initial)
    evaluation = policy.evaluate(_facts())
    awaiting = apply_policy_evaluation(ready, evaluation)
    uow.apply_policy_transition(initial, awaiting, evaluation)

    replacement = FactSnapshot(
        source="hris",
        owner="hris",
        facts=_facts(department="department:finance").model_dump(mode="json"),
    )
    changed = replace_facts_for_reevaluation(awaiting, replacement)
    ready_again = start_policy_evaluation(changed)
    new_evaluation = policy.evaluate(_facts(department="department:finance"))
    updated = apply_policy_evaluation(ready_again, new_evaluation)
    uow.replace_facts_and_apply_policy(awaiting, updated, new_evaluation)

    history = list_fact_snapshots(store, awaiting.case_id)
    assert len(history) == 2
    assert history[0].snapshot_id != history[1].snapshot_id
    assert history[0].facts["department_ref"] == "department:engineering"
    assert history[1].facts["department_ref"] == "department:finance"
    assert updated.authority_epoch > awaiting.authority_epoch


def test_semantic_verification_rejects_business_state_mismatch() -> None:
    authorization_id = uuid4()
    effect = EffectRecord(
        case_id=uuid4(),
        case_version=3,
        authority_epoch=2,
        authorization_id=authorization_id,
        target_system="iam",
        operation="identity.create",
        subject_ref="employee:new",
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=AuthorityClass.PRIVILEGED_ACCESS,
        status=EffectStatus.SUCCEEDED,
    )
    facts = _facts().model_dump(mode="json")
    observation = RealityObservation(
        found=True,
        target_system="iam",
        operation="identity.create",
        subject_ref="employee:new",
        state={"active": False, "payload": facts},
    )

    result = verify_onboarding_observation(effect, observation, facts)
    assert result.disposition == VerificationDisposition.MISMATCH
    assert "active" in result.differences


def test_completion_requires_declared_outcome_identity_not_only_count() -> None:
    effect = EffectRecord(
        case_id=uuid4(),
        case_version=3,
        authority_epoch=2,
        authorization_id=uuid4(),
        target_system="hris",
        operation="employee.create",
        subject_ref="employee:new",
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=AuthorityClass.EMPLOYMENT,
    )
    wrong_outcome = ConfirmedOutcome(
        case_id=effect.case_id,
        case_version=effect.case_version,
        authority_epoch=effect.authority_epoch,
        effect_id=uuid4(),
        realization_assessment_id=uuid4(),
        outcome_kind="iam.identity.create.verified",
        evidence=[
            {
                "source": "test",
                "owner": "test",
                "observed_at": datetime.now(UTC),
            }
        ],
    )

    assessment = assess_onboarding_completion([effect], [wrong_outcome])
    assert assessment.satisfied is False
    assert assessment.missing_effect_ids == (effect.effect_id,)
    assert assessment.missing_outcome_kinds == ("hris.employee.create.verified",)


def test_dead_letter_is_visible_after_attempt_budget_is_exhausted() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    with store.sessions.begin() as db:
        event_id = emit_outbox(
            db,
            event_type="workflow.case_changed",
            aggregate_id="case-1",
            payload={"case_id": "case-1"},
        )

    claimed = claim_outbox(store)
    assert [item.event_id for item in claimed] == [event_id]
    assert mark_retry(store, event_id, "boom", max_attempts=1) is True

    failed = list_failed_outbox(store)
    assert len(failed) == 1
    assert failed[0].event_id == event_id
    assert failed[0].attempts == 1
    assert failed[0].last_error == "boom"
