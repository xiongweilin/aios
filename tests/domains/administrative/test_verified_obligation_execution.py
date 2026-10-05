from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from administrative_orchestrator.domain import AdministrativeCase, CaseStatus, EffectStatus
from administrative_orchestrator.effect_provider import (
    ProviderExecutionResult,
    ProviderExecutionStatus,
)
from administrative_orchestrator.execution_transitions import resume_execution
from administrative_orchestrator.service import TransitionError
from administrative_orchestrator.verification import (
    SemanticVerificationResult,
    VerificationDisposition,
)
from administrative_orchestrator.verified_obligation_execution import (
    VerifiedObligationExecutor,
)


class _Repository:
    def __init__(self, effect) -> None:
        self.effect = effect
        self.status_updates: list[tuple[EffectStatus, str | None]] = []

    def get_effect(self, effect_id):
        assert effect_id == self.effect.effect_id
        return self.effect

    def set_effect_status(self, effect_id, *, status, provider_ref=None):
        assert effect_id == self.effect.effect_id
        self.effect.status = status
        if provider_ref is not None:
            self.effect.provider_ref = provider_ref
        self.status_updates.append((status, provider_ref))
        return self.effect


class _Provider:
    def __init__(
        self,
        *,
        result: ProviderExecutionResult | None = None,
        forbid_execute: bool = False,
    ) -> None:
        self.result = result or ProviderExecutionResult(
            status=ProviderExecutionStatus.SUCCEEDED,
            provider_ref="provider:executed",
        )
        self.forbid_execute = forbid_execute
        self.execute_calls = 0
        self.observe_calls = 0

    def observe(self, effect):
        self.observe_calls += 1
        return SimpleNamespace(provider_ref=f"provider:{effect.effect_id}")

    def execute(self, effect, payload):
        del effect, payload
        self.execute_calls += 1
        if self.forbid_execute:
            pytest.fail("historical dispatch must be reconciled, not executed again")
        return self.result


def _effect(status: EffectStatus):
    return SimpleNamespace(
        effect_id=uuid4(),
        status=status,
        provider_ref=None,
    )


def _owner(effect, *, disposition, provider, dispatch_payload=None):
    repository = _Repository(effect)
    owner = SimpleNamespace(
        repository=repository,
        provider=provider,
        _effect_dispatch_order=lambda item: str(item.effect_id),
        _obligation_for_effect=lambda effect_id, obligation_set, links: None,
        _verify_observation=lambda *args, **kwargs: SemanticVerificationResult(
            disposition=disposition,
            reason="test verification",
        ),
        _payload_for_effect=lambda current, effects, payload: (
            payload if dispatch_payload is None else dispatch_payload
        ),
    )
    return owner, repository


def test_dispatch_reconciles_existing_dispatch_without_reexecution() -> None:
    effect = _effect(EffectStatus.DISPATCHED)
    provider = _Provider(forbid_execute=True)
    owner, repository = _owner(
        effect,
        disposition=VerificationDisposition.VERIFIED,
        provider=provider,
    )

    result = VerifiedObligationExecutor(owner).drive_dispatch(
        SimpleNamespace(fact_snapshot=None),
        [effect],
        None,
        (),
    )

    assert result == "succeeded"
    assert provider.observe_calls == 1
    assert provider.execute_calls == 0
    assert effect.status is EffectStatus.SUCCEEDED
    assert repository.status_updates == [
        (EffectStatus.SUCCEEDED, f"provider:{effect.effect_id}")
    ]


def test_dispatch_mismatch_becomes_unknown_without_reexecution() -> None:
    effect = _effect(EffectStatus.DISPATCHED)
    provider = _Provider(forbid_execute=True)
    owner, repository = _owner(
        effect,
        disposition=VerificationDisposition.MISMATCH,
        provider=provider,
    )

    result = VerifiedObligationExecutor(owner).drive_dispatch(
        SimpleNamespace(fact_snapshot=None),
        [effect],
        None,
        (),
    )

    assert result == "outcome_unknown"
    assert provider.execute_calls == 0
    assert effect.status is EffectStatus.OUTCOME_UNKNOWN
    assert repository.status_updates == [
        (EffectStatus.OUTCOME_UNKNOWN, f"provider:{effect.effect_id}")
    ]


@pytest.mark.parametrize(
    "disposition",
    [
        VerificationDisposition.UNAVAILABLE,
        VerificationDisposition.UNKNOWN,
        VerificationDisposition.STALE,
    ],
)
def test_dispatch_unobservable_historical_effect_stays_unknown(disposition) -> None:
    effect = _effect(EffectStatus.DISPATCHED)
    provider = _Provider(forbid_execute=True)
    owner, repository = _owner(
        effect,
        disposition=disposition,
        provider=provider,
    )

    result = VerifiedObligationExecutor(owner).drive_dispatch(
        SimpleNamespace(fact_snapshot=None),
        [effect],
        None,
        (),
    )

    assert result == "outcome_unknown"
    assert provider.execute_calls == 0
    assert repository.status_updates == []


def test_outcome_unknown_absence_is_not_retry_permission() -> None:
    effect = _effect(EffectStatus.OUTCOME_UNKNOWN)
    provider = _Provider(forbid_execute=True)
    owner, repository = _owner(
        effect,
        disposition=VerificationDisposition.ABSENT,
        provider=provider,
    )

    result = VerifiedObligationExecutor(owner).drive_dispatch(
        SimpleNamespace(fact_snapshot=None),
        [effect],
        None,
        (),
    )

    assert result == "outcome_unknown"
    assert provider.observe_calls == 1
    assert provider.execute_calls == 0
    assert effect.status is EffectStatus.OUTCOME_UNKNOWN
    assert repository.status_updates == []


def test_missing_dispatch_dependency_does_not_call_provider() -> None:
    effect = _effect(EffectStatus.PLANNED)
    provider = _Provider(forbid_execute=True)
    owner, repository = _owner(
        effect,
        disposition=VerificationDisposition.UNKNOWN,
        provider=provider,
        dispatch_payload=False,
    )
    owner._payload_for_effect = lambda current, effects, payload: None

    result = VerifiedObligationExecutor(owner).drive_dispatch(
        SimpleNamespace(fact_snapshot=None),
        [effect],
        None,
        (),
    )

    assert result == "outcome_unknown"
    assert provider.execute_calls == 0
    assert repository.status_updates == [(EffectStatus.DISPATCHED, None)]


def test_deferred_provider_result_restores_planned_without_reality_retry() -> None:
    effect = _effect(EffectStatus.PLANNED)
    provider = _Provider(
        result=ProviderExecutionResult(
            status=ProviderExecutionStatus.DEFERRED,
            error="admission held before provider attempt",
        )
    )
    owner, repository = _owner(
        effect,
        disposition=VerificationDisposition.UNKNOWN,
        provider=provider,
    )

    result = VerifiedObligationExecutor(owner).drive_dispatch(
        SimpleNamespace(fact_snapshot=None),
        [effect],
        None,
        (),
    )

    assert result == "deferred"
    assert provider.execute_calls == 1
    assert effect.status is EffectStatus.PLANNED
    assert repository.status_updates == [
        (EffectStatus.DISPATCHED, None),
        (EffectStatus.PLANNED, None),
    ]


def test_definitive_provider_failure_marks_effect_failed() -> None:
    effect = _effect(EffectStatus.PLANNED)
    provider = _Provider(
        result=ProviderExecutionResult(
            status=ProviderExecutionStatus.FAILED,
            provider_ref="provider:failed",
            error="definitive test failure",
        )
    )
    owner, repository = _owner(
        effect,
        disposition=VerificationDisposition.UNKNOWN,
        provider=provider,
    )

    result = VerifiedObligationExecutor(owner).drive_dispatch(
        SimpleNamespace(fact_snapshot=None),
        [effect],
        None,
        (),
    )

    assert result == "failed"
    assert provider.execute_calls == 1
    assert effect.status is EffectStatus.FAILED
    assert repository.status_updates == [
        (EffectStatus.DISPATCHED, None),
        (EffectStatus.FAILED, "provider:failed"),
    ]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (EffectStatus.FAILED, "failed"),
        (EffectStatus.SUCCEEDED, "succeeded"),
    ],
)
def test_persisted_terminal_effect_status_short_circuits_provider(status, expected) -> None:
    effect = _effect(status)
    provider = _Provider(forbid_execute=True)
    owner, repository = _owner(
        effect,
        disposition=VerificationDisposition.UNKNOWN,
        provider=provider,
    )

    result = VerifiedObligationExecutor(owner).drive_dispatch(
        SimpleNamespace(fact_snapshot=None),
        [effect],
        None,
        (),
    )

    assert result == expected
    assert provider.observe_calls == 0
    assert provider.execute_calls == 0
    assert repository.status_updates == []


class _RunRepository:
    def __init__(self, effects) -> None:
        self.effects = {item.effect_id: item for item in effects}

    def list_effects(self, case_id, authority_epoch):
        del case_id, authority_epoch
        return list(self.effects.values())

    def get_effect(self, effect_id):
        return self.effects.get(effect_id)


class _RunOwner:
    def __init__(self, case, effects, *, verify_result="verified") -> None:
        self.case = case
        self.repository = _RunRepository(effects)
        self.obligations = SimpleNamespace(
            get_current=lambda case_id, authority_epoch: None,
            list_links=lambda case_id, authority_epoch: (),
        )
        self.verify_result = verify_result
        self.verify_calls = []
        self.transitions = []

    def _require_case(self, case_id):
        assert case_id == self.case.case_id
        return self.case

    def _validate_current_governance(self, case):
        del case
        return None

    def _verify_all(self, case, effects, obligation_set, links):
        del case, obligation_set, links
        self.verify_calls.append(tuple(item.effect_id for item in effects))
        for item in effects:
            if item.status is EffectStatus.OUTCOME_UNKNOWN:
                item.status = EffectStatus.SUCCEEDED
        return self.verify_result

    def _persist_case_transition(self, before, after, event_type, payload=None):
        assert before.case_id == after.case_id == self.case.case_id
        self.case = after
        self.transitions.append((event_type, payload))


def _reconciling_case() -> AdministrativeCase:
    return AdministrativeCase(
        case_kind="employee-offboarding",
        requester_principal_id="person:requester",
        subject_ref="employee:test",
        status=CaseStatus.RECONCILING,
        version=7,
        authority_epoch=3,
    )


def test_resume_execution_requires_reconciling_state() -> None:
    case = _reconciling_case()
    resumed = resume_execution(case)
    assert resumed.status is CaseStatus.EXECUTING
    assert resumed.version == case.version + 1

    with pytest.raises(TransitionError, match="execution resume requires reconciling state"):
        resume_execution(resumed)


def test_reconciliation_with_only_planned_effects_resumes_execution() -> None:
    case = _reconciling_case()
    planned = _effect(EffectStatus.PLANNED)
    owner = _RunOwner(case, [planned])

    result = VerifiedObligationExecutor(owner).run(case.case_id)

    assert result.status is CaseStatus.EXECUTING
    assert result.version == case.version + 1
    assert owner.verify_calls == []
    assert owner.transitions == [
        ("case.reconciliation_resolved_for_execution", None)
    ]


def test_reconciliation_verifies_attempted_effect_then_resumes_planned_work() -> None:
    case = _reconciling_case()
    ambiguous = _effect(EffectStatus.OUTCOME_UNKNOWN)
    planned = _effect(EffectStatus.PLANNED)
    owner = _RunOwner(case, [ambiguous, planned])

    result = VerifiedObligationExecutor(owner).run(case.case_id)

    assert result.status is CaseStatus.EXECUTING
    assert ambiguous.status is EffectStatus.SUCCEEDED
    assert planned.status is EffectStatus.PLANNED
    assert owner.verify_calls == [(ambiguous.effect_id,)]
    assert owner.transitions == [
        ("case.reconciliation_resolved_for_execution", None)
    ]
