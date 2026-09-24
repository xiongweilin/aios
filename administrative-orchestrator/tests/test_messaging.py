from datetime import UTC, datetime
from uuid import uuid4

import pytest

from administrative_orchestrator.domain import (
    AdministrativeRequest,
    Decision,
    DecisionDisposition,
    PolicyRef,
)
from administrative_orchestrator.messaging import (
    OUTBOX_DISPATCHED,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OutboxEventNotFailed,
    OutboxEventRow,
    claim_outbox,
    mark_dispatched,
    replay_failed_outbox,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy
from administrative_orchestrator.service import (
    apply_policy_evaluation,
    create_case,
    record_decision,
    start_policy_evaluation,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork


def _policy_ref() -> PolicyRef:
    return PolicyRef(
        policy_id="employee-onboarding",
        version="v0.1",
        owner="test",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _awaiting_case(store: SqlStore, uow: AdministrativeUnitOfWork):
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:new",
    )
    original = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref="employee:new",
    )
    store.create_case(request, original)
    ready = start_policy_evaluation(original)
    evaluation = OnboardingPolicy(_policy_ref()).evaluate(
        OnboardingFacts(
            employee_ref="employee:new",
            department_ref="department:engineering",
            manager_principal_id="person:manager",
            start_date="2026-09-15",
            employment_type="full-time",
        )
    )
    awaiting = apply_policy_evaluation(ready, evaluation)
    uow.apply_policy_transition(original, awaiting, evaluation)
    return awaiting


def test_policy_and_decision_commit_workflow_wake_events() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    uow = AdministrativeUnitOfWork(store)
    awaiting = _awaiting_case(store, uow)

    events = claim_outbox(store)
    assert len(events) == 1
    assert events[0].event_type == "workflow.case_changed"
    assert events[0].aggregate_id == str(awaiting.case_id)
    assert events[0].payload["cause"] == "policy_evaluated"
    assert events[0].payload["case_kind"] == "employee-onboarding"
    mark_dispatched(store, events[0].event_id)

    decision = Decision(
        case_id=awaiting.case_id,
        case_version=awaiting.version,
        authority_epoch=awaiting.authority_epoch,
        principal_id="person:hr-approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="approved",
        policy_ref=_policy_ref(),
    )
    authorized = record_decision(awaiting, decision)
    uow.apply_decision_transition(awaiting, authorized, decision)

    decision_events = claim_outbox(store)
    assert len(decision_events) == 1
    assert decision_events[0].payload["cause"] == "decision_recorded"
    assert decision_events[0].payload["decision_id"] == str(decision.decision_id)

    with store.sessions() as db:
        first = db.get(OutboxEventRow, events[0].event_id)
        assert first is not None
        assert first.status == OUTBOX_DISPATCHED


def test_failed_outbox_replay_starts_one_fresh_bounded_attempt_window() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    event_id = uuid4()
    with store.sessions.begin() as db:
        db.add(
            OutboxEventRow(
                event_id=event_id,
                event_type="intake.feishu.received",
                aggregate_id=str(event_id),
                payload_json={"event_id": str(event_id)},
                status=OUTBOX_FAILED,
                attempts=10,
                last_error="provider sender is not bound",
                created_at=datetime.now(UTC),
            )
        )

    replayed = replay_failed_outbox(store, event_id, reason="identity binding repaired")

    assert replayed.event_id == event_id
    assert replayed.status == OUTBOX_PENDING
    assert replayed.attempts == 0
    claimed = claim_outbox(store)
    assert [item.event_id for item in claimed] == [event_id]
    with pytest.raises(OutboxEventNotFailed):
        replay_failed_outbox(store, event_id, reason="duplicate replay")
