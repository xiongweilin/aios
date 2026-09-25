from pathlib import Path


def test_no_embedded_or_predecessor_runtime_code() -> None:
    root = Path(__file__).resolve().parents[3]
    forbidden_paths = [
        "src/agent_kernel",
        "src/meta_controller",
        "agent-kernel-pin.json",
        "MIGRATION.md",
        "deployments/portable-local",
        "src/control_plane/service.py",
        "src/control_plane/storage.py",
        "src/control_plane/portable_authority.py",
        "src/control_plane/closure_authority.py",
        "src/control_plane/reconciliation.py",
        "src/control_plane/state_machine.py",
        "src/control_plane/verifier.py",
        "src/control_plane/codex_runner.py",
        "src/control_plane/budget.py",
        "src/control_plane/evidence.py",
        "src/control_plane/outward_semantics.py",
        "src/control_plane/kernel_bridge.py",
    ]
    leftovers = [path for path in forbidden_paths if (root / path).exists()]
    assert leftovers == []


def test_profile_source_has_no_world_runtime_python_imports() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "control_plane"
    predecessor_imports = ("from agent_" + "kernel", "from meta_" + "controller")
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    for token in predecessor_imports:
        assert token not in text
    assert "from world_runtime" not in text
    assert "import world_runtime" not in text


def test_profile_has_no_world_runtime_package_dependency() -> None:
    root = Path(__file__).resolve().parents[3]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "world-runtime @" not in pyproject
    assert "world-runtime.git" not in pyproject
    assert not (root / "uv.lock").exists()
