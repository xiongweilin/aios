import pytest
from semantic_language import (
    NonSubstitutionError,
    SemanticKind,
    SemanticRef,
    assert_distinct,
)


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (SemanticKind.EVIDENCE, SemanticKind.CLAIM),
        (SemanticKind.DECISION, SemanticKind.AUTHORIZATION),
        (SemanticKind.AUTHORIZATION, SemanticKind.EFFECT),
        (SemanticKind.EFFECT, SemanticKind.OUTCOME),
        (
            SemanticRef(SemanticKind.RESPONSIBILITY, "responsibility:1"),
            SemanticKind.EFFECT,
        ),
    ],
)
def test_forbidden_substitutions_fail(actual, expected) -> None:
    with pytest.raises(NonSubstitutionError):
        assert_distinct(actual, expected)
