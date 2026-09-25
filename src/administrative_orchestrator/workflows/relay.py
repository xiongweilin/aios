from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ..messaging import OutboxEvent
from .protocol import CASE_CHANGED_TOPIC


@dataclass(frozen=True)
class WorkflowWakeAction:
    workflow_id: str
    topic: str
    message: dict[str, Any]
    idempotency_key: str


def plan_outbox_action(event: OutboxEvent) -> WorkflowWakeAction:
    """Map a business outbox event to one deterministic DBOS start+wake action."""
    if event.event_type != "workflow.case_changed":
        raise ValueError(f"no DBOS relay action for event type {event.event_type!r}")
    case_id = str(event.payload.get("case_id") or event.aggregate_id)
    if not case_id:
        raise ValueError("workflow.case_changed requires case_id")
    return WorkflowWakeAction(
        workflow_id=case_id,
        topic=CASE_CHANGED_TOPIC,
        message={
            **event.payload,
            "event_id": str(event.event_id),
        },
        idempotency_key=str(event.event_id),
    )


def execute_outbox_action(action: WorkflowWakeAction) -> None:
    """Ensure the deterministic workflow exists, then durably wake it.

    Replaying this sequence is safe: SetWorkflowID makes start idempotent and
    DBOS.send deduplicates the wake by the outbox event id.
    """
    from dbos import DBOS, SetWorkflowID

    from ..config import get_settings
    from ..persistence import SqlStore
    from .definitions import (
        meeting_commitment_case_workflow,
        offboarding_case_workflow,
        onboarding_case_workflow,
    )

    case_kind = str(action.message.get("case_kind") or "").strip()
    if not case_kind:
        settings = get_settings()
        case = SqlStore(settings.worker_database_url or settings.database_url).get_case(
            UUID(action.workflow_id)
        )
        case_kind = case.case_kind if case is not None else ""
    workflows = {
        "employee-onboarding": onboarding_case_workflow,
        "employee-offboarding": offboarding_case_workflow,
        "procurement-request": onboarding_case_workflow,
        "invoice-ap-preparation": onboarding_case_workflow,
        "expense-reimbursement": onboarding_case_workflow,
        "meeting-commitment": meeting_commitment_case_workflow,
    }
    workflow = workflows.get(case_kind)
    if workflow is None:
        raise ValueError(f"no DBOS workflow for case kind {case_kind!r}")

    with SetWorkflowID(action.workflow_id):
        DBOS.start_workflow(workflow, case_id=action.workflow_id)
    DBOS.send(
        destination_id=action.workflow_id,
        topic=action.topic,
        message=action.message,
        idempotency_key=action.idempotency_key,
    )


def dispatch_outbox_event(event: OutboxEvent) -> None:
    """Dispatch a provider-neutral business workflow wake from the outbox."""
    execute_outbox_action(plan_outbox_action(event))


__all__ = [
    "WorkflowWakeAction",
    "dispatch_outbox_event",
    "execute_outbox_action",
    "plan_outbox_action",
]
