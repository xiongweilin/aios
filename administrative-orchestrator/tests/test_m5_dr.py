from __future__ import annotations

import sqlite3

from administrative_orchestrator.world_runtime_state_dr import (
    backup_world_runtime_state,
    restore_world_runtime_state,
    verify_world_runtime_state_backup,
)
from scripts.world_runtime_state_backup import main


def test_world_runtime_state_online_backup_restore_round_trip(tmp_path):
    source = tmp_path / "runtime.db"
    backup_path = tmp_path / "backups" / "runtime.db"
    restored = tmp_path / "restored" / "runtime.db"
    backup_path.parent.mkdir()
    restored.parent.mkdir()
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE recovery_fact (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        db.execute("INSERT INTO recovery_fact VALUES ('attempt:1', 'execution-unknown')")
        db.commit()

    digest = backup_world_runtime_state(source, backup_path)
    assert verify_world_runtime_state_backup(backup_path) == digest

    with sqlite3.connect(source) as db:
        db.execute("UPDATE recovery_fact SET status = 'recovered-completed' WHERE id = 'attempt:1'")
        db.commit()

    restore_world_runtime_state(backup_path, restored)
    with sqlite3.connect(restored) as db:
        row = db.execute("SELECT status FROM recovery_fact WHERE id = 'attempt:1'").fetchone()
    assert row == ("execution-unknown",)
    assert callable(main)
