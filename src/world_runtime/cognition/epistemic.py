from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from .models import EpistemicState


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class EpistemicIssueKind(StrEnum):
    MODEL_INTERNAL_UNKNOWN = "model-internal-unknown"
    ACQUISITION_GAP = "acquisition-gap"
    DISTINCTION_GAP = "distinction-gap"
    REPRESENTATION_MISMATCH = "representation-mismatch"
    CANDIDATE_SPACE_SUSPECTED_INCOMPLETE = "candidate-space-suspected-incomplete"
    IDENTIFIABILITY_GAP = "identifiability-gap"
    VERIFICATION_GAP = "verification-gap"
    GOAL_AMBIGUITY = "goal-ambiguity"
    SELF_MODEL_GAP = "self-model-gap"
    EFFECT_STATE_AMBIGUITY = "effect-state-ambiguity"
    AUTHORIZATION_GAP = "authorization-gap"
    PROBLEM_DEFINITION_GAP = "problem-definition-gap"


class EpistemicIssueStatus(StrEnum):
    OPEN = "open"
    DEFERRED = "deferred"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class EpistemicIssue:
    kind: EpistemicIssueKind
    statement: str
    scope: str
    basis_refs: tuple[str, ...]
    decision_relevance: float = 1.0
    status: EpistemicIssueStatus = EpistemicIssueStatus.OPEN
    candidate_refs: tuple[str, ...] = ()
    id: str = field(default_factory=lambda: _new_id("epistemic_issue"))

    def __post_init__(self) -> None:
        if not self.statement.strip() or not self.scope.strip():
            raise ValueError("epistemic issue requires statement and bounded scope")
        if not self.basis_refs:
            raise ValueError("epistemic issue requires basis_refs")
        if not 0.0 <= self.decision_relevance <= 1.0:
            raise ValueError("decision_relevance must be between zero and one")


@dataclass(frozen=True, slots=True)
class UncertaintyProfile:
    unresolved_count: int
    by_kind: tuple[tuple[EpistemicIssueKind, int], ...]
    candidate_space_suspected_incomplete: bool

    @classmethod
    def from_issues(cls, issues: tuple[EpistemicIssue, ...]) -> UncertaintyProfile:
        unresolved = tuple(
            issue for issue in issues if issue.status is not EpistemicIssueStatus.RESOLVED
        )
        counts = Counter(issue.kind for issue in unresolved)
        return cls(
            unresolved_count=len(unresolved),
            by_kind=tuple(sorted(counts.items(), key=lambda item: item[0].value)),
            candidate_space_suspected_incomplete=(
                EpistemicIssueKind.CANDIDATE_SPACE_SUSPECTED_INCOMPLETE in counts
            ),
        )


class StructuralTensionKind(StrEnum):
    PERSISTENT_RESIDUAL = "persistent-residual"
    REPEATED_REOPEN = "repeated-reopen"
    CONTRADICTORY_EVIDENCE = "contradictory-evidence"
    REPRESENTATION_INSTABILITY = "representation-instability"
    PROXY_TARGET_MISMATCH = "proxy-target-mismatch"
    SCOPE_DRIFT = "scope-drift"
    UNEXPECTED_OUTCOME = "unexpected-outcome"


@dataclass(frozen=True, slots=True)
class StructuralTension:
    kind: StructuralTensionKind
    statement: str
    basis_refs: tuple[str, ...]
    affected_issue_refs: tuple[str, ...] = ()
    persistence: int = 1
    recurrence: int = 1
    decision_relevance: float = 1.0
    id: str = field(default_factory=lambda: _new_id("structural_tension"))

    def __post_init__(self) -> None:
        if not self.statement.strip() or not self.basis_refs:
            raise ValueError("structural tension requires statement and reality-grounded basis")
        if self.persistence < 1 or self.recurrence < 1:
            raise ValueError("persistence and recurrence must be positive")
        if not 0.0 <= self.decision_relevance <= 1.0:
            raise ValueError("decision_relevance must be between zero and one")


@dataclass(frozen=True, slots=True)
class EpistemicAssessment:
    controller_ref: str
    kernel_state_version: int
    policy_version: str
    mode: str
    issues: tuple[EpistemicIssue, ...]
    uncertainty: UncertaintyProfile
    tensions: tuple[StructuralTension, ...] = ()
    candidate_frontier_refs: tuple[str, ...] = ()
    representation_ref: str | None = None
    self_model_ref: str | None = None
    basis_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kernel_state_version < 0:
            raise ValueError("kernel_state_version cannot be negative")
        if not self.controller_ref.strip() or not self.policy_version.strip():
            raise ValueError("assessment identity and policy_version must be non-empty")

    @property
    def open_issues(self) -> tuple[EpistemicIssue, ...]:
        return tuple(issue for issue in self.issues if issue.status is EpistemicIssueStatus.OPEN)

    @property
    def decision_relevant_open_issues(self) -> tuple[EpistemicIssue, ...]:
        return tuple(issue for issue in self.open_issues if issue.decision_relevance >= 0.5)


class EpistemicAssessor:
    """Build policy state from a kernel projection without minting current truth."""

    def assess(
        self,
        projection: EpistemicState,
        *,
        policy_version: str,
        issues: tuple[EpistemicIssue, ...] = (),
        tensions: tuple[StructuralTension, ...] = (),
        candidate_frontier_refs: tuple[str, ...] = (),
        representation_ref: str | None = None,
        self_model_ref: str | None = None,
        basis_refs: tuple[str, ...] = (),
    ) -> EpistemicAssessment:
        if any(issue.scope != projection.controller_ref for issue in issues):
            raise ValueError("epistemic issue scope does not match the current controller")
        synthesized = list(issues)
        state_basis = basis_refs or (
            f"controller:{projection.controller_ref}:v{projection.state_version}",
        )
        if not synthesized and projection.open_issue_count:
            kind = (
                EpistemicIssueKind.CANDIDATE_SPACE_SUSPECTED_INCOMPLETE
                if "candidate-space" in projection.tags
                else EpistemicIssueKind.MODEL_INTERNAL_UNKNOWN
            )
            synthesized.append(
                EpistemicIssue(
                    kind=kind,
                    statement="Kernel state contains unresolved cognitive issues.",
                    scope=projection.controller_ref,
                    basis_refs=state_basis,
                )
            )
        issue_tuple = tuple(synthesized)
        return EpistemicAssessment(
            controller_ref=projection.controller_ref,
            kernel_state_version=projection.state_version,
            policy_version=policy_version,
            mode=projection.mode.value,
            issues=issue_tuple,
            uncertainty=UncertaintyProfile.from_issues(issue_tuple),
            tensions=tuple(tensions),
            candidate_frontier_refs=tuple(candidate_frontier_refs),
            representation_ref=representation_ref,
            self_model_ref=self_model_ref,
            basis_refs=state_basis,
        )
