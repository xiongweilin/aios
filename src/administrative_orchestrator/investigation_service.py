from __future__ import annotations

import time
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import structlog
from sqlalchemy.exc import OperationalError

from .commitment_repository import CommitmentRepository
from .domain import AdministrativeCase, CaseStatus, ReopenReason, utcnow
from .governance import GovernanceRepository
from .investigation_client import (
    InvestigationClient,
    InvestigationClientError,
    InvestigationRequestEnvelope,
    UnavailableInvestigationClient,
)
from .investigation_models import (
    InvestigationConstraints,
    InvestigationEvidence,
    InvestigationEvidenceRequest,
    InvestigationProposal,
    InvestigationRequest,
    InvestigationStatus,
    InvestigationTrigger,
    InvestigationTriggerType,
    ReopenAssessment,
    ReopenAssessmentDisposition,
    ReopenAssessmentKind,
    ReopenRecord,
)
from .investigation_reconciliation import (
    UnavailableWorldRuntimeReconciliationVerifier,
    WorldRuntimeReconciliationVerificationError,
    WorldRuntimeReconciliationVerifier,
)
from .investigation_repository import (
    InvestigationBudgetExceeded,
    InvestigationConflict,
    InvestigationNotFound,
    InvestigationRepository,
)
from .obligations import ObligationRepository
from .observability import (
    current_correlation_id,
    observe_investigation_duration,
    record_investigation_failure,
    record_investigation_request,
    record_reopen,
    record_reopen_assessment,
)
from .persistence import SqlStore

_REOPEN_REASON_BY_TRIGGER = {
    InvestigationTriggerType.AMBIGUOUS_EVIDENCE: ReopenReason.MISSING_REQUIRED_FACT,
    InvestigationTriggerType.CONFLICTING_FACTS: ReopenReason.POLICY_CONFLICT,
    InvestigationTriggerType.MISSING_QUALIFICATION: ReopenReason.MISSING_REQUIRED_FACT,
    InvestigationTriggerType.MISSING_AUTHORITY: ReopenReason.AUTHORITY_UNRESOLVED,
    InvestigationTriggerType.POLICY_UNDERSPECIFIED: ReopenReason.NO_APPLICABLE_POLICY,
    InvestigationTriggerType.UNEXPECTED_REALITY_STATE: ReopenReason.REALITY_MISMATCH,
    InvestigationTriggerType.OUTCOME_UNKNOWN: ReopenReason.OUTCOME_UNKNOWN,
    InvestigationTriggerType.VERIFICATION_CONTRADICTION: ReopenReason.REALITY_MISMATCH,
    InvestigationTriggerType.OBLIGATION_STALLED: ReopenReason.OBLIGATION_STALLED,
    InvestigationTriggerType.COMMITMENT_CONFLICT: ReopenReason.COMMITMENT_CONFLICT,
    InvestigationTriggerType.LATE_EVIDENCE: ReopenReason.LATE_EVIDENCE,
    InvestigationTriggerType.HUMAN_REQUESTED_REVIEW: ReopenReason.HUMAN_REQUESTED_REVIEW,
}


class InvestigationService:
    def __init__(
        self,
        store: SqlStore,
        *,
        repository: InvestigationRepository | None = None,
        client: InvestigationClient | None = None,
        reconciliation_verifier: WorldRuntimeReconciliationVerifier | None = None,
    ) -> None:
        self.store = store
        self.repository = repository or InvestigationRepository(store)
        self.client = client or UnavailableInvestigationClient()
        self.reconciliation_verifier = (
            reconciliation_verifier or UnavailableWorldRuntimeReconciliationVerifier()
        )
        self.governance = GovernanceRepository(store)
        self.obligations = ObligationRepository(store)
        self.commitments = CommitmentRepository(store)

    def request_investigation(
        self,
        case_id: UUID,
        *,
        trigger_type: InvestigationTriggerType,
        reason: str,
        requested_question: str,
        created_by: str,
        idempotency_key: str,
        evidence_refs: tuple[str, ...] = (),
        allowed_evidence_refs: tuple[str, ...] = (),
        constraints: InvestigationConstraints | None = None,
        source_type: str = "administrative",
        reconciliation_ref: str | None = None,
    ) -> InvestigationRequest:
        case = self._case(case_id)
        trigger = InvestigationTrigger(
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            trigger_type=trigger_type,
            reason=reason,
            evidence_refs=evidence_refs,
            source_type=source_type,
            reconciliation_ref=reconciliation_ref,
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
        InvestigationPolicyBoundary.validate_trigger(trigger)
        if trigger.trigger_type is InvestigationTriggerType.OUTCOME_UNKNOWN:
            try:
                self.reconciliation_verifier.verify(
                    case.case_id,
                    case.authority_epoch,
                    trigger.reconciliation_ref or "",
                )
            except WorldRuntimeReconciliationVerificationError as exc:
                raise InvestigationConflict(str(exc)) from exc
        current_governance = self.governance.get_current_for_case(
            case.case_id, case.authority_epoch
        )
        obligation_refs: tuple[str, ...] = ()
        try:
            obligation_set = self.obligations.get_current(case.case_id, case.authority_epoch)
            if obligation_set is not None:
                obligation_refs = tuple(str(item.obligation_id) for item in obligation_set.obligations)
        except OperationalError:
            # Missing historical/optional obligation tables must not prevent a
            # read-only investigation request from being recorded.
            obligation_refs = ()
        commitment = self.commitments.get_commitment(case.case_id)
        commitment_refs = (str(commitment.commitment_id),) if commitment is not None else ()
        tenant_id = "*"
        if case.fact_snapshot is not None:
            candidate_tenant = case.fact_snapshot.facts.get("tenant_ref")
            if isinstance(candidate_tenant, str) and candidate_tenant.strip():
                tenant_id = candidate_tenant.strip()
        request = InvestigationRequest(
            tenant_id=tenant_id,
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            trigger=trigger,
            requested_question=requested_question,
            allowed_evidence_refs=allowed_evidence_refs,
            current_fact_snapshot_ref=(
                str(case.fact_snapshot.snapshot_id) if case.fact_snapshot is not None else None
            ),
            current_governance_basis_ref=(
                str(current_governance.basis_id) if current_governance is not None else None
            ),
            current_obligation_refs=obligation_refs,
            current_commitment_refs=commitment_refs,
            constraints=constraints or InvestigationConstraints(),
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
        result = self.repository.create_request(trigger, request)
        record_investigation_request(trigger_type=trigger_type.value, result="requested")
        self._log(
            "investigation_requested",
            case=case,
            investigation=result,
            trigger_type=trigger_type.value,
        )
        return result

    def run(self, investigation_id: UUID) -> InvestigationProposal:
        request = self.repository.get_request(investigation_id)
        if request is None:
            raise InvestigationNotFound(investigation_id)
        self._ensure_not_expired(request)
        self._ensure_current_epoch(request)
        existing = self.repository.list_proposals(investigation_id)
        if existing and request.status is not InvestigationStatus.REQUESTED:
            return existing[-1]
        started = time.perf_counter()
        self.repository.mark_running(investigation_id)
        envelope = self._envelope(request)
        try:
            proposal = self.client.investigate(envelope)
            if (
                proposal.investigation_id != request.investigation_id
                or proposal.case_id != request.case_id
                or proposal.authority_epoch != request.authority_epoch
            ):
                raise InvestigationClientError("advisory proposal lineage is stale or mismatched")
            InvestigationPolicyBoundary.validate_proposal(request, proposal)
            recorded = self.repository.record_proposal(proposal)
            record_investigation_request(
                trigger_type=request.trigger.trigger_type.value,
                result="proposal_recorded",
            )
            return recorded
        except (InvestigationClientError, InvestigationConflict, InvestigationBudgetExceeded) as exc:
            record_investigation_failure(trigger_type=request.trigger.trigger_type.value)
            self.repository.mark_failed(investigation_id, error_code=type(exc).__name__)
            raise
        finally:
            observe_investigation_duration(
                trigger_type=request.trigger.trigger_type.value,
                seconds=time.perf_counter() - started,
            )

    def record_proposal(self, proposal: InvestigationProposal) -> InvestigationProposal:
        request = self.repository.get_request(proposal.investigation_id)
        if request is None:
            raise InvestigationNotFound(proposal.investigation_id)
        self._ensure_not_expired(request)
        self._ensure_current_epoch(request)
        InvestigationPolicyBoundary.validate_proposal(request, proposal)
        return self.repository.record_proposal(proposal)

    def request_evidence(
        self,
        investigation_id: UUID,
        *,
        source_kind: str,
        requested_question: str,
        requested_by: str,
        idempotency_key: str,
        allowed_evidence_refs: tuple[str, ...] = (),
    ) -> InvestigationEvidenceRequest:
        request = self._request(investigation_id)
        item = InvestigationEvidenceRequest(
            investigation_id=request.investigation_id,
            case_id=request.case_id,
            authority_epoch=request.authority_epoch,
            source_kind=source_kind,
            requested_question=requested_question,
            allowed_evidence_refs=allowed_evidence_refs,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
        )
        self._ensure_current_epoch(request)
        return self.repository.create_evidence_request(item)

    def add_evidence(
        self,
        investigation_id: UUID,
        *,
        evidence_request_id: UUID | None,
        evidence_ref: str,
        source_kind: str,
        source: str,
        owner: str,
        source_ref: str | None,
        source_version: str | None,
        digest: str | None,
        added_by: str,
        idempotency_key: str,
    ) -> InvestigationEvidence:
        request = self._request(investigation_id)
        self._ensure_current_epoch(request)
        if source_kind not in request.constraints.allowed_source_kinds:
            raise InvestigationConflict("evidence source kind is outside the investigation boundary")
        if request.allowed_evidence_refs and evidence_ref not in request.allowed_evidence_refs:
            raise InvestigationConflict("evidence reference is outside the investigation boundary")
        item = InvestigationEvidence(
            investigation_id=request.investigation_id,
            case_id=request.case_id,
            authority_epoch=request.authority_epoch,
            evidence_request_id=evidence_request_id,
            evidence_ref=evidence_ref,
            source_kind=source_kind,
            source=source,
            owner=owner,
            source_ref=source_ref,
            source_version=source_version,
            digest=digest,
            added_by=added_by,
            idempotency_key=idempotency_key,
        )
        return self.repository.add_evidence(item)

    def assess_reopen(
        self,
        investigation_id: UUID,
        *,
        disposition: ReopenAssessmentDisposition,
        reason: str,
        evidence_refs: tuple[str, ...],
        proposal_ref: UUID | None,
        assessment_kind: ReopenAssessmentKind,
        assessed_by: str,
        idempotency_key: str,
    ) -> ReopenAssessment:
        request = self.repository.get_request(investigation_id)
        if request is None:
            raise InvestigationNotFound(investigation_id)
        proposal = None
        if proposal_ref is not None:
            proposal = self.repository.get_proposal(proposal_ref)
            if (
                proposal is None
                or proposal.investigation_id != request.investigation_id
                or proposal.case_id != request.case_id
                or proposal.authority_epoch != request.authority_epoch
            ):
                raise InvestigationConflict("reopen assessment proposal reference is invalid")
        known_evidence_refs = set(request.trigger.evidence_refs)
        known_evidence_refs.update(item.evidence_ref for item in self.repository.list_evidence(investigation_id))
        if any(item not in known_evidence_refs for item in evidence_refs):
            raise InvestigationConflict("reopen assessment references unknown evidence")
        if self.repository.get_assessment_by_idempotency(investigation_id, idempotency_key) is None:
            self._request(investigation_id)
            self._ensure_current_epoch(request)
        assessment = ReopenAssessment(
            investigation_id=request.investigation_id,
            case_id=request.case_id,
            authority_epoch=request.authority_epoch,
            disposition=disposition,
            reason=reason,
            evidence_refs=evidence_refs,
            proposal_ref=proposal_ref,
            assessment_kind=assessment_kind,
            assessed_by=assessed_by,
            idempotency_key=idempotency_key,
        )
        result = self.repository.record_assessment(assessment)
        record_reopen_assessment(disposition=disposition.value)
        return result

    def authorize_reopen(
        self,
        case_id: UUID,
        *,
        assessment_id: UUID,
        authorized_by: str,
        idempotency_key: str,
    ) -> tuple[ReopenRecord, AdministrativeCase, bool]:
        case = self._case(case_id)
        assessment = self.repository.get_assessment(assessment_id)
        if assessment is None or assessment.case_id != case_id:
            raise InvestigationConflict("reopen assessment not found for case")
        existing_record = self.repository.get_reopen_record(case_id, idempotency_key)
        if existing_record is not None:
            if (
                existing_record.assessment_ref != assessment_id
                or existing_record.investigation_id != assessment.investigation_id
                or existing_record.authorized_by != authorized_by
            ):
                raise InvestigationConflict(
                    "reopen authorization idempotency key was reused with different semantics"
                )
            return existing_record, case, False
        if assessment.authority_epoch != case.authority_epoch:
            raise InvestigationConflict("reopen assessment is stale for the current case")
        if case.status is CaseStatus.CANCELLED:
            raise InvestigationConflict("cancelled case cannot be reopened by this path")
        reason = self._reopen_reason(assessment.investigation_id)
        record, updated, created = self.repository.apply_reopen(
            case,
            assessment,
            reopen_reason=reason,
            evidence_refs=assessment.evidence_refs,
            idempotency_key=idempotency_key,
            reopen_id=uuid5(NAMESPACE_URL, f"administrative-reopen:{case_id}:{idempotency_key}"),
            authorized_by=authorized_by,
        )
        if created:
            record_reopen()
        return record, updated, created

    def detail(self, investigation_id: UUID) -> dict[str, Any]:
        request = self.repository.get_request(investigation_id)
        if request is None:
            raise InvestigationNotFound(investigation_id)
        return {
            "request": request.model_dump(mode="json"),
            "proposals": [
                item.model_dump(mode="json")
                for item in self.repository.list_proposals(investigation_id)
            ],
            "evidence_requests": [
                item.model_dump(mode="json")
                for item in self.repository.list_evidence_requests(investigation_id)
            ],
            "evidence": [
                item.model_dump(mode="json")
                for item in self.repository.list_evidence(investigation_id)
            ],
            "reopen_assessments": [
                item.model_dump(mode="json")
                for item in self.repository.list_assessments(request.case_id)
                if item.investigation_id == investigation_id
            ],
        }

    def _request(self, investigation_id: UUID) -> InvestigationRequest:
        request = self.repository.get_request(investigation_id)
        if request is None:
            raise InvestigationNotFound(investigation_id)
        self._ensure_not_expired(request)
        if request.status in {
            InvestigationStatus.CLOSURE_PRESERVED,
            InvestigationStatus.REOPENED,
            InvestigationStatus.EXPIRED,
        }:
            raise InvestigationConflict("investigation is no longer accepting new inputs")
        return request

    def _ensure_not_expired(self, request: InvestigationRequest) -> None:
        if request.constraints.deadline is None or request.constraints.deadline > utcnow():
            return
        self.repository.mark_expired(request.investigation_id, reason="deadline_expired")
        raise InvestigationConflict("investigation deadline has expired")

    def _case(self, case_id: UUID) -> AdministrativeCase:
        case = self.store.get_case(case_id)
        if case is None:
            raise InvestigationNotFound(case_id)
        return case

    def _ensure_current_epoch(self, request: InvestigationRequest) -> AdministrativeCase:
        case = self._case(request.case_id)
        if case.authority_epoch != request.authority_epoch:
            self.repository.mark_expired(
                request.investigation_id,
                reason="authority_epoch_advanced",
            )
            raise InvestigationConflict(
                "investigation authority_epoch is stale for the current case"
            )
        return case

    def _envelope(self, request: InvestigationRequest) -> InvestigationRequestEnvelope:
        case = self._case(request.case_id)
        return InvestigationRequestEnvelope(
            investigation_id=request.investigation_id,
            case_id=request.case_id,
            tenant_id=request.tenant_id,
            case_kind=case.case_kind,
            case_status=case.status.value,
            authority_epoch=request.authority_epoch,
            trigger_type=request.trigger.trigger_type,
            requested_question=request.requested_question,
            allowed_evidence_refs=request.allowed_evidence_refs,
            current_fact_snapshot_ref=request.current_fact_snapshot_ref,
            current_governance_basis_ref=request.current_governance_basis_ref,
            current_obligation_refs=request.current_obligation_refs,
            current_commitment_refs=request.current_commitment_refs,
            constraints=request.constraints,
        )

    def _reopen_reason(self, investigation_id: UUID) -> ReopenReason:
        request = self._request(investigation_id)
        return _REOPEN_REASON_BY_TRIGGER[request.trigger.trigger_type]

    @staticmethod
    def _log(event: str, *, case: AdministrativeCase, investigation: InvestigationRequest, **fields: Any) -> None:
        structlog.get_logger("administrative.investigation").info(
            event,
            correlation_id=current_correlation_id(),
            case=str(case.case_id),
            investigation=str(investigation.investigation_id),
            authority_epoch=investigation.authority_epoch,
            **fields,
        )


class InvestigationPolicyBoundary:
    """Administrative qualification boundary around the advisory contract."""

    @staticmethod
    def validate_trigger(trigger: InvestigationTrigger) -> None:
        if trigger.trigger_type is InvestigationTriggerType.OUTCOME_UNKNOWN and not (
            trigger.reconciliation_ref or ""
        ).strip():
            raise InvestigationConflict(
                "outcome_unknown investigation requires Kernel reconciliation first"
            )

    @staticmethod
    def validate_proposal(
        request: InvestigationRequest,
        proposal: InvestigationProposal,
    ) -> None:
        if request.case_id != proposal.case_id or request.authority_epoch != proposal.authority_epoch:
            raise InvestigationConflict("proposal is stale for the current investigation")
        if proposal.investigation_id != request.investigation_id:
            raise InvestigationConflict("proposal belongs to another investigation")
        if any(item.effect_class != "read-only" for item in proposal.recommended_queries):
            raise InvestigationConflict("investigation proposal contains an effectful query")


__all__ = [
    "InvestigationService",
    "InvestigationPolicyBoundary",
    "InvestigationBudgetExceeded",
    "InvestigationClientError",
    "InvestigationConflict",
    "InvestigationNotFound",
    "WorldRuntimeReconciliationVerificationError",
]
