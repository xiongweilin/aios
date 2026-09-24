from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Iterator, Mapping, Protocol, runtime_checkable

from .common import new_id, utcnow


class LedgerConcurrencyConflict(RuntimeError):
    """A concurrent semantic transition won the database race."""


class ProjectionVersionConflict(LedgerConcurrencyConflict):
    """Projection create/update lost its expected-version CAS."""


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    id: str
    stream: str
    kind: str
    payload: Mapping[str, Any]
    recorded_at: datetime
    valid_at: datetime
    sequence: int | None = None


@runtime_checkable
class SemanticLedger(Protocol):
    """Backend-neutral durable semantic ledger contract."""

    def close(self) -> None: ...

    def transaction(self) -> Iterator[None]: ...

    def append(
        self,
        *,
        stream: str,
        kind: str,
        payload: Mapping[str, Any],
        event_id: str | None = None,
        valid_at: datetime | None = None,
        recorded_at: datetime | None = None,
    ) -> LedgerEvent: ...

    def events(
        self,
        *,
        stream: str | None = None,
        kind: str | None = None,
        through_sequence: int | None = None,
    ) -> list[LedgerEvent]: ...

    def project_get(
        self,
        namespace: str,
        key: str,
    ) -> tuple[dict[str, Any], int] | None: ...

    def project_put(
        self,
        namespace: str,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_version: int | None = None,
    ) -> int: ...

    def export_events(self) -> Iterable[dict[str, Any]]: ...

    def export_event_rows(self) -> list[dict[str, Any]]: ...

    def export_projection_rows(self) -> list[dict[str, Any]]: ...

    def import_state_rows(
        self,
        *,
        events: list[Mapping[str, Any]],
        projections: list[Mapping[str, Any]],
    ) -> None: ...


class SQLiteLedger:
    """Append-only semantic event ledger plus versioned materialized projections."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = RLock()
        self._transaction_depth = 0
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ledger_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                stream TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                valid_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ledger_stream_seq
                ON ledger_events(stream, sequence);
            CREATE TABLE IF NOT EXISTS projections (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(namespace, key)
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Make a semantic transition's event/projection writes atomic.

        Nested service calls share the outer transaction. Provider/network I/O must
        never occur inside this context.
        """

        self._lock.acquire()
        outer = self._transaction_depth == 0
        if outer:
            self._conn.execute("BEGIN IMMEDIATE")
        self._transaction_depth += 1
        try:
            yield
        except Exception:
            self._transaction_depth -= 1
            if outer:
                self._conn.rollback()
            raise
        else:
            self._transaction_depth -= 1
            if outer:
                self._conn.commit()
        finally:
            self._lock.release()

    def _commit_if_outer(self) -> None:
        if self._transaction_depth == 0:
            self._conn.commit()

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
        eid = event_id or new_id("event")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO ledger_events(
                       id, stream, kind, payload_json, recorded_at, valid_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (eid, stream, kind, encoded, recorded.isoformat(), valid.isoformat()),
            )
            self._commit_if_outer()
        return LedgerEvent(
            eid,
            stream,
            kind,
            dict(payload),
            recorded,
            valid,
            int(cur.lastrowid),
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
            clauses.append("stream = ?")
            params.append(stream)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if through_sequence is not None:
            clauses.append("sequence <= ?")
            params.append(through_sequence)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM ledger_events{where} ORDER BY sequence ASC",
            params,
        ).fetchall()
        return [
            LedgerEvent(
                id=row["id"],
                stream=row["stream"],
                kind=row["kind"],
                payload=json.loads(row["payload_json"]),
                recorded_at=datetime.fromisoformat(row["recorded_at"]),
                valid_at=datetime.fromisoformat(row["valid_at"]),
                sequence=int(row["sequence"]),
            )
            for row in rows
        ]

    def project_get(
        self,
        namespace: str,
        key: str,
    ) -> tuple[dict[str, Any], int] | None:
        row = self._conn.execute(
            "SELECT value_json, version FROM projections WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["value_json"]), int(row["version"])

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
            if expected_version is None:
                row = self._conn.execute(
                    """INSERT INTO projections(
                           namespace, key, value_json, version, updated_at
                       ) VALUES (?, ?, ?, 1, ?)
                       ON CONFLICT(namespace, key) DO UPDATE SET
                           value_json = excluded.value_json,
                           version = projections.version + 1,
                           updated_at = excluded.updated_at
                       RETURNING version""",
                    (namespace, key, encoded, updated_at),
                ).fetchone()
                assert row is not None
                self._commit_if_outer()
                return int(row["version"])

            if expected_version == 0:
                try:
                    row = self._conn.execute(
                        """INSERT INTO projections(
                               namespace, key, value_json, version, updated_at
                           ) VALUES (?, ?, ?, 1, ?)
                           RETURNING version""",
                        (namespace, key, encoded, updated_at),
                    ).fetchone()
                except sqlite3.IntegrityError as exc:
                    raise ProjectionVersionConflict(
                        "projection version conflict"
                    ) from exc
                assert row is not None
                self._commit_if_outer()
                return int(row["version"])

            row = self._conn.execute(
                """UPDATE projections
                   SET value_json = ?,
                       version = version + 1,
                       updated_at = ?
                   WHERE namespace = ?
                     AND key = ?
                     AND version = ?
                   RETURNING version""",
                (encoded, updated_at, namespace, key, expected_version),
            ).fetchone()
            if row is None:
                raise ProjectionVersionConflict("projection version conflict")
            self._commit_if_outer()
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
        rows = self._conn.execute(
            """SELECT namespace, key, value_json, version, updated_at
               FROM projections ORDER BY namespace, key"""
        ).fetchall()
        return [
            {
                "namespace": str(row["namespace"]),
                "key": str(row["key"]),
                "value": json.loads(row["value_json"]),
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
                    """INSERT INTO ledger_events(
                           sequence, id, stream, kind, payload_json,
                           recorded_at, valid_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
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
                    """INSERT INTO projections(
                           namespace, key, value_json, version, updated_at
                       ) VALUES (?, ?, ?, ?, ?)""",
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
