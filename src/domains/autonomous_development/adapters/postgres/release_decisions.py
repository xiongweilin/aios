from __future__ import annotations

from sqlalchemy import Engine, insert, select

from autonomous_development.domain.models import ReleaseDecision
from autonomous_development.ports.persistence import (
    OperationConflictError,
    ReleaseDecisionReceipt,
    ReleaseDecisionRepository,
)

from .records import insert_once, load_one, record_from_row, record_values
from .schema import release_decision_operations


class SqlReleaseDecisionRepository(ReleaseDecisionRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, operation_id: str) -> ReleaseDecisionReceipt | None:
        return load_one(
            self._engine,
            select(release_decision_operations).where(
                release_decision_operations.c.operation_id == operation_id
            ),
            ReleaseDecisionReceipt,
            transform=_receipt_from_row,
        )

    def record(
        self,
        operation_id: str,
        decision: ReleaseDecision,
    ) -> ReleaseDecisionReceipt:
        if not operation_id.strip():
            raise ValueError("operation_id must be non-empty")
        receipt = ReleaseDecisionReceipt(operation_id=operation_id, decision=decision)
        return insert_once(
            self._engine,
            insert(release_decision_operations).values(
                **record_values(
                    release_decision_operations,
                    decision,
                    operation_id=operation_id,
                    decision_kind=decision.kind.value,
                )
            ),
            load=lambda: self.get(operation_id),
            expected=receipt,
            conflict=lambda: OperationConflictError(
                f"operation id {operation_id} is already bound to another release decision"
            ),
        )


def _receipt_from_row(row: object) -> ReleaseDecisionReceipt:
    return ReleaseDecisionReceipt(
        operation_id=str(row["operation_id"]),  # type: ignore[index]
        decision=record_from_row(
            ReleaseDecision,
            row,
            rename={
                "decision_kind": "kind",
                "gate_refs_json": "gate_refs",
                "evidence_refs_json": "evidence_refs",
            },
        ),
    )
