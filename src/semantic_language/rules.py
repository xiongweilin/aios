from __future__ import annotations

from .core import SemanticKind, SemanticObject


_DISTINCTIONS: frozenset[frozenset[SemanticKind]] = frozenset(
    {
        frozenset((SemanticKind.CLAIM, SemanticKind.EVIDENCE)),
        frozenset((SemanticKind.GOAL, SemanticKind.CLAIM)),
        frozenset((SemanticKind.CONSTRAINT, SemanticKind.GOAL)),
        frozenset((SemanticKind.PROPOSAL, SemanticKind.DECISION)),
        frozenset((SemanticKind.DECISION, SemanticKind.AUTHORIZATION)),
        frozenset((SemanticKind.AUTHORIZATION, SemanticKind.EFFECT)),
        frozenset((SemanticKind.ACTION, SemanticKind.EFFECT)),
        frozenset((SemanticKind.EFFECT, SemanticKind.OUTCOME)),
        frozenset((SemanticKind.OUTCOME, SemanticKind.ACCEPTANCE)),
        frozenset((SemanticKind.RESPONSIBILITY, SemanticKind.ACTION)),
    }
)


class NonSubstitutionError(ValueError):
    pass


def distinction(left: SemanticKind, right: SemanticKind) -> bool:
    return frozenset((left, right)) in _DISTINCTIONS


def assert_distinct(actual: SemanticObject, expected_kind: SemanticKind) -> None:
    if actual.kind == expected_kind:
        return
    if distinction(actual.kind, expected_kind):
        raise NonSubstitutionError(
            f"{actual.kind.value} is not a valid substitute for {expected_kind.value}"
        )
    raise TypeError(f"expected {expected_kind.value}, received {actual.kind.value}")
