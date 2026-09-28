from __future__ import annotations

from sqlalchemy import Engine, insert, select

from autonomous_development.domain.soak import PostPromotionSoakDecision
from autonomous_development.ports.persistence import (
    OperationConflictError,
    SoakDecisionReceipt,
    SoakDecisionRepository,
)

from .records import insert_once, load_one, record_from_row, record_values
from .schema import soak_decision_operations


class SqlSoakDecisionRepository(SoakDecisionRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, operation_id: str) -> SoakDecisionReceipt | None:
        return load_one(
            self._engine,
            select(soak_decision_operations).where(
                soak_decision_operations.c.operation_id == operation_id
            ),
            SoakDecisionReceipt,
            transform=_receipt_from_row,
        )

    def record(
        self,
        operation_id: str,
        cycle_id: str,
        decision: PostPromotionSoakDecision,
    ) -> SoakDecisionReceipt:
        if not operation_id.strip():
            raise ValueError("operation_id must be non-empty")
        if not cycle_id.strip():
            raise ValueError("cycle_id must be non-empty")
        receipt = SoakDecisionReceipt(
            operation_id=operation_id,
            cycle_id=cycle_id,
            decision=decision,
        )
        return insert_once(
            self._engine,
            insert(soak_decision_operations).values(
                **record_values(
                    soak_decision_operations,
                    decision,
                    operation_id=operation_id,
                    cycle_id=cycle_id,
                    decision_kind=decision.kind.value,
                )
            ),
            load=lambda: self.get(operation_id),
            expected=receipt,
            conflict=lambda: OperationConflictError(
                f"operation id {operation_id} is already bound to another soak decision"
            ),
        )


def _receipt_from_row(row: object) -> SoakDecisionReceipt:
    return SoakDecisionReceipt(
        operation_id=str(row["operation_id"]),  # type: ignore[index]
        cycle_id=str(row["cycle_id"]),  # type: ignore[index]
        decision=record_from_row(
            PostPromotionSoakDecision,
            row,
            rename={
                "decision_kind": "kind",
                "evidence_refs_json": "evidence_refs",
                "violated_guardrails_json": "violated_guardrails",
            },
        ),
    )
