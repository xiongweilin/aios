from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_ROOT = REPO_ROOT / "docs" / "domains" / "administrative"
CANONICAL_LANGUAGE_FILES = (
    DOC_ROOT / "contracts" / "domain-model.md",
    DOC_ROOT / "contracts" / "workflow-authority.md",
    DOC_ROOT / "architecture.md",
)
CURRENT_LANGUAGE_FILES = (DOC_ROOT / "README.md", *CANONICAL_LANGUAGE_FILES)
MILESTONE_TOKENS = {f"M{number}" for number in range(20)}


def _words(text: str) -> set[str]:
    normalized = "".join(character if character.isalnum() else " " for character in text)
    return set(normalized.split())


def test_canonical_language_does_not_depend_on_delivery_milestones() -> None:
    for path in CANONICAL_LANGUAGE_FILES:
        milestone_words = _words(path.read_text(encoding="utf-8")) & MILESTONE_TOKENS
        assert not milestone_words, f"{path} leaks milestone vocabulary: {milestone_words}"


def test_current_language_uses_runtime_execution_authorization_term() -> None:
    for path in CURRENT_LANGUAGE_FILES:
        text = path.read_text(encoding="utf-8")
        assert "AdministrativeExecutionGrant" not in text
        assert "ExecutionAuthorization" in text


def test_readme_routes_to_current_contracts() -> None:
    text = (DOC_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/contracts/domain-model.md" not in text
    assert "contracts/domain-model.md" in text
    assert "contracts/workflow-authority.md" in text
    assert "Historical identifiers" not in text
