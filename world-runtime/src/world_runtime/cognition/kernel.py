from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from ..common import new_id
from ..epistemics import BeliefVerdict, EpistemicLedger
from ..ledger import SemanticLedger


class InvestigationClosureReadiness(StrEnum):
    NOT_READY = "not-ready"
    TEMPORARY = "temporary"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class InvestigationCandidate:
    id: str
    description: str
    expected_information_gain: float
    cost: float
    effect_class: str = "read-only"
    capability: str | None = None


@dataclass(frozen=True, slots=True)
class InvestigationBudget:
    max_actions: int
    max_cost: float
    used_actions: int = 0
    used_cost: float = 0.0

    def admits(self, candidate: InvestigationCandidate) -> bool:
        return self.used_actions < self.max_actions and self.used_cost + candidate.cost <= self.max_cost


@dataclass(frozen=True, slots=True)
class CognitiveEpisode:
    id: str
    subject: str
    goal_ref: str | None
    status: str
    frame: Mapping[str, Any] = field(default_factory=dict)


class CognitionEngine:
    """Investigation, closure and reframing; never authority minting."""

    def __init__(self, ledger: SemanticLedger, epistemics: EpistemicLedger) -> None:
        self.ledger = ledger
        self.epistemics = epistemics

    def open_episode(self, subject: str, *, goal_ref: str | None = None, frame: Mapping[str, Any] | None = None) -> CognitiveEpisode:
        item = CognitiveEpisode(new_id("cognitive-episode"), subject, goal_ref, "open", dict(frame or {}))
        self.ledger.project_put(
            "cognition.episode", item.id,
            {"id": item.id, "subject": subject, "goal_ref": goal_ref, "status": "open", "frame": dict(item.frame)},
        )
        self.ledger.append(stream=f"cognition:{item.id}", kind="cognition.episode.opened", payload={"id": item.id, "subject": subject})
        return item

    def select_candidate(self, candidates: list[InvestigationCandidate], budget: InvestigationBudget) -> InvestigationCandidate | None:
        admitted = [c for c in candidates if budget.admits(c)]
        if not admitted:
            return None
        return max(
            admitted,
            key=lambda c: (float("inf") if c.cost == 0 else c.expected_information_gain / c.cost, c.expected_information_gain),
        )

    def closure_readiness(self, *, subject: str, material_claim_ids: tuple[str, ...]) -> InvestigationClosureReadiness:
        if self.epistemics.open_unknowns(subject):
            return InvestigationClosureReadiness.NOT_READY
        verdicts = [self.epistemics.current_belief(cid)[0] for cid in material_claim_ids]
        if any(v is BeliefVerdict.CONFLICTED for v in verdicts):
            return InvestigationClosureReadiness.NOT_READY
        if any(v is BeliefVerdict.UNKNOWN for v in verdicts):
            return InvestigationClosureReadiness.TEMPORARY
        return InvestigationClosureReadiness.READY

    def close_episode(self, episode_id: str, *, temporary: bool, basis_refs: tuple[str, ...]) -> None:
        current = self.ledger.project_get("cognition.episode", episode_id)
        if current is None:
            raise KeyError(episode_id)
        value, version = current
        value["status"] = "temporarily-closed" if temporary else "closed"
        value["closure_basis_refs"] = list(basis_refs)
        self.ledger.project_put("cognition.episode", episode_id, value, expected_version=version)
        self.ledger.append(stream=f"cognition:{episode_id}", kind="cognition.episode.closed", payload={"temporary": temporary, "basis_refs": list(basis_refs)})

    def reopen(self, episode_id: str, *, reason: str, basis_refs: tuple[str, ...]) -> None:
        current = self.ledger.project_get("cognition.episode", episode_id)
        if current is None:
            raise KeyError(episode_id)
        value, version = current
        value["status"] = "open"
        value["reopen_reason"] = reason
        self.ledger.project_put("cognition.episode", episode_id, value, expected_version=version)
        self.ledger.append(stream=f"cognition:{episode_id}", kind="cognition.episode.reopened", payload={"reason": reason, "basis_refs": list(basis_refs)})

    def revise_representation(self, episode_id: str, *, new_frame: Mapping[str, Any], reason: str) -> None:
        current = self.ledger.project_get("cognition.episode", episode_id)
        if current is None:
            raise KeyError(episode_id)
        value, version = current
        old_frame = dict(value.get("frame", {}))
        value["frame"] = dict(new_frame)
        value["status"] = "open"
        self.ledger.project_put("cognition.episode", episode_id, value, expected_version=version)
        self.ledger.append(
            stream=f"cognition:{episode_id}",
            kind="cognition.representation.revised",
            payload={"reason": reason, "old_frame": old_frame, "new_frame": dict(new_frame)},
        )
