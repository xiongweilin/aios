"""Keep operator-facing production commands aligned with the checked-in scripts.

This is a static reference test, not an authorization to execute production effects.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = ROOT / "docs/domains/administrative/production-operations.md"


def test_documented_script_commands_resolve_in_repository() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    scripts = set(re.findall(r"(?<![\\w/])(scripts/(?:[\\w-]+/)*[\\w-]+\\.py)", text))
    assert scripts, "No executable script references found in the production runbook"
    assert all((ROOT / script).is_file() for script in scripts), sorted(
        script for script in scripts if not (ROOT / script).is_file()
    )


def test_production_factory_resolves_to_checked_in_definition() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    match = re.search(r"WORLD_RUNTIME_FACTORY=(scripts(?:\\.[a-z_]+)+):([a-z_]+)", text)
    assert match is not None
    module, function = match.groups()
    source = ROOT / (module.replace(".", "/") + ".py")
    assert source.is_file(), module
    assert re.search(rf"(?m)^def {re.escape(function)}\\(", source.read_text(encoding="utf-8"))


def test_runbook_build_file_exists() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "root `Dockerfile`" in text
    assert (ROOT / "Dockerfile").is_file()
