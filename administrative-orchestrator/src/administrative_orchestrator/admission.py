from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .domain import AdministrativeCase, AdministrativeRequest
from .ingress import IngressReceiptRow
from .intake.models import (
    AssessmentAuthority,
    CandidateAdministrativeRequest,
    CandidateStatus,
    IntakeAssessment,
    IntakeDisposition,
    IntakeVerificationStatus,
    PromotionRecord,
)
from .intake.repository import (
    AssessmentConflict,
    CandidateAdministrativeRequestRow,
    IntakeRepository,
    PromotionConflict,
    PromotionRecordRow,
)
from .persistence import CaseRow, RequestRow, SqlStore
from .service import create_case


class AdmissionRejected(ValueError):
    """The candidate is not eligible for the requested admission transition."""


class AdmissionConflict(RuntimeError):
    """A durable admission identity or lineage already belongs to another result."""


@dataclass(frozen=True, slots=True)
class PromotionResult:
    promotion: PromotionRecord
    request: AdministrativeRequest
    case: AdministrativeCase
    created: bool


class IntakeAssessmentService:
    """Persist non-authoritative suggestions and explicitly authorized finals."""

    def __init__(self, repository: IntakeRepository) -> None:
        self.repository = repository

    def suggest(
        self,
        candidate_ref: UUID,
        disposition: IntakeDisposition,
        *,
        basis: dict[str, Any] | None = None,
    ) -> IntakeAssessment:
        self._require_candidate(candidate_ref)
        return self.repository.append_assessment(
            IntakeAssessment(
                candidate_ref=candidate_ref,
                disposition=disposition,
                basis=dict(basis or {}),
                authority=AssessmentAuthority.MODEL_SUGGESTION,
                is_final=False,
            )
        )

    def finalize_deterministic(
        self,
        candidate_ref: UUID,
        disposition: IntakeDisposition,
        *,
        rule_ref: str,
        input_digest: str,
        basis: dict[str, Any] | None = None,
    ) -> IntakeAssessment:
        rule_ref = rule_ref.strip()
        input_digest = input_digest.strip()
        if not rule_ref or not input_digest:
            raise AdmissionRejected("deterministic final assessment requires rule proof")
        proof = {**(basis or {}), "rule_ref": rule_ref, "input_digest": input_digest}
        return self._finalize(
            candidate_ref,
            disposition,
            authority=AssessmentAuthority.DETERMINISTIC_RULE,
            basis=proof,
            reviewer_principal_id=None,
        )

    def finalize_human(
        self,
        candidate_ref: UUID,
        disposition: IntakeDisposition,
        *,
        reviewer_principal_id: str,
        basis: dict[str, Any] | None = None,
    ) -> IntakeAssessment:
        reviewer_principal_id = reviewer_principal_id.strip()
        if not reviewer_principal_id:
            raise AdmissionRejected("human final assessment requires a reviewer")
        proof = {
            **(basis or {}),
            "reviewer_principal_id": reviewer_principal_id,
        }
        return self._finalize(
            candidate_ref,
            disposition,
            authority=AssessmentAuthority.HUMAN_REVIEW,
            basis=proof,
            reviewer_principal_id=reviewer_principal_id,
        )

    def _finalize(
        self,
        candidate_ref: UUID,
        disposition: IntakeDisposition,
        *,
        authority: AssessmentAuthority,
        basis: dict[str, Any],
        reviewer_principal_id: str | None,
    ) -> IntakeAssessment:
        self._require_candidate(candidate_ref)
        existing_finals = [
            item for item in self.repository.list_assessments(candidate_ref) if item.is_final
        ]
        if existing_finals:
            existing = existing_finals[0]
            if (
                existing.disposition == disposition
                and existing.authority == authority
                and existing.basis == basis
                and existing.reviewer_principal_id == reviewer_principal_id
            ):
                return existing
            raise AssessmentConflict("candidate already has a different final assessment")

        try:
            return self.repository.append_assessment(
                IntakeAssessment(
                    candidate_ref=candidate_ref,
                    disposition=disposition,
                    basis=basis,
                    authority=authority,
                    is_final=True,
                    reviewer_principal_id=reviewer_principal_id,
                )
            )
        except AssessmentConflict as exc:
            final_assessments = [
                item for item in self.repository.list_assessments(candidate_ref) if item.is_final
            ]
            if final_assessments:
                raise AssessmentConflict(
                    "candidate already has a different final assessment"
                ) from exc
            raise

    def _require_candidate(self, candidate_ref: UUID) -> CandidateAdministrativeRequest:
        candidate = self.repository.get_candidate(candidate_ref)
        if candidate is None:
            raise AdmissionRejected("assessment requires a persisted candidate")
        if candidate.status not in {CandidateStatus.ACTIVE, CandidateStatus.ADMITTED}:
            raise AdmissionRejected("assessment cannot target a superseded or rejected candidate")
        return candidate


class IntakePromotionService:
    """Atomically promote one admitted candidate into the existing M5 path."""

    def __init__(self, store: SqlStore, repository: IntakeRepository | None = None) -> None:
        self.store = store
        self.repository = repository or IntakeRepository(store)

    def promote(
        self,
        candidate: CandidateAdministrativeRequest,
        assessment: IntakeAssessment,
        *,
        source_system: str,
        tenant_ref: str,
        source_event_id: str,
        requester_principal_id: str,
        channel: str = "intake",
        case_kind: str = "intake",
        subject_ref: str | None = None,
        promotion_policy_ref: str = "m6-human-confirmed-v1",
    ) -> PromotionResult:
        source_system = source_system.strip()
        tenant_ref = tenant_ref.strip()
        source_event_id = source_event_id.strip()
        requester_principal_id = requester_principal_id.strip()
        channel = channel.strip()
        case_kind = case_kind.strip()
        promotion_policy_ref = promotion_policy_ref.strip()
        if not all(
            (
                source_system,
                tenant_ref,
                source_event_id,
                requester_principal_id,
                channel,
                case_kind,
                promotion_policy_ref,
            )
        ):
            raise AdmissionRejected("promotion context must not contain blank identifiers")

        existing = self.repository.get_promotion(candidate.candidate_id)
        if existing is not None:
            return self._load_existing(
                existing,
                assessment=assessment,
                source_event_id=source_event_id,
                requester_principal_id=requester_principal_id,
            )

        persisted_candidate = self.repository.get_candidate(candidate.candidate_id)
        if persisted_candidate is None or persisted_candidate.model_dump() != candidate.model_dump():
            raise AdmissionRejected("promotion requires the current persisted candidate")
        if candidate.status is not CandidateStatus.ACTIVE:
            raise AdmissionRejected("only an active candidate may be promoted")

        persisted_assessment = self.repository.get_assessment(assessment.assessment_id)
        if persisted_assessment is None or persisted_assessment.model_dump() != assessment.model_dump():
            raise AdmissionRejected("promotion requires the current persisted assessment")
        if not assessment.is_final or assessment.disposition is not IntakeDisposition.ADMIT:
            raise AdmissionRejected("promotion requires a final ADMIT assessment")
        if assessment.authority is AssessmentAuthority.MODEL_SUGGESTION:
            raise AdmissionRejected("model suggestion cannot authorize promotion")

        intake_receipt = self.repository.get_intake_receipt(
            source_system=source_system,
            tenant_ref=tenant_ref,
            source_event_id=source_event_id,
        )
        if intake_receipt is None:
            raise AdmissionRejected("promotion requires a persisted IntakeReceipt")
        if intake_receipt.verification_status is not IntakeVerificationStatus.VERIFIED:
            raise AdmissionRejected("promotion requires a verified IntakeReceipt")
        if (
            intake_receipt.artifact_ref is not None
            and intake_receipt.artifact_ref not in candidate.source_refs
        ):
            raise AdmissionRejected("IntakeReceipt artifact is not part of the candidate lineage")

        request = AdministrativeRequest(
            requester_principal_id=requester_principal_id,
            channel=channel,
            intent=candidate.candidate_intent,
            source_ref=f"intake:{source_system}/{source_event_id}",
        )
        case = create_case(
            request,
            case_kind=case_kind,
            subject_ref=subject_ref or str(candidate.candidate_id),
        )
        promotion = PromotionRecord(
            candidate_ref=candidate.candidate_id,
            assessment_ref=assessment.assessment_id,
            request_id=request.request_id,
            ingress_receipt_ref=source_event_id,
            promotion_policy_ref=promotion_policy_ref,
        )

        try:
            with self.store.sessions.begin() as db:
                existing_row = db.execute(
                    select(PromotionRecordRow).where(
                        PromotionRecordRow.candidate_ref == candidate.candidate_id
                    )
                ).scalar_one_or_none()
                if existing_row is not None:
                    raise PromotionConflict("candidate was concurrently promoted")
                if db.get(IngressReceiptRow, source_event_id) is not None:
                    raise AdmissionConflict("source event already created an M5 case")

                db.add(
                    RequestRow(
                        request_id=request.request_id,
                        requester_principal_id=request.requester_principal_id,
                        channel=request.channel,
                        intent=request.intent,
                        received_at=request.received_at,
                        source_ref=request.source_ref,
                    )
                )
                db.flush()
                db.add(self.store._case_row(case, request.request_id))
                db.flush()
                db.add(
                    IngressReceiptRow(
                        source_event_id=source_event_id,
                        request_id=request.request_id,
                        case_id=case.case_id,
                    )
                )
                db.flush()
                db.add(
                    PromotionRecordRow(
                        promotion_id=promotion.promotion_id,
                        candidate_ref=promotion.candidate_ref,
                        assessment_ref=promotion.assessment_ref,
                        request_id=promotion.request_id,
                        ingress_receipt_ref=promotion.ingress_receipt_ref,
                        promoted_at=promotion.promoted_at,
                        promotion_policy_ref=promotion.promotion_policy_ref,
                    )
                )
                db.flush()
                candidate_row = db.get(CandidateAdministrativeRequestRow, candidate.candidate_id)
                if candidate_row is not None:
                    candidate_row.status = CandidateStatus.ADMITTED.value
                self.store._append_audit(
                    db,
                    case.case_id,
                    "intake.candidate_promoted",
                    {
                        "candidate_id": str(candidate.candidate_id),
                        "assessment_id": str(assessment.assessment_id),
                        "request_id": str(request.request_id),
                        "source_event_id": source_event_id,
                    },
                )
        except PromotionConflict as exc:
            existing = self.repository.get_promotion(candidate.candidate_id)
            if existing is None:
                raise AdmissionConflict("candidate was concurrently promoted") from exc
            return self._load_existing(
                existing,
                assessment=assessment,
                source_event_id=source_event_id,
                requester_principal_id=requester_principal_id,
            )
        except IntegrityError as exc:
            existing = self.repository.get_promotion(candidate.candidate_id)
            if existing is None:
                raise AdmissionConflict("promotion transaction conflicted") from exc
            return self._load_existing(
                existing,
                assessment=assessment,
                source_event_id=source_event_id,
                requester_principal_id=requester_principal_id,
            )

        return PromotionResult(promotion=promotion, request=request, case=case, created=True)

    def _load_existing(
        self,
        promotion: PromotionRecord,
        *,
        assessment: IntakeAssessment,
        source_event_id: str,
        requester_principal_id: str,
    ) -> PromotionResult:
        if promotion.assessment_ref != assessment.assessment_id:
            raise AdmissionConflict("candidate was already promoted with another assessment")
        if promotion.ingress_receipt_ref != source_event_id:
            raise AdmissionConflict("candidate was already promoted from another source event")

        with self.store.sessions() as db:
            ingress = db.get(IngressReceiptRow, promotion.ingress_receipt_ref)
            request_row = db.get(RequestRow, promotion.request_id)
            if ingress is None or request_row is None:
                raise AdmissionConflict("promotion lineage points to missing M5 records")
            case_row = db.get(CaseRow, ingress.case_id)
            if case_row is None:
                raise AdmissionConflict("promotion lineage points to a missing case")
            if request_row.requester_principal_id != requester_principal_id:
                raise AdmissionConflict("redelivery requester differs from the promoted request")
            request = AdministrativeRequest(
                request_id=request_row.request_id,
                requester_principal_id=request_row.requester_principal_id,
                channel=request_row.channel,
                intent=request_row.intent,
                received_at=request_row.received_at,
                source_ref=request_row.source_ref,
            )
            case = self.store._case_from_row(case_row)
        return PromotionResult(promotion=promotion, request=request, case=case, created=False)


AssessmentService = IntakeAssessmentService
PromotionService = IntakePromotionService


__all__ = [
    "AdmissionConflict",
    "AdmissionRejected",
    "AssessmentService",
    "IntakeAssessmentService",
    "IntakePromotionService",
    "PromotionResult",
    "PromotionService",
]
