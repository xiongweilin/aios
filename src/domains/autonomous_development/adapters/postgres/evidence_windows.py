from __future__ import annotations

from sqlalchemy import Engine, insert, select

from autonomous_development.domain.models import EvidenceWindow
from autonomous_development.ports.persistence import EvidenceWindowRepository

from .records import insert_once, load_one, record_values
from .schema import evidence_windows


class SqlEvidenceWindowRepository(EvidenceWindowRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, window: EvidenceWindow) -> EvidenceWindow:
        return insert_once(
            self._engine,
            insert(evidence_windows).values(**record_values(evidence_windows, window)),
            load=lambda: self.get(window.id),
            expected=window,
            conflict=lambda: ValueError(
                f"evidence window id already exists with different content: {window.id}"
            ),
        )

    def get(self, id: str) -> EvidenceWindow | None:
        return load_one(
            self._engine,
            select(evidence_windows).where(evidence_windows.c.id == id),
            EvidenceWindow,
        )
