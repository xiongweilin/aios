from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from ..access_policy import AdministrativePermission
from ..investigation_client import InvestigationClientError
from ..investigation_models import ReopenAssessmentKind
from ..investigation_repository import (
    InvestigationBudgetExceeded,
    InvestigationConflict,
    InvestigationNotFound,
)
from ..persistence import ConcurrencyConflict
from .models import (
    InvestigationEvidenceBody,
    InvestigationEvidenceRequestBody,
    InvestigationProposalBody,
    InvestigationRequestBody,
    ReopenAssessmentBody,
    ReopenCaseBody,
)
from .runtime import OperationsRuntime


def build_investigation_router(runtime: OperationsRuntime) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/operations/cases/{case_id}/investigations")
    def request_case_investigation(
        case_id: UUID,
        payload: InvestigationRequestBody,
        request: Request,
    ) -> dict[str, Any]:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.INVESTIGATION_REQUEST, case=case)
        try:
            investigation = runtime.investigation_service.request_investigation(
                case_id,
                trigger_type=payload.trigger,
                reason=payload.reason,
                requested_question=payload.requested_question,
                created_by=actor.principal_id,
                idempotency_key=payload.idempotency_key,
                evidence_refs=payload.evidence_refs,
                allowed_evidence_refs=payload.allowed_evidence_refs,
                constraints=payload.constraints,
                source_type=payload.source_type,
                reconciliation_ref=payload.reconciliation_ref,
            )
        except (InvestigationConflict, InvestigationBudgetExceeded, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"investigation": investigation.model_dump(mode="json")}

    @router.get("/v1/operations/cases/{case_id}/investigations")
    def list_case_investigations(case_id: UUID, request: Request) -> list[dict[str, Any]]:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.INVESTIGATION_READ, case=case)
        return [
            item.model_dump(mode="json")
            for item in runtime.investigation_service.repository.list_requests(case_id)
        ]

    @router.get("/v1/operations/investigations/{investigation_id}")
    def investigation_detail(investigation_id: UUID, request: Request) -> dict[str, Any]:
        actor = runtime.actor(request)
        investigation = runtime.investigation_service.repository.get_request(investigation_id)
        if investigation is None:
            raise HTTPException(status_code=404, detail="investigation not found")
        case = runtime.store.get_case(investigation.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.INVESTIGATION_READ, case=case)
        return runtime.investigation_service.detail(investigation_id)

    @router.post("/v1/operations/investigations/{investigation_id}/run")
    def run_investigation(investigation_id: UUID, request: Request) -> dict[str, Any]:
        actor = runtime.actor(request)
        investigation = runtime.investigation_service.repository.get_request(investigation_id)
        if investigation is None:
            raise HTTPException(status_code=404, detail="investigation not found")
        case = runtime.store.get_case(investigation.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.INVESTIGATION_REVIEW, case=case)
        try:
            proposal = runtime.investigation_service.run(investigation_id)
        except InvestigationNotFound as exc:
            raise HTTPException(status_code=404, detail="investigation not found") from exc
        except InvestigationClientError as exc:
            raise HTTPException(status_code=503, detail="investigation advisory unavailable") from exc
        except (InvestigationConflict, InvestigationBudgetExceeded, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"proposal": proposal.model_dump(mode="json")}

    @router.post("/v1/operations/investigations/{investigation_id}/proposals")
    def record_investigation_proposal(
        investigation_id: UUID,
        payload: InvestigationProposalBody,
        request: Request,
    ) -> dict[str, Any]:
        actor = runtime.actor(request)
        investigation = runtime.investigation_service.repository.get_request(investigation_id)
        if investigation is None:
            raise HTTPException(status_code=404, detail="investigation not found")
        case = runtime.store.get_case(investigation.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.INVESTIGATION_REVIEW, case=case)
        if payload.proposal.investigation_id != investigation_id:
            raise HTTPException(status_code=409, detail="proposal investigation identity mismatch")
        try:
            proposal = runtime.investigation_service.record_proposal(payload.proposal)
        except (InvestigationConflict, InvestigationBudgetExceeded, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"proposal": proposal.model_dump(mode="json")}

    @router.post("/v1/operations/investigations/{investigation_id}/evidence-requests")
    def request_investigation_evidence(
        investigation_id: UUID,
        payload: InvestigationEvidenceRequestBody,
        request: Request,
    ) -> dict[str, Any]:
        actor = runtime.actor(request)
        investigation = runtime.investigation_service.repository.get_request(investigation_id)
        if investigation is None:
            raise HTTPException(status_code=404, detail="investigation not found")
        case = runtime.store.get_case(investigation.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.INVESTIGATION_REVIEW, case=case)
        try:
            item = runtime.investigation_service.request_evidence(
                investigation_id,
                source_kind=payload.source_kind,
                requested_question=payload.requested_question,
                requested_by=actor.principal_id,
                idempotency_key=payload.idempotency_key,
                allowed_evidence_refs=payload.allowed_evidence_refs,
            )
        except (InvestigationConflict, InvestigationBudgetExceeded, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"evidence_request": item.model_dump(mode="json")}

    @router.post("/v1/operations/investigations/{investigation_id}/evidence")
    def add_investigation_evidence(
        investigation_id: UUID,
        payload: InvestigationEvidenceBody,
        request: Request,
    ) -> dict[str, Any]:
        actor = runtime.actor(request)
        investigation = runtime.investigation_service.repository.get_request(investigation_id)
        if investigation is None:
            raise HTTPException(status_code=404, detail="investigation not found")
        case = runtime.store.get_case(investigation.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.INVESTIGATION_REVIEW, case=case)
        try:
            item = runtime.investigation_service.add_evidence(
                investigation_id,
                evidence_request_id=payload.evidence_request_id,
                evidence_ref=payload.evidence_ref,
                source_kind=payload.source_kind,
                source=payload.source,
                owner=payload.owner,
                source_ref=payload.source_ref,
                source_version=payload.source_version,
                digest=payload.digest,
                added_by=actor.principal_id,
                idempotency_key=payload.idempotency_key,
            )
        except (InvestigationConflict, InvestigationBudgetExceeded, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"evidence": item.model_dump(mode="json")}

    @router.post("/v1/operations/investigations/{investigation_id}/human-assessment")
    def assess_investigation_reopen(
        investigation_id: UUID,
        payload: ReopenAssessmentBody,
        request: Request,
    ) -> dict[str, Any]:
        actor = runtime.actor(request)
        investigation = runtime.investigation_service.repository.get_request(investigation_id)
        if investigation is None:
            raise HTTPException(status_code=404, detail="investigation not found")
        case = runtime.store.get_case(investigation.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.INVESTIGATION_REVIEW, case=case)
        if payload.investigation_id != investigation_id:
            raise HTTPException(status_code=409, detail="assessment investigation identity mismatch")
        try:
            assessment = runtime.investigation_service.assess_reopen(
                investigation_id,
                disposition=payload.disposition,
                reason=payload.reason,
                evidence_refs=payload.evidence_refs,
                proposal_ref=payload.proposal_ref,
                assessment_kind=ReopenAssessmentKind.HUMAN,
                assessed_by=actor.principal_id,
                idempotency_key=payload.idempotency_key,
            )
        except (InvestigationConflict, InvestigationBudgetExceeded, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"assessment": assessment.model_dump(mode="json")}

    @router.post("/v1/operations/cases/{case_id}/reopen-assessments")
    def assess_case_reopen(
        case_id: UUID,
        payload: ReopenAssessmentBody,
        request: Request,
    ) -> dict[str, Any]:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.INVESTIGATION_REVIEW, case=case)
        investigation = runtime.investigation_service.repository.get_request(
            payload.investigation_id
        )
        if investigation is None or investigation.case_id != case_id:
            raise HTTPException(status_code=404, detail="investigation not found for case")
        try:
            assessment = runtime.investigation_service.assess_reopen(
                payload.investigation_id,
                disposition=payload.disposition,
                reason=payload.reason,
                evidence_refs=payload.evidence_refs,
                proposal_ref=payload.proposal_ref,
                assessment_kind=ReopenAssessmentKind.HUMAN,
                assessed_by=actor.principal_id,
                idempotency_key=payload.idempotency_key,
            )
        except (InvestigationConflict, InvestigationBudgetExceeded, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"assessment": assessment.model_dump(mode="json")}

    @router.post("/v1/operations/cases/{case_id}/reopen")
    def authorize_case_reopen(
        case_id: UUID,
        payload: ReopenCaseBody,
        request: Request,
    ) -> dict[str, Any]:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.REOPEN_AUTHORIZE, case=case)
        try:
            record, updated, created = runtime.investigation_service.authorize_reopen(
                case_id,
                assessment_id=payload.assessment_id,
                authorized_by=actor.principal_id,
                idempotency_key=payload.idempotency_key,
            )
        except InvestigationNotFound as exc:
            raise HTTPException(status_code=404, detail="reopen assessment not found") from exc
        except (InvestigationConflict, ConcurrencyConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "reopen": record.model_dump(mode="json"),
            "case": updated.model_dump(mode="json"),
            "created": created,
        }

    @router.get("/v1/operations/cases/{case_id}/reopen-history")
    def case_reopen_history(case_id: UUID, request: Request) -> list[dict[str, Any]]:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.INVESTIGATION_READ, case=case)
        return [
            item.model_dump(mode="json")
            for item in runtime.investigation_service.repository.list_reopen_records(case_id)
        ]

    return router


__all__ = ["build_investigation_router"]
