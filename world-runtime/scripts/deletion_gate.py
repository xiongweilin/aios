#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

IGNORED_PARTS = {
    ".git", ".github", "docs", "tests", "test", "fixtures", "migrations",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules",
}
MANIFEST_NAMES = {
    "pyproject.toml", "requirements.txt", "requirements-dev.txt", "package.json",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock",
}
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".toml", ".yaml", ".yml", ".json"}
FORBIDDEN_MANIFEST = (
    re.compile(r"\bagent-kernel\b", re.I),
    re.compile(r"\bmeta-controller\b", re.I),
    re.compile(r"\bworld-state\b", re.I),
    re.compile(r"@worldstate/", re.I),
)
FORBIDDEN_ACTIVE = (
    re.compile(r"\bagent_kernel\b"),
    re.compile(r"\bmeta_controller\b"),
    re.compile(r"@worldstate/", re.I),
    re.compile(r"agent-kernel-contracts-v\d+", re.I),
    re.compile(r"meta-controller-contracts-v\d+", re.I),
    re.compile(r"agent-kernel/contracts", re.I),
)

def ignored(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    return any(part in IGNORED_PARTS for part in rel.parts[:-1])

def scan(root: Path) -> list[str]:
    findings: list[str] = []
    gate_script = Path(__file__).resolve()
    for path in root.rglob("*"):
        if not path.is_file() or ignored(path, root):
            continue
        if path.resolve() == gate_script:
            continue
        rel = path.relative_to(root)
        is_manifest = path.name in MANIFEST_NAMES
        is_source = "src" in rel.parts or "app" in rel.parts or "apps" in rel.parts or "scripts" in rel.parts
        if not is_manifest and (not is_source or path.suffix.lower() not in SOURCE_SUFFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        patterns = FORBIDDEN_MANIFEST if is_manifest else FORBIDDEN_ACTIVE
        for pattern in patterns:
            if pattern.search(text):
                findings.append(f"{root.name}/{rel}: {pattern.pattern}")
    return findings

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail when active code or dependency manifests still depend on frozen predecessor repositories."
    )
    parser.add_argument("roots", nargs="+", type=Path)
    args = parser.parse_args()

    findings: list[str] = []
    for root in args.roots:
        if not root.exists():
            findings.append(f"{root}: root does not exist")
            continue
        findings.extend(scan(root.resolve()))

    if findings:
        print("Predecessor deletion gate FAILED:")
        for item in findings:
            print(f"  - {item}")
        return 1

    print("Predecessor deletion gate PASS: no active predecessor dependencies/imports/protocols found.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
