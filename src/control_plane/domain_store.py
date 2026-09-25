from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}:{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class DomainEvent:
    id: str
    stream: str
    kind: str
    payload: dict[str, Any]
    recorded_at: datetime


class DomainJournal:
    """Control-plane-local domain journal.

    This persists only control-plane controller/work/result state. It does not
    own universal semantic objects such as Mandate, Decision, Authorization,
    Responsibility, Goal, Evidence or Outcome.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS domain_events (
              seq INTEGER PRIMARY KEY AUTOINCREMENT,
              id TEXT NOT NULL UNIQUE,
              stream TEXT NOT NULL,
              kind TEXT NOT NULL,
              payload TEXT NOT NULL,
              recorded_at TEXT NOT NULL
            )
            """
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS domain_projections (
              namespace TEXT NOT NULL,
              key TEXT NOT NULL,
              value TEXT NOT NULL,
              version INTEGER NOT NULL,
              PRIMARY KEY(namespace, key)
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def append(
        self,
        *,
        stream: str,
        kind: str,
        payload: dict[str, Any],
        event_id: str | None = None,
    ) -> DomainEvent:
        event = DomainEvent(
            id=event_id or new_id("event"),
            stream=stream,
            kind=kind,
            payload=dict(payload),
            recorded_at=utcnow(),
        )
        with self._lock:
            existing = self._db.execute(
                "SELECT stream, kind, payload, recorded_at FROM domain_events WHERE id = ?",
                (event.id,),
            ).fetchone()
            if existing is not None:
                old_payload = json.loads(str(existing["payload"]))
                if (
                    str(existing["stream"]) != event.stream
                    or str(existing["kind"]) != event.kind
                    or old_payload != event.payload
                ):
                    raise ValueError("domain event identity rebound")
                return DomainEvent(
                    id=event.id,
                    stream=str(existing["stream"]),
                    kind=str(existing["kind"]),
                    payload=old_payload,
                    recorded_at=datetime.fromisoformat(str(existing["recorded_at"])),
                )
            self._db.execute(
                """
                INSERT INTO domain_events(id, stream, kind, payload, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.stream,
                    event.kind,
                    json.dumps(event.payload, ensure_ascii=False, sort_keys=True),
                    event.recorded_at.isoformat(),
                ),
            )
            self._db.commit()
        return event

    def events(self, *, stream: str | None = None) -> list[DomainEvent]:
        query = "SELECT id, stream, kind, payload, recorded_at FROM domain_events"
        args: tuple[Any, ...] = ()
        if stream is not None:
            query += " WHERE stream = ?"
            args = (stream,)
        query += " ORDER BY seq ASC"
        rows = self._db.execute(query, args).fetchall()
        return [
            DomainEvent(
                id=str(row["id"]),
                stream=str(row["stream"]),
                kind=str(row["kind"]),
                payload=json.loads(str(row["payload"])),
                recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
            )
            for row in rows
        ]

    def project_get(
        self,
        namespace: str,
        key: str,
    ) -> tuple[dict[str, Any], int] | None:
        row = self._db.execute(
            """
            SELECT value, version FROM domain_projections
            WHERE namespace = ? AND key = ?
            """,
            (namespace, key),
        ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["value"])), int(row["version"])

    def project_put(
        self,
        namespace: str,
        key: str,
        value: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> int:
        with self._lock:
            current = self.project_get(namespace, key)
            if current is None:
                if expected_version not in (None, 0):
                    raise ValueError("domain projection version mismatch")
                version = 1
                self._db.execute(
                    """
                    INSERT INTO domain_projections(namespace, key, value, version)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        namespace,
                        key,
                        json.dumps(value, ensure_ascii=False, sort_keys=True),
                        version,
                    ),
                )
            else:
                _, current_version = current
                if expected_version is not None and expected_version != current_version:
                    raise ValueError("domain projection version mismatch")
                version = current_version + 1
                self._db.execute(
                    """
                    UPDATE domain_projections
                    SET value = ?, version = ?
                    WHERE namespace = ? AND key = ?
                    """,
                    (
                        json.dumps(value, ensure_ascii=False, sort_keys=True),
                        version,
                        namespace,
                        key,
                    ),
                )
            self._db.commit()
        return version

    def project_list(self, namespace: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """
            SELECT value FROM domain_projections
            WHERE namespace = ?
            ORDER BY key ASC
            """,
            (namespace,),
        ).fetchall()
        return [json.loads(str(row["value"])) for row in rows]


__all__ = ["DomainEvent", "DomainJournal", "new_id", "utcnow"]
