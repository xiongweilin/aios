from __future__ import annotations

from sqlalchemy import Engine, insert, select

from autonomous_development.domain.models import Diagnosis
from autonomous_development.ports.persistence import DiagnosisRepository

from .records import insert_once, load_one, record_values
from .schema import diagnoses


class SqlDiagnosisRepository(DiagnosisRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, diagnosis: Diagnosis) -> Diagnosis:
        return insert_once(
            self._engine,
            insert(diagnoses).values(**record_values(diagnoses, diagnosis)),
            load=lambda: self.get(diagnosis.id),
            expected=diagnosis,
            conflict=lambda: ValueError(
                f"diagnosis id already exists with different content: {diagnosis.id}"
            ),
        )

    def get(self, id: str) -> Diagnosis | None:
        return load_one(
            self._engine,
            select(diagnoses).where(diagnoses.c.id == id),
            Diagnosis,
        )
