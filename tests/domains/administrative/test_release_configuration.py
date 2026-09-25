from pathlib import Path

HEX_DIGITS = frozenset("0123456789abcdef")


def _is_full_git_sha(value: str) -> bool:
    return len(value) == 40 and set(value) <= HEX_DIGITS


def test_world_runtime_dependency_is_immutable_and_agent_kernel_is_absent() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    prefix = (
        "world-runtime @ "
        "git+https://github.com/xiongweilin/aios.git@"
    )
    line = next(
        item.strip().strip('",')
        for item in pyproject.splitlines()
        if prefix in item
    )
    revision_and_path = line.split(prefix, 1)[1]
    revision, subdirectory = revision_and_path.split("#", 1)
    assert _is_full_git_sha(revision)
    assert subdirectory == "subdirectory=world-runtime"

    active_paths = [
        Path("pyproject.toml"),
        Path("compose.production.yaml"),
        Path("Dockerfile"),
        Path("Dockerfile.runtime"),
    ]
    for path in active_paths:
        content = path.read_text(encoding="utf-8")
        assert "agent-kernel" not in content
        assert "agent_kernel" not in content
        assert "AGENT_KERNEL" not in content
