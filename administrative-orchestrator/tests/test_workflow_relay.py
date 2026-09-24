from datetime import UTC, datetime, timedelta
from uuid import uuid4

from administrative_orchestrator.messaging import OutboxEvent
from administrative_orchestrator.workflows.protocol import CASE_CHANGED_TOPIC
from administrative_orchestrator.workflows.relay import (
    WorkflowWakeAction,
    execute_outbox_action,
    plan_outbox_action,
)


def test_case_changed_maps_to_deterministic_start_and_wake() -> None:
    event_id = uuid4()
    case_id = uuid4()
    event = OutboxEvent(
        event_id=event_id,
        event_type="workflow.case_changed",
        aggregate_id=str(case_id),
        payload={
            "case_id": str(case_id),
            "case_kind": "employee-onboarding",
            "case_version": 4,
            "authority_epoch": 2,
            "status": "authorized",
            "cause": "decision_recorded",
        },
        attempts=0,
    )

    action = plan_outbox_action(event)

    assert action.workflow_id == str(case_id)
    assert action.topic == CASE_CHANGED_TOPIC
    assert action.idempotency_key == str(event_id)
    assert action.message["event_id"] == str(event_id)
    assert action.message["authority_epoch"] == 2
    assert action.message["case_kind"] == "employee-onboarding"


def test_case_kind_selects_offboarding_workflow(monkeypatch) -> None:
    from dbos import DBOS

    from administrative_orchestrator.workflows.definitions import (
        offboarding_case_workflow,
    )

    started: list[object] = []
    sent: list[dict] = []
    monkeypatch.setattr(
        DBOS,
        "start_workflow",
        lambda workflow, **kwargs: started.append((workflow, kwargs)),
    )
    monkeypatch.setattr(DBOS, "send", lambda **kwargs: sent.append(kwargs))
    action = WorkflowWakeAction(
        workflow_id=str(uuid4()),
        topic=CASE_CHANGED_TOPIC,
        message={"case_kind": "employee-offboarding"},
        idempotency_key="event:1",
    )

    execute_outbox_action(action)

    assert started == [(offboarding_case_workflow, {"case_id": action.workflow_id})]
    assert sent[0]["destination_id"] == action.workflow_id


def test_offboarding_wait_timeout_targets_effective_time(monkeypatch) -> None:
    from administrative_orchestrator.workflows import definitions

    now = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)
    monkeypatch.setattr(definitions, "utcnow", lambda: now)
    timeout = definitions._offboarding_wake_timeout(
        {
            "status": "waiting",
            "next_qualified_action_at": (now + timedelta(minutes=7)).isoformat(),
        }
    )
    assert timeout == 420


def test_unknown_outbox_event_fails_closed() -> None:
    event = OutboxEvent(
        event_id=uuid4(),
        event_type="unknown.event",
        aggregate_id="x",
        payload={},
        attempts=0,
    )

    try:
        plan_outbox_action(event)
    except ValueError as exc:
        assert "no DBOS relay action" in str(exc)
    else:
        raise AssertionError("unknown outbox event must fail closed")


