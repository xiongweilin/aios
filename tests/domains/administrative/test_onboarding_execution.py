from datetime import UTC, datetime

from administrative_orchestrator.domain import (
    AdministrativeRequest,
    CaseStatus,
    Decision,
    DecisionDisposition,
    FactSnapshot,
    PolicyRef,
)
from administrative_orchestrator.effect_provider import (
    ProviderExecutionResult,
    ProviderExecutionStatus,
    RealityObservation,
)
from administrative_orchestrator.execution_repository import ExecutionRepository
from administrative_orchestrator.onboarding_execution import OnboardingExecutionEngine
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy
from administrative_orchestrator.service import (
    apply_policy_evaluation,
    create_case,
    record_decision,
    start_policy_evaluation,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork

FIXED_TIME = datetime(2026, 9, 8, 8, 0, tzinfo=UTC)


class FakeProvider:
    def __init__(self, *, ambiguous_response: bool = False) -> None:
        self.ambiguous_response = ambiguous_response
        self.execute_calls = 0
        self.observations: dict[str, RealityObservation] = {}

    def execute(self, effect, payload):
        self.execute_calls += 1
        observation = RealityObservation(
            found=True,
            target_system=effect.target_system,
            operation=effect.operation,
            subject_ref=effect.subject_ref,
            provider_ref=f"fake:{effect.effect_id}",
            state={"payload": payload, "active": True},
            digest=f"digest:{effect.effect_id}",
            observed_at=FIXED_TIME,
        )
        self.observations[str(effect.effect_id)] = observation
        if self.ambiguous_response:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.OUTCOME_UNKNOWN,
                error="response was lost after the provider committed",
            )
        return ProviderExecutionResult(
            status=ProviderExecutionStatus.SUCCEEDED,
            provider_ref=observation.provider_ref,
        )

    def observe(self, effect):
        return self.observations.get(
            str(effect.effect_id),
            RealityObservation(
                found=False,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                observed_at=FIXED_TIME,
            ),
        )


def _policy_ref() -> PolicyRef:
    return PolicyRef(
        policy_id="employee-onboarding",
        version="v0.1",
        owner="test",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _authorized_case(store: SqlStore):
    uow = AdministrativeUnitOfWork(store)
    facts = OnboardingFacts(
        employee_ref="employee:new",
        department_ref="department:engineering",
        manager_principal_id="person:manager",
        start_date="2026-09-15",
        employment_type="full-time",
        requested_systems=("github",),
    )
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:new",
    )
    original = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref="employee:new",
        fact_snapshot=FactSnapshot(
            source="ingress:test",
            owner="administrative-orchestrator",
            observed_at=FIXED_TIME,
            facts=facts.model_dump(mode="json"),
        ),
    )
    store.create_case(request, original)
    ready = start_policy_evaluation(original)
    evaluation = OnboardingPolicy(_policy_ref()).evaluate(facts)
    awaiting = apply_policy_evaluation(ready, evaluation)
    uow.apply_policy_transition(original, awaiting, evaluation)
    decision = Decision(
        case_id=awaiting.case_id,
        case_version=awaiting.version,
        authority_epoch=awaiting.authority_epoch,
        principal_id="person:hr-approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="approved",
        policy_ref=_policy_ref(),
        decided_at=FIXED_TIME,
    )
    authorized = record_decision(awaiting, decision)
    uow.apply_decision_transition(awaiting, authorized, decision)
    return authorized


def test_onboarding_completes_only_after_every_effect_is_verified() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authorized = _authorized_case(store)
    provider = FakeProvider()

    completed = OnboardingExecutionEngine(store, provider).run(authorized.case_id)

    assert completed.status == CaseStatus.COMPLETED
    effects = ExecutionRepository(store).list_effects(
        completed.case_id,
        completed.authority_epoch,
    )
    assert len(effects) == 3
    assert provider.execute_calls == 3
    for effect in effects:
        outcome_id = OnboardingExecutionEngine._stable_id(
            "outcome",
            completed,
            str(effect.effect_id),
        )
        assert ExecutionRepository(store).get_outcome(outcome_id) is not None

    replayed = OnboardingExecutionEngine(store, provider).run(completed.case_id)
    assert replayed.status == CaseStatus.COMPLETED
    assert provider.execute_calls == 3


def test_unknown_provider_response_uses_readback_instead_of_blind_retry() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authorized = _authorized_case(store)
    provider = FakeProvider(ambiguous_response=True)

    completed = OnboardingExecutionEngine(store, provider).run(authorized.case_id)

    assert completed.status == CaseStatus.COMPLETED
    assert provider.execute_calls == 3
    audit_types = [event["event_type"] for event in store.list_audit_events(completed.case_id)]
    assert "case.reconciliation_started" in audit_types
    assert "case.reconciliation_resolved" in audit_types
