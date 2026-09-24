import inspect
from dataclasses import is_dataclass

from pydantic import BaseModel

import world_runtime
import world_runtime.cognition as cognition
from world_runtime.semantic_ownership import (
    IMPLEMENTATION_ONLY_PUBLIC_CLASSES,
    PUBLIC_SEMANTIC_CLASSES,
    SEMANTIC_OWNERS,
    owner_of,
    public_semantic_classification,
    validate_semantic_owners,
)


def _public_semantic_bearing_classes() -> set[str]:
    symbols: set[str] = set()
    for module in (world_runtime, cognition):
        for name in getattr(module, "__all__", ()):
            value = getattr(module, name, None)
            if not inspect.isclass(value):
                continue
            is_pydantic = issubclass(value, BaseModel)
            if is_dataclass(value) or is_pydantic:
                symbols.add(f"{module.__name__}.{name}")
    return symbols


def test_semantic_concepts_have_single_canonical_owner() -> None:
    validate_semantic_owners()
    concepts = [entry.concept for entry in SEMANTIC_OWNERS]
    assert len(concepts) == len(set(concepts))


def test_universal_meaning_is_not_reowned_by_runtime() -> None:
    assert owner_of("Evidence") == "semantic-language"
    assert owner_of("Decision") == "semantic-language"
    assert owner_of("Authorization") == "semantic-language"
    assert owner_of("Outcome") == "semantic-language"
    assert owner_of("DomainAssignment") == "world-runtime/domains"
    assert owner_of("DomainOutcomeQualification") == "domain-controller"


def test_every_public_semantic_bearing_class_is_classified() -> None:
    classified = set(public_semantic_classification())
    implementation_only = set(IMPLEMENTATION_ONLY_PUBLIC_CLASSES)
    actual = _public_semantic_bearing_classes()

    missing = actual - classified - implementation_only
    stale = classified - actual
    assert not missing, f"unclassified public semantic classes: {sorted(missing)}"
    assert not stale, f"stale semantic class declarations: {sorted(stale)}"


def test_predecessor_named_cognition_surface_has_explicit_non_owner_status() -> None:
    classifications = public_semantic_classification()
    assert classifications["world_runtime.cognition.MetaControlIntent"].owner == (
        "world-runtime/cognition"
    )
    assert "world_runtime.cognition.MetaControllerEngine" in IMPLEMENTATION_ONLY_PUBLIC_CLASSES
    assert "world_runtime.cognition.MetaPolicyJournal" in IMPLEMENTATION_ONLY_PUBLIC_CLASSES
    assert "world_runtime.cognition.StagedMetaPolicy" in IMPLEMENTATION_ONLY_PUBLIC_CLASSES


def test_public_semantic_class_owner_matches_canonical_owner_when_registered() -> None:
    canonical = {entry.concept: entry.owner for entry in SEMANTIC_OWNERS}
    for entry in PUBLIC_SEMANTIC_CLASSES:
        if entry.canonical_concept in canonical:
            assert entry.owner == canonical[entry.canonical_concept]
