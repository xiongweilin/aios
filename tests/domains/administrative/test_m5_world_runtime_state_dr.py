from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import administrative_orchestrator.world_runtime_state_dr as runtime_state_dr
from administrative_orchestrator.world_runtime_state_dr import (
    WorldRuntimeStateRecoveryError,
    backup_world_runtime_state,
    restore_world_runtime_state,
    verify_world_runtime_state_backup,
)


def _create_state(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE attempts (request_ref TEXT PRIMARY KEY, state TEXT NOT NULL)")
        db.execute("INSERT INTO attempts VALUES (?, ?)", ("req-1", "reconciling"))
        db.commit()


def test_world_runtime_state_backup_verify_restore_round_trip(tmp_path: Path):
    source = tmp_path / "runtime.db"
    backup = tmp_path / "backup" / "runtime.db"
    restored = tmp_path / "restored.db"
    backup.parent.mkdir()
    _create_state(source)

    digest = backup_world_runtime_state(source, backup)
    assert len(digest) == 64
    assert verify_world_runtime_state_backup(backup) == digest
    assert backup.with_name("runtime.db.sha256").is_file()

    restored_digest = restore_world_runtime_state(backup, restored)
    assert restored_digest == digest
    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT request_ref, state FROM attempts").fetchall() == [
            ("req-1", "reconciling")
        ]


def test_world_runtime_state_restore_requires_explicit_force(tmp_path: Path):
    source = tmp_path / "runtime.db"
    backup = tmp_path / "backup.db"
    destination = tmp_path / "destination.db"
    _create_state(source)
    backup_world_runtime_state(source, backup)
    _create_state(destination)

    with pytest.raises(WorldRuntimeStateRecoveryError, match="already exists"):
        restore_world_runtime_state(backup, destination)
    restore_world_runtime_state(backup, destination, force=True)


def test_world_runtime_state_manifest_detects_tampering(tmp_path: Path):
    source = tmp_path / "runtime.db"
    backup = tmp_path / "backup.db"
    _create_state(source)
    backup_world_runtime_state(source, backup)
    manifest = backup.with_name("backup.db.sha256")
    manifest.write_text("0" * 64 + "  backup.db\n", encoding="utf-8")

    with pytest.raises(WorldRuntimeStateRecoveryError, match="digest does not match"):
        verify_world_runtime_state_backup(backup)


def test_world_runtime_restore_reraises_atomic_replace_permission_for_new_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "runtime.db"
    backup = tmp_path / "backup.db"
    _create_state(source)
    backup_world_runtime_state(source, backup)

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(runtime_state_dr.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="locked"):
        restore_world_runtime_state(backup, tmp_path / "new.db", force=True)
