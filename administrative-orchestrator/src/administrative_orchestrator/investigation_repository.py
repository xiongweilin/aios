from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from .domain import AdministrativeCase, CaseStatus, ReopenReason
from .investigation_models import (
    EvidenceRequestStatus,
    InvestigationConstraints,
    InvestigationEvidence,
    InvestigationEvidenceRequest,
    InvestigationProposal,
    InvestigationRequest,
    InvestigationStatus,
    InvestigationTrigger,
    ReopenAssessment,
    ReopenAssessmentDisposition,
    ReopenAssessmentKind,
    ReopenRecord,
)
from .investigation_rows import (
    InvestigationEvidenceRequestRow,
    InvestigationEvidenceRow,
    InvestigationProposalRow,
    InvestigationRow,
    ReframingProposalRow,
    ReopenAssessmentRow,
    ReopenRecordRow,
)
from .investigation_serialization import assessment_digest as _assessment_digest
from .investigation_serialization import assessment_from_row as _assessment_from_row
from .investigation_serialization import assessment_row as _assessment_row
from .investigation_serialization import evidence_from_row as _evidence_from_row
from .investigation_serialization import evidence_request_from_row as _evidence_request_from_row
from .investigation_serialization import evidence_request_row as _evidence_request_row
from .investigation_serialization import evidence_row as _evidence_row
from .investigation_serialization import proposal_digest as _proposal_digest
from .investigation_serialization import proposal_from_row as _proposal_from_row
from .investigation_serialization import proposal_row as _proposal_row
from .investigation_serialization import record_from_row as _record_from_row
from .investigation_serialization import record_row as _record_row
from .investigation_serialization import request_digest as _request_digest
from .investigation_serialization import request_from_row as _request_from_row
from .investigation_serialization import request_row as _request_row
from .persistence import (
    AuthorizationRow,
    CaseRow,
    ConcurrencyConflict,
    DecisionRow,
    SqlStore,
    utcnow,
)


class InvestigationConflict(RuntimeError):
    pass


class InvestigationBudgetExceeded(InvestigationConflict):
    pass


class InvestigationNotFound(KeyError):
    pass


class InvestigationRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def create_request(
        self,
        trigger: InvestigationTrigger,
        request: InvestigationRequest,
    ) -> InvestigationRequest:
        if trigger != request.trigger:
            raise InvestigationConflict("request trigger lineage does not match")
        digest = _request_digest(request)
        with self.store.sessions.begin() as db:
            existing = db.execute(
                select(InvestigationRow).where(
                    InvestigationRow.case_id == request.case_id,
                    InvestigationRow.idempotency_key == request.idempotency_key,
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.request_digest != digest:
                    raise InvestigationConflict(
                        "investigation idempotency key was reused with different semantics"
                    )
                return self._request_from_row(existing)
            db.add(self._request_row(request, digest))
            db.flush()
            self.store._append_audit(
                db,
                request.case_id,
                "investigation.triggered",
                {
                    "investigation_id": str(request.investigation_id),
                    "trigger_type": request.trigger.trigger_type.value,
                    "authority_epoch": request.authority_epoch,
                    "source_type": request.trigger.source_type,
                    "evidence_ref_count": len(request.trigger.evidence_refs),
                },
            )
            self.store._append_audit(
                db,
                request.case_id,
                "investigation.requested",
                {
                    "investigation_id": str(request.investigation_id),
                    "authority_epoch": request.authority_epoch,
                    "status": request.status.value,
                    "max_rounds": request.constraints.max_rounds,
                    "max_model_calls": request.constraints.max_model_calls,
                    "max_evidence_requests": request.constraints.max_evidence_requests,
                },
            )
        return request

    def get_request(self, investigation_id: UUID) -> InvestigationRequest | None:
        with self.store.sessions() as db:
            row = db.get(InvestigationRow, investigation_id)
            return None if row is None else self._request_from_row(row)

    def list_requests(self, case_id: UUID) -> list[InvestigationRequest]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(InvestigationRow)
                    .where(InvestigationRow.case_id == case_id)
                    .order_by(InvestigationRow.created_at, InvestigationRow.investigation_id)
                )
                .scalars()
                .all()
            )
            return [self._request_from_row(row) for row in rows]

    def mark_running(self, investigation_id: UUID) -> InvestigationRequest:
        budget_error: str | None = None
        with self.store.sessions.begin() as db:
            row = db.get(InvestigationRow, investigation_id)
            if row is None:
                raise InvestigationNotFound(investigation_id)
            if row.status in {
                InvestigationStatus.CLOSURE_PRESERVED.value,
                InvestigationStatus.REOPENED.value,
                InvestigationStatus.EXPIRED.value,
            }:
                raise InvestigationConflict("terminal investigation cannot run again")
            if row.status == InvestigationStatus.REQUIRES_HUMAN_REVIEW.value:
                raise InvestigationBudgetExceeded(
                    "investigation requires human review before another advisory run"
                )
            self._assert_case_epoch(db, row.case_id, row.authority_epoch)
            constraints = InvestigationConstraints.model_validate(row.constraints_json)
            if row.rounds_used >= constraints.max_rounds:
                row.status = InvestigationStatus.REQUIRES_HUMAN_REVIEW.value
                row.updated_at = utcnow()
                budget_error = "investigation round budget exhausted"
            elif row.model_calls_used >= constraints.max_model_calls:
                row.status = InvestigationStatus.REQUIRES_HUMAN_REVIEW.value
                row.updated_at = utcnow()
                budget_error = "investigation model-call budget exhausted"
            else:
                # Reserve both budgets before the external call. A crash or
                # timeout after invocation must not make retries unbounded.
                row.rounds_used += 1
                row.model_calls_used += 1
                row.status = InvestigationStatus.RUNNING.value
                row.updated_at = utcnow()
            if budget_error is not None:
                self.store._append_audit(
                    db,
                    row.case_id,
                    "investigation.budget_exhausted",
                    {
                        "investigation_id": str(row.investigation_id),
                        "budget": "max_rounds"
                        if row.rounds_used >= constraints.max_rounds
                        else "max_model_calls",
                    },
                )
            db.flush()
            result = self._request_from_row(row)
        if budget_error is not None:
            raise InvestigationBudgetExceeded(budget_error)
        return result

    def mark_failed(
        self,
        investigation_id: UUID,
        *,
        error_code: str,
    ) -> InvestigationRequest:
        with self.store.sessions.begin() as db:
            row = db.get(InvestigationRow, investigation_id)
            if row is None:
                raise InvestigationNotFound(investigation_id)
            if row.status in {
                InvestigationStatus.CLOSURE_PRESERVED.value,
                InvestigationStatus.REOPENED.value,
                InvestigationStatus.REQUIRES_HUMAN_REVIEW.value,
                InvestigationStatus.EXPIRED.value,
            }:
                return self._request_from_row(row)
            row.status = InvestigationStatus.FAILED.value
            row.last_error_code = error_code[:256]
            row.updated_at = utcnow()
            self.store._append_audit(
                db,
                row.case_id,
                "investigation.failed",
                {
                    "investigation_id": str(row.investigation_id),
                    "authority_epoch": row.authority_epoch,
                    "error_code": row.last_error_code,
                },
            )
            db.flush()
            return self._request_from_row(row)

    def mark_expired(
        self,
        investigation_id: UUID,
        *,
        reason: str,
    ) -> InvestigationRequest:
        with self.store.sessions.begin() as db:
            row = db.get(InvestigationRow, investigation_id)
            if row is None:
                raise InvestigationNotFound(investigation_id)
            if row.status in {
                InvestigationStatus.CLOSURE_PRESERVED.value,
                InvestigationStatus.REOPENED.value,
                InvestigationStatus.EXPIRED.value,
            }:
                return self._request_from_row(row)
            row.status = InvestigationStatus.EXPIRED.value
            row.last_error_code = reason[:256]
            row.updated_at = utcnow()
            self.store._append_audit(
                db,
                row.case_id,
                "investigation.expired",
                {
                    "investigation_id": str(row.investigation_id),
                    "authority_epoch": row.authority_epoch,
                    "reason": row.last_error_code,
                },
            )
            db.flush()
            return self._request_from_row(row)

    def record_proposal(self, proposal: InvestigationProposal) -> InvestigationProposal:
        digest = _proposal_digest(proposal)
        budget_error: str | None = None
        with self.store.sessions.begin() as db:
            investigation = db.get(InvestigationRow, proposal.investigation_id)
            if investigation is None:
                raise InvestigationNotFound(proposal.investigation_id)
            if investigation.case_id != proposal.case_id:
                raise InvestigationConflict("proposal belongs to another case")
            if investigation.authority_epoch != proposal.authority_epoch:
                raise InvestigationConflict("proposal is stale for the investigation epoch")
            existing = db.execute(
                select(InvestigationProposalRow).where(
                    InvestigationProposalRow.investigation_id == proposal.investigation_id,
                    InvestigationProposalRow.idempotency_key == proposal.idempotency_key,
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.proposal_digest != digest:
                    raise InvestigationConflict(
                        "proposal callback idempotency key was reused with different semantics"
                    )
                return self._proposal_from_row(existing)
            self._assert_case_epoch(db, proposal.case_id, proposal.authority_epoch)
            reserved = investigation.status == InvestigationStatus.RUNNING.value
            if investigation.status in {
                InvestigationStatus.CLOSURE_PRESERVED.value,
                InvestigationStatus.REOPENED.value,
                InvestigationStatus.EXPIRED.value,
            }:
                raise InvestigationConflict("terminal investigation cannot record a proposal")
            if investigation.status == InvestigationStatus.REQUIRES_HUMAN_REVIEW.value:
                raise InvestigationBudgetExceeded(
                    "investigation requires human review before another proposal"
                )
            constraints = InvestigationConstraints.model_validate(investigation.constraints_json)
            if not reserved and investigation.rounds_used >= constraints.max_rounds:
                investigation.status = InvestigationStatus.REQUIRES_HUMAN_REVIEW.value
                investigation.updated_at = utcnow()
                self.store._append_audit(
                    db,
                    proposal.case_id,
                    "investigation.budget_exhausted",
                    {
                        "investigation_id": str(proposal.investigation_id),
                        "budget": "max_rounds",
                    },
                )
                budget_error = "investigation round budget exhausted"
            elif not reserved and investigation.model_calls_used >= constraints.max_model_calls:
                investigation.status = InvestigationStatus.REQUIRES_HUMAN_REVIEW.value
                investigation.updated_at = utcnow()
                self.store._append_audit(
                    db,
                    proposal.case_id,
                    "investigation.budget_exhausted",
                    {
                        "investigation_id": str(proposal.investigation_id),
                        "budget": "max_model_calls",
                    },
                )
                budget_error = "investigation model-call budget exhausted"
            else:
                db.add(self._proposal_row(proposal, digest))
                for reframing in proposal.possible_reframings:
                    db.add(
                        ReframingProposalRow(
                            reframing_id=reframing.reframing_id,
                            investigation_id=reframing.investigation_id,
                            proposal_id=proposal.proposal_id,
                            case_id=reframing.case_id,
                            current_frame=reframing.current_frame,
                            proposed_frame=reframing.proposed_frame,
                            reason=reframing.reason,
                            evidence_refs_json=list(reframing.evidence_refs),
                            status=reframing.status.value,
                            created_at=reframing.created_at,
                        )
                    )
                if not reserved:
                    investigation.rounds_used += 1
                    investigation.model_calls_used += 1
                investigation.status = InvestigationStatus.PROPOSAL_RECORDED.value
                investigation.updated_at = utcnow()
            db.flush()
            if budget_error is None:
                self.store._append_audit(
                    db,
                    proposal.case_id,
                    "investigation.proposal_recorded",
                    {
                        "investigation_id": str(proposal.investigation_id),
                        "proposal_id": str(proposal.proposal_id),
                        "authority_epoch": proposal.authority_epoch,
                        "hypothesis_count": len(proposal.hypotheses),
                        "missing_evidence_count": len(proposal.missing_evidence),
                        "reframing_count": len(proposal.possible_reframings),
                    },
                )
                for reframing in proposal.possible_reframings:
                    self.store._append_audit(
                        db,
                        proposal.case_id,
                        "case.reframing_proposed",
                        {
                            "investigation_id": str(proposal.investigation_id),
                            "proposal_id": str(proposal.proposal_id),
                            "reframing_id": str(reframing.reframing_id),
                        },
                    )
        if budget_error is not None:
            raise InvestigationBudgetExceeded(budget_error)
        return proposal

    def list_proposals(self, investigation_id: UUID) -> list[InvestigationProposal]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(InvestigationProposalRow)
                    .where(InvestigationProposalRow.investigation_id == investigation_id)
                    .order_by(InvestigationProposalRow.created_at, InvestigationProposalRow.proposal_id)
                )
                .scalars()
                .all()
            )
            return [self._proposal_from_row(row) for row in rows]

    def get_proposal(self, proposal_id: UUID) -> InvestigationProposal | None:
        with self.store.sessions() as db:
            row = db.get(InvestigationProposalRow, proposal_id)
            return None if row is None else self._proposal_from_row(row)

    def create_evidence_request(
        self,
        item: InvestigationEvidenceRequest,
    ) -> InvestigationEvidenceRequest:
        budget_error: str | None = None
        with self.store.sessions.begin() as db:
            investigation = db.get(InvestigationRow, item.investigation_id)
            if investigation is None:
                raise InvestigationNotFound(item.investigation_id)
            if investigation.case_id != item.case_id:
                raise InvestigationConflict("evidence request belongs to another case")
            if investigation.authority_epoch != item.authority_epoch:
                raise InvestigationConflict("evidence request is stale")
            existing = db.execute(
                select(InvestigationEvidenceRequestRow).where(
                    InvestigationEvidenceRequestRow.investigation_id == item.investigation_id,
                    InvestigationEvidenceRequestRow.idempotency_key == item.idempotency_key,
                )
            ).scalar_one_or_none()
            if existing is not None:
                restored = self._evidence_request_from_row(existing)
                if restored != item:
                    raise InvestigationConflict(
                        "evidence request idempotency key was reused with different semantics"
                    )
                return restored
            self._assert_case_epoch(db, item.case_id, item.authority_epoch)
            constraints = InvestigationConstraints.model_validate(investigation.constraints_json)
            if investigation.evidence_requests_used >= constraints.max_evidence_requests:
                investigation.status = InvestigationStatus.REQUIRES_HUMAN_REVIEW.value
                investigation.updated_at = utcnow()
                budget_error = "investigation evidence-request budget exhausted"
            else:
                if item.source_kind not in constraints.allowed_source_kinds:
                    raise InvestigationConflict(
                        "evidence source kind is outside the investigation boundary"
                    )
                db.add(self._evidence_request_row(item))
                investigation.evidence_requests_used += 1
                investigation.status = InvestigationStatus.AWAITING_EVIDENCE.value
                investigation.updated_at = utcnow()
            db.flush()
            if budget_error is None:
                self.store._append_audit(
                    db,
                    item.case_id,
                    "investigation.evidence_requested",
                    {
                        "investigation_id": str(item.investigation_id),
                        "evidence_request_id": str(item.evidence_request_id),
                        "source_kind": item.source_kind,
                        "authority_epoch": item.authority_epoch,
                    },
                )
        if budget_error is not None:
            raise InvestigationBudgetExceeded(budget_error)
        return item

    def list_evidence_requests(self, investigation_id: UUID) -> list[InvestigationEvidenceRequest]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(InvestigationEvidenceRequestRow)
                    .where(InvestigationEvidenceRequestRow.investigation_id == investigation_id)
                    .order_by(
                        InvestigationEvidenceRequestRow.created_at,
                        InvestigationEvidenceRequestRow.evidence_request_id,
                    )
                )
                .scalars()
                .all()
            )
            return [self._evidence_request_from_row(row) for row in rows]

    def add_evidence(self, item: InvestigationEvidence) -> InvestigationEvidence:
        with self.store.sessions.begin() as db:
            investigation = db.get(InvestigationRow, item.investigation_id)
            if investigation is None:
                raise InvestigationNotFound(item.investigation_id)
            if investigation.case_id != item.case_id:
                raise InvestigationConflict("evidence belongs to another case")
            if investigation.authority_epoch != item.authority_epoch:
                raise InvestigationConflict("evidence is stale for the investigation epoch")
            existing = db.execute(
                select(InvestigationEvidenceRow).where(
                    InvestigationEvidenceRow.investigation_id == item.investigation_id,
                    InvestigationEvidenceRow.idempotency_key == item.idempotency_key,
                )
            ).scalar_one_or_none()
            if existing is not None:
                restored = self._evidence_from_row(existing)
                if restored != item:
                    raise InvestigationConflict(
                        "evidence idempotency key was reused with different semantics"
                    )
                return restored
            self._assert_case_epoch(db, item.case_id, item.authority_epoch)
            if item.evidence_request_id is not None:
                evidence_request = db.get(
                    InvestigationEvidenceRequestRow, item.evidence_request_id
                )
                if (
                    evidence_request is None
                    or evidence_request.investigation_id != item.investigation_id
                    or evidence_request.case_id != item.case_id
                    or evidence_request.authority_epoch != item.authority_epoch
                ):
                    raise InvestigationConflict("evidence request lineage is missing")
                if evidence_request.source_kind != item.source_kind:
                    raise InvestigationConflict("evidence source kind does not match the request")
                if (
                    evidence_request.allowed_evidence_refs_json
                    and item.evidence_ref not in evidence_request.allowed_evidence_refs_json
                ):
                    raise InvestigationConflict(
                        "evidence reference is outside the evidence request boundary"
                    )
                evidence_request.evidence_refs_json = [
                    *dict.fromkeys([*evidence_request.evidence_refs_json, item.evidence_ref])
                ]
                evidence_request.status = EvidenceRequestStatus.FULFILLED.value
                evidence_request.fulfilled_at = item.created_at
            db.add(self._evidence_row(item))
            investigation.status = InvestigationStatus.REQUIRES_HUMAN_REVIEW.value
            investigation.updated_at = utcnow()
            db.flush()
            self.store._append_audit(
                db,
                item.case_id,
                "investigation.evidence_added",
                {
                    "investigation_id": str(item.investigation_id),
                    "evidence_id": str(item.evidence_id),
                    "evidence_request_id": (
                        str(item.evidence_request_id) if item.evidence_request_id else None
                    ),
                    "source_kind": item.source_kind,
                    "source": item.source,
                    "authority_epoch": item.authority_epoch,
                },
            )
        return item

    def list_evidence(self, investigation_id: UUID) -> list[InvestigationEvidence]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(InvestigationEvidenceRow)
                    .where(InvestigationEvidenceRow.investigation_id == investigation_id)
                    .order_by(InvestigationEvidenceRow.created_at, InvestigationEvidenceRow.evidence_id)
                )
                .scalars()
                .all()
            )
            return [self._evidence_from_row(row) for row in rows]

    def record_assessment(self, assessment: ReopenAssessment) -> ReopenAssessment:
        digest = _assessment_digest(assessment)
        with self.store.sessions.begin() as db:
            investigation = db.get(InvestigationRow, assessment.investigation_id)
            if investigation is None:
                raise InvestigationNotFound(assessment.investigation_id)
            if investigation.case_id != assessment.case_id:
                raise InvestigationConflict("reopen assessment belongs to another case")
            if investigation.authority_epoch != assessment.authority_epoch:
                raise InvestigationConflict("reopen assessment is stale")
            existing = db.execute(
                select(ReopenAssessmentRow).where(
                    ReopenAssessmentRow.investigation_id == assessment.investigation_id,
                    ReopenAssessmentRow.idempotency_key == assessment.idempotency_key,
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.assessment_digest != digest:
                    raise InvestigationConflict(
                        "reopen assessment idempotency key was reused with different semantics"
                    )
                return self._assessment_from_row(existing)
            if assessment.assessment_kind is ReopenAssessmentKind.HUMAN and not assessment.assessed_by:
                raise InvestigationConflict("human assessment requires an authenticated principal")
            db.add(self._assessment_row(assessment, digest))
            if assessment.disposition is ReopenAssessmentDisposition.PRESERVE_CLOSURE:
                investigation.status = InvestigationStatus.CLOSURE_PRESERVED.value
            else:
                investigation.status = InvestigationStatus.REQUIRES_HUMAN_REVIEW.value
            investigation.updated_at = utcnow()
            db.flush()
            event_type = (
                "case.closure_preserved"
                if assessment.disposition is ReopenAssessmentDisposition.PRESERVE_CLOSURE
                else "case.reopen_assessed"
            )
            self.store._append_audit(
                db,
                assessment.case_id,
                event_type,
                {
                    "investigation_id": str(assessment.investigation_id),
                    "assessment_id": str(assessment.assessment_id),
                    "authority_epoch": assessment.authority_epoch,
                    "disposition": assessment.disposition.value,
                    "assessment_kind": assessment.assessment_kind.value,
                },
            )
        return assessment

    def get_assessment(self, assessment_id: UUID) -> ReopenAssessment | None:
        with self.store.sessions() as db:
            row = db.get(ReopenAssessmentRow, assessment_id)
            return None if row is None else self._assessment_from_row(row)

    def get_assessment_by_idempotency(
        self,
        investigation_id: UUID,
        idempotency_key: str,
    ) -> ReopenAssessment | None:
        with self.store.sessions() as db:
            row = db.execute(
                select(ReopenAssessmentRow).where(
                    ReopenAssessmentRow.investigation_id == investigation_id,
                    ReopenAssessmentRow.idempotency_key == idempotency_key,
                )
            ).scalar_one_or_none()
            return None if row is None else self._assessment_from_row(row)

    def list_assessments(self, case_id: UUID) -> list[ReopenAssessment]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(ReopenAssessmentRow)
                    .where(ReopenAssessmentRow.case_id == case_id)
                    .order_by(ReopenAssessmentRow.created_at, ReopenAssessmentRow.assessment_id)
                )
                .scalars()
                .all()
            )
            return [self._assessment_from_row(row) for row in rows]

    def apply_reopen(
        self,
        case: AdministrativeCase,
        assessment: ReopenAssessment,
        *,
        reopen_reason: ReopenReason,
        evidence_refs: tuple[str, ...],
        idempotency_key: str,
        reopen_id: UUID,
        authorized_by: str,
    ) -> tuple[ReopenRecord, AdministrativeCase, bool]:
        if assessment.disposition is not ReopenAssessmentDisposition.REOPEN_REQUIRED:
            raise InvestigationConflict("only a REOPEN_REQUIRED assessment may authorize reopen")
        if assessment.case_id != case.case_id or assessment.authority_epoch != case.authority_epoch:
            raise InvestigationConflict("reopen assessment is stale for the current case")
        with self.store.sessions.begin() as db:
            existing = db.execute(
                select(ReopenRecordRow).where(
                    ReopenRecordRow.case_id == case.case_id,
                    ReopenRecordRow.idempotency_key == idempotency_key,
                )
            ).scalar_one_or_none()
            if existing is None:
                existing = db.execute(
                    select(ReopenRecordRow).where(
                        ReopenRecordRow.assessment_ref == assessment.assessment_id
                    )
                ).scalar_one_or_none()
            if existing is not None:
                return self._record_from_row(existing), self.store.get_case(case.case_id) or case, False

            row = db.get(CaseRow, case.case_id)
            if row is None:
                raise InvestigationNotFound(case.case_id)
            if row.version != case.version or row.authority_epoch != case.authority_epoch:
                raise ConcurrencyConflict(
                    f"case {case.case_id} changed before authorized reopen"
                )
            assessment_row = db.get(ReopenAssessmentRow, assessment.assessment_id)
            if assessment_row is None:
                raise InvestigationConflict("reopen assessment is not persisted")

            invalidated_decisions = [
                str(item)
                for item in db.execute(
                    select(DecisionRow.decision_id).where(
                        DecisionRow.case_id == case.case_id,
                        DecisionRow.authority_epoch == case.authority_epoch,
                    )
                ).scalars()
            ]
            invalidated_authorizations = [
                str(item)
                for item in db.execute(
                    select(AuthorizationRow.authorization_id).where(
                        AuthorizationRow.case_id == case.case_id,
                        AuthorizationRow.authority_epoch == case.authority_epoch,
                    )
                ).scalars()
            ]
            governance_refs, obligation_refs, commitment_refs = self._current_lineage_refs(
                db, case
            )
            record = ReopenRecord(
                reopen_id=reopen_id,
                investigation_id=assessment.investigation_id,
                case_id=case.case_id,
                assessment_ref=assessment.assessment_id,
                previous_authority_epoch=case.authority_epoch,
                new_authority_epoch=case.authority_epoch + 1,
                reopen_reason=reopen_reason.value,
                evidence_refs=evidence_refs,
                authorized_by=authorized_by,
                invalidated_decision_refs=tuple(invalidated_decisions),
                invalidated_governance_basis_refs=governance_refs,
                affected_obligation_refs=obligation_refs,
                affected_execution_authorization_refs=tuple(invalidated_authorizations),
                affected_commitment_refs=commitment_refs,
                idempotency_key=idempotency_key,
            )
            db.add(self._record_row(record))
            row.status = CaseStatus.GATHERING_FACTS.value
            row.reopen_reason = None
            row.version += 1
            row.authority_epoch = record.new_authority_epoch
            row.updated_at = record.created_at
            investigation = db.get(InvestigationRow, assessment.investigation_id)
            if investigation is None:
                raise InvestigationNotFound(assessment.investigation_id)
            investigation.status = InvestigationStatus.REOPENED.value
            investigation.updated_at = record.created_at
            db.flush()
            self.store._append_audit(
                db,
                case.case_id,
                "governance.invalidated",
                {
                    "investigation_id": str(assessment.investigation_id),
                    "assessment_id": str(assessment.assessment_id),
                    "previous_authority_epoch": record.previous_authority_epoch,
                    "new_authority_epoch": record.new_authority_epoch,
                    "governance_basis_refs": list(record.invalidated_governance_basis_refs),
                },
            )
            self.store._append_audit(
                db,
                case.case_id,
                "authority.epoch_advanced",
                {
                    "investigation_id": str(assessment.investigation_id),
                    "reopen_id": str(record.reopen_id),
                    "previous_authority_epoch": record.previous_authority_epoch,
                    "new_authority_epoch": record.new_authority_epoch,
                },
            )
            if obligation_refs:
                self.store._append_audit(
                    db,
                    case.case_id,
                    "obligation.revalidation_required",
                    {
                        "reopen_id": str(record.reopen_id),
                        "obligation_count": len(obligation_refs),
                    },
                )
            if commitment_refs:
                self.store._append_audit(
                    db,
                    case.case_id,
                    "commitment.revalidation_required",
                    {
                        "reopen_id": str(record.reopen_id),
                        "commitment_count": len(commitment_refs),
                    },
                )
            self.store._append_audit(
                db,
                case.case_id,
                "case.reopened",
                {
                    "investigation_id": str(assessment.investigation_id),
                    "reopen_id": str(record.reopen_id),
                    "authorized_by": authorized_by,
                    "new_authority_epoch": record.new_authority_epoch,
                    "status": row.status,
                },
            )
            return record, self.store._case_from_row(row), True

    def list_reopen_records(self, case_id: UUID) -> list[ReopenRecord]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(ReopenRecordRow)
                    .where(ReopenRecordRow.case_id == case_id)
                    .order_by(ReopenRecordRow.created_at, ReopenRecordRow.reopen_id)
                )
                .scalars()
                .all()
            )
            return [self._record_from_row(row) for row in rows]

    def get_reopen_record(
        self,
        case_id: UUID,
        idempotency_key: str,
    ) -> ReopenRecord | None:
        with self.store.sessions() as db:
            row = db.execute(
                select(ReopenRecordRow).where(
                    ReopenRecordRow.case_id == case_id,
                    ReopenRecordRow.idempotency_key == idempotency_key,
                )
            ).scalar_one_or_none()
            return None if row is None else self._record_from_row(row)

    @staticmethod
    def _current_lineage_refs(db, case: AdministrativeCase) -> tuple[tuple[str, ...], ...]:
        from .commitment_repository import CommitmentRow
        from .governance import GovernanceBasisRow
        from .obligations import ObligationRow, ObligationSetRow

        governance_refs = tuple(
            str(item)
            for item in db.execute(
                select(GovernanceBasisRow.basis_id).where(
                    GovernanceBasisRow.case_id == case.case_id,
                    GovernanceBasisRow.authority_epoch == case.authority_epoch,
                )
            ).scalars()
        )
        obligation_refs = tuple(
            str(item)
            for item in db.execute(
                select(ObligationRow.obligation_id).where(
                    ObligationRow.case_id == case.case_id,
                    ObligationRow.authority_epoch == case.authority_epoch,
                )
            ).scalars()
        )
        set_refs = tuple(
            str(item)
            for item in db.execute(
                select(ObligationSetRow.requirement_id).where(
                    ObligationSetRow.case_id == case.case_id,
                    ObligationSetRow.authority_epoch == case.authority_epoch,
                )
            ).scalars()
        )
        commitment_refs = tuple(
            str(item)
            for item in db.execute(
                select(CommitmentRow.commitment_id).where(
                    CommitmentRow.case_id == case.case_id,
                    CommitmentRow.authority_epoch == case.authority_epoch,
                )
            ).scalars()
        )
        return governance_refs, (*set_refs, *obligation_refs), commitment_refs

    @staticmethod
    def _assert_case_epoch(db, case_id: UUID, authority_epoch: int) -> None:
        row = db.get(CaseRow, case_id)
        if row is None:
            raise InvestigationNotFound(case_id)
        if row.authority_epoch != authority_epoch:
            raise InvestigationConflict(
                "investigation mutation is stale for the current case authority epoch"
            )

    _request_row = staticmethod(_request_row)
    _request_from_row = staticmethod(_request_from_row)
    _proposal_row = staticmethod(_proposal_row)
    _proposal_from_row = staticmethod(_proposal_from_row)
    _evidence_request_row = staticmethod(_evidence_request_row)
    _evidence_request_from_row = staticmethod(_evidence_request_from_row)
    _evidence_row = staticmethod(_evidence_row)
    _evidence_from_row = staticmethod(_evidence_from_row)
    _assessment_row = staticmethod(_assessment_row)
    _assessment_from_row = staticmethod(_assessment_from_row)
    _record_row = staticmethod(_record_row)
    _record_from_row = staticmethod(_record_from_row)


__all__ = [
    "InvestigationBudgetExceeded",
    "InvestigationConflict",
    "InvestigationEvidenceRow",
    "InvestigationEvidenceRequestRow",
    "InvestigationNotFound",
    "InvestigationProposalRow",
    "InvestigationRepository",
    "InvestigationRow",
    "ReframingProposalRow",
    "ReopenAssessmentRow",
    "ReopenRecordRow",
]
