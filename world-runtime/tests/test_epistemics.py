from datetime import UTC, datetime, timedelta

import pytest
from semantic_language import Claim, Conflict, Evidence, SemanticKind, SemanticRef, Unknown

from world_runtime import (
    BeliefVerdict,
    EvidencePredicate,
    EvidenceRelation,
    EvidenceRequirement,
    EvaluatorKind,
    FalsificationCondition,
    WorldRuntime,
)


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def test_unknown_is_first_class_and_evidence_is_immutable() -> None:
    runtime = WorldRuntime.sqlite()
    claim = Claim(id="claim:latency", subject="checkout", proposition="p95 > 500ms")
    evidence = Evidence(
        id="evidence:1",
        subject="checkout",
        source="telemetry",
        content={"p95": 910},
    )
    unknown = Unknown(
        id="unknown:1",
        subject="checkout",
        question="traffic-specific?",
    )
    runtime.epistemics.record_claim(claim)
    runtime.epistemics.record_evidence(evidence)
    runtime.epistemics.record_unknown(unknown)
    assert runtime.epistemics.current_belief(claim.id) == (
        BeliefVerdict.UNKNOWN,
        None,
    )
    runtime.epistemics.assess(
        claim=claim,
        evidence=evidence,
        verdict=BeliefVerdict.SUPPORTED,
        rationale="direct telemetry",
        assessed_by="verifier",
        evaluator_kind=EvaluatorKind.DOMAIN_VERIFIER,
    )
    assert runtime.epistemics.current_belief(claim.id)[0] is BeliefVerdict.SUPPORTED
    with pytest.raises(ValueError, match="immutable"):
        runtime.epistemics.record_evidence(evidence)


def test_numeric_confidence_requires_explicit_calibration_contract() -> None:
    runtime = WorldRuntime.sqlite()
    claim = Claim(id="claim:1", subject="x", proposition="x")
    evidence = Evidence(id="evidence:1", subject="x", source="test", content={"x": 1})
    runtime.epistemics.record_claim(claim)
    runtime.epistemics.record_evidence(evidence)

    with pytest.raises(ValueError, match="calibration_ref"):
        runtime.epistemics.assess(
            claim=claim,
            evidence=evidence,
            verdict=BeliefVerdict.SUPPORTED,
            confidence=0.9,
            rationale="uncalibrated",
            assessed_by="model",
            evaluator_kind=EvaluatorKind.MODEL,
        )

    runtime.epistemics.assess(
        claim=claim,
        evidence=evidence,
        verdict=BeliefVerdict.SUPPORTED,
        confidence=0.8,
        calibration_ref="calibration:telemetry-v1",
        rationale="calibrated",
        assessed_by="verifier",
        evaluator_kind=EvaluatorKind.DOMAIN_VERIFIER,
    )
    state = runtime.epistemics.belief_state(claim.id)
    assert state.calibrated_confidence == 0.8
    assert state.calibration_refs == ("calibration:telemetry-v1",)


def test_claim_revision_is_append_only_and_bitemporal() -> None:
    runtime = WorldRuntime.sqlite()
    claim = Claim(id="claim:latency", subject="checkout", proposition="p95 < 500")
    first = runtime.epistemics.record_claim(
        claim,
        actor="service:test",
        valid_from=NOW,
        valid_to=NOW + timedelta(days=1),
    )
    second = runtime.epistemics.revise_claim(
        claim.id,
        proposition="p95 < 400",
        actor="service:test",
        valid_from=NOW + timedelta(days=1),
    )

    history = runtime.epistemics.claim_history(claim.id)
    assert [item.revision_number for item in history] == [1, 2]
    assert second.previous_revision_id == first.id
    assert runtime.epistemics.claim_revision_as_of(
        claim.id,
        valid_at=NOW + timedelta(hours=12),
    ).id == first.id
    assert runtime.epistemics.claim_revision_as_of(
        claim.id,
        valid_at=NOW + timedelta(days=2),
    ).id == second.id
    before_second_was_recorded = second.recorded_at - timedelta(microseconds=1)
    assert runtime.epistemics.claim_revision_as_of(
        claim.id,
        valid_at=NOW + timedelta(days=2),
        recorded_at=before_second_was_recorded,
    ) is None


def test_deterministic_falsification_and_support_requirements_drive_belief() -> None:
    runtime = WorldRuntime.sqlite()
    claim = Claim(id="claim:latency", subject="checkout", proposition="p95 < 500")
    requirement = EvidenceRequirement(
        id="requirement:telemetry",
        kinds=("runtime_observation",),
        provenance=("primary",),
        scope={"service": "checkout"},
        support_predicate=EvidencePredicate(path="p95", op="lt", value=500),
    )
    falsifier = FalsificationCondition(
        id="falsifier:latency",
        description="latency exceeded threshold",
        evidence_kind="runtime_observation",
        predicate=EvidencePredicate(path="p95", op="gte", value=500),
    )
    runtime.epistemics.record_claim(
        claim,
        scope={"service": "checkout"},
        evidence_requirements=(requirement,),
        falsification_conditions=(falsifier,),
    )

    supporting = Evidence(
        id="evidence:support",
        subject="checkout",
        source="telemetry",
        content={"p95": 420},
        metadata={
            "kind": "runtime_observation",
            "scope": {"service": "checkout"},
            "provenance_class": "primary",
        },
    )
    runtime.epistemics.record_evidence(supporting)
    assessment = runtime.epistemics.deterministic_assess(
        claim_id=claim.id,
        evidence_id=supporting.id,
    )
    assert assessment.relation is EvidenceRelation.SUPPORTS
    assert runtime.epistemics.current_belief(claim.id)[0] is BeliefVerdict.SUPPORTED

    contradiction = Evidence(
        id="evidence:contradiction",
        subject="checkout",
        source="telemetry",
        content={"p95": 700},
        metadata={
            "kind": "runtime_observation",
            "scope": {"service": "checkout"},
            "provenance_class": "primary",
        },
    )
    runtime.epistemics.record_evidence(contradiction)
    assessment = runtime.epistemics.deterministic_assess(
        claim_id=claim.id,
        evidence_id=contradiction.id,
    )
    assert assessment.relation is EvidenceRelation.CONTRADICTS
    assert runtime.epistemics.current_belief(claim.id)[0] is BeliefVerdict.DISPUTED


def test_conflict_resolution_preserves_open_and_resolution_history() -> None:
    runtime = WorldRuntime.sqlite()
    conflict = Conflict(
        id="conflict:1",
        subject="checkout",
        members=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:1"),
            SemanticRef(SemanticKind.EVIDENCE, "evidence:2"),
        ),
        description="two measurements disagree",
    )
    runtime.epistemics.record_conflict(conflict)
    runtime.epistemics.resolve_conflict(
        conflict.id,
        resolution="measurement 2 used stale configuration",
        basis_refs=("evidence:3",),
        actor="service:verifier",
    )

    history = runtime.epistemics.conflict_history(conflict.id)
    assert len(history) == 2
    assert history[0]["status"] == "open"
    assert history[1]["resolution"] == "measurement 2 used stale configuration"
    current = runtime.ledger.project_get("epistemics.conflict", conflict.id)
    assert current is not None
    assert current[0]["status"] == "resolved"


def test_derived_evidence_cannot_masquerade_as_independent_observation() -> None:
    runtime = WorldRuntime.sqlite()
    claim = Claim(id="claim:derived", subject="x", proposition="x is true")
    primary = Evidence(
        id="evidence:primary",
        subject="x",
        source="sensor",
        content={"value": True},
        metadata={"provenance_class": "primary"},
    )
    runtime.epistemics.record_claim(claim)
    runtime.epistemics.record_evidence(primary)

    derived = Evidence(
        id="evidence:derived",
        subject="x",
        source="model-synthesis",
        content={"value": True},
        derived_from=(SemanticRef(SemanticKind.EVIDENCE, primary.id),),
    )
    runtime.epistemics.record_evidence(derived)
    stored = runtime.ledger.project_get("epistemics.evidence", derived.id)
    assert stored is not None
    assert stored[0]["provenance_class"] == "derived"

    runtime.epistemics.assess(
        claim=claim,
        evidence=derived,
        verdict=BeliefVerdict.SUPPORTED,
        rationale="synthesized from existing evidence",
        assessed_by="service:verifier",
        evaluator_kind=EvaluatorKind.DOMAIN_VERIFIER,
    )
    assert runtime.epistemics.current_belief(claim.id)[0] is BeliefVerdict.UNKNOWN

    bad = Evidence(
        id="evidence:bad-derived",
        subject="x",
        source="model-synthesis",
        content={"value": True},
        derived_from=(SemanticRef(SemanticKind.EVIDENCE, primary.id),),
        metadata={"provenance_class": "runtime_observation"},
    )
    with pytest.raises(ValueError, match="derived_from"):
        runtime.epistemics.record_evidence(bad)


def test_model_assessment_is_recorded_but_cannot_establish_belief() -> None:
    runtime = WorldRuntime.sqlite()
    claim = Claim(id="claim:model", subject="x", proposition="x is true")
    evidence = Evidence(
        id="evidence:model-input",
        subject="x",
        source="telemetry",
        content={"value": True},
        metadata={"provenance_class": "primary"},
    )
    runtime.epistemics.record_claim(claim)
    runtime.epistemics.record_evidence(evidence)

    assessment = runtime.epistemics.assess(
        claim=claim,
        evidence=evidence,
        verdict=BeliefVerdict.SUPPORTED,
        rationale="model interpretation",
        assessed_by="model:reasoner",
        evaluator_kind=EvaluatorKind.MODEL,
    )
    assert assessment.evaluator_kind is EvaluatorKind.MODEL
    assert runtime.epistemics.current_belief(claim.id)[0] is BeliefVerdict.UNKNOWN

    runtime.epistemics.assess(
        claim=claim,
        evidence=evidence,
        verdict=BeliefVerdict.SUPPORTED,
        rationale="human verified the telemetry interpretation",
        assessed_by="human:operator",
        evaluator_kind=EvaluatorKind.HUMAN,
    )
    assert runtime.epistemics.current_belief(claim.id)[0] is BeliefVerdict.SUPPORTED
