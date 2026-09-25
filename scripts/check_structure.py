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
    "migrations",
    "scripts",
}
SINGLETON_FILES = {
    ".env.example",
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

    if (ROOT / "config").exists():
        errors.append("component-local config root is forbidden; use root .env/.env.example")

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

    expected_source_packages = {
        "src/aios",
        "src/semantic/semantic_language",
        "src/kernel/personal_world",
        "src/kernel/world_runtime",
        "src/domains/control_plane",
        "src/domains/administrative_orchestrator",
        "src/domains/autonomous_development",
    }
    missing_packages = {
        path
        for path in expected_source_packages
        if not (ROOT / path / "__init__.py").is_file()
    }
    if missing_packages:
        errors.append("source package missing: " + ", ".join(sorted(missing_packages)))

    retired_flat_packages = {
        "semantic_language",
        "personal_world",
        "world_runtime",
        "control_plane",
        "administrative_orchestrator",
        "autonomous_development",
    }
    returned_flat_packages = {
        name for name in retired_flat_packages if (ROOT / "src" / name).exists()
    }
    if returned_flat_packages:
        errors.append(
            "flat component source roots returned: "
            + ", ".join(sorted(returned_flat_packages))
        )

    for group in ("semantic", "kernel", "domains"):
        if not (ROOT / "src" / group).is_dir():
            errors.append(f"source ownership group missing: src/{group}")
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

    runtime_texts = {
        "compose.yaml": compose_text,
        "Dockerfile": (ROOT / "Dockerfile").read_text(encoding="utf-8"),
    }
    for source in (ROOT / "src").rglob("*.py"):
        runtime_texts[source.relative_to(ROOT).as_posix()] = source.read_text(encoding="utf-8")

    forbidden_literals = {
        "/var/lib/aios",
        "/workspace",
        "/app/config",
        "D:\\",
        "C:\\",
        "Path.home()",
        "Path.cwd()",
        "os.getcwd()",
        "__file__",
        ".resolve().parents",
        "sqlite:///./",
        "sqlite+pysqlite:///./",
    }
    for source_name, source_text in runtime_texts.items():
        present = sorted(item for item in forbidden_literals if item in source_text)
        if present:
            errors.append(
                f"hard-coded runtime path in {source_name}: " + ", ".join(present)
            )

    legacy_config_locators = {
        "config/domains/",
        "config/kernel/",
        ".env.production.example",
        "control_plane.toml.example",
        "control_plane.container.toml",
    }
    legacy_source_locators = {
        "src/semantic_language/",
        "src/personal_world/",
        "src/world_runtime/",
        "src/control_plane/",
        "src/administrative_orchestrator/",
        "src/autonomous_development/",
    }
    text_suffixes = {".py", ".md", ".toml", ".yaml", ".yml", ".json", ".txt"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        if path == ROOT / "scripts" / "check_structure.py":
            continue
        try:
            source_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        present = sorted(item for item in legacy_config_locators if item in source_text)
        if present:
            errors.append(
                f"retired component config locator in {path.relative_to(ROOT).as_posix()}: "
                + ", ".join(present)
            )
        old_source_paths = sorted(
            item for item in legacy_source_locators if item in source_text
        )
        if old_source_paths:
            errors.append(
                f"retired flat source locator in {path.relative_to(ROOT).as_posix()}: "
                + ", ".join(old_source_paths)
            )

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

    print("AIOS structure OK: unified project, container-only runtime, configurable paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
