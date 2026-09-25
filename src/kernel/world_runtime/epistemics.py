from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping

from semantic_language import Claim, Conflict, Evidence, SemanticRef, Unknown

from .common import new_id, utcnow
from .ledger import SemanticLedger


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


class EpistemicLedger:
    """Append-only epistemic history with versioned claims and reduced belief."""

    def __init__(self, ledger: SemanticLedger) -> None:
        self.ledger = ledger

    def record_claim(
        self,
        claim: Claim,
        *,
        actor: str = "runtime",
        scope: Mapping[str, Any] | None = None,
        evidence_requirements: tuple[EvidenceRequirement, ...] = (),
        falsification_conditions: tuple[FalsificationCondition, ...] = (),
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        declared_status: str = "unknown",
        criticality: str = "material",
        metadata: Mapping[str, Any] | None = None,
    ) -> ClaimRevision:
        existing = self.ledger.project_get("epistemics.claim", claim.id)
        if existing is not None:
            current = self.current_claim_revision(claim.id)
            if current.subject == claim.subject and current.proposition == claim.proposition:
                return current
            raise ValueError("claim identity already exists; use revise_claim")
        now = utcnow()
        revision = ClaimRevision(
            id=new_id("claim-revision"),
            claim_id=claim.id,
            revision_number=1,
            subject=claim.subject,
            proposition=claim.proposition,
            scope=dict(scope or {}),
            declared_status=declared_status,
            criticality=criticality,
            evidence_requirements=tuple(evidence_requirements),
            falsification_conditions=tuple(falsification_conditions),
            valid_from=valid_from or now,
            valid_to=valid_to,
            previous_revision_id=None,
            cause_type=None,
            cause_id=None,
            actor=actor,
            recorded_at=now,
            metadata=dict(metadata or {}),
        )
        self._persist_claim_revision(revision)
        return revision

    def revise_claim(
        self,
        claim_id: str,
        *,
        proposition: str | None = None,
        subject: str | None = None,
        scope: Mapping[str, Any] | None = None,
        evidence_requirements: tuple[EvidenceRequirement, ...] | None = None,
        falsification_conditions: tuple[FalsificationCondition, ...] | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        declared_status: str | None = None,
        criticality: str | None = None,
        cause_type: str | None = None,
        cause_id: str | None = None,
        actor: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ClaimRevision:
        current = self.current_claim_revision(claim_id)
        revision = ClaimRevision(
            id=new_id("claim-revision"),
            claim_id=claim_id,
            revision_number=current.revision_number + 1,
            subject=subject if subject is not None else current.subject,
            proposition=proposition if proposition is not None else current.proposition,
            scope=dict(scope) if scope is not None else dict(current.scope),
            declared_status=(
                declared_status if declared_status is not None else current.declared_status
            ),
            criticality=criticality if criticality is not None else current.criticality,
            evidence_requirements=(
                tuple(evidence_requirements)
                if evidence_requirements is not None
                else current.evidence_requirements
            ),
            falsification_conditions=(
                tuple(falsification_conditions)
                if falsification_conditions is not None
                else current.falsification_conditions
            ),
            valid_from=valid_from or utcnow(),
            valid_to=valid_to,
            previous_revision_id=current.id,
            cause_type=cause_type,
            cause_id=cause_id,
            actor=actor,
            recorded_at=utcnow(),
            metadata=(
                dict(metadata)
                if metadata is not None
                else dict(current.metadata)
            ),
        )
        self._persist_claim_revision(revision)
        return revision

    def import_claim_revision(self, revision: ClaimRevision) -> ClaimRevision:
        existing_revision = self.ledger.project_get(
            "epistemics.claim-revision",
            revision.id,
        )
        if existing_revision is not None:
            current = self._claim_revision_from_value(existing_revision[0])
            if current != revision:
                raise ValueError("claim revision identity conflicts with existing Runtime state")
            return current

        identity = self.ledger.project_get("epistemics.claim", revision.claim_id)
        if identity is None:
            if revision.revision_number != 1 or revision.previous_revision_id is not None:
                raise ValueError("first imported claim revision must be revision 1")
        else:
            current = self.current_claim_revision(revision.claim_id)
            if revision.revision_number != current.revision_number + 1:
                raise ValueError("claim revision sequence is not contiguous")
            if revision.previous_revision_id != current.id:
                raise ValueError("claim revision predecessor does not match current revision")
        self._persist_claim_revision(revision)
        return revision

    def import_assessment(self, assessment: EvidenceAssessment) -> EvidenceAssessment:
        existing = [
            event
            for event in self.ledger.events(
                stream=f"claim:{assessment.claim_ref.id}",
                kind="epistemics.evidence.assessed",
            )
            if event.payload.get("id") == assessment.id
        ]
        if existing:
            payload = existing[-1].payload
            if (
                payload.get("claim_revision_id") != assessment.claim_revision_id
                or payload.get("evidence_id") != assessment.evidence_ref.id
                or payload.get("relation") != assessment.relation.value
                or payload.get("evaluator_kind") != assessment.evaluator_kind.value
            ):
                raise ValueError("assessment identity conflicts with existing Runtime state")
            return assessment
        if self.ledger.project_get(
            "epistemics.claim-revision",
            assessment.claim_revision_id,
        ) is None:
            raise ValueError("claim revision must be imported before assessment")
        self._persist_assessment(assessment)
        return assessment

    def _persist_claim_revision(self, revision: ClaimRevision) -> None:
        value = self._claim_revision_value(revision)
        identity = self.ledger.project_get("epistemics.claim", revision.claim_id)
        identity_value = {
            "id": revision.claim_id,
            "subject": revision.subject,
            "current_revision_id": revision.id,
            "current_revision_number": revision.revision_number,
        }
        with self.ledger.transaction():
            self.ledger.project_put(
                "epistemics.claim-revision",
                revision.id,
                value,
            )
            self.ledger.project_put(
                "epistemics.claim",
                revision.claim_id,
                identity_value,
                expected_version=identity[1] if identity is not None else None,
            )
            self.ledger.append(
                stream=f"claim:{revision.claim_id}",
                kind="epistemics.claim.revision-recorded",
                payload=value,
                valid_at=revision.valid_from,
                recorded_at=revision.recorded_at,
            )
            self._recompute_belief(revision.claim_id)

    def current_claim_revision(self, claim_id: str) -> ClaimRevision:
        identity = self.ledger.project_get("epistemics.claim", claim_id)
        if identity is None:
            raise KeyError(claim_id)
        revision_id = str(identity[0]["current_revision_id"])
        row = self.ledger.project_get("epistemics.claim-revision", revision_id)
        if row is None:
            raise RuntimeError("claim current revision is missing")
        return self._claim_revision_from_value(row[0])

    def claim_history(self, claim_id: str) -> tuple[ClaimRevision, ...]:
        revisions = [
            self._claim_revision_from_value(event.payload)
            for event in self.ledger.events(stream=f"claim:{claim_id}")
            if event.kind == "epistemics.claim.revision-recorded"
        ]
        return tuple(sorted(revisions, key=lambda item: item.revision_number))

    def claim_revision_as_of(
        self,
        claim_id: str,
        *,
        valid_at: datetime,
        recorded_at: datetime | None = None,
    ) -> ClaimRevision | None:
        recorded_limit = recorded_at or utcnow()
        candidates: list[ClaimRevision] = []
        for event in self.ledger.events(stream=f"claim:{claim_id}"):
            if event.kind != "epistemics.claim.revision-recorded":
                continue
            if event.recorded_at > recorded_limit:
                continue
            revision = self._claim_revision_from_value(event.payload)
            if valid_at < revision.valid_from:
                continue
            if revision.valid_to is not None and valid_at >= revision.valid_to:
                continue
            candidates.append(revision)
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.revision_number)

    def record_evidence(self, evidence: Evidence) -> None:
        if self.ledger.project_get("epistemics.evidence", evidence.id) is not None:
            raise ValueError("evidence is immutable and already exists")
        metadata = dict(evidence.metadata)
        declared_provenance = metadata.get("provenance_class")
        if evidence.derived_from:
            if any(ref.kind.value != "evidence" for ref in evidence.derived_from):
                raise ValueError("derived evidence may derive only from Evidence refs")
            if declared_provenance is not None and str(declared_provenance) != "derived":
                raise ValueError(
                    "evidence with derived_from must use provenance_class=derived"
                )
            provenance_class = "derived"
        else:
            if str(declared_provenance or "") == "derived":
                raise ValueError("derived evidence requires non-empty derived_from lineage")
            provenance_class = str(declared_provenance or "runtime_observation")
        value = {
            "id": evidence.id,
            "subject": evidence.subject,
            "content": dict(evidence.content),
            "source": evidence.source,
            "observed_at": evidence.observed_at.isoformat() if evidence.observed_at else None,
            "valid_from": evidence.valid_from.isoformat() if evidence.valid_from else None,
            "valid_to": evidence.valid_to.isoformat() if evidence.valid_to else None,
            "derived_from": [
                {"kind": ref.kind.value, "id": ref.id} for ref in evidence.derived_from
            ],
            "metadata": metadata,
            "kind": str(metadata.get("kind", "observation")),
            "scope": dict(metadata.get("scope", {}))
            if isinstance(metadata.get("scope"), Mapping)
            else {},
            "provenance_class": provenance_class,
            "content_hash": metadata.get("content_hash"),
        }
        with self.ledger.transaction():
            self.ledger.project_put("epistemics.evidence", evidence.id, value)
            self.ledger.append(
                stream=f"evidence:{evidence.id}",
                kind="epistemics.evidence.recorded",
                payload=value,
                valid_at=evidence.observed_at or evidence.valid_from,
            )

    def record_unknown(self, unknown: Unknown) -> None:
        value = {
            "id": unknown.id,
            "subject": unknown.subject,
            "question": unknown.question,
            "status": "open",
            "blocks": [
                {"kind": ref.kind.value, "id": ref.id} for ref in unknown.blocks
            ],
        }
        with self.ledger.transaction():
            self.ledger.project_put("epistemics.unknown", unknown.id, value)
            self.ledger.append(
                stream=f"unknown:{unknown.id}",
                kind="epistemics.unknown.opened",
                payload=value,
            )

    def resolve_unknown(
        self,
        unknown_id: str,
        *,
        basis_refs: tuple[str, ...],
        resolution: str = "",
    ) -> None:
        if not basis_refs:
            raise ValueError("unknown resolution requires basis_refs")
        current = self.ledger.project_get("epistemics.unknown", unknown_id)
        if current is None:
            raise KeyError(unknown_id)
        value, version = current
        value["status"] = "resolved"
        value["basis_refs"] = list(basis_refs)
        value["resolution"] = resolution
        with self.ledger.transaction():
            self.ledger.project_put(
                "epistemics.unknown",
                unknown_id,
                value,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"unknown:{unknown_id}",
                kind="epistemics.unknown.resolved",
                payload={
                    "id": unknown_id,
                    "basis_refs": list(basis_refs),
                    "resolution": resolution,
                },
            )

    def record_conflict(self, conflict: Conflict) -> None:
        if len(conflict.members) < 2:
            raise ValueError("a conflict requires at least two members")
        value = {
            "id": conflict.id,
            "subject": conflict.subject,
            "members": [
                {"kind": ref.kind.value, "id": ref.id} for ref in conflict.members
            ],
            "description": conflict.description,
            "status": "open",
        }
        with self.ledger.transaction():
            self.ledger.project_put("epistemics.conflict", conflict.id, value)
            self.ledger.append(
                stream=f"conflict:{conflict.id}",
                kind="epistemics.conflict.opened",
                payload=value,
            )

    def resolve_conflict(
        self,
        conflict_id: str,
        *,
        resolution: str,
        basis_refs: tuple[str, ...],
        actor: str,
    ) -> None:
        if not resolution.strip() or not basis_refs or not actor.strip():
            raise ValueError("conflict resolution requires resolution, basis_refs and actor")
        current = self.ledger.project_get("epistemics.conflict", conflict_id)
        if current is None:
            raise KeyError(conflict_id)
        value, version = current
        if value.get("status") == "resolved":
            return
        value["status"] = "resolved"
        value["resolution"] = resolution
        value["basis_refs"] = list(basis_refs)
        value["resolved_by"] = actor
        value["resolved_at"] = utcnow().isoformat()
        with self.ledger.transaction():
            self.ledger.project_put(
                "epistemics.conflict",
                conflict_id,
                value,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"conflict:{conflict_id}",
                kind="epistemics.conflict.resolved",
                payload={
                    "id": conflict_id,
                    "resolution": resolution,
                    "basis_refs": list(basis_refs),
                    "actor": actor,
                },
            )

    def conflict_history(self, conflict_id: str) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            event.payload for event in self.ledger.events(stream=f"conflict:{conflict_id}")
        )

    def assess(
        self,
        *,
        claim: Claim,
        evidence: Evidence,
        verdict: BeliefVerdict,
        rationale: str,
        assessed_by: str,
        evaluator_kind: EvaluatorKind,
        confidence: float | None = None,
        calibration_ref: str | None = None,
    ) -> EvidenceAssessment:
        if confidence is not None:
            if calibration_ref is None:
                raise ValueError("numeric confidence requires calibration_ref")
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("confidence must be in [0, 1]")
        relation = (
            EvidenceRelation.SUPPORTS
            if verdict is BeliefVerdict.SUPPORTED
            else EvidenceRelation.CONTRADICTS
            if verdict is BeliefVerdict.UNSUPPORTED
            else EvidenceRelation.INCONCLUSIVE
        )
        revision = self.current_claim_revision(claim.id)
        assessment = EvidenceAssessment(
            id=new_id("assessment"),
            claim_ref=claim.ref,
            claim_revision_id=revision.id,
            evidence_ref=evidence.ref,
            relation=relation,
            rationale=rationale,
            assessed_by=assessed_by,
            evaluator_kind=evaluator_kind,
            assessed_at=utcnow(),
            confidence=confidence,
            calibration_ref=calibration_ref,
        )
        self._persist_assessment(assessment)
        return assessment

    def deterministic_assess(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        assessed_by: str = "world-runtime:deterministic",
    ) -> EvidenceAssessment:
        revision = self.current_claim_revision(claim_id)
        evidence_row = self.ledger.project_get("epistemics.evidence", evidence_id)
        if evidence_row is None:
            raise KeyError(evidence_id)
        evidence = evidence_row[0]
        scope_relation, evaluated_scope, unevaluated_scope = self._compare_scope(
            revision.scope,
            dict(evidence.get("scope", {})),
        )
        relation = EvidenceRelation.INCONCLUSIVE
        rationale = "no deterministic support or falsification relation"

        if scope_relation == "disjoint":
            relation = EvidenceRelation.IRRELEVANT
            rationale = "evidence scope is disjoint from claim scope"
        elif not self._time_overlaps(revision, evidence):
            relation = EvidenceRelation.INSUFFICIENT_TIME
            rationale = "evidence valid-time does not overlap claim valid-time"
        else:
            falsifier = next(
                (
                    condition
                    for condition in revision.falsification_conditions
                    if self._matches_falsifier(condition, evidence)
                ),
                None,
            )
            if falsifier is not None:
                relation = EvidenceRelation.CONTRADICTS
                rationale = falsifier.description
            elif scope_relation in {"partial", "unknown"}:
                relation = EvidenceRelation.INSUFFICIENT_SCOPE
                rationale = "evidence does not cover the full claim scope"
            else:
                supporting = next(
                    (
                        requirement
                        for requirement in revision.evidence_requirements
                        if self._evidence_matches_requirement(requirement, evidence)
                        and requirement.support_predicate is not None
                        and self._matches_predicate(
                            requirement.support_predicate,
                            evidence,
                        )
                    ),
                    None,
                )
                if supporting is not None:
                    relation = EvidenceRelation.SUPPORTS
                    rationale = (
                        "evidence matched declared support condition for "
                        f"requirement {supporting.id}"
                    )

        identity = self.ledger.project_get("epistemics.claim", claim_id)
        if identity is None:
            raise KeyError(claim_id)
        claim_ref = SemanticRef(kind=Claim(id=claim_id).kind, id=claim_id)
        evidence_ref = SemanticRef(kind=Evidence(id=evidence_id).kind, id=evidence_id)
        assessment = EvidenceAssessment(
            id=new_id("assessment"),
            claim_ref=claim_ref,
            claim_revision_id=revision.id,
            evidence_ref=evidence_ref,
            relation=relation,
            rationale=rationale,
            assessed_by=assessed_by,
            evaluator_kind=EvaluatorKind.DETERMINISTIC,
            assessed_at=utcnow(),
            evaluated_scope=evaluated_scope,
            unevaluated_scope=unevaluated_scope,
        )
        self._persist_assessment(assessment)
        return assessment

    def _persist_assessment(self, assessment: EvidenceAssessment) -> None:
        if self.ledger.project_get(
            "epistemics.evidence",
            assessment.evidence_ref.id,
        ) is None:
            raise ValueError("evidence must be recorded before assessment")
        payload = {
            "id": assessment.id,
            "claim_id": assessment.claim_ref.id,
            "claim_revision_id": assessment.claim_revision_id,
            "evidence_id": assessment.evidence_ref.id,
            "relation": assessment.relation.value,
            "rationale": assessment.rationale,
            "assessed_by": assessment.assessed_by,
            "evaluator_kind": assessment.evaluator_kind.value,
            "assessed_at": assessment.assessed_at.isoformat(),
            "confidence": assessment.confidence,
            "calibration_ref": assessment.calibration_ref,
            "evaluated_scope": dict(assessment.evaluated_scope),
            "unevaluated_scope": dict(assessment.unevaluated_scope),
        }
        with self.ledger.transaction():
            self.ledger.append(
                stream=f"claim:{assessment.claim_ref.id}",
                kind="epistemics.evidence.assessed",
                payload=payload,
                event_id=assessment.id,
                recorded_at=assessment.assessed_at,
            )
            self._recompute_belief(assessment.claim_ref.id)

    def current_belief(
        self,
        claim_id: str,
    ) -> tuple[BeliefVerdict, float | None]:
        row = self.ledger.project_get("epistemics.belief", claim_id)
        if row is None:
            return BeliefVerdict.UNKNOWN, None
        return (
            BeliefVerdict(str(row[0]["verdict"])),
            (
                float(row[0]["calibrated_confidence"])
                if row[0].get("calibrated_confidence") is not None
                else None
            ),
        )

    def belief_state(self, claim_id: str) -> BeliefState:
        row = self.ledger.project_get("epistemics.belief", claim_id)
        if row is None:
            revision = self.current_claim_revision(claim_id)
            return BeliefState(
                claim_id=claim_id,
                claim_revision_id=revision.id,
                verdict=BeliefVerdict.UNKNOWN,
                supporting_assessment_ids=(),
                contradicting_assessment_ids=(),
                satisfied_requirement_ids=(),
                unsatisfied_requirement_ids=tuple(
                    item.id for item in revision.evidence_requirements if item.mandatory
                ),
                stale_requirement_ids=(),
                derived_only_support=False,
                calibrated_confidence=None,
                calibration_refs=(),
            )
        value = row[0]
        return BeliefState(
            claim_id=claim_id,
            claim_revision_id=str(value["claim_revision_id"]),
            verdict=BeliefVerdict(str(value["verdict"])),
            supporting_assessment_ids=tuple(value.get("supporting_assessment_ids", [])),
            contradicting_assessment_ids=tuple(
                value.get("contradicting_assessment_ids", [])
            ),
            satisfied_requirement_ids=tuple(value.get("satisfied_requirement_ids", [])),
            unsatisfied_requirement_ids=tuple(
                value.get("unsatisfied_requirement_ids", [])
            ),
            stale_requirement_ids=tuple(value.get("stale_requirement_ids", [])),
            derived_only_support=bool(value.get("derived_only_support", False)),
            calibrated_confidence=(
                float(value["calibrated_confidence"])
                if value.get("calibrated_confidence") is not None
                else None
            ),
            calibration_refs=tuple(value.get("calibration_refs", [])),
        )

    def _recompute_belief(self, claim_id: str) -> None:
        try:
            revision = self.current_claim_revision(claim_id)
        except KeyError:
            return
        assessments = [
            event.payload
            for event in self.ledger.events(stream=f"claim:{claim_id}")
            if event.kind == "epistemics.evidence.assessed"
            and event.payload.get("claim_revision_id") == revision.id
        ]
        establishing_kinds = {
            EvaluatorKind.DETERMINISTIC.value,
            EvaluatorKind.HUMAN.value,
            EvaluatorKind.DOMAIN_VERIFIER.value,
        }
        establishing_assessments = [
            item
            for item in assessments
            if item.get("evaluator_kind") in establishing_kinds
        ]
        supports = [
            item
            for item in establishing_assessments
            if item.get("relation") == EvidenceRelation.SUPPORTS
        ]
        contradictions = [
            item
            for item in establishing_assessments
            if item.get("relation") == EvidenceRelation.CONTRADICTS
        ]

        satisfied: list[str] = []
        unsatisfied: list[str] = []
        stale: list[str] = []
        supporting_evidence: list[Mapping[str, Any]] = []
        now = utcnow()
        for item in supports:
            evidence = self.ledger.project_get(
                "epistemics.evidence",
                str(item["evidence_id"]),
            )
            if evidence is not None:
                supporting_evidence.append(evidence[0])

        for requirement in (
            item for item in revision.evidence_requirements if item.mandatory
        ):
            matching = [
                evidence
                for evidence in supporting_evidence
                if self._evidence_matches_requirement(requirement, evidence)
            ]
            fresh = [
                evidence
                for evidence in matching
                if not self._is_stale(requirement, evidence, now)
            ]
            if fresh:
                satisfied.append(requirement.id)
            else:
                unsatisfied.append(requirement.id)
                if matching:
                    stale.append(requirement.id)

        derived_only = bool(supporting_evidence) and all(
            evidence.get("provenance_class") == "derived"
            for evidence in supporting_evidence
        )
        mandatory_count = sum(
            1 for item in revision.evidence_requirements if item.mandatory
        )
        non_derived_support = any(
            evidence.get("provenance_class") != "derived"
            for evidence in supporting_evidence
        )

        if contradictions:
            verdict = BeliefVerdict.DISPUTED
        elif revision.declared_status == BeliefVerdict.UNSUPPORTED.value:
            verdict = BeliefVerdict.UNSUPPORTED
        elif mandatory_count and not unsatisfied and not derived_only:
            verdict = BeliefVerdict.SUPPORTED
        elif mandatory_count and stale and len(stale) == len(unsatisfied):
            verdict = BeliefVerdict.STALE
        elif not mandatory_count and non_derived_support:
            verdict = BeliefVerdict.SUPPORTED
        else:
            verdict = BeliefVerdict.UNKNOWN

        calibrated = [
            (float(item["confidence"]), str(item["calibration_ref"]))
            for item in establishing_assessments
            if item.get("confidence") is not None and item.get("calibration_ref")
        ]
        calibrated_confidence = calibrated[-1][0] if calibrated else None
        calibration_refs = tuple(dict.fromkeys(item[1] for item in calibrated))
        value = {
            "claim_id": claim_id,
            "claim_revision_id": revision.id,
            "verdict": verdict.value,
            "supporting_assessment_ids": [str(item["id"]) for item in supports],
            "contradicting_assessment_ids": [
                str(item["id"]) for item in contradictions
            ],
            "satisfied_requirement_ids": satisfied,
            "unsatisfied_requirement_ids": unsatisfied,
            "stale_requirement_ids": stale,
            "derived_only_support": derived_only,
            "calibrated_confidence": calibrated_confidence,
            "calibration_refs": list(calibration_refs),
        }
        self.ledger.project_put("epistemics.belief", claim_id, value)

    def open_unknowns(
        self,
        subject: str | None = None,
    ) -> list[Mapping[str, Any]]:
        values: list[Mapping[str, Any]] = []
        for row in self.ledger.export_projection_rows():
            if row["namespace"] != "epistemics.unknown":
                continue
            value = row["value"]
            if value.get("status") != "open":
                continue
            if subject is None or value.get("subject") == subject:
                values.append(value)
        return values

    @staticmethod
    def _matches_predicate(
        predicate: EvidencePredicate,
        evidence: Mapping[str, Any],
    ) -> bool:
        content = evidence.get("content")
        if not isinstance(content, Mapping):
            return False
        actual = _get_path(content, predicate.path)
        return evaluate_predicate(actual, predicate.op, predicate.value)

    @classmethod
    def _matches_falsifier(
        cls,
        condition: FalsificationCondition,
        evidence: Mapping[str, Any],
    ) -> bool:
        if condition.predicate is None:
            return False
        if (
            condition.evidence_kind is not None
            and condition.evidence_kind != evidence.get("kind")
        ):
            return False
        return cls._matches_predicate(condition.predicate, evidence)

    @classmethod
    def _evidence_matches_requirement(
        cls,
        requirement: EvidenceRequirement,
        evidence: Mapping[str, Any],
    ) -> bool:
        if requirement.kinds and str(evidence.get("kind")) not in requirement.kinds:
            return False
        if (
            requirement.provenance
            and str(evidence.get("provenance_class")) not in requirement.provenance
        ):
            return False
        relation, _, _ = cls._compare_scope(
            requirement.scope,
            dict(evidence.get("scope", {})),
        )
        return relation == "covers"

    @staticmethod
    def _scope_set(value: Any) -> set[str] | None:
        if value == "*":
            return None
        if isinstance(value, list):
            return {str(item) for item in value}
        return {str(value)}

    @classmethod
    def _compare_scope(
        cls,
        required: Mapping[str, Any],
        observed: Mapping[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        evaluated: dict[str, Any] = {}
        unevaluated: dict[str, Any] = {}
        relation = "covers"
        for dimension, required_value in required.items():
            if dimension not in observed:
                relation = "unknown" if relation != "disjoint" else relation
                unevaluated[dimension] = required_value
                continue
            observed_value = observed[dimension]
            required_set = cls._scope_set(required_value)
            observed_set = cls._scope_set(observed_value)
            if required_set is None:
                if observed_set is None:
                    evaluated[dimension] = "*"
                else:
                    relation = "partial" if relation == "covers" else relation
                    evaluated[dimension] = observed_value
                    unevaluated[dimension] = "*"
                continue
            if observed_set is None:
                evaluated[dimension] = required_value
                continue
            overlap = required_set & observed_set
            if not overlap:
                relation = "disjoint"
                unevaluated[dimension] = required_value
                continue
            evaluated[dimension] = sorted(overlap)
            missing = required_set - observed_set
            if missing and relation not in {"disjoint", "unknown"}:
                relation = "partial"
                unevaluated[dimension] = sorted(missing)
        return relation, evaluated, unevaluated

    @staticmethod
    def _time_overlaps(
        revision: ClaimRevision,
        evidence: Mapping[str, Any],
    ) -> bool:
        evidence_from = evidence.get("valid_from") or evidence.get("observed_at")
        evidence_to = evidence.get("valid_to")
        if not evidence_from:
            return True
        start = datetime.fromisoformat(str(evidence_from))
        end = datetime.fromisoformat(str(evidence_to)) if evidence_to else None
        revision_end = revision.valid_to
        return (
            revision.valid_from < (end or datetime.max.replace(tzinfo=revision.valid_from.tzinfo))
            and start < (
                revision_end
                or datetime.max.replace(tzinfo=revision.valid_from.tzinfo)
            )
        )

    @staticmethod
    def _is_stale(
        requirement: EvidenceRequirement,
        evidence: Mapping[str, Any],
        now: datetime,
    ) -> bool:
        if requirement.freshness_seconds is None:
            return False
        anchor = (
            evidence.get("valid_to")
            or evidence.get("valid_from")
            or evidence.get("observed_at")
        )
        if not anchor:
            return True
        observed = datetime.fromisoformat(str(anchor))
        return (now - observed).total_seconds() > requirement.freshness_seconds

    @staticmethod
    def _predicate_value(value: EvidencePredicate | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return {"path": value.path, "op": value.op, "value": value.value}

    @classmethod
    def _requirement_value(cls, value: EvidenceRequirement) -> dict[str, Any]:
        return {
            "id": value.id,
            "kinds": list(value.kinds),
            "provenance": list(value.provenance),
            "scope": dict(value.scope),
            "freshness_seconds": value.freshness_seconds,
            "mandatory": value.mandatory,
            "support_predicate": cls._predicate_value(value.support_predicate),
        }

    @classmethod
    def _requirement_from_value(cls, value: Mapping[str, Any]) -> EvidenceRequirement:
        raw_predicate = value.get("support_predicate")
        predicate = (
            EvidencePredicate(
                path=str(raw_predicate["path"]),
                op=str(raw_predicate["op"]),
                value=raw_predicate.get("value"),
            )
            if isinstance(raw_predicate, Mapping)
            else None
        )
        return EvidenceRequirement(
            id=str(value["id"]),
            kinds=tuple(str(item) for item in value.get("kinds", [])),
            provenance=tuple(str(item) for item in value.get("provenance", [])),
            scope=dict(value.get("scope", {})),
            freshness_seconds=(
                int(value["freshness_seconds"])
                if value.get("freshness_seconds") is not None
                else None
            ),
            mandatory=bool(value.get("mandatory", True)),
            support_predicate=predicate,
        )

    @classmethod
    def _falsifier_value(cls, value: FalsificationCondition) -> dict[str, Any]:
        return {
            "id": value.id,
            "description": value.description,
            "evidence_kind": value.evidence_kind,
            "predicate": cls._predicate_value(value.predicate),
        }

    @classmethod
    def _falsifier_from_value(
        cls,
        value: Mapping[str, Any],
    ) -> FalsificationCondition:
        raw_predicate = value.get("predicate")
        predicate = (
            EvidencePredicate(
                path=str(raw_predicate["path"]),
                op=str(raw_predicate["op"]),
                value=raw_predicate.get("value"),
            )
            if isinstance(raw_predicate, Mapping)
            else None
        )
        return FalsificationCondition(
            id=str(value["id"]),
            description=str(value.get("description", "")),
            evidence_kind=(
                str(value["evidence_kind"])
                if value.get("evidence_kind") is not None
                else None
            ),
            predicate=predicate,
        )

    @classmethod
    def _claim_revision_value(cls, value: ClaimRevision) -> dict[str, Any]:
        return {
            "id": value.id,
            "claim_id": value.claim_id,
            "revision_number": value.revision_number,
            "subject": value.subject,
            "proposition": value.proposition,
            "scope": dict(value.scope),
            "declared_status": value.declared_status,
            "criticality": value.criticality,
            "evidence_requirements": [
                cls._requirement_value(item) for item in value.evidence_requirements
            ],
            "falsification_conditions": [
                cls._falsifier_value(item) for item in value.falsification_conditions
            ],
            "valid_from": value.valid_from.isoformat(),
            "valid_to": value.valid_to.isoformat() if value.valid_to else None,
            "previous_revision_id": value.previous_revision_id,
            "cause_type": value.cause_type,
            "cause_id": value.cause_id,
            "actor": value.actor,
            "recorded_at": value.recorded_at.isoformat(),
            "metadata": dict(value.metadata),
        }

    @classmethod
    def _claim_revision_from_value(
        cls,
        value: Mapping[str, Any],
    ) -> ClaimRevision:
        return ClaimRevision(
            id=str(value["id"]),
            claim_id=str(value["claim_id"]),
            revision_number=int(value["revision_number"]),
            subject=str(value["subject"]),
            proposition=str(value["proposition"]),
            scope=dict(value.get("scope", {})),
            declared_status=str(value.get("declared_status", "unknown")),
            criticality=str(value.get("criticality", "material")),
            evidence_requirements=tuple(
                cls._requirement_from_value(item)
                for item in value.get("evidence_requirements", [])
            ),
            falsification_conditions=tuple(
                cls._falsifier_from_value(item)
                for item in value.get("falsification_conditions", [])
            ),
            valid_from=datetime.fromisoformat(str(value["valid_from"])),
            valid_to=(
                datetime.fromisoformat(str(value["valid_to"]))
                if value.get("valid_to")
                else None
            ),
            previous_revision_id=(
                str(value["previous_revision_id"])
                if value.get("previous_revision_id")
                else None
            ),
            cause_type=str(value["cause_type"]) if value.get("cause_type") else None,
            cause_id=str(value["cause_id"]) if value.get("cause_id") else None,
            actor=str(value.get("actor", "")),
            recorded_at=datetime.fromisoformat(str(value["recorded_at"])),
            metadata=dict(value.get("metadata", {})),
        )


__all__ = [
    "BeliefState",
    "BeliefVerdict",
    "ClaimRevision",
    "EpistemicLedger",
    "EvidenceAssessment",
    "EvidencePredicate",
    "EvidenceRelation",
    "EvidenceRequirement",
    "FalsificationCondition",
    "evaluate_predicate",
]
