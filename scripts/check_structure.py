from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED_PROJECT_ROOTS = {
    "semantic-language",
    "personal-world",
    "world-runtime",
    "control-plane",
    "administrative-orchestrator",
    "autonomous-development",
}
REQUIRED_ROOTS = {
    "src",
    "tests",
    "docs",
    "config",
    "migrations",
    "scripts",
}
SINGLETON_FILES = {
    "pyproject.toml",
    "sonar-project.properties",
    "Dockerfile",
    "compose.yaml",
}


def main() -> int:
    errors: list[str] = []

    for name in sorted(RETIRED_PROJECT_ROOTS):
        if (ROOT / name).exists():
            errors.append(f"retired project root returned: {name}")

    for name in sorted(REQUIRED_ROOTS):
        if not (ROOT / name).is_dir():
            errors.append(f"required unified root missing: {name}")

    for name in sorted(SINGLETON_FILES):
        if not (ROOT / name).is_file():
            errors.append(f"root-owned file missing: {name}")

    nested_singletons = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if (
            len(relative.parts) > 1
            and relative.parts[0] != "tests"
            and path.name
            in {
                "pyproject.toml",
                "uv.lock",
                "sonar-project.properties",
                "Dockerfile",
                "Dockerfile.runtime",
                "compose.yaml",
                "compose.production.yaml",
            }
        ):
            nested_singletons.append(relative.as_posix())
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            errors.append(f"generated Python artifact is tracked: {relative.as_posix()}")

    if nested_singletons:
        errors.append(
            "component-local project/build roots are forbidden: "
            + ", ".join(sorted(nested_singletons))
        )

    expected_packages = {
        "aios",
        "semantic_language",
        "personal_world",
        "world_runtime",
        "control_plane",
        "administrative_orchestrator",
        "autonomous_development",
    }
    actual_packages = {
        path.name
        for path in (ROOT / "src").iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }
    missing_packages = expected_packages - actual_packages
    if missing_packages:
        errors.append("source package missing: " + ", ".join(sorted(missing_packages)))

    for group in ("semantic", "kernel", "domains"):
        if not (ROOT / "tests" / group).is_dir():
            errors.append(f"test ownership group missing: tests/{group}")
        if not (ROOT / "docs" / group).is_dir():
            errors.append(f"documentation ownership group missing: docs/{group}")

    compose_text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    required_services = {
        "postgres",
        "personal-world",
        "world-runtime",
        "control-plane",
        "administrative-api",
        "administrative-worker",
        "autonomous-development",
    }
    missing_services = {
        service
        for service in required_services
        if f"  {service}:\n" not in compose_text
    }
    if missing_services:
        errors.append(
            "container runtime service missing: " + ", ".join(sorted(missing_services))
        )
    if "host.docker.internal" in compose_text:
        errors.append("host-local runtime dependency is forbidden in compose.yaml")
    if "profiles:" in compose_text:
        errors.append("AIOS runtime services must not depend on optional Compose profiles")

    forbidden_runtime_paths = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if relative.parts[0] not in {"deploy", "scripts"}:
            continue
        if path.suffix.lower() in {".ps1", ".bat", ".cmd", ".service", ".timer"}:
            forbidden_runtime_paths.append(relative.as_posix())
    if forbidden_runtime_paths:
        errors.append(
            "native runtime/deployment entrypoints are forbidden: "
            + ", ".join(sorted(forbidden_runtime_paths))
        )

    if errors:
        print("\n".join(errors))
        return 1

    print("AIOS structure OK: one project root, one source tree, one test tree, container-only runtime")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
