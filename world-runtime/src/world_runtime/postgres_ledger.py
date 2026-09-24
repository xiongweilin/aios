from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from threading import RLock
from typing import Any, Iterable, Iterator, Mapping

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .common import new_id, utcnow
from .ledger import LedgerConcurrencyConflict, LedgerEvent, ProjectionVersionConflict


class PostgresLedger:
    """PostgreSQL implementation of the semantic ledger contract.

    Process-local locking protects one connection from concurrent use. Cross-process
    correctness comes from PostgreSQL transactions, unique constraints, and version-CAS
    statements rather than from the Python lock.
    """

    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "public",
    ) -> None:
        if not dsn.strip():
            raise ValueError("PostgresLedger requires a DSN")
        if not schema.strip():
            raise ValueError("PostgresLedger requires a schema")
        self.dsn = dsn
        self.schema = schema
        self._lock = RLock()
        self._conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self._conn.isolation_level = psycopg.IsolationLevel.SERIALIZABLE
        with self._lock:
            self._conn.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
            )
            self._conn.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ledger_events (
                    sequence BIGSERIAL PRIMARY KEY,
                    id TEXT NOT NULL UNIQUE,
                    stream TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    valid_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ledger_stream_seq
                ON ledger_events(stream, sequence)
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projections (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    version BIGINT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(namespace, key)
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Make one semantic transition atomic across processes.

        Psycopg nested transactions use savepoints. Any serialization/deadlock
        failure is rolled back by psycopg before it is translated into the
        backend-neutral concurrency conflict.
        """

        self._lock.acquire()
        try:
            try:
                with self._conn.transaction():
                    yield
            except (
                psycopg.errors.SerializationFailure,
                psycopg.errors.DeadlockDetected,
            ) as exc:
                raise LedgerConcurrencyConflict(
                    "PostgreSQL semantic transaction lost a concurrency race"
                ) from exc
        finally:
            self._lock.release()

    def append(
        self,
        *,
        stream: str,
        kind: str,
        payload: Mapping[str, Any],
        event_id: str | None = None,
        valid_at: datetime | None = None,
        recorded_at: datetime | None = None,
    ) -> LedgerEvent:
        recorded = recorded_at or utcnow()
        valid = valid_at or recorded
        event_identifier = event_id or new_id("event")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        with self._lock:
            row = self._conn.execute(
                """
                INSERT INTO ledger_events(
                    id, stream, kind, payload_json, recorded_at, valid_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING sequence
                """,
                (
                    event_identifier,
                    stream,
                    kind,
                    encoded,
                    recorded.isoformat(),
                    valid.isoformat(),
                ),
            ).fetchone()
        assert row is not None
        return LedgerEvent(
            event_identifier,
            stream,
            kind,
            dict(payload),
            recorded,
            valid,
            int(row["sequence"]),
        )

    def events(
        self,
        *,
        stream: str | None = None,
        kind: str | None = None,
        through_sequence: int | None = None,
    ) -> list[LedgerEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if stream is not None:
            clauses.append("stream = %s")
            params.append(stream)
        if kind is not None:
            clauses.append("kind = %s")
            params.append(kind)
        if through_sequence is not None:
            clauses.append("sequence <= %s")
            params.append(through_sequence)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM ledger_events{where} ORDER BY sequence ASC",
                params,
            ).fetchall()
        return [
            LedgerEvent(
                id=str(row["id"]),
                stream=str(row["stream"]),
                kind=str(row["kind"]),
                payload=json.loads(str(row["payload_json"])),
                recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
                valid_at=datetime.fromisoformat(str(row["valid_at"])),
                sequence=int(row["sequence"]),
            )
            for row in rows
        ]

    def project_get(
        self,
        namespace: str,
        key: str,
    ) -> tuple[dict[str, Any], int] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT value_json, version
                FROM projections
                WHERE namespace = %s AND key = %s
                """,
                (namespace, key),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["value_json"])), int(row["version"])

    def project_put(
        self,
        namespace: str,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_version: int | None = None,
    ) -> int:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        updated_at = utcnow().isoformat()
        with self._lock:
            if expected_version == 0:
                row = self._conn.execute(
                    """
                    INSERT INTO projections(
                        namespace, key, value_json, version, updated_at
                    ) VALUES (%s, %s, %s, 1, %s)
                    ON CONFLICT(namespace, key) DO NOTHING
                    RETURNING version
                    """,
                    (namespace, key, encoded, updated_at),
                ).fetchone()
                if row is None:
                    raise ProjectionVersionConflict("projection version conflict")
                return int(row["version"])

            if expected_version is not None:
                row = self._conn.execute(
                    """
                    UPDATE projections
                    SET value_json = %s,
                        version = version + 1,
                        updated_at = %s
                    WHERE namespace = %s
                      AND key = %s
                      AND version = %s
                    RETURNING version
                    """,
                    (encoded, updated_at, namespace, key, expected_version),
                ).fetchone()
                if row is None:
                    raise ProjectionVersionConflict("projection version conflict")
                return int(row["version"])

            row = self._conn.execute(
                """
                INSERT INTO projections(
                    namespace, key, value_json, version, updated_at
                ) VALUES (%s, %s, %s, 1, %s)
                ON CONFLICT(namespace, key) DO UPDATE
                SET value_json = EXCLUDED.value_json,
                    version = projections.version + 1,
                    updated_at = EXCLUDED.updated_at
                RETURNING version
                """,
                (namespace, key, encoded, updated_at),
            ).fetchone()
            assert row is not None
            return int(row["version"])

    def export_events(self) -> Iterable[dict[str, Any]]:
        yield from self.export_event_rows()

    def export_event_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "sequence": event.sequence,
                "id": event.id,
                "stream": event.stream,
                "kind": event.kind,
                "payload": dict(event.payload),
                "recorded_at": event.recorded_at.isoformat(),
                "valid_at": event.valid_at.isoformat(),
            }
            for event in self.events()
        ]

    def export_projection_rows(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT namespace, key, value_json, version, updated_at
                FROM projections
                ORDER BY namespace, key
                """
            ).fetchall()
        return [
            {
                "namespace": str(row["namespace"]),
                "key": str(row["key"]),
                "value": json.loads(str(row["value_json"])),
                "version": int(row["version"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def import_state_rows(
        self,
        *,
        events: list[Mapping[str, Any]],
        projections: list[Mapping[str, Any]],
    ) -> None:
        with self.transaction():
            if self.events() or self.export_projection_rows():
                raise ValueError("state import requires empty ledger")
            for raw in events:
                self._conn.execute(
                    """
                    INSERT INTO ledger_events(
                        sequence, id, stream, kind, payload_json,
                        recorded_at, valid_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        int(raw["sequence"]),
                        str(raw["id"]),
                        str(raw["stream"]),
                        str(raw["kind"]),
                        json.dumps(
                            raw["payload"],
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        ),
                        str(raw["recorded_at"]),
                        str(raw["valid_at"]),
                    ),
                )
            for raw in projections:
                self._conn.execute(
                    """
                    INSERT INTO projections(
                        namespace, key, value_json, version, updated_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        str(raw["namespace"]),
                        str(raw["key"]),
                        json.dumps(
                            raw["value"],
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        ),
                        int(raw["version"]),
                        str(raw["updated_at"]),
                    ),
                )
            if events:
                max_sequence = max(int(raw["sequence"]) for raw in events)
                self._conn.execute(
                    """
                    SELECT setval(
                        pg_get_serial_sequence('ledger_events', 'sequence'),
                        %s,
                        true
                    )
                    """,
                    (max_sequence,),
                )


__all__ = ["PostgresLedger"]
