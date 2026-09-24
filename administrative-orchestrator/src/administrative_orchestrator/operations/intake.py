from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from ..access_policy import AdministrativePermission
from ..admission import AdmissionConflict, AdmissionRejected
from ..candidate_admission import CandidateAdministrativeAdmissionService
from ..financial_admission import (
    CandidateExpenseAdmissionService,
    CandidateInvoiceAPAdmissionService,
    CandidateProcurementAdmissionService,
)
from ..intake.models import CandidateStatus, IntakeAssessment
from ..intake.repository import AssessmentConflict
from ..offboarding_admission import CandidateOffboardingAdmissionService
from ..onboarding_admission import CandidateOnboardingAdmissionService, OnboardingAdmissionError
from .models import (
    IntakeAssessmentBody,
    IntakeCandidateDetail,
    IntakePromotionBody,
    IntakePromotionResponse,
    IntakeQueueItem,
)
from .runtime import OperationsRuntime


def _admission_bridge(
    runtime: OperationsRuntime,
    case_kind: str,
) -> CandidateAdministrativeAdmissionService:
    if case_kind == "employee-onboarding":
        return CandidateOnboardingAdmissionService(
            runtime.store,
            runtime.intake,
            runtime.intake_promotions,
            policies=runtime.policies,
            uow=runtime.uow,
        )
    if case_kind == "employee-offboarding":
        return CandidateOffboardingAdmissionService(
            runtime.store,
            runtime.intake,
            runtime.intake_promotions,
            policies=runtime.policies,
            uow=runtime.uow,
        )
    if case_kind == "procurement-request":
        return CandidateProcurementAdmissionService(
            runtime.store,
            runtime.intake,
            runtime.intake_promotions,
            policies=runtime.policies,
            uow=runtime.uow,
        )
    if case_kind == "invoice-ap-preparation":
        return CandidateInvoiceAPAdmissionService(
            runtime.store,
            runtime.intake,
            runtime.intake_promotions,
            policies=runtime.policies,
            uow=runtime.uow,
        )
    if case_kind == "expense-reimbursement":
        return CandidateExpenseAdmissionService(
            runtime.store,
            runtime.intake,
            runtime.intake_promotions,
            policies=runtime.policies,
            uow=runtime.uow,
        )
    raise OnboardingAdmissionError(
        f"typed admission does not support case_kind={case_kind!r}"
    )


def build_intake_router(runtime: OperationsRuntime) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/operations/intake/candidates", response_model=list[IntakeQueueItem])
    def intake_candidate_queue(
        request: Request,
        status_filter: Annotated[
            CandidateStatus | None, Query(alias="status")
        ] = CandidateStatus.ACTIVE,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    ) -> list[IntakeQueueItem]:
        actor = runtime.actor(request)
        runtime.require(actor, AdministrativePermission.OPERATIONS_READ)
        candidates = runtime.intake.list_candidates(status=status_filter, limit=limit)
        result: list[IntakeQueueItem] = []
        for candidate in candidates:
            assessments = runtime.intake.list_assessments(candidate.candidate_id)
            result.append(
                IntakeQueueItem(
                    candidate_id=candidate.candidate_id,
                    conversation_ref=candidate.conversation_ref,
                    candidate_requester=candidate.candidate_requester,
                    candidate_intent=candidate.candidate_intent,
                    status=candidate.status,
                    created_at=candidate.created_at,
                    latest_assessment=assessments[-1] if assessments else None,
                )
            )
        return result

    @router.get(
        "/v1/operations/intake/candidates/{candidate_id}",
        response_model=IntakeCandidateDetail,
    )
    def intake_candidate_detail(candidate_id: UUID, request: Request) -> IntakeCandidateDetail:
        actor = runtime.actor(request)
        candidate = runtime.intake.get_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="intake candidate not found")
        runtime.require(actor, AdministrativePermission.OPERATIONS_READ)
        return IntakeCandidateDetail(
            candidate=candidate,
            assessments=runtime.intake.list_assessments(candidate_id),
            promotion=runtime.intake.get_promotion(candidate_id),
        )

    @router.post(
        "/v1/operations/intake/candidates/{candidate_id}/assessments",
        response_model=IntakeAssessment,
    )
    def finalize_intake_assessment(
        candidate_id: UUID,
        payload: IntakeAssessmentBody,
        request: Request,
    ) -> IntakeAssessment:
        actor = runtime.actor(request)
        runtime.require_intake_review(actor)
        if runtime.intake.get_candidate(candidate_id) is None:
            raise HTTPException(status_code=404, detail="intake candidate not found")
        try:
            return runtime.intake_assessments.finalize_human(
                candidate_id,
                payload.disposition,
                reviewer_principal_id=actor.principal_id,
                basis=payload.basis,
            )
        except (AdmissionRejected, AssessmentConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/v1/operations/intake/candidates/{candidate_id}/promote",
        response_model=IntakePromotionResponse,
    )
    def promote_intake_candidate(
        candidate_id: UUID,
        payload: IntakePromotionBody,
        request: Request,
    ) -> IntakePromotionResponse:
        actor = runtime.actor(request)
        runtime.require_intake_review(actor)
        candidate = runtime.intake.get_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="intake candidate not found")
        assessment = runtime.intake.get_assessment(payload.assessment_id)
        if assessment is None or assessment.candidate_ref != candidate_id:
            raise HTTPException(status_code=404, detail="intake assessment not found")
        try:
            if payload.bridge_to_m5 or payload.bridge_to_m8:
                if payload.subject_ref is None:
                    raise OnboardingAdmissionError("typed promotion requires subject_ref")
                admission = _admission_bridge(runtime, payload.case_kind).promote_and_evaluate(
                    candidate,
                    assessment,
                    source_system=payload.source_system,
                    tenant_ref=payload.tenant_ref,
                    source_event_id=payload.source_event_id,
                    requester_principal_id=payload.requester_principal_id,
                    subject_ref=payload.subject_ref,
                    channel=payload.channel,
                    promotion_policy_ref=payload.promotion_policy_ref,
                )
                result = admission.promotion
                promoted_case = admission.case
                policy_evaluation = admission.policy_evaluation
            else:
                result = runtime.intake_promotions.promote(
                    candidate,
                    assessment,
                    source_system=payload.source_system,
                    tenant_ref=payload.tenant_ref,
                    source_event_id=payload.source_event_id,
                    requester_principal_id=payload.requester_principal_id,
                    channel=payload.channel,
                    case_kind=payload.case_kind,
                    subject_ref=payload.subject_ref,
                    promotion_policy_ref=payload.promotion_policy_ref,
                )
                promoted_case = result.case
                policy_evaluation = None
        except (AdmissionConflict, AdmissionRejected, OnboardingAdmissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return IntakePromotionResponse(
            promotion=result.promotion,
            request=result.request,
            case=promoted_case,
            created=result.created,
            policy_evaluation=policy_evaluation,
        )

    return router


__all__ = ["build_intake_router"]
