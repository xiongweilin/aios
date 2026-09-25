from __future__ import annotations

from personal_world import (
    PERSONAL_WORLD_CONFORMANCE,
    PERSONAL_WORLD_CONTRACT,
    SEMANTIC_LANGUAGE_BASELINE,
    SEMANTIC_REF_WIRE_VERSION,
    __version__,
)

CONFORMANCE = {
    "manifest": PERSONAL_WORLD_CONTRACT,
    "consumer_conformance": PERSONAL_WORLD_CONFORMANCE,
    "package": __version__,
    "semantic_language": SEMANTIC_LANGUAGE_BASELINE,
    "semantic_ref_wire": SEMANTIC_REF_WIRE_VERSION,
    "required_invariants": (
        "source-observation-claim-state-non-substitution",
        "historical-current-non-substitution",
        "projection-truth-non-substitution",
        "personal-context-authority-non-substitution",
        "domain-projection-domain-ownership-non-substitution",
        "model-inference-current-state-non-substitution",
        "revision-cas",
        "purpose-limited-projection",
        "derived-retrieval-index-only",
        "root-subject-isolation",
        "short-lived-workload-identity",
    ),
}


def assert_conformance() -> None:
    expected = {
        "manifest": "personal-world-contracts-v1",
        "consumer_conformance": "personal-world-conformance-v1",
        "package": "1.0.0",
        "semantic_language": "0.2.0",
        "semantic_ref_wire": "0.1",
    }
    for key, value in expected.items():
        if CONFORMANCE[key] != value:
            raise RuntimeError(f"conformance mismatch for {key}: {CONFORMANCE[key]!r}")
    if len(CONFORMANCE["required_invariants"]) != 11:
        raise RuntimeError("conformance invariant set is incomplete for 1.0")
