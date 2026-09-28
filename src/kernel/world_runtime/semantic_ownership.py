from __future__ import annotations

from dataclasses import dataclass

from semantic_language import SemanticKind


@dataclass(frozen=True, slots=True)
class BoundaryOwnership:
    """Ownership of a universal semantic role's concrete payload.

    semantic-language owns the role distinction itself. This registry says which
    subsystem owns the concrete payload/lifecycle when AIOS materializes that role.
    """

    role: SemanticKind
    payload_owner: str
    authority_bearing: bool = False


BOUNDARY_OWNERSHIP: tuple[BoundaryOwnership, ...] = (
    BoundaryOwnership(SemanticKind.CLAIM, "world-runtime/epistemics"),
    BoundaryOwnership(SemanticKind.EVIDENCE, "world-runtime/epistemics"),
    BoundaryOwnership(SemanticKind.UNKNOWN, "world-runtime/epistemics"),
    BoundaryOwnership(SemanticKind.DECISION, "world-runtime/decisions", True),
    BoundaryOwnership(SemanticKind.AUTHORIZATION, "world-runtime/governance", True),
    BoundaryOwnership(SemanticKind.EFFECT, "world-runtime/execution"),
    BoundaryOwnership(SemanticKind.OUTCOME, "domain-controller"),
    BoundaryOwnership(SemanticKind.RESPONSIBILITY, "world-runtime/responsibility"),
    BoundaryOwnership(SemanticKind.REVISION, "world-runtime/lineage"),
)


def validate_boundary_ownership(
    entries: tuple[BoundaryOwnership, ...] = BOUNDARY_OWNERSHIP,
) -> None:
    roles = [entry.role for entry in entries]
    if len(roles) != len(set(roles)):
        raise ValueError("universal semantic role has multiple payload owners")
    missing = set(SemanticKind) - set(roles)
    extra = set(roles) - set(SemanticKind)
    if missing or extra:
        raise ValueError(
            f"boundary ownership must cover SemanticKind exactly: "
            f"missing={sorted(item.value for item in missing)}, "
            f"extra={sorted(item.value for item in extra)}"
        )


def payload_owner_of(role: SemanticKind | str) -> str:
    resolved = role if isinstance(role, SemanticKind) else SemanticKind(role)
    validate_boundary_ownership()
    for entry in BOUNDARY_OWNERSHIP:
        if entry.role is resolved:
            return entry.payload_owner
    raise KeyError(resolved.value)


__all__ = [
    "BOUNDARY_OWNERSHIP",
    "BoundaryOwnership",
    "payload_owner_of",
    "validate_boundary_ownership",
]
