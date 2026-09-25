from semantic_language import (
    Claim,
    Evidence,
    Goal,
    SEMANTIC_REF_WIRE_VERSION,
    SemanticKind,
    SemanticRef,
    canonical_json,
    semantic_digest,
)


def test_kinds_and_refs_are_explicit():
    claim = Claim(id="claim:1", subject="checkout", proposition="latency is high")
    assert claim.kind is SemanticKind.CLAIM
    assert claim.ref.id == "claim:1"

    evidence = Evidence(id="evidence:1", subject="checkout", source="telemetry", content={"p95": 910})
    assert evidence.kind is SemanticKind.EVIDENCE
    assert evidence.ref.kind is SemanticKind.EVIDENCE


def test_canonicalization_is_order_independent_for_mappings():
    left = Goal(id="goal:1", subject="checkout", desired_state={"b": 2, "a": 1})
    right = Goal(id="goal:1", subject="checkout", desired_state={"a": 1, "b": 2}, created_at=left.created_at)
    assert canonical_json(left) == canonical_json(right)
    assert semantic_digest(left) == semantic_digest(right)


def test_semantic_ref_wire_version_and_domain_extension_are_explicit():
    ref = SemanticRef(kind="candidate", id="candidate:1", namespace="development")
    assert ref.kind_value == "candidate"
    assert ref.version == SEMANTIC_REF_WIRE_VERSION == "0.1"

    try:
        SemanticRef(kind="candidate", id="candidate:1")
    except ValueError as exc:
        assert "non-universal namespace" in str(exc)
    else:
        raise AssertionError("domain-specific kind must not enter universal namespace")
