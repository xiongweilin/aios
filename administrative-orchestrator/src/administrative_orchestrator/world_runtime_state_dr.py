from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4


class WorldRuntimeStateRecoveryError(RuntimeError):
    pass


def backup_world_runtime_state(source: Path, destination: Path) -> str:
    """Create a consistent online SQLite backup and sidecar SHA-256 manifest."""

    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if source == destination:
        raise WorldRuntimeStateRecoveryError("World Runtime state backup destination must differ from source")
    if not source.is_file():
        raise WorldRuntimeStateRecoveryError(f"World Runtime state source does not exist: {source}")
    _require_parent(destination)

    temporary = _temporary_path(destination)
    try:
        _sqlite_backup(source, temporary)
        _quick_check(temporary)
        os.replace(temporary, destination)
        digest = _sha256(destination)
        _write_manifest(destination, digest)
        return digest
    finally:
        temporary.unlink(missing_ok=True)


def verify_world_runtime_state_backup(backup: Path) -> str:
    backup = backup.expanduser().resolve()
    if not backup.is_file():
        raise WorldRuntimeStateRecoveryError(f"World Runtime state backup does not exist: {backup}")
    _quick_check(backup)
    digest = _sha256(backup)
    manifest = _manifest_path(backup)
    if manifest.exists():
        expected = manifest.read_text(encoding="utf-8").strip().split(maxsplit=1)[0]
        if not expected or expected != digest:
            raise WorldRuntimeStateRecoveryError("World Runtime state backup digest does not match manifest")
    return digest


def restore_world_runtime_state(backup: Path, destination: Path, *, force: bool = False) -> str:
    """Restore through SQLite backup semantics, never by copying a potentially live DB file."""

    backup = backup.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if backup == destination:
        raise WorldRuntimeStateRecoveryError("World Runtime state restore destination must differ from backup")
    digest = verify_world_runtime_state_backup(backup)
    _require_parent(destination)
    destination_existed = destination.exists()
    if destination_existed and not force:
        raise WorldRuntimeStateRecoveryError("World Runtime state restore destination already exists")

    temporary = _temporary_path(destination)
    try:
        _sqlite_backup(backup, temporary)
        _quick_check(temporary)
        try:
            os.replace(temporary, destination)
        except PermissionError:
            # Windows cannot atomically replace a file that another SQLite
            # handle still has open.  A forced restore is explicitly allowed
            # to overwrite that target, so fall back to SQLite's own backup
            # semantics while preserving the temporary validation step.
            if not force or not destination_existed:
                raise
            _sqlite_backup(backup, destination)
            _quick_check(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return digest


def _sqlite_backup(source: Path, destination: Path) -> None:
    source_uri = f"{source.as_uri()}?mode=ro"
    try:
        with (
            closing(sqlite3.connect(source_uri, uri=True, timeout=30.0)) as source_db,
            closing(sqlite3.connect(destination, timeout=30.0)) as destination_db,
        ):
            source_db.backup(destination_db)
            destination_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            destination_db.commit()
    except sqlite3.Error as exc:
        raise WorldRuntimeStateRecoveryError(f"SQLite backup failed: {exc}") from exc


def _quick_check(path: Path) -> None:
    uri = f"{path.as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=30.0)) as db:
            rows = [str(row[0]) for row in db.execute("PRAGMA quick_check").fetchall()]
    except sqlite3.Error as exc:
        raise WorldRuntimeStateRecoveryError(f"SQLite integrity check failed: {exc}") from exc
    if rows != ["ok"]:
        raise WorldRuntimeStateRecoveryError("World Runtime state backup failed SQLite quick_check")


def _write_manifest(path: Path, digest: str) -> None:
    manifest = _manifest_path(path)
    temporary = _temporary_path(manifest)
    payload = f"{digest}  {path.name}\n"
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, manifest)
    finally:
        temporary.unlink(missing_ok=True)


def _manifest_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.sha256")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_parent(path: Path) -> None:
    if not path.parent.exists() or not path.parent.is_dir():
        raise WorldRuntimeStateRecoveryError(f"destination parent does not exist: {path.parent}")


def _temporary_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid4().hex}.tmp")


__all__ = [
    "WorldRuntimeStateRecoveryError",
    "backup_world_runtime_state",
    "restore_world_runtime_state",
    "verify_world_runtime_state_backup",
]
