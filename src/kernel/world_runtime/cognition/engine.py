from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .candidates import Candidate, CandidateFrontier, FrontierBuilder
from .epistemic import (
    EpistemicAssessment,
    EpistemicAssessor,
    EpistemicIssue,
    StructuralTension,
)
from .journal import MetaPolicyJournal
from .models import EpistemicMode, EpistemicState
from .planning import (
    ActionPlanner,
    ClosurePolicy,
    ClosureReadiness,
    ClosureReadinessKind,
    EpistemicAction,
    EpistemicActionKind,
    SearchBudget,
    SearchPolicy,
    SearchSelection,
)
from .self_model import WorkingSelfModel


class MetaControlIntentKind(StrEnum):
    ACQUIRE_EVIDENCE = "acquire-evidence"
    REVISE_REPRESENTATION = "revise-representation"
    EFFECTFUL_EXPERIMENT = "effectful-experiment"
    FORM_CLOSURE = "form-closure"
    WAIT = "wait"
    CLOSE = "close"
    REOPEN = "reopen"


@dataclass(frozen=True, slots=True)
class MetaControlIntent:
    controller_ref: str
    kernel_state_version: int
    policy_version: str
    kind: MetaControlIntentKind
    reason: str
    action: EpistemicAction | None = None
    candidate_ref: str | None = None


@dataclass(frozen=True, slots=True)
class MetaControlFrame:
    assessment: EpistemicAssessment
    frontier: CandidateFrontier
    actions: tuple[EpistemicAction, ...]
    selection: SearchSelection
    closure_readiness: ClosureReadiness
    intent: MetaControlIntent


class MetaControllerEngine:
    """Pure policy orchestration above Agent Kernel's legal controller state machine."""

    def __init__(
        self,
        *,
        policy_version: str = "meta-controller-policy-v1",
        assessor: EpistemicAssessor | None = None,
        frontier_builder: FrontierBuilder | None = None,
        action_planner: ActionPlanner | None = None,
        search_policy: SearchPolicy | None = None,
        closure_policy: ClosurePolicy | None = None,
        journal: MetaPolicyJournal | None = None,
    ) -> None:
        if not policy_version.strip():
            raise ValueError("policy_version must be non-empty")
        self.policy_version = policy_version
        self.assessor = assessor or EpistemicAssessor()
        self.frontier_builder = frontier_builder or FrontierBuilder()
        self.action_planner = action_planner or ActionPlanner()
        self.search_policy = search_policy or SearchPolicy()
        self.closure_policy = closure_policy or ClosurePolicy()
        self.journal = journal

    def evaluate(
        self,
        projection: EpistemicState,
        *,
        issues: tuple[EpistemicIssue, ...] = (),
        tensions: tuple[StructuralTension, ...] = (),
        candidates: Sequence[Candidate] = (),
        representation_ref: str | None = None,
        self_model: WorkingSelfModel | None = None,
        budget: SearchBudget | None = None,
        used_redundancy_keys: frozenset[str] = frozenset(),
        adopted_candidate_ref: str | None = None,
        acceptance_criteria: Sequence[str] = (),
        verification_plan: Sequence[str] = (),
        reopen_conditions: Sequence[str] = (),
        basis_refs: tuple[str, ...] = (),
    ) -> MetaControlFrame:
        current_budget = budget or SearchBudget()
        initial = self.assessor.assess(
            projection,
            policy_version=self.policy_version,
            issues=issues,
            tensions=tensions,
            representation_ref=representation_ref,
            self_model_ref=self_model.id if self_model is not None else None,
            basis_refs=basis_refs,
        )
        frontier = self.frontier_builder.build(initial, candidates)
        assessment = self.assessor.assess(
            projection,
            policy_version=self.policy_version,
            issues=issues,
            tensions=tensions,
            candidate_frontier_refs=tuple(item.id for item in frontier.candidates),
            representation_ref=representation_ref,
            self_model_ref=self_model.id if self_model is not None else None,
            basis_refs=basis_refs,
        )
        actions = self.action_planner.from_frontier(frontier, self_model)
        selection = self.search_policy.select(
            actions,
            current_budget,
            used_redundancy_keys=used_redundancy_keys,
        )
        readiness = self.closure_policy.assess(
            assessment,
            frontier,
            selection,
            adopted_candidate_ref=adopted_candidate_ref,
            acceptance_criteria=acceptance_criteria,
            verification_plan=verification_plan,
            reopen_conditions=reopen_conditions,
        )
        intent = self._intent(projection, readiness, selection, adopted_candidate_ref)
        frame = MetaControlFrame(assessment, frontier, actions, selection, readiness, intent)
        self._record(frame)
        return frame

    def _intent(
        self,
        projection: EpistemicState,
        readiness: ClosureReadiness,
        selection: SearchSelection,
        adopted_candidate_ref: str | None,
    ) -> MetaControlIntent:
        if projection.mode is EpistemicMode.CLOSED:
            return self._make_intent(
                projection,
                kind=MetaControlIntentKind.CLOSE,
                reason="kernel controller is already closed; meta-policy mints no new episode",
            )
        if projection.mode is EpistemicMode.REOPEN_REQUIRED:
            return self._make_intent(
                projection,
                kind=MetaControlIntentKind.REOPEN,
                reason="kernel revision state requires an explicit reopen",
            )
        if readiness.kind is ClosureReadinessKind.READY:
            return self._make_intent(
                projection,
                kind=MetaControlIntentKind.FORM_CLOSURE,
                reason="closure readiness gate is satisfied",
                candidate_ref=adopted_candidate_ref,
            )
        action = selection.action
        if action is None:
            return self._make_intent(
                projection,
                kind=MetaControlIntentKind.WAIT,
                reason=selection.reason,
            )
        if action.kind is EpistemicActionKind.RE_REPRESENT:
            kind = MetaControlIntentKind.REVISE_REPRESENTATION
        elif action.effect_class == "read-only":
            kind = MetaControlIntentKind.ACQUIRE_EVIDENCE
        else:
            kind = MetaControlIntentKind.EFFECTFUL_EXPERIMENT
        return self._make_intent(
            projection,
            kind=kind,
            reason=selection.reason,
            action=action,
            candidate_ref=action.candidate_ref,
        )

    def _make_intent(
        self,
        projection: EpistemicState,
        *,
        kind: MetaControlIntentKind,
        reason: str,
        action: EpistemicAction | None = None,
        candidate_ref: str | None = None,
    ) -> MetaControlIntent:
        return MetaControlIntent(
            controller_ref=projection.controller_ref,
            kernel_state_version=projection.state_version,
            policy_version=self.policy_version,
            kind=kind,
            reason=reason,
            action=action,
            candidate_ref=candidate_ref,
        )

    def _record(self, frame: MetaControlFrame) -> None:
        if self.journal is None:
            return
        assessment = frame.assessment
        self.journal.record(
            event_type="EpistemicAssessmentRecorded",
            controller_ref=assessment.controller_ref,
            kernel_state_version=assessment.kernel_state_version,
            policy_version=assessment.policy_version,
            payload={
                "mode": assessment.mode,
                "issue_refs": [issue.id for issue in assessment.issues],
                "frontier_refs": list(assessment.candidate_frontier_refs),
                "tension_refs": [tension.id for tension in assessment.tensions],
                "representation_ref": assessment.representation_ref,
                "self_model_ref": assessment.self_model_ref,
            },
            basis_refs=assessment.basis_refs,
        )
        self.journal.record(
            event_type="MetaControlIntentSelected",
            controller_ref=assessment.controller_ref,
            kernel_state_version=assessment.kernel_state_version,
            policy_version=assessment.policy_version,
            payload={
                "intent": frame.intent.kind.value,
                "candidate_ref": frame.intent.candidate_ref,
                "action_ref": frame.intent.action.id if frame.intent.action else None,
                "closure_readiness": frame.closure_readiness.kind.value,
                "novel_discrimination": (
                    frame.selection.action is not None
                    and frame.selection.action.discrimination_value > 0.0
                ),
            },
            basis_refs=assessment.basis_refs,
        )
