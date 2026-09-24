import pytest

from semantic_language import (
    Authorization,
    Decision,
    Effect,
    Evidence,
    NonSubstitutionError,
    Outcome,
    SemanticKind,
    assert_distinct,
)


@pytest.mark.parametrize(
    ("obj", "expected"),
    [
        (Evidence(id="e:1"), SemanticKind.CLAIM),
        (Decision(id="d:1"), SemanticKind.AUTHORIZATION),
        (Authorization(id="a:1"), SemanticKind.EFFECT),
        (Effect(id="fx:1"), SemanticKind.OUTCOME),
        (Outcome(id="o:1"), SemanticKind.ACCEPTANCE),
    ],
)
def test_forbidden_substitutions_fail(obj, expected):
    with pytest.raises(NonSubstitutionError):
        assert_distinct(obj, expected)
