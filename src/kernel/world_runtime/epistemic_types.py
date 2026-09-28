from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from semantic_language import SemanticKind, SemanticRef

from .common import utcnow

EPISTEMICS_NAMESPACE = "world-runtime.epistemics"


@dataclass(frozen=True, slots=True)
class EpistemicObject:
    id: str
    created_at: datetime = field(default_factory=utcnow)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Claim(EpistemicObject):
    subject: str = ""
    proposition: str = ""

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.CLAIM

    @property
    def ref(self) -> SemanticRef:
        return SemanticRef(self.kind, self.id)


@dataclass(frozen=True, slots=True)
class Evidence(EpistemicObject):
    subject: str = ""
    content: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    derived_from: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.EVIDENCE

    @property
    def ref(self) -> SemanticRef:
        return SemanticRef(self.kind, self.id)


@dataclass(frozen=True, slots=True)
class Unknown(EpistemicObject):
    subject: str = ""
    question: str = ""
    blocks: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.UNKNOWN

    @property
    def ref(self) -> SemanticRef:
        return SemanticRef(self.kind, self.id)


@dataclass(frozen=True, slots=True)
class Conflict(EpistemicObject):
    subject: str = ""
    members: tuple[SemanticRef, ...] = ()
    description: str = ""

    @property
    def ref(self) -> SemanticRef:
        return SemanticRef(
            kind="conflict",
            id=self.id,
            namespace=EPISTEMICS_NAMESPACE,
        )


class BeliefVerdict(StrEnum):
    UNKNOWN = "unknown"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    DISPUTED = "disputed"
    STALE = "stale"


class EvidenceRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    INCONCLUSIVE = "inconclusive"
    IRRELEVANT = "irrelevant"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    INSUFFICIENT_TIME = "insufficient_time"


class EvaluatorKind(StrEnum):
    DETERMINISTIC = "deterministic"
    HUMAN = "human"
    MODEL = "model"
    DOMAIN_VERIFIER = "domain_verifier"


@dataclass(frozen=True, slots=True)
class EvidencePredicate:
    path: str
    op: str
    value: Any = None


@dataclass(frozen=True, slots=True)
class EvidenceRequirement:
    id: str
    kinds: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    scope: Mapping[str, Any] = field(default_factory=dict)
    freshness_seconds: int | None = None
    mandatory: bool = True
    support_predicate: EvidencePredicate | None = None


@dataclass(frozen=True, slots=True)
class FalsificationCondition:
    id: str
    description: str
    evidence_kind: str | None = None
    predicate: EvidencePredicate | None = None


@dataclass(frozen=True, slots=True)
class ClaimRevision:
    id: str
    claim_id: str
    revision_number: int
    subject: str
    proposition: str
    scope: Mapping[str, Any]
    declared_status: str
    criticality: str
    evidence_requirements: tuple[EvidenceRequirement, ...]
    falsification_conditions: tuple[FalsificationCondition, ...]
    valid_from: datetime
    valid_to: datetime | None
    previous_revision_id: str | None
    cause_type: str | None
    cause_id: str | None
    actor: str
    recorded_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    id: str
    claim_ref: SemanticRef
    claim_revision_id: str
    evidence_ref: SemanticRef
    relation: EvidenceRelation
    rationale: str
    assessed_by: str
    evaluator_kind: EvaluatorKind
    assessed_at: datetime
    confidence: float | None = None
    calibration_ref: str | None = None
    evaluated_scope: Mapping[str, Any] = field(default_factory=dict)
    unevaluated_scope: Mapping[str, Any] = field(default_factory=dict)

    @property
    def verdict(self) -> BeliefVerdict:
        if self.relation is EvidenceRelation.SUPPORTS:
            return BeliefVerdict.SUPPORTED
        if self.relation is EvidenceRelation.CONTRADICTS:
            return BeliefVerdict.UNSUPPORTED
        return BeliefVerdict.UNKNOWN


@dataclass(frozen=True, slots=True)
class BeliefState:
    claim_id: str
    claim_revision_id: str
    verdict: BeliefVerdict
    supporting_assessment_ids: tuple[str, ...]
    contradicting_assessment_ids: tuple[str, ...]
    satisfied_requirement_ids: tuple[str, ...]
    unsatisfied_requirement_ids: tuple[str, ...]
    stale_requirement_ids: tuple[str, ...]
    derived_only_support: bool
    calibrated_confidence: float | None
    calibration_refs: tuple[str, ...]


def _get_path(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for segment in (part for part in path.split(".") if part):
        if not isinstance(current, Mapping):
            return None
        if segment not in current:
            return None
        current = current[segment]
    return current


def evaluate_predicate(actual: Any, op: str, expected: Any = None) -> bool:
    if op == "exists":
        return actual is not None
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "gt":
        return (
            isinstance(actual, (int, float))
            and isinstance(expected, (int, float))
            and actual > expected
        )
    if op == "gte":
        return (
            isinstance(actual, (int, float))
            and isinstance(expected, (int, float))
            and actual >= expected
        )
    if op == "lt":
        return (
            isinstance(actual, (int, float))
            and isinstance(expected, (int, float))
            and actual < expected
        )
    if op == "lte":
        return (
            isinstance(actual, (int, float))
            and isinstance(expected, (int, float))
            and actual <= expected
        )
    if op == "contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, list):
            return expected in actual
        return False
    raise ValueError(f"unsupported predicate operator: {op}")

__all__ = [
    "BeliefState",
    "BeliefVerdict",
    "Claim",
    "ClaimRevision",
    "Conflict",
    "EpistemicObject",
    "Evidence",
    "EvidenceAssessment",
    "EvidencePredicate",
    "EvidenceRelation",
    "EvidenceRequirement",
    "EvaluatorKind",
    "FalsificationCondition",
    "Unknown",
    "evaluate_predicate",
]
