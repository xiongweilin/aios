from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .migrations import MigrationReport, SemanticMigrator
from .runtime import WorldRuntime


@dataclass(frozen=True, slots=True)
class AcceptedSnapshotResult:
    source: str
    frozen_sha: str
    report: MigrationReport
    namespaces: frozenset[str]


def verify_accepted_snapshot(
    snapshot: dict[str, Any],
    *,
    required_namespaces: set[str] | frozenset[str] = frozenset(),
) -> AcceptedSnapshotResult:
    source = str(snapshot["source"])
    frozen_sha = str(snapshot["frozen_sha"])
    records = snapshot.get("records")
    if not isinstance(records, list):
        raise ValueError("accepted snapshot records must be a list")
    namespaces = frozenset(
        str(item.get("namespace", ""))
        for item in records
        if isinstance(item, dict)
    )
    missing = set(required_namespaces) - namespaces
    if missing:
        raise ValueError(
            "accepted snapshot is missing required namespaces: "
            + ", ".join(sorted(missing))
        )
    runtime = WorldRuntime.sqlite()
    report = SemanticMigrator(runtime).import_records(source, records)
    if not report.deletion_ready:
        unresolved = [
            f"{entry.namespace}:{entry.source_id}:{entry.disposition.value}:{entry.reason}"
            for entry in report.entries
            if entry.disposition.value in {"unresolved", "rejected"}
        ]
        raise RuntimeError(
            f"accepted predecessor snapshot {source}@{frozen_sha} did not reconcile: "
            + " | ".join(unresolved)
        )
    return AcceptedSnapshotResult(
        source=source,
        frozen_sha=frozen_sha,
        report=report,
        namespaces=namespaces,
    )


def verify_accepted_snapshot_directory(root: Path) -> tuple[AcceptedSnapshotResult, ...]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != "predecessor-migration-acceptance-v1":
        raise ValueError("unsupported predecessor migration acceptance manifest")
    results: list[AcceptedSnapshotResult] = []
    for item in manifest.get("snapshots", []):
        fixture = root / str(item["fixture"])
        snapshot = json.loads(fixture.read_text(encoding="utf-8"))
        if snapshot.get("source") != item.get("source"):
            raise ValueError("accepted snapshot source does not match manifest")
        if snapshot.get("frozen_sha") != item.get("frozen_sha"):
            raise ValueError("accepted snapshot frozen sha does not match manifest")
        results.append(
            verify_accepted_snapshot(
                snapshot,
                required_namespaces=set(item.get("required_namespaces", [])),
            )
        )
    return tuple(results)


__all__ = [
    "AcceptedSnapshotResult",
    "verify_accepted_snapshot",
    "verify_accepted_snapshot_directory",
]
