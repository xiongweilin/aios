from semantic_language import SemanticKind

from world_runtime.semantic_ownership import (
    BOUNDARY_OWNERSHIP,
    payload_owner_of,
    validate_boundary_ownership,
)


def test_boundary_ownership_covers_only_universal_roles() -> None:
    validate_boundary_ownership()
    assert {entry.role for entry in BOUNDARY_OWNERSHIP} == set(SemanticKind)


def test_payload_owners_match_actual_subsystem_ownership() -> None:
    assert payload_owner_of(SemanticKind.EVIDENCE) == "world-runtime/epistemics"
    assert payload_owner_of("decision") == "world-runtime/decisions"
    assert payload_owner_of("authorization") == "world-runtime/governance"
    assert payload_owner_of("responsibility") == "world-runtime/responsibility"
    assert payload_owner_of("outcome") == "domain-controller"


def test_semantic_language_does_not_reown_payloads() -> None:
    assert all(entry.payload_owner != "semantic-language" for entry in BOUNDARY_OWNERSHIP)
