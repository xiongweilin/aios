from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql
from semantic_language import Responsibility

from world_runtime import WorldRuntime


DSN_ENV = "WORLD_RUNTIME_TEST_POSTGRES_DSN"


def _database_dsn(base_dsn: str, database: str) -> str:
    parts = urlsplit(base_dsn)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            "/" + database,
            parts.query,
            parts.fragment,
        )
    )


def _admin_dsn(base_dsn: str) -> str:
    return _database_dsn(base_dsn, "postgres")


def _create_database(admin_dsn: str, name: str) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
        )


def _drop_database(admin_dsn: str, name: str) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(name)
            )
        )


def _populate(dsn: str) -> dict[str, object]:
    runtime = WorldRuntime.postgres(dsn, runtime_id="backup-source")
    try:
        runtime.responsibility.create(
            Responsibility(
                id="responsibility:postgres-backup",
                principal="service:backup-smoke",
                subject="prove PostgreSQL backup and restore",
            ),
            domain="operations",
        )
        work = runtime.execution.admit_work(
            responsibility_id="responsibility:postgres-backup",
            kind="backup-smoke",
            payload={"durable": True},
            work_id="work:postgres-backup",
        )
        runtime.start_run(work.id, workflow_id="backup-smoke")
        runtime.ledger.project_put(
            "operations.backup-smoke",
            "sentinel",
            {"value": "durable"},
            expected_version=0,
        )
        return runtime.state_bundle.export()
    finally:
        runtime.ledger.close()


def _verify(dsn: str, expected_bundle: dict[str, object]) -> None:
    runtime = WorldRuntime.postgres(dsn, runtime_id="backup-restored")
    try:
        responsibility = runtime.responsibility.get("responsibility:postgres-backup")
        if responsibility.principal != "service:backup-smoke":
            raise AssertionError("restored Responsibility identity mismatch")
        sentinel = runtime.ledger.project_get("operations.backup-smoke", "sentinel")
        if sentinel is None or sentinel[0] != {"value": "durable"}:
            raise AssertionError("restored projection mismatch")
        restored_bundle = runtime.state_bundle.export()
        if restored_bundle != expected_bundle:
            raise AssertionError("restored PostgreSQL state differs from source")
    finally:
        runtime.ledger.close()


def main() -> None:
    base_dsn = os.getenv(DSN_ENV, "").strip()
    if not base_dsn:
        raise SystemExit(f"{DSN_ENV} is required")

    suffix = uuid.uuid4().hex[:12]
    source_db = f"wr_backup_source_{suffix}"
    restored_db = f"wr_backup_restored_{suffix}"
    admin_dsn = _admin_dsn(base_dsn)
    source_dsn = _database_dsn(base_dsn, source_db)
    restored_dsn = _database_dsn(base_dsn, restored_db)

    _drop_database(admin_dsn, source_db)
    _drop_database(admin_dsn, restored_db)
    _create_database(admin_dsn, source_db)
    _create_database(admin_dsn, restored_db)

    try:
        source_bundle = _populate(source_dsn)
        with tempfile.TemporaryDirectory(prefix="world-runtime-pg-backup-") as temp_dir:
            dump_path = Path(temp_dir) / "world-runtime.dump"
            subprocess.run(
                [
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "--dbname",
                    source_dsn,
                    "--file",
                    str(dump_path),
                ],
                check=True,
            )
            subprocess.run(
                [
                    "pg_restore",
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "--dbname",
                    restored_dsn,
                    str(dump_path),
                ],
                check=True,
            )
        _verify(restored_dsn, source_bundle)
    finally:
        _drop_database(admin_dsn, source_db)
        _drop_database(admin_dsn, restored_db)


if __name__ == "__main__":
    main()
