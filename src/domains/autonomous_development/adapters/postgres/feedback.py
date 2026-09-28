from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine, insert, or_, select

from autonomous_development.domain.models import UserFeedback
from autonomous_development.ports.persistence import FeedbackRepository

from .records import insert_once, load_one, record_from_row, record_values
from .schema import user_feedback


class SqlFeedbackRepository(FeedbackRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, feedback: UserFeedback) -> UserFeedback:
        return insert_once(
            self._engine,
            insert(user_feedback).values(**record_values(user_feedback, feedback)),
            load=lambda: self.get(feedback.id),
            expected=feedback,
            conflict=lambda: ValueError(
                f"feedback id already exists with different content: {feedback.id}"
            ),
        )

    def get(self, feedback_id: str) -> UserFeedback | None:
        return load_one(
            self._engine,
            select(user_feedback).where(user_feedback.c.id == feedback_id),
            UserFeedback,
        )

    def list_attributable(
        self,
        target_id: str,
        release_id: str,
        *,
        deployment_id: str,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[UserFeedback, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(user_feedback)
                    .where(
                        user_feedback.c.target_id == target_id,
                        or_(
                            user_feedback.c.release_id == release_id,
                            user_feedback.c.deployment_id == deployment_id,
                        ),
                        user_feedback.c.received_at >= opened_at,
                        user_feedback.c.received_at <= closed_at,
                    )
                    .order_by(user_feedback.c.received_at, user_feedback.c.id)
                )
                .mappings()
                .all()
            )
        return tuple(record_from_row(UserFeedback, row) for row in rows)
