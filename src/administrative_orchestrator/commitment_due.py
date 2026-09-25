from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from .commitment_common import CommitmentIntakeError
from .commitment_models import CommitmentState, CommunicationDeliveryState
from .domain import utcnow


class CommitmentDueCoordinator:
    """Own due-state advancement and bounded communication dispatch."""

    def __init__(self, service: Any) -> None:
        self.service = service

    def drive(self, case_id: UUID, *, at: datetime | None = None) -> dict[str, Any]:
        svc = self.service
        at = at or utcnow()
        commitment = svc.repository.get_commitment(case_id)
        case = svc.store.get_case(case_id)
        if commitment is None or case is None:
            raise CommitmentIntakeError("commitment case not found")
        if commitment.authority_epoch != case.authority_epoch:
            raise CommitmentIntakeError(
                "commitment drive requires revalidation after an authority epoch change"
            )
        if commitment.state is CommitmentState.ACTIVE and at >= commitment.due_at:
            overdue = commitment.model_copy(
                update={"state": CommitmentState.OVERDUE, "was_overdue": True, "updated_at": at}
            )
            commitment = svc.repository.update_commitment(overdue)

        if commitment.state is CommitmentState.OVERDUE and not any(
            (draft := svc.repository.get_draft(item.draft_id)) is not None
            and draft.draft_kind == "reminder"
            for item in svc.repository.list_communications(case_id)
        ):
            svc.ensure_communication(commitment, draft_kind="reminder")

        if not svc.settings.external_effects_enabled:
            return {
                "case_id": str(case_id),
                "commitment_state": commitment.state.value,
                "due_at": commitment.due_at.isoformat(),
                "dispatched_communication_event_ids": [],
                "reason": "external_effects_disabled",
            }

        dispatched: list[str] = []
        for communication in svc.repository.list_communications(
            case_id, authority_epoch=commitment.authority_epoch
        ):
            if communication.delivery_state is CommunicationDeliveryState.PREPARED:
                svc.dispatch_communication(communication.communication_event_id)
                dispatched.append(str(communication.communication_event_id))
        return {
            "case_id": str(case_id),
            "commitment_state": commitment.state.value,
            "due_at": commitment.due_at.isoformat(),
            "dispatched_communication_event_ids": dispatched,
        }


__all__ = ["CommitmentDueCoordinator"]
