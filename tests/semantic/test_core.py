from semantic_language import (
    SEMANTIC_REF_WIRE_VERSION,
    SemanticKind,
    SemanticRef,
    canonical_json,
    semantic_digest,
)


def test_universal_roles_are_small_and_explicit() -> None:
    assert {item.value for item in SemanticKind} == {
        "claim",
        "evidence",
        "unknown",
        "decision",
        "authorization",
        "effect",
        "outcome",
        "responsibility",
        "revision",
    }


def test_canonicalization_is_order_independent_for_refs() -> None:
    left = {
        "subject": "checkout",
        "desired_state": {"b": 2, "a": 1},
        "ref": SemanticRef(kind="goal", id="goal:1", namespace="strategy"),
    }
    right = {
        "ref": SemanticRef(kind="goal", id="goal:1", namespace="strategy"),
        "desired_state": {"a": 1, "b": 2},
        "subject": "checkout",
    }
    assert canonical_json(left) == canonical_json(right)
    assert semantic_digest(left) == semantic_digest(right)


def test_semantic_ref_wire_version_and_owner_extension_are_explicit() -> None:
    ref = SemanticRef(kind="candidate", id="candidate:1", namespace="development")
    assert ref.kind_value == "candidate"
    assert ref.version == SEMANTIC_REF_WIRE_VERSION == "0.1"

    try:
        SemanticRef(kind="candidate", id="candidate:1")
    except ValueError as exc:
        assert "non-universal namespace" in str(exc)
    else:
        raise AssertionError("owner-specific kind must not enter universal namespace")
