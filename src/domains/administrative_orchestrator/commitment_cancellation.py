from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from .commitment_common import CommitmentIntakeError
from .commitment_models import CommitmentRecord, CommitmentState, CommunicationDeliveryState
from .domain import CaseStatus, utcnow


class CommitmentCancellationCoordinator:
    """Own commitment cancellation and stale communication closure."""

    def __init__(self, service: Any) -> None:
        self.service = service

    def cancel_commitment(
        self,
        case_id: UUID,
        *,
        reviewer_principal_id: str,
        basis: str,
    ) -> CommitmentRecord:
        svc = self.service
        svc._require_reviewer(reviewer_principal_id)
        basis = basis.strip()
        if not basis:
            raise CommitmentIntakeError("commitment cancellation requires a basis")
        commitment = svc.repository.get_commitment(case_id)
        case = svc.store.get_case(case_id)
        if commitment is None or case is None:
            raise CommitmentIntakeError("commitment case not found")
        if commitment.authority_epoch != case.authority_epoch:
            raise CommitmentIntakeError(
                "commitment cancellation requires revalidation after an authority epoch change"
            )
        if commitment.state is CommitmentState.CANCELLED:
            return commitment
        if commitment.state is CommitmentState.FULFILLED or case.status in {
            CaseStatus.COMPLETED,
            CaseStatus.CANCELLED,
        }:
            raise CommitmentIntakeError("fulfilled or terminal commitment cannot be cancelled")

        now = utcnow()
        cancelled_case = case.model_copy(
            update={
                "status": CaseStatus.CANCELLED,
                "version": case.version + 1,
                "authority_epoch": case.authority_epoch + 1,
                "updated_at": now,
            }
        )
        svc.store.update_case(
            cancelled_case,
            expected_previous_version=case.version,
            event_type="commitment.cancelled",
            payload={
                "reviewer_principal_id": reviewer_principal_id,
                "basis_digest": hashlib.sha256(basis.encode("utf-8")).hexdigest(),
                "responsibility_reassessment_required": commitment.responsibility_ref is not None,
            },
        )
        cancelled = svc.repository.update_commitment(
            commitment.model_copy(
                update={
                    "state": CommitmentState.CANCELLED,
                    "authority_epoch": cancelled_case.authority_epoch,
                    "version": commitment.version,
                    "updated_at": now,
                }
            )
        )
        for communication in svc.repository.list_communications(case_id):
            if communication.delivery_state in {
                CommunicationDeliveryState.PREPARED,
                CommunicationDeliveryState.RETRYING,
            }:
                svc.repository.update_communication(
                    communication.model_copy(
                        update={
                            "delivery_state": CommunicationDeliveryState.PERMANENT_FAILED,
                            "last_error_code": "COMMITMENT_CANCELLED",
                            "updated_at": now,
                        }
                    )
                )
        return cancelled


__all__ = ["CommitmentCancellationCoordinator"]
