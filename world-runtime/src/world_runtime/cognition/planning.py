from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from .candidates import Candidate, CandidateFrontier, CandidateKind
from .epistemic import EpistemicAssessment, EpistemicIssueKind
from .self_model import WorkingSelfModel


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


_EFFECT_CLASS_RANK = {
    "read-only": 0,
    "internal-reversible": 1,
    "external-effect": 2,
}


def _stricter_effect_class(left: str, right: str) -> str:
    return max((left, right), key=_EFFECT_CLASS_RANK.__getitem__)


class EpistemicActionKind(StrEnum):
    OBSERVE = "observe"
    RETRIEVE = "retrieve"
    COMPARE = "compare"
    TEST = "test"
    SIMULATE = "simulate"
    ASK = "ask"
    RE_REPRESENT = "re-represent"
    GENERATE_CANDIDATES = "generate-candidates"
    VERIFY = "verify"
    WAIT = "wait"
    CLOSE = "close"


@dataclass(frozen=True, slots=True)
class EpistemicAction:
    kind: EpistemicActionKind
    candidate_ref: str | None
    instruction: str
    capability: str | None = None
    expected_discrimination: float = 0.0
    decision_relevance: float = 1.0
    estimated_cost: float = 0.0
    estimated_latency: float = 0.0
    effect_class: str = "read-only"
    basis_refs: tuple[str, ...] = ()
    redundancy_key: str | None = None
    id: str = field(default_factory=lambda: _new_id("epistemic_action"))

    def __post_init__(self) -> None:
        if not self.instruction.strip():
            raise ValueError("epistemic action requires an instruction")
        if self.effect_class not in {"read-only", "internal-reversible", "external-effect"}:
            raise ValueError("invalid epistemic action effect_class")
        if not 0.0 <= self.expected_discrimination <= 1.0:
            raise ValueError("expected_discrimination must be between zero and one")
        if not 0.0 <= self.decision_relevance <= 1.0:
            raise ValueError("decision_relevance must be between zero and one")
        if self.estimated_cost < 0 or self.estimated_latency < 0:
            raise ValueError("action cost and latency cannot be negative")

    @property
    def discrimination_value(self) -> float:
        return self.expected_discrimination * self.decision_relevance


@dataclass(frozen=True, slots=True)
class SearchBudget:
    max_actions: int = 4
    max_cost: float = 8.0
    max_latency: float = 3600.0
    consumed_actions: int = 0
    consumed_cost: float = 0.0
    consumed_latency: float = 0.0

    def admits(self, action: EpistemicAction) -> bool:
        return (
            self.consumed_actions + 1 <= self.max_actions
            and self.consumed_cost + action.estimated_cost <= self.max_cost
            and self.consumed_latency + action.estimated_latency <= self.max_latency
        )

    @property
    def exhausted(self) -> bool:
        return (
            self.consumed_actions >= self.max_actions
            or self.consumed_cost >= self.max_cost
            or self.consumed_latency >= self.max_latency
        )


@dataclass(frozen=True, slots=True)
class SearchSelection:
    action: EpistemicAction | None
    reason: str
    budget_exhausted: bool
    rejected_action_refs: tuple[str, ...] = ()


class ActionPlanner:
    def from_frontier(
        self,
        frontier: CandidateFrontier,
        self_model: WorkingSelfModel | None,
    ) -> tuple[EpistemicAction, ...]:
        return tuple(
            self._from_candidate(candidate, self_model) for candidate in frontier.candidates
        )

    def _from_candidate(
        self,
        candidate: Candidate,
        self_model: WorkingSelfModel | None,
    ) -> EpistemicAction:
        capability = candidate.required_capabilities[0] if candidate.required_capabilities else None
        effect_class = candidate.effect_class
        if capability and self_model is not None:
            belief = self_model.capability(capability)
            if belief is None or not self_model.can_attempt(capability):
                capability = None
            else:
                effect_class = _stricter_effect_class(effect_class, belief.effect_class)
        kind_map = {
            CandidateKind.ACQUISITION: EpistemicActionKind.OBSERVE,
            CandidateKind.REPRESENTATION: EpistemicActionKind.RE_REPRESENT,
            CandidateKind.VERIFICATION: EpistemicActionKind.VERIFY,
            CandidateKind.EXPERIMENT: EpistemicActionKind.TEST,
            CandidateKind.HYPOTHESIS: EpistemicActionKind.COMPARE,
            CandidateKind.PROBLEM_REFRAME: EpistemicActionKind.RE_REPRESENT,
        }
        return EpistemicAction(
            kind=kind_map[candidate.kind],
            candidate_ref=candidate.id,
            capability=capability,
            instruction=candidate.statement,
            expected_discrimination=candidate.expected_discrimination,
            decision_relevance=candidate.decision_relevance,
            estimated_cost=candidate.estimated_cost,
            estimated_latency=candidate.estimated_latency,
            effect_class=effect_class,
            basis_refs=candidate.basis_refs,
            redundancy_key=candidate.redundancy_key,
        )


class SearchPolicy:
    """Select by expected discriminating value after hard budget/redundancy gates."""

    def select(
        self,
        actions: Sequence[EpistemicAction],
        budget: SearchBudget,
        *,
        used_redundancy_keys: frozenset[str] = frozenset(),
    ) -> SearchSelection:
        rejected: list[str] = []
        admissible: list[EpistemicAction] = []
        for action in actions:
            if action.redundancy_key and action.redundancy_key in used_redundancy_keys:
                rejected.append(action.id)
                continue
            if not budget.admits(action):
                rejected.append(action.id)
                continue
            if action.capability is None and action.kind in {
                EpistemicActionKind.OBSERVE,
                EpistemicActionKind.VERIFY,
                EpistemicActionKind.TEST,
                EpistemicActionKind.COMPARE,
            }:
                rejected.append(action.id)
                continue
            admissible.append(action)
        if not admissible:
            return SearchSelection(
                action=None,
                reason="no non-redundant epistemic action fits the current budget/capability model",
                budget_exhausted=budget.exhausted,
                rejected_action_refs=tuple(rejected),
            )
        action = max(admissible, key=self._priority)
        return SearchSelection(
            action=action,
            reason="selected highest current discriminating value after hard gates",
            budget_exhausted=False,
            rejected_action_refs=tuple(rejected),
        )

    def _priority(self, action: EpistemicAction) -> tuple[float, float, float]:
        return (
            action.discrimination_value,
            -action.estimated_cost,
            -action.estimated_latency,
        )


class ClosureReadinessKind(StrEnum):
    READY = "ready"
    NOT_READY = "not-ready"
    WAIT_REQUIRED = "wait-required"
    ESCALATION_REQUIRED = "escalation-required"


@dataclass(frozen=True, slots=True)
class ClosureReadiness:
    kind: ClosureReadinessKind
    reasons: tuple[str, ...]
    selected_candidate_ref: str | None = None
    deferred_issue_refs: tuple[str, ...] = ()


class ClosurePolicy:
    def __init__(self, continue_search_threshold: float = 0.25) -> None:
        self.continue_search_threshold = continue_search_threshold

    def assess(
        self,
        assessment: EpistemicAssessment,
        frontier: CandidateFrontier,
        selection: SearchSelection,
        *,
        adopted_candidate_ref: str | None,
        acceptance_criteria: Sequence[str],
        verification_plan: Sequence[str],
        reopen_conditions: Sequence[str],
    ) -> ClosureReadiness:
        blockers = assessment.decision_relevant_open_issues
        if blockers:
            return ClosureReadiness(
                ClosureReadinessKind.NOT_READY,
                ("decision-relevant epistemic issues remain open",),
                adopted_candidate_ref,
            )
        if selection.action is not None and (
            selection.action.discrimination_value >= self.continue_search_threshold
        ):
            return ClosureReadiness(
                ClosureReadinessKind.NOT_READY,
                ("a budget-admissible action still has material discriminating value",),
                adopted_candidate_ref,
            )
        if adopted_candidate_ref is None or frontier.get(adopted_candidate_ref) is None:
            return ClosureReadiness(
                ClosureReadinessKind.WAIT_REQUIRED,
                ("no qualified candidate has been explicitly adopted",),
            )
        if not acceptance_criteria or not verification_plan or not reopen_conditions:
            return ClosureReadiness(
                ClosureReadinessKind.NOT_READY,
                ("closure requires acceptance, verification and reopen conditions",),
                adopted_candidate_ref,
            )
        return ClosureReadiness(
            ClosureReadinessKind.READY,
            ("current frontier supports bounded temporary closure",),
            adopted_candidate_ref,
        )


class RevisionTarget(StrEnum):
    EXECUTION = "execution"
    WORK_SPEC = "work-spec"
    DECISION = "decision"
    REPRESENTATION = "representation"
    INPUTS = "inputs"
    EVIDENCE_ACQUISITION = "evidence-acquisition"
    VERIFICATION = "verification"
    GOAL = "goal"
    AUTHORIZATION = "authorization"
    PROBLEM_DEFINITION = "problem-definition"


@dataclass(frozen=True, slots=True)
class RevisionDiagnosis:
    target: RevisionTarget
    recommended_disposition: str
    reason: str
    basis_refs: tuple[str, ...]
    unresolved_alternatives: tuple[RevisionTarget, ...] = ()


class RevisionPlanner:
    """Classify where a closure may have failed without self-executing the disposition."""

    def diagnose(
        self,
        assessment: EpistemicAssessment,
        *,
        new_discriminating_evidence: bool,
        verification_present: bool,
    ) -> RevisionDiagnosis:
        kinds = {issue.kind for issue in assessment.open_issues}
        basis = tuple(dict.fromkeys(assessment.basis_refs))
        if EpistemicIssueKind.EFFECT_STATE_AMBIGUITY in kinds:
            return RevisionDiagnosis(
                RevisionTarget.EXECUTION,
                "reconcile-effect",
                "effect state is ambiguous; reconcile before any retry",
                basis,
            )
        if EpistemicIssueKind.AUTHORIZATION_GAP in kinds:
            return RevisionDiagnosis(
                RevisionTarget.AUTHORIZATION,
                "request-authorization",
                "the selected action lacks current authorization",
                basis,
            )
        if kinds & {
            EpistemicIssueKind.REPRESENTATION_MISMATCH,
            EpistemicIssueKind.DISTINCTION_GAP,
            EpistemicIssueKind.CANDIDATE_SPACE_SUSPECTED_INCOMPLETE,
        }:
            return RevisionDiagnosis(
                RevisionTarget.REPRESENTATION,
                "reopen-cognition",
                "current representation/candidate space is implicated by reality feedback",
                basis,
            )
        if EpistemicIssueKind.PROBLEM_DEFINITION_GAP in kinds:
            return RevisionDiagnosis(
                RevisionTarget.PROBLEM_DEFINITION,
                "reopen-cognition",
                "problem framing requires explicit reconsideration",
                basis,
            )
        if EpistemicIssueKind.GOAL_AMBIGUITY in kinds:
            return RevisionDiagnosis(
                RevisionTarget.GOAL,
                "reopen-cognition",
                "goal ambiguity prevents a bounded retry",
                basis,
            )
        if kinds & {
            EpistemicIssueKind.ACQUISITION_GAP,
            EpistemicIssueKind.IDENTIFIABILITY_GAP,
        }:
            return RevisionDiagnosis(
                RevisionTarget.EVIDENCE_ACQUISITION,
                "acquire-evidence",
                "additional discriminating evidence is required",
                basis,
            )
        if EpistemicIssueKind.VERIFICATION_GAP in kinds or not verification_present:
            return RevisionDiagnosis(
                RevisionTarget.VERIFICATION,
                "acquire-evidence",
                "verification is missing or insufficient",
                basis,
            )
        if not new_discriminating_evidence:
            return RevisionDiagnosis(
                RevisionTarget.EVIDENCE_ACQUISITION,
                "acquire-evidence",
                "an equivalent retry would consume no new discriminating reality difference",
                basis,
            )
        return RevisionDiagnosis(
            RevisionTarget.EXECUTION,
            "retry-run",
            "failure is localized to execution and a retry consumes new discriminating evidence",
            basis,
        )
