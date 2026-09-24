from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .controller import ControllerState, ControllerStatus


class EpistemicMode(StrEnum):
    OPEN_EXPLORATION = "open-exploration"
    TEMPORARY_CLOSURE = "temporary-closure"
    WAITING_REALITY = "waiting-reality"
    REOPEN_REQUIRED = "reopen-required"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class EpistemicState:
    """Advisory cognitive projection, never truth, Work, or authority."""

    controller_ref: str
    state_version: int
    mode: EpistemicMode
    candidate_count: int
    open_issue_count: int
    has_result: bool
    has_closure: bool
    has_work: bool
    has_revision: bool
    tags: frozenset[str]


class EpistemicStateEstimator:
    def estimate(self, state: ControllerState) -> EpistemicState:
        if state.status is ControllerStatus.CLOSED:
            mode = EpistemicMode.CLOSED
        elif state.status is ControllerStatus.REOPEN_REQUIRED:
            mode = EpistemicMode.REOPEN_REQUIRED
        elif state.status is ControllerStatus.WAITING:
            mode = EpistemicMode.WAITING_REALITY
        elif state.active_closure_ref is not None:
            mode = EpistemicMode.TEMPORARY_CLOSURE
        else:
            mode = EpistemicMode.OPEN_EXPLORATION

        tags: set[str] = {mode.value}
        if state.last_revision_ref:
            tags.add("retry")
        if state.open_issue_refs:
            tags.add("unknown")
        if state.candidate_refs:
            tags.add("candidate-space")
        if state.last_result_ref:
            tags.add("has-reality-result")
        if state.work_proposal_ref:
            tags.add("work-handed-off")
        return EpistemicState(
            controller_ref=state.id,
            state_version=state.version,
            mode=mode,
            candidate_count=len(state.candidate_refs),
            open_issue_count=len(state.open_issue_refs),
            has_result=state.last_result_ref is not None,
            has_closure=state.active_closure_ref is not None,
            has_work=state.work_proposal_ref is not None,
            has_revision=state.last_revision_ref is not None,
            tags=frozenset(tags),
        )
