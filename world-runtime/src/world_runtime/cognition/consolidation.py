from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConsolidationStatus(StrEnum):
    REJECTED = "rejected"
    CANDIDATE = "candidate"
    SCOPED_CONDITIONAL = "scoped-conditional"


@dataclass(frozen=True, slots=True)
class ExperienceCandidate:
    summary: str
    scope: str
    evidence_refs: tuple[str, ...]
    policy_effects: tuple[str, ...]
    reopen_conditions: tuple[str, ...] = ()
    repeated_validation_count: int = 1


@dataclass(frozen=True, slots=True)
class ConsolidationAssessment:
    status: ConsolidationStatus
    reason: str


class ExperienceConsolidator:
    """Minimal gate extracted from ratio's durable-experience discipline.

    It never promotes an episode directly to a universal policy, truth or authority.
    """

    def assess(self, candidate: ExperienceCandidate) -> ConsolidationAssessment:
        if not candidate.summary.strip() or not candidate.scope.strip():
            return ConsolidationAssessment(
                ConsolidationStatus.REJECTED,
                "durable experience requires an explicit summary and bounded scope",
            )
        if not candidate.evidence_refs or any(not ref.strip() for ref in candidate.evidence_refs):
            return ConsolidationAssessment(
                ConsolidationStatus.REJECTED,
                "durable experience requires fresh reality evidence references",
            )
        if not candidate.policy_effects:
            return ConsolidationAssessment(
                ConsolidationStatus.REJECTED,
                "retain only experience that changes future distinction, action, verification "
                "or stopping",
            )
        if candidate.repeated_validation_count < 1:
            return ConsolidationAssessment(
                ConsolidationStatus.REJECTED,
                "validation count cannot be less than one",
            )
        distinct_evidence_count = len(set(candidate.evidence_refs))
        if candidate.repeated_validation_count > distinct_evidence_count:
            return ConsolidationAssessment(
                ConsolidationStatus.REJECTED,
                "validation count cannot exceed distinct supporting evidence references",
            )
        if candidate.repeated_validation_count == 1:
            return ConsolidationAssessment(
                ConsolidationStatus.SCOPED_CONDITIONAL,
                "one verified episode is admissible only as scoped conditional experience",
            )
        return ConsolidationAssessment(
            ConsolidationStatus.CANDIDATE,
            "repeated validation supports a policy-rule candidate; promotion remains a "
            "separate decision",
        )
