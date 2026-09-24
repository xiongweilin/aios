from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ..messaging import OutboxEvent
from ..providers.feishu import FEISHU_INTAKE_EVENT_TYPE
from .protocol import CASE_CHANGED_TOPIC


@dataclass(frozen=True)
class WorkflowWakeAction:
    workflow_id: str
    topic: str
    message: dict[str, Any]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class FeishuInboxAction:
    """Durable handoff for the provider pipeline, not a DBOS Work."""

    receipt_id: str
    payload: dict[str, Any]
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


def plan_feishu_inbox_action(event: OutboxEvent) -> FeishuInboxAction:
    """Map a Feishu intake outbox event to an idempotent async job."""
    if event.event_type != FEISHU_INTAKE_EVENT_TYPE:
        raise ValueError(f"no Feishu intake action for event type {event.event_type!r}")
    required = ("event_id", "tenant_ref", "message_id", "sender_external_subject")
    if any(not str(event.payload.get(field) or "").strip() for field in required):
        raise ValueError("Feishu intake event is missing provider identity metadata")
    return FeishuInboxAction(
        receipt_id=str(event.event_id),
        payload=dict(event.payload),
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


def dispatch_outbox_event(
    event: OutboxEvent,
    *,
    feishu_processor: Callable[[dict[str, Any]], object] | None = None,
) -> None:
    """Dispatch business workflow events or an explicitly supplied intake worker.

    The default worker does not guess provider credentials or model runtime
    configuration. A deployment must inject the configured Feishu pipeline;
    otherwise the event fails closed and remains retryable in the outbox.
    """
    if event.event_type == FEISHU_INTAKE_EVENT_TYPE:
        if feishu_processor is None:
            raise ValueError("Feishu intake processor is not configured")
        action = plan_feishu_inbox_action(event)
        feishu_processor(action.payload)
        return
    execute_outbox_action(plan_outbox_action(event))


__all__ = [
    "WorkflowWakeAction",
    "FeishuInboxAction",
    "dispatch_outbox_event",
    "execute_outbox_action",
    "plan_feishu_inbox_action",
    "plan_outbox_action",
]
