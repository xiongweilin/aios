from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from ..access_policy import AdministrativePermission
from ..commitment_models import CandidateCommitmentStatus, SpeakerPrincipalResolution
from ..commitment_repository import CommitmentConflict
from ..commitment_service import CommitmentIntakeError
from .models import (
    CommitmentCancellationBody,
    CommitmentCandidateQueueItem,
    CommitmentConfirmationBody,
    CommitmentDueRevisionBody,
    CommitmentFulfillmentBody,
    CommitmentSpeakerResolutionBody,
)
from .runtime import OperationsRuntime


def build_commitment_router(runtime: OperationsRuntime) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/v1/operations/commitments/candidates",
        response_model=list[CommitmentCandidateQueueItem],
    )
    def commitment_candidate_queue(
        request: Request,
        status_filter: Annotated[
            CandidateCommitmentStatus | None, Query(alias="status")
        ] = CandidateCommitmentStatus.ACTIVE,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    ) -> list[CommitmentCandidateQueueItem]:
        actor = runtime.actor(request)
        runtime.require(actor, AdministrativePermission.OPERATIONS_READ)
        return [
            CommitmentCandidateQueueItem(
                candidate=item,
                resolution=runtime.commitments.get_resolution(item.candidate_commitment_id),
                commitment=runtime.commitments.get_commitment_for_candidate(
                    item.candidate_commitment_id
                ),
            )
            for item in runtime.commitments.list_candidates(
                status=status_filter, limit=limit
            )
        ]

    @router.get(
        "/v1/operations/commitments/candidates/{candidate_id}",
        response_model=CommitmentCandidateQueueItem,
    )
    def commitment_candidate_detail(
        candidate_id: UUID,
        request: Request,
    ) -> CommitmentCandidateQueueItem:
        actor = runtime.actor(request)
        runtime.require(actor, AdministrativePermission.OPERATIONS_READ)
        candidate = runtime.commitments.get_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="commitment candidate not found")
        return CommitmentCandidateQueueItem(
            candidate=candidate,
            resolution=runtime.commitments.get_resolution(candidate_id),
            commitment=runtime.commitments.get_commitment_for_candidate(candidate_id),
        )

    @router.post(
        "/v1/operations/commitments/candidates/{candidate_id}/resolve-speaker",
        response_model=SpeakerPrincipalResolution,
    )
    def resolve_commitment_speaker(
        candidate_id: UUID,
        payload: CommitmentSpeakerResolutionBody,
        request: Request,
    ) -> SpeakerPrincipalResolution:
        actor = runtime.actor(request)
        runtime.require_intake_review(actor)
        try:
            return runtime.commitment_service.resolve_speaker(
                candidate_id,
                reviewer_principal_id=actor.principal_id,
                external_subject=payload.external_subject,
                provider=payload.provider,
                basis=payload.basis,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (CommitmentIntakeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/v1/operations/commitments/candidates/{candidate_id}/confirm")
    def confirm_commitment_candidate(
        candidate_id: UUID,
        payload: CommitmentConfirmationBody,
        request: Request,
    ) -> dict[str, Any]:
        actor = runtime.actor(request)
        runtime.require_intake_review(actor)
        try:
            case, commitment = runtime.commitment_service.confirm_candidate(
                candidate_id,
                reviewer_principal_id=actor.principal_id,
                qualified_due_at=payload.qualified_due_at,
                due_time_basis=payload.due_time_basis,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (CommitmentIntakeError, CommitmentConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "case": case.model_dump(mode="json"),
            "commitment": commitment.model_dump(mode="json"),
            "communication": [
                item.model_dump(mode="json")
                for item in runtime.commitments.list_communications(case.case_id)
            ],
        }

    @router.get("/v1/operations/commitments/{case_id}")
    def commitment_detail(case_id: UUID, request: Request) -> dict[str, Any]:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.OPERATIONS_READ)
        commitment = runtime.commitments.get_commitment(case_id)
        if commitment is None:
            raise HTTPException(status_code=404, detail="commitment not found")
        return {
            "case": case.model_dump(mode="json"),
            "commitment": commitment.model_dump(mode="json"),
            "candidate": (
                candidate.model_dump(mode="json")
                if (
                    candidate := runtime.commitments.get_candidate(
                        commitment.candidate_ref
                    )
                )
                is not None
                else None
            ),
            "speaker_resolution": (
                resolution.model_dump(mode="json")
                if (
                    resolution := runtime.commitments.get_resolution(
                        commitment.candidate_ref
                    )
                )
                is not None
                else None
            ),
            "communications": [
                item.model_dump(mode="json")
                for item in runtime.commitments.list_communications(case_id)
            ],
        }

    @router.post("/v1/operations/commitments/{case_id}/fulfillment")
    def attest_commitment_fulfillment(
        case_id: UUID,
        payload: CommitmentFulfillmentBody,
        request: Request,
    ) -> dict[str, Any]:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        commitment = runtime.commitments.get_commitment(case_id)
        if commitment is None:
            raise HTTPException(status_code=404, detail="commitment not found")
        if actor.principal_id != commitment.committer_principal_id:
            runtime.require(actor, AdministrativePermission.COMMITMENT_ATTEST, case=case)
        try:
            commitment = runtime.commitment_service.attest_fulfillment(
                case_id,
                principal_id=actor.principal_id,
                basis=payload.basis,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (CommitmentIntakeError, CommitmentConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"commitment": commitment.model_dump(mode="json")}

    @router.post("/v1/operations/commitments/{case_id}/due-revision")
    def revise_commitment_due(
        case_id: UUID,
        payload: CommitmentDueRevisionBody,
        request: Request,
    ) -> dict[str, Any]:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require_intake_review(actor)
        try:
            commitment = runtime.commitment_service.revise_due_at(
                case_id,
                reviewer_principal_id=actor.principal_id,
                due_at=payload.due_at,
                basis=payload.basis,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (CommitmentIntakeError, CommitmentConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"commitment": commitment.model_dump(mode="json")}

    @router.post("/v1/operations/commitments/{case_id}/cancel")
    def cancel_commitment(
        case_id: UUID,
        payload: CommitmentCancellationBody,
        request: Request,
    ) -> dict[str, Any]:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require_intake_review(actor)
        try:
            commitment = runtime.commitment_service.cancel_commitment(
                case_id,
                reviewer_principal_id=actor.principal_id,
                basis=payload.basis,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (CommitmentIntakeError, CommitmentConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "case": (runtime.store.get_case(case_id) or case).model_dump(mode="json"),
            "commitment": commitment.model_dump(mode="json"),
        }

    return router


__all__ = ["build_commitment_router"]
