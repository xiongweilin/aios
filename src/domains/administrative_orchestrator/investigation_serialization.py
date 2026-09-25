from __future__ import annotations

import hashlib
import json
from typing import Any

from .investigation_models import (
    InvestigationConstraints,
    InvestigationEvidence,
    InvestigationEvidenceRequest,
    InvestigationHypothesis,
    InvestigationModelProvenance,
    InvestigationProposal,
    InvestigationQueryRecommendation,
    InvestigationRequest,
    InvestigationTrigger,
    ReframingProposal,
    ReopenAssessment,
    ReopenRecord,
)
from .investigation_rows import (
    InvestigationEvidenceRequestRow,
    InvestigationEvidenceRow,
    InvestigationProposalRow,
    InvestigationRow,
    ReopenAssessmentRow,
    ReopenRecordRow,
)


def digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def request_digest(request: InvestigationRequest) -> str:
    payload = request.model_dump(
        mode="json",
        exclude={
            "investigation_id",
            "created_at",
            "updated_at",
            "status",
            "rounds_used",
            "model_calls_used",
            "evidence_requests_used",
            "last_error_code",
        },
    )
    payload["trigger"].pop("trigger_id", None)
    payload["trigger"].pop("created_at", None)
    return digest(payload)


def proposal_digest(proposal: InvestigationProposal) -> str:
    return digest(
        proposal.model_dump(
            mode="json",
            exclude={"proposal_id", "created_at", "idempotency_key"},
        )
    )


def assessment_digest(assessment: ReopenAssessment) -> str:
    return digest(
        assessment.model_dump(
            mode="json",
            exclude={"assessment_id", "created_at", "idempotency_key"},
        )
    )


def request_row(item: InvestigationRequest, item_digest: str) -> InvestigationRow:
    return InvestigationRow(
        investigation_id=item.investigation_id,
        tenant_id=item.tenant_id,
        case_id=item.case_id,
        authority_epoch=item.authority_epoch,
        trigger_type=item.trigger.trigger_type.value,
        trigger_json=item.trigger.model_dump(mode="json"),
        requested_question=item.requested_question,
        allowed_evidence_refs_json=list(item.allowed_evidence_refs),
        current_fact_snapshot_ref=item.current_fact_snapshot_ref,
        current_governance_basis_ref=item.current_governance_basis_ref,
        current_obligation_refs_json=list(item.current_obligation_refs),
        current_commitment_refs_json=list(item.current_commitment_refs),
        constraints_json=item.constraints.model_dump(mode="json"),
        created_at=item.created_at,
        created_by=item.created_by,
        status=item.status.value,
        idempotency_key=item.idempotency_key,
        request_digest=item_digest,
        rounds_used=item.rounds_used,
        model_calls_used=item.model_calls_used,
        evidence_requests_used=item.evidence_requests_used,
        last_error_code=item.last_error_code,
        updated_at=item.updated_at,
    )


def request_from_row(row: InvestigationRow) -> InvestigationRequest:
    return InvestigationRequest(
        investigation_id=row.investigation_id,
        tenant_id=row.tenant_id,
        case_id=row.case_id,
        authority_epoch=row.authority_epoch,
        trigger=InvestigationTrigger.model_validate(row.trigger_json),
        requested_question=row.requested_question,
        allowed_evidence_refs=tuple(row.allowed_evidence_refs_json or ()),
        current_fact_snapshot_ref=row.current_fact_snapshot_ref,
        current_governance_basis_ref=row.current_governance_basis_ref,
        current_obligation_refs=tuple(row.current_obligation_refs_json or ()),
        current_commitment_refs=tuple(row.current_commitment_refs_json or ()),
        constraints=InvestigationConstraints.model_validate(row.constraints_json),
        created_at=row.created_at,
        created_by=row.created_by,
        status=row.status,
        idempotency_key=row.idempotency_key,
        rounds_used=row.rounds_used,
        model_calls_used=row.model_calls_used,
        evidence_requests_used=row.evidence_requests_used,
        last_error_code=row.last_error_code,
        updated_at=row.updated_at,
    )


def proposal_row(item: InvestigationProposal, item_digest: str) -> InvestigationProposalRow:
    return InvestigationProposalRow(
        proposal_id=item.proposal_id,
        investigation_id=item.investigation_id,
        case_id=item.case_id,
        authority_epoch=item.authority_epoch,
        representation_version=item.representation_version,
        hypotheses_json=[value.model_dump(mode="json") for value in item.hypotheses],
        ambiguities_json=list(item.ambiguities),
        missing_evidence_json=list(item.missing_evidence),
        recommended_queries_json=[
            value.model_dump(mode="json") for value in item.recommended_queries
        ],
        recommended_human_questions_json=list(item.recommended_human_questions),
        possible_reframings_json=[
            value.model_dump(mode="json") for value in item.possible_reframings
        ],
        possible_reopen_targets_json=list(item.possible_reopen_targets),
        uncertainty_json=dict(item.uncertainty),
        model_provenance_json=item.model_provenance.model_dump(mode="json"),
        created_at=item.created_at,
        idempotency_key=item.idempotency_key,
        proposal_digest=item_digest,
    )


def proposal_from_row(row: InvestigationProposalRow) -> InvestigationProposal:
    return InvestigationProposal(
        proposal_id=row.proposal_id,
        investigation_id=row.investigation_id,
        case_id=row.case_id,
        authority_epoch=row.authority_epoch,
        representation_version=row.representation_version,
        hypotheses=tuple(
            InvestigationHypothesis.model_validate(item) for item in row.hypotheses_json
        ),
        ambiguities=tuple(row.ambiguities_json or ()),
        missing_evidence=tuple(row.missing_evidence_json or ()),
        recommended_queries=tuple(
            InvestigationQueryRecommendation.model_validate(item)
            for item in row.recommended_queries_json
        ),
        recommended_human_questions=tuple(row.recommended_human_questions_json or ()),
        possible_reframings=tuple(
            ReframingProposal.model_validate(item) for item in row.possible_reframings_json
        ),
        possible_reopen_targets=tuple(row.possible_reopen_targets_json or ()),
        uncertainty=dict(row.uncertainty_json or {}),
        model_provenance=InvestigationModelProvenance.model_validate(
            row.model_provenance_json
        ),
        created_at=row.created_at,
        idempotency_key=row.idempotency_key,
    )


def evidence_request_row(item: InvestigationEvidenceRequest) -> InvestigationEvidenceRequestRow:
    return InvestigationEvidenceRequestRow(
        evidence_request_id=item.evidence_request_id,
        investigation_id=item.investigation_id,
        case_id=item.case_id,
        authority_epoch=item.authority_epoch,
        source_kind=item.source_kind,
        requested_question=item.requested_question,
        allowed_evidence_refs_json=list(item.allowed_evidence_refs),
        status=item.status.value,
        evidence_refs_json=list(item.evidence_refs),
        requested_by=item.requested_by,
        created_at=item.created_at,
        fulfilled_at=item.fulfilled_at,
        idempotency_key=item.idempotency_key,
    )


def evidence_request_from_row(row: InvestigationEvidenceRequestRow) -> InvestigationEvidenceRequest:
    return InvestigationEvidenceRequest(
        evidence_request_id=row.evidence_request_id,
        investigation_id=row.investigation_id,
        case_id=row.case_id,
        authority_epoch=row.authority_epoch,
        source_kind=row.source_kind,
        requested_question=row.requested_question,
        allowed_evidence_refs=tuple(row.allowed_evidence_refs_json or ()),
        status=row.status,
        evidence_refs=tuple(row.evidence_refs_json or ()),
        requested_by=row.requested_by,
        created_at=row.created_at,
        fulfilled_at=row.fulfilled_at,
        idempotency_key=row.idempotency_key,
    )


def evidence_row(item: InvestigationEvidence) -> InvestigationEvidenceRow:
    return InvestigationEvidenceRow(
        evidence_id=item.evidence_id,
        investigation_id=item.investigation_id,
        case_id=item.case_id,
        authority_epoch=item.authority_epoch,
        evidence_request_id=item.evidence_request_id,
        evidence_ref=item.evidence_ref,
        source_kind=item.source_kind,
        source=item.source,
        owner=item.owner,
        source_ref=item.source_ref,
        source_version=item.source_version,
        digest=item.digest,
        added_by=item.added_by,
        created_at=item.created_at,
        idempotency_key=item.idempotency_key,
    )


def evidence_from_row(row: InvestigationEvidenceRow) -> InvestigationEvidence:
    return InvestigationEvidence(
        evidence_id=row.evidence_id,
        investigation_id=row.investigation_id,
        case_id=row.case_id,
        authority_epoch=row.authority_epoch,
        evidence_request_id=row.evidence_request_id,
        evidence_ref=row.evidence_ref,
        source_kind=row.source_kind,
        source=row.source,
        owner=row.owner,
        source_ref=row.source_ref,
        source_version=row.source_version,
        digest=row.digest,
        added_by=row.added_by,
        created_at=row.created_at,
        idempotency_key=row.idempotency_key,
    )


def assessment_row(item: ReopenAssessment, item_digest: str) -> ReopenAssessmentRow:
    return ReopenAssessmentRow(
        assessment_id=item.assessment_id,
        investigation_id=item.investigation_id,
        case_id=item.case_id,
        authority_epoch=item.authority_epoch,
        disposition=item.disposition.value,
        reason=item.reason,
        evidence_refs_json=list(item.evidence_refs),
        proposal_ref=item.proposal_ref,
        assessment_kind=item.assessment_kind.value,
        assessed_by=item.assessed_by,
        created_at=item.created_at,
        idempotency_key=item.idempotency_key,
        assessment_digest=item_digest,
    )


def assessment_from_row(row: ReopenAssessmentRow) -> ReopenAssessment:
    return ReopenAssessment(
        assessment_id=row.assessment_id,
        investigation_id=row.investigation_id,
        case_id=row.case_id,
        authority_epoch=row.authority_epoch,
        disposition=row.disposition,
        reason=row.reason,
        evidence_refs=tuple(row.evidence_refs_json or ()),
        proposal_ref=row.proposal_ref,
        assessment_kind=row.assessment_kind,
        assessed_by=row.assessed_by,
        created_at=row.created_at,
        idempotency_key=row.idempotency_key,
    )


def record_row(item: ReopenRecord) -> ReopenRecordRow:
    return ReopenRecordRow(
        reopen_id=item.reopen_id,
        investigation_id=item.investigation_id,
        case_id=item.case_id,
        assessment_ref=item.assessment_ref,
        previous_authority_epoch=item.previous_authority_epoch,
        new_authority_epoch=item.new_authority_epoch,
        reopen_reason=item.reopen_reason,
        evidence_refs_json=list(item.evidence_refs),
        authorized_by=item.authorized_by,
        invalidated_decision_refs_json=list(item.invalidated_decision_refs),
        invalidated_governance_basis_refs_json=list(item.invalidated_governance_basis_refs),
        affected_obligation_refs_json=list(item.affected_obligation_refs),
        affected_execution_authorization_refs_json=list(
            item.affected_execution_authorization_refs
        ),
        affected_commitment_refs_json=list(item.affected_commitment_refs),
        created_at=item.created_at,
        idempotency_key=item.idempotency_key,
    )


def record_from_row(row: ReopenRecordRow) -> ReopenRecord:
    return ReopenRecord(
        reopen_id=row.reopen_id,
        investigation_id=row.investigation_id,
        case_id=row.case_id,
        assessment_ref=row.assessment_ref,
        previous_authority_epoch=row.previous_authority_epoch,
        new_authority_epoch=row.new_authority_epoch,
        reopen_reason=row.reopen_reason,
        evidence_refs=tuple(row.evidence_refs_json or ()),
        authorized_by=row.authorized_by,
        invalidated_decision_refs=tuple(row.invalidated_decision_refs_json or ()),
        invalidated_governance_basis_refs=tuple(
            row.invalidated_governance_basis_refs_json or ()
        ),
        affected_obligation_refs=tuple(row.affected_obligation_refs_json or ()),
        affected_execution_authorization_refs=tuple(
            row.affected_execution_authorization_refs_json or ()
        ),
        affected_commitment_refs=tuple(row.affected_commitment_refs_json or ()),
        created_at=row.created_at,
        idempotency_key=row.idempotency_key,
    )


__all__ = [
    "assessment_digest",
    "assessment_from_row",
    "assessment_row",
    "digest",
    "evidence_from_row",
    "evidence_request_from_row",
    "evidence_request_row",
    "evidence_row",
    "proposal_digest",
    "proposal_from_row",
    "proposal_row",
    "record_from_row",
    "record_row",
    "request_digest",
    "request_from_row",
    "request_row",
]
