from __future__ import annotations

import hashlib
import json
from typing import Any

from .investigation_models import (
    InvestigationEvidence,
    InvestigationEvidenceRequest,
    InvestigationProposal,
    InvestigationRequest,
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
from .persistence_mapping import model_from_row, model_values


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
            mode="json", exclude={"proposal_id", "created_at", "idempotency_key"}
        )
    )


def assessment_digest(assessment: ReopenAssessment) -> str:
    return digest(
        assessment.model_dump(
            mode="json", exclude={"assessment_id", "created_at", "idempotency_key"}
        )
    )


def request_row(item: InvestigationRequest, item_digest: str) -> InvestigationRow:
    json_fields = {
        "trigger",
        "allowed_evidence_refs",
        "current_obligation_refs",
        "current_commitment_refs",
        "constraints",
    }
    return InvestigationRow(
        **model_values(
            item,
            rename={name: f"{name}_json" for name in json_fields},
            json_fields=json_fields,
            extra={"trigger_type": item.trigger.trigger_type.value, "request_digest": item_digest},
        )
    )


def request_from_row(row: InvestigationRow) -> InvestigationRequest:
    names = (
        "trigger",
        "allowed_evidence_refs",
        "current_obligation_refs",
        "current_commitment_refs",
        "constraints",
    )
    return model_from_row(
        InvestigationRequest,
        row,
        rename={f"{name}_json": name for name in names},
    )


def proposal_row(item: InvestigationProposal, item_digest: str) -> InvestigationProposalRow:
    json_fields = {
        "hypotheses",
        "ambiguities",
        "missing_evidence",
        "recommended_queries",
        "recommended_human_questions",
        "possible_reframings",
        "possible_reopen_targets",
        "uncertainty",
        "model_provenance",
    }
    return InvestigationProposalRow(
        **model_values(
            item,
            rename={name: f"{name}_json" for name in json_fields},
            json_fields=json_fields,
            extra={"proposal_digest": item_digest},
        )
    )


def proposal_from_row(row: InvestigationProposalRow) -> InvestigationProposal:
    names = (
        "hypotheses",
        "ambiguities",
        "missing_evidence",
        "recommended_queries",
        "recommended_human_questions",
        "possible_reframings",
        "possible_reopen_targets",
        "uncertainty",
        "model_provenance",
    )
    return model_from_row(
        InvestigationProposal,
        row,
        rename={f"{name}_json": name for name in names},
    )


def evidence_request_row(item: InvestigationEvidenceRequest) -> InvestigationEvidenceRequestRow:
    fields = {"allowed_evidence_refs", "evidence_refs"}
    return InvestigationEvidenceRequestRow(
        **model_values(
            item,
            rename={name: f"{name}_json" for name in fields},
            json_fields=fields,
        )
    )


def evidence_request_from_row(row: InvestigationEvidenceRequestRow) -> InvestigationEvidenceRequest:
    return model_from_row(
        InvestigationEvidenceRequest,
        row,
        rename={
            "allowed_evidence_refs_json": "allowed_evidence_refs",
            "evidence_refs_json": "evidence_refs",
        },
    )


def evidence_row(item: InvestigationEvidence) -> InvestigationEvidenceRow:
    return InvestigationEvidenceRow(**model_values(item))


def evidence_from_row(row: InvestigationEvidenceRow) -> InvestigationEvidence:
    return model_from_row(InvestigationEvidence, row)


def assessment_row(item: ReopenAssessment, item_digest: str) -> ReopenAssessmentRow:
    return ReopenAssessmentRow(
        **model_values(
            item,
            rename={"evidence_refs": "evidence_refs_json"},
            json_fields={"evidence_refs"},
            extra={"assessment_digest": item_digest},
        )
    )


def assessment_from_row(row: ReopenAssessmentRow) -> ReopenAssessment:
    return model_from_row(
        ReopenAssessment, row, rename={"evidence_refs_json": "evidence_refs"}
    )


def record_row(item: ReopenRecord) -> ReopenRecordRow:
    names = {
        "evidence_refs",
        "invalidated_decision_refs",
        "invalidated_governance_basis_refs",
        "affected_obligation_refs",
        "affected_execution_authorization_refs",
        "affected_commitment_refs",
    }
    return ReopenRecordRow(
        **model_values(
            item,
            rename={name: f"{name}_json" for name in names},
            json_fields=names,
        )
    )


def record_from_row(row: ReopenRecordRow) -> ReopenRecord:
    names = (
        "evidence_refs",
        "invalidated_decision_refs",
        "invalidated_governance_basis_refs",
        "affected_obligation_refs",
        "affected_execution_authorization_refs",
        "affected_commitment_refs",
    )
    return model_from_row(
        ReopenRecord,
        row,
        rename={f"{name}_json": name for name in names},
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
