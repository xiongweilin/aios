from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from .candidates import Candidate
from .controller import (
    CognitiveController,
    ControllerDecision,
    ControllerDecisionKind,
    ControllerState,
    ControllerStatus,
    controller_capability_result,
    latest_controller_decision,
)
from .engine import MetaControlFrame, MetaControllerEngine
from .epistemic import EpistemicIssue, StructuralTension
from .experience import ExperienceResolver
from .models import EpistemicState, EpistemicStateEstimator
from .planning import SearchBudget
from .self_model import WorkingSelfModel


class StagedMetaPolicy(ABC):
    """Profile staging over World Runtime cognitive control."""

    controller: CognitiveController
    estimator = EpistemicStateEstimator()
    experience_resolver = ExperienceResolver()
    meta_engine = MetaControllerEngine()

    @property
    @abstractmethod
    def policy_ref(self) -> str: ...

    @abstractmethod
    def _diagnosis(self, state: ControllerState) -> ControllerDecision: ...

    @abstractmethod
    def _form_closure(
        self, state: ControllerState, diagnosis_result: dict[str, Any] | None
    ) -> ControllerDecision: ...

    @abstractmethod
    def _propose_work(self, state: ControllerState) -> ControllerDecision: ...

    @abstractmethod
    def _current_revision(self, state: ControllerState) -> Any | None: ...

    @abstractmethod
    def _revision(self, state: ControllerState) -> ControllerDecision: ...

    @abstractmethod
    def _human_reopen_revision(self, state: ControllerState) -> ControllerDecision: ...

    def _has_human_followup(self) -> bool:
        value = getattr(self, "human_instruction", None)
        return isinstance(value, str) and bool(value.strip())

    def epistemic_state(self, state: ControllerState) -> EpistemicState:
        return self.estimator.estimate(state)

    def meta_control_frame(
        self,
        state: ControllerState,
        *,
        issues: tuple[EpistemicIssue, ...] = (),
        tensions: tuple[StructuralTension, ...] = (),
        candidates: Sequence[Candidate] = (),
        self_model: WorkingSelfModel | None = None,
        budget: SearchBudget | None = None,
        used_redundancy_keys: frozenset[str] = frozenset(),
        adopted_candidate_ref: str | None = None,
        acceptance_criteria: Sequence[str] = (),
        verification_plan: Sequence[str] = (),
        reopen_conditions: Sequence[str] = (),
        basis_refs: tuple[str, ...] = (),
    ) -> MetaControlFrame:
        return self.meta_engine.evaluate(
            self.epistemic_state(state),
            issues=issues,
            tensions=tensions,
            candidates=candidates,
            self_model=self_model,
            budget=budget,
            used_redundancy_keys=used_redundancy_keys,
            adopted_candidate_ref=adopted_candidate_ref,
            acceptance_criteria=acceptance_criteria,
            verification_plan=verification_plan,
            reopen_conditions=reopen_conditions,
            basis_refs=basis_refs,
        )

    def experience_hints(self, state: ControllerState, *extra_tags: str) -> str:
        return self.experience_resolver.render(
            (*self.epistemic_state(state).tags, *extra_tags)
        )

    async def select(self, state: ControllerState) -> ControllerDecision:
        if state.status is ControllerStatus.CLOSED:
            raise ValueError("closed controller must not restart implicitly")
        if state.status is ControllerStatus.REOPEN_REQUIRED:
            return ControllerDecision(
                controller_ref=state.id,
                state_version=state.version,
                kind=ControllerDecisionKind.REOPEN,
                reason="revision requires an explicit new cognitive episode",
            )
        if state.status is ControllerStatus.WAITING:
            if state.work_proposal_ref:
                if self._current_revision(state) is None:
                    return self._revision(state)
                if self._has_human_followup():
                    return self._human_reopen_revision(state)
                raise ValueError("waiting controller requires explicit follow-up after revision")
            return ControllerDecision(
                controller_ref=state.id,
                state_version=state.version,
                kind=ControllerDecisionKind.REOPEN,
                reason="resume an explicit cognitive wait without handed-off Work",
            )
        if state.active_closure_ref:
            return self._propose_work(state)

        last = latest_controller_decision(self.controller, state.id)
        if last is None or last.kind is ControllerDecisionKind.REOPEN:
            return self._diagnosis(state)
        if (
            last.kind is ControllerDecisionKind.INVOKE_CAPABILITY
            and last.parameters.get("phase") == "diagnosis"
        ):
            result = controller_capability_result(self.controller, state.id, last.id)
            if result is None:
                result = {
                    "status": "failed",
                    "message": "diagnosis returned no durable result",
                }
            if str(result.get("status", "")) != "succeeded":
                return ControllerDecision(
                    controller_ref=state.id,
                    state_version=state.version,
                    kind=ControllerDecisionKind.WAIT,
                    reason="diagnosis failed; wait rather than invent cognitive closure",
                )
            return self._form_closure(state, result)
        raise ValueError(f"unexpected open controller stage after {last.kind.value}")
