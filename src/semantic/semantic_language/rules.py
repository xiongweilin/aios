from __future__ import annotations

from .core import SemanticKind, SemanticRef


KindLike = SemanticKind | str | SemanticRef


_BOUNDARIES: frozenset[frozenset[str]] = frozenset(
    {
        frozenset((SemanticKind.CLAIM.value, SemanticKind.EVIDENCE.value)),
        frozenset((SemanticKind.DECISION.value, SemanticKind.AUTHORIZATION.value)),
        frozenset((SemanticKind.AUTHORIZATION.value, SemanticKind.EFFECT.value)),
        frozenset((SemanticKind.EFFECT.value, SemanticKind.OUTCOME.value)),
        frozenset((SemanticKind.RESPONSIBILITY.value, SemanticKind.EFFECT.value)),
    }
)


class NonSubstitutionError(ValueError):
    pass


def _kind_value(value: KindLike) -> str:
    if isinstance(value, SemanticRef):
        return value.kind_value
    if isinstance(value, SemanticKind):
        return value.value
    return str(value)


def distinction(left: KindLike, right: KindLike) -> bool:
    return frozenset((_kind_value(left), _kind_value(right))) in _BOUNDARIES


def assert_distinct(actual: KindLike, expected: KindLike) -> None:
    actual_value = _kind_value(actual)
    expected_value = _kind_value(expected)
    if actual_value == expected_value:
        return
    if distinction(actual_value, expected_value):
        raise NonSubstitutionError(
            f"{actual_value} is not a valid substitute for {expected_value}"
        )
    raise TypeError(f"expected {expected_value}, received {actual_value}")
