from __future__ import annotations

from administrative_orchestrator import investigation_repository as repository_module
from administrative_orchestrator import investigation_serialization as serialization
from administrative_orchestrator.investigation_repository import InvestigationRepository
from administrative_orchestrator.investigation_rows import (
    InvestigationEvidenceRequestRow,
    InvestigationEvidenceRow,
    InvestigationProposalRow,
    InvestigationRow,
    ReframingProposalRow,
    ReopenAssessmentRow,
    ReopenRecordRow,
)


def test_investigation_rows_remain_reexported_from_repository() -> None:
    assert repository_module.InvestigationRow is InvestigationRow
    assert repository_module.InvestigationProposalRow is InvestigationProposalRow
    assert repository_module.ReframingProposalRow is ReframingProposalRow
    assert repository_module.InvestigationEvidenceRequestRow is InvestigationEvidenceRequestRow
    assert repository_module.InvestigationEvidenceRow is InvestigationEvidenceRow
    assert repository_module.ReopenAssessmentRow is ReopenAssessmentRow
    assert repository_module.ReopenRecordRow is ReopenRecordRow


def test_repository_keeps_private_serialization_seams_as_static_aliases() -> None:
    assert InvestigationRepository._request_row is serialization.request_row
    assert InvestigationRepository._request_from_row is serialization.request_from_row
    assert InvestigationRepository._proposal_row is serialization.proposal_row
    assert InvestigationRepository._proposal_from_row is serialization.proposal_from_row
    assert InvestigationRepository._evidence_request_row is serialization.evidence_request_row
    assert InvestigationRepository._evidence_request_from_row is serialization.evidence_request_from_row
    assert InvestigationRepository._evidence_row is serialization.evidence_row
    assert InvestigationRepository._evidence_from_row is serialization.evidence_from_row
    assert InvestigationRepository._assessment_row is serialization.assessment_row
    assert InvestigationRepository._assessment_from_row is serialization.assessment_from_row
    assert InvestigationRepository._record_row is serialization.record_row
    assert InvestigationRepository._record_from_row is serialization.record_from_row


def test_reopen_transaction_owner_remains_in_repository_class() -> None:
    assert InvestigationRepository.apply_reopen.__qualname__ == (
        "InvestigationRepository.apply_reopen"
    )
    assert InvestigationRepository.apply_reopen.__module__ == (
        "administrative_orchestrator.investigation_repository"
    )
