from __future__ import annotations

from sqlalchemy import Engine, insert, select

from autonomous_development.ports.persistence import (
    FeedbackTriggerReceipt,
    FeedbackTriggerRepository,
    OperationConflictError,
)

from .records import insert_once, load_one, record_values
from .schema import feedback_iteration_triggers


class SqlFeedbackTriggerRepository(FeedbackTriggerRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, feedback_id: str) -> FeedbackTriggerReceipt | None:
        return load_one(
            self._engine,
            select(feedback_iteration_triggers).where(
                feedback_iteration_triggers.c.feedback_id == feedback_id
            ),
            FeedbackTriggerReceipt,
        )

    def record(self, receipt: FeedbackTriggerReceipt) -> FeedbackTriggerReceipt:
        return insert_once(
            self._engine,
            insert(feedback_iteration_triggers).values(
                **record_values(feedback_iteration_triggers, receipt)
            ),
            load=lambda: self.get(receipt.feedback_id),
            expected=receipt,
            conflict=lambda: OperationConflictError(
                f"feedback {receipt.feedback_id} is already bound to another iteration trigger"
            ),
        )
