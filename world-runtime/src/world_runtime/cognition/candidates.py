from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from .epistemic import EpistemicAssessment, StructuralTensionKind


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class CandidateKind(StrEnum):
    HYPOTHESIS = "hypothesis"
    ACQUISITION = "acquisition"
    REPRESENTATION = "representation"
    VERIFICATION = "verification"
    EXPERIMENT = "experiment"
    PROBLEM_REFRAME = "problem-reframe"


class CandidateStatus(StrEnum):
    GENERATED = "generated"
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    ADOPTED = "adopted"


@dataclass(frozen=True, slots=True)
class Candidate:
    kind: CandidateKind
    statement: str
    scope: str
    basis_refs: tuple[str, ...]
    discriminates_between: tuple[str, ...] = ()
    expected_observable_difference: str = ""
    required_capabilities: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    expected_discrimination: float = 0.0
    decision_relevance: float = 1.0
    estimated_cost: float = 0.0
    estimated_latency: float = 0.0
    effect_class: str = "read-only"
    redundancy_key: str | None = None
    status: CandidateStatus = CandidateStatus.GENERATED
    id: str = field(default_factory=lambda: _new_id("candidate"))

    def __post_init__(self) -> None:
        if not self.statement.strip() or not self.scope.strip() or not self.basis_refs:
            raise ValueError("candidate requires statement, bounded scope and basis_refs")
        if not 0.0 <= self.expected_discrimination <= 1.0:
            raise ValueError("expected_discrimination must be between zero and one")
        if not 0.0 <= self.decision_relevance <= 1.0:
            raise ValueError("decision_relevance must be between zero and one")
        if self.estimated_cost < 0 or self.estimated_latency < 0:
            raise ValueError("candidate cost and latency cannot be negative")
        if self.effect_class not in {"read-only", "internal-reversible", "external-effect"}:
            raise ValueError("invalid candidate effect_class")

    @property
    def discrimination_value(self) -> float:
        return self.expected_discrimination * self.decision_relevance


class CandidateQualificationStatus(StrEnum):
    QUALIFIED = "qualified"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CandidateQualification:
    candidate_ref: str
    status: CandidateQualificationStatus
    reason: str


class CandidateGenerator(Protocol):
    def generate(self, assessment: EpistemicAssessment) -> Sequence[Candidate]: ...


class CandidateQualifier:
    def qualify(
        self,
        candidate: Candidate,
        assessment: EpistemicAssessment,
    ) -> CandidateQualification:
        if not candidate.basis_refs:
            return CandidateQualification(
                candidate.id,
                CandidateQualificationStatus.REJECTED,
                "candidate has no explicit basis",
            )
        if candidate.kind in {CandidateKind.ACQUISITION, CandidateKind.EXPERIMENT}:
            if not candidate.expected_observable_difference.strip():
                return CandidateQualification(
                    candidate.id,
                    CandidateQualificationStatus.REJECTED,
                    "acquisition/experiment candidate lacks a discriminating observable",
                )
            if not candidate.required_capabilities:
                return CandidateQualification(
                    candidate.id,
                    CandidateQualificationStatus.REJECTED,
                    "acquisition/experiment candidate lacks a capability path",
                )
        if (
            candidate.kind not in {CandidateKind.REPRESENTATION, CandidateKind.PROBLEM_REFRAME}
            and not candidate.discriminates_between
            and candidate.expected_discrimination <= 0.0
        ):
            return CandidateQualification(
                candidate.id,
                CandidateQualificationStatus.REJECTED,
                "candidate does not create a decision-relevant distinction",
            )
        if candidate.scope != assessment.controller_ref:
            return CandidateQualification(
                candidate.id,
                CandidateQualificationStatus.REJECTED,
                "candidate scope does not match the current controller",
            )
        return CandidateQualification(
            candidate.id,
            CandidateQualificationStatus.QUALIFIED,
            "candidate preserves a bounded discriminating consequence",
        )


@dataclass(frozen=True, slots=True)
class CandidateFrontier:
    candidates: tuple[Candidate, ...]
    rejected: tuple[CandidateQualification, ...] = ()

    def get(self, candidate_ref: str) -> Candidate | None:
        return next(
            (candidate for candidate in self.candidates if candidate.id == candidate_ref),
            None,
        )


class FrontierBuilder:
    def __init__(self, qualifier: CandidateQualifier | None = None) -> None:
        self.qualifier = qualifier or CandidateQualifier()

    def build(
        self,
        assessment: EpistemicAssessment,
        candidates: Sequence[Candidate],
    ) -> CandidateFrontier:
        qualified: list[Candidate] = []
        rejected: list[CandidateQualification] = []
        for candidate in candidates:
            result = self.qualifier.qualify(candidate, assessment)
            if result.status is CandidateQualificationStatus.REJECTED:
                rejected.append(result)
                continue
            qualified.append(candidate)

        survivors: list[Candidate] = []
        for candidate in qualified:
            if any(
                self._dominates(other, candidate)
                for other in qualified
                if other.id != candidate.id
            ):
                rejected.append(
                    CandidateQualification(
                        candidate.id,
                        CandidateQualificationStatus.REJECTED,
                        "candidate is dominated by a no-worse alternative",
                    )
                )
                continue
            if any(self._same_candidate(existing, candidate) for existing in survivors):
                rejected.append(
                    CandidateQualification(
                        candidate.id,
                        CandidateQualificationStatus.REJECTED,
                        "candidate duplicates an existing frontier distinction",
                    )
                )
                continue
            survivors.append(candidate)

        survivors.sort(
            key=lambda candidate: (
                candidate.discrimination_value,
                -candidate.estimated_cost,
                -candidate.estimated_latency,
            ),
            reverse=True,
        )
        return CandidateFrontier(tuple(survivors), tuple(rejected))

    def _same_candidate(self, left: Candidate, right: Candidate) -> bool:
        if left.redundancy_key and right.redundancy_key:
            return left.redundancy_key == right.redundancy_key
        return (
            left.kind is right.kind
            and left.scope == right.scope
            and left.statement == right.statement
        )

    def _dominates(self, left: Candidate, right: Candidate) -> bool:
        if left.kind is not right.kind or left.scope != right.scope:
            return False
        if left.redundancy_key != right.redundancy_key:
            return False
        no_worse = (
            left.discrimination_value >= right.discrimination_value
            and left.estimated_cost <= right.estimated_cost
            and left.estimated_latency <= right.estimated_latency
        )
        strictly_better = (
            left.discrimination_value > right.discrimination_value
            or left.estimated_cost < right.estimated_cost
            or left.estimated_latency < right.estimated_latency
        )
        return no_worse and strictly_better


class ResidualDrivenGenerator:
    """Generate structural candidates from durable tension, not from mystery labels."""

    def generate(self, assessment: EpistemicAssessment) -> Sequence[Candidate]:
        generated: list[Candidate] = []
        for tension in assessment.tensions:
            if tension.kind in {
                StructuralTensionKind.REPRESENTATION_INSTABILITY,
                StructuralTensionKind.REPEATED_REOPEN,
                StructuralTensionKind.CONTRADICTORY_EVIDENCE,
            }:
                generated.append(
                    Candidate(
                        kind=CandidateKind.REPRESENTATION,
                        statement=(
                            "Revise the current representation before repeating the same pass."
                        ),
                        scope=assessment.controller_ref,
                        basis_refs=(tension.id, *tension.basis_refs),
                        expected_observable_difference=(
                            "A revised representation should produce a different partition of live "
                            "hypotheses or a new discriminating observation."
                        ),
                        expected_discrimination=min(1.0, 0.4 + 0.1 * tension.recurrence),
                        decision_relevance=tension.decision_relevance,
                        redundancy_key=f"representation:{tension.kind.value}",
                    )
                )
            elif tension.kind in {
                StructuralTensionKind.PERSISTENT_RESIDUAL,
                StructuralTensionKind.PROXY_TARGET_MISMATCH,
                StructuralTensionKind.UNEXPECTED_OUTCOME,
            }:
                generated.append(
                    Candidate(
                        kind=CandidateKind.PROBLEM_REFRAME,
                        statement=(
                            "Re-open the problem framing around the unresolved reality residual."
                        ),
                        scope=assessment.controller_ref,
                        basis_refs=(tension.id, *tension.basis_refs),
                        expected_observable_difference=(
                            "The reframed problem should expose a distinction not represented "
                            "by the "
                            "current closure."
                        ),
                        expected_discrimination=min(1.0, 0.35 + 0.1 * tension.persistence),
                        decision_relevance=tension.decision_relevance,
                        redundancy_key=f"reframe:{tension.kind.value}",
                    )
                )
        return generated
