from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_internal_components_are_one_distribution() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "aios"' in pyproject
    assert "subdirectory=world-runtime" not in pyproject
    assert "subdirectory=semantic-language" not in pyproject
    assert "git+https://github.com/xiongweilin/aios.git@" not in pyproject


def test_release_configuration_is_owned_by_aios_root() -> None:
    active_paths = (
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "Dockerfile",
        REPO_ROOT / "compose.yaml",
    )
    for path in active_paths:
        assert path.is_file()
        content = path.read_text(encoding="utf-8")
        assert "agent-kernel" not in content
        assert "agent_kernel" not in content
        assert "AGENT_KERNEL" not in content

    for retired_root in (
        "semantic-language",
        "personal-world",
        "world-runtime",
        "control-plane",
        "administrative-orchestrator",
        "autonomous-development",
    ):
        assert not (REPO_ROOT / retired_root).exists()
