from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from .commitment_common import M9_NAMESPACE, CommitmentIntakeError
from .commitment_models import CommitmentFulfillmentAttestation, CommitmentRecord, CommitmentState
from .domain import CaseStatus, utcnow


class CommitmentLifecycleCoordinator:
    """Own fulfillment transitions outside candidate admission."""

    def __init__(self, service: Any) -> None:
        self.service = service

    def attest_fulfillment(
        self,
        case_id: UUID,
        *,
        principal_id: str,
        basis: dict[str, Any],
        at: datetime | None = None,
    ) -> CommitmentRecord:
        svc = self.service
        at = at or utcnow()
        commitment = svc.repository.get_commitment(case_id)
        case = svc.store.get_case(case_id)
        if commitment is None or case is None:
            raise CommitmentIntakeError("commitment case not found")
        if commitment.authority_epoch != case.authority_epoch:
            raise CommitmentIntakeError(
                "fulfillment requires commitment revalidation after an authority epoch change"
            )
        if principal_id != commitment.committer_principal_id:
            raise PermissionError("only the qualified committer may attest fulfillment")
        if not svc.authority.get_principal(principal_id):
            raise CommitmentIntakeError("attesting principal is inactive or unknown")
        if not basis:
            raise CommitmentIntakeError("fulfillment attestation requires a basis")
        if commitment.state is CommitmentState.FULFILLED:
            return commitment
        attestation = CommitmentFulfillmentAttestation(
            attestation_id=uuid5(M9_NAMESPACE, f"attestation:{case_id}:{commitment.version}"),
            case_id=case_id,
            authority_epoch=commitment.authority_epoch,
            commitment_version=commitment.version,
            principal_id=principal_id,
            basis=basis,
        )
        svc.repository.put_attestation(attestation)
        updated = commitment.model_copy(
            update={
                "state": CommitmentState.FULFILLED,
                "was_overdue": commitment.was_overdue or at > commitment.due_at,
                "updated_at": at,
            }
        )
        updated = svc.repository.update_commitment(updated)
        if case.status not in {CaseStatus.COMPLETED, CaseStatus.CANCELLED}:
            completed = case.model_copy(
                update={
                    "status": CaseStatus.COMPLETED,
                    "version": case.version + 1,
                    "updated_at": at,
                }
            )
            svc.store.update_case(
                completed,
                expected_previous_version=case.version,
                event_type="commitment.fulfilled",
                payload={"attestation_id": str(attestation.attestation_id)},
            )
        return updated


__all__ = ["CommitmentLifecycleCoordinator"]
