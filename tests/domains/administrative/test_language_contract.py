from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_LANGUAGE_FILES = (
    ROOT / "docs/contracts/domain-model.md",
    ROOT / "docs/contracts/workflow-authority.md",
    ROOT / "docs/architecture.md",
)
CURRENT_LANGUAGE_FILES = (ROOT / "README.md", *CANONICAL_LANGUAGE_FILES)
MILESTONE_TOKENS = {f"M{number}" for number in range(20)}


def _words(text: str) -> set[str]:
    normalized = "".join(character if character.isalnum() else " " for character in text)
    return set(normalized.split())


def test_canonical_language_does_not_depend_on_delivery_milestones() -> None:
    for path in CANONICAL_LANGUAGE_FILES:
        milestone_words = _words(path.read_text(encoding="utf-8")) & MILESTONE_TOKENS
        assert not milestone_words, f"{path} leaks milestone vocabulary: {milestone_words}"


def test_current_language_uses_the_runtime_execution_authorization_term() -> None:
    for path in CURRENT_LANGUAGE_FILES:
        text = path.read_text(encoding="utf-8")
        assert "AdministrativeExecutionGrant" not in text
        assert "ExecutionAuthorization" in text


def test_readme_separates_current_v1_from_historical_stages() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/contracts/domain-model.md" in text
    assert "## Historical identifiers" in text
    assert "Staged M5–M9 deployment and acceptance artifacts are preserved" in text
    assert "Current V1 acceptance" in text
    assert "Production Trust workflow" in text
