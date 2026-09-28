from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from autonomous_development.domain.enums import (
    DevelopmentRequestStatus,
    HumanInterventionStatus,
)
from autonomous_development.domain.models import (
    DevelopmentRequest,
    HumanIntervention,
    OperatorEvent,
    RequirementAnalysis,
)
from autonomous_development.ports.persistence import OperatorRepository

from .records import record_from_row, record_values
from .schema import development_requests, human_interventions, operator_events, requirement_analyses


class SqlOperatorRepository(OperatorRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add_request(self, request: DevelopmentRequest) -> DevelopmentRequest:
        existing = self.get_request(request.id)
        if existing is not None:
            if existing.content_sha256 != request.content_sha256:
                raise ValueError("request id already exists with different content")
            return existing
        try:
            with self._engine.begin() as connection:
                connection.execute(insert(development_requests).values(**record_values(development_requests, request)))
        except IntegrityError as exc:
            by_external = self._get_by_external_digest(request.external_reference_digest)
            if by_external is not None:
                if by_external.content_sha256 != request.content_sha256:
                    raise ValueError(
                        "external reference digest already exists with different content"
                    ) from exc
                return by_external
            raise
        return request

    def get_request(self, request_id: str) -> DevelopmentRequest | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(development_requests).where(development_requests.c.id == request_id)
                )
                .mappings()
                .first()
            )
        return None if row is None else record_from_row(DevelopmentRequest, row)

    def update_request(self, request: DevelopmentRequest) -> DevelopmentRequest:
        with self._engine.begin() as connection:
            result = connection.execute(
                update(development_requests)
                .where(development_requests.c.id == request.id)
                .values(**record_values(development_requests, request))
            )
        if result.rowcount != 1:
            raise KeyError(f"unknown development request: {request.id}")
        return request

    def add_analysis(self, analysis: RequirementAnalysis) -> RequirementAnalysis:
        existing = self.get_analysis(analysis.request_id)
        if existing is not None:
            if existing != analysis:
                raise ValueError("request already has a different requirement analysis")
            return existing
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(requirement_analyses).values(**record_values(requirement_analyses, analysis))
                )
        except IntegrityError:
            existing = self.get_analysis(analysis.request_id)
            if existing is None or existing != analysis:
                raise
            return existing
        return analysis

    def get_analysis(self, request_id: str) -> RequirementAnalysis | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(requirement_analyses).where(
                        requirement_analyses.c.request_id == request_id
                    )
                )
                .mappings()
                .first()
            )
        return None if row is None else record_from_row(RequirementAnalysis, row)

    def replace_analysis(self, analysis: RequirementAnalysis) -> RequirementAnalysis:
        """Re-derive the stored analysis after a human clarification entered the requirement.

        The analysis stays durable evidence of what was known at the time, so replacement
        is explicit and only used when new human qualification must be reflected.
        """
        with self._engine.begin() as connection:
            connection.execute(
                delete(requirement_analyses).where(
                    requirement_analyses.c.request_id == analysis.request_id
                )
            )
            connection.execute(insert(requirement_analyses).values(**record_values(requirement_analyses, analysis)))
        stored = self.get_analysis(analysis.request_id)
        if stored is None:
            raise RuntimeError("requirement analysis was not readable after replacement")
        return stored

    def add_intervention(self, intervention: HumanIntervention) -> HumanIntervention:
        existing = self.get_intervention(intervention.id)
        if existing is not None:
            if existing != intervention:
                raise ValueError("intervention id already exists with different content")
            return existing
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(human_interventions).values(**record_values(human_interventions, intervention))
                )
        except IntegrityError:
            existing = self.get_intervention(intervention.id)
            if existing is None or existing != intervention:
                raise
            return existing
        return intervention

    def get_intervention(self, intervention_id: str) -> HumanIntervention | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(human_interventions).where(human_interventions.c.id == intervention_id)
                )
                .mappings()
                .first()
            )
        return None if row is None else record_from_row(HumanIntervention, row)

    def list_responded_interventions(
        self,
        request_id: str,
    ) -> tuple[HumanIntervention, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(human_interventions)
                    .where(human_interventions.c.request_id == request_id)
                    .where(
                        human_interventions.c.status
                        == HumanInterventionStatus.RESPONDED.value
                    )
                    .order_by(human_interventions.c.responded_at)
                )
                .mappings()
                .all()
            )
        return tuple(record_from_row(HumanIntervention, row) for row in rows)

    def respond_intervention(
        self,
        intervention_id: str,
        response: str,
        responded_at: datetime,
    ) -> HumanIntervention:
        existing = self.get_intervention(intervention_id)
        if existing is None:
            raise KeyError(f"unknown intervention: {intervention_id}")
        if existing.status in {
            HumanInterventionStatus.RESPONDED,
            HumanInterventionStatus.CLOSED,
        }:
            if existing.response != response:
                raise ValueError("closed intervention cannot be rewritten")
            return existing
        updated = HumanIntervention(
            id=existing.id,
            request_id=existing.request_id,
            cycle_id=existing.cycle_id,
            kind=existing.kind,
            question=existing.question,
            choices=existing.choices,
            status=HumanInterventionStatus.RESPONDED,
            created_at=existing.created_at,
            response=response,
            responded_at=responded_at,
        )
        with self._engine.begin() as connection:
            connection.execute(
                update(human_interventions)
                .where(human_interventions.c.id == intervention_id)
                .values(**record_values(human_interventions, updated))
            )
        return updated

    def append_event(self, event: OperatorEvent) -> OperatorEvent:
        existing = self._event_by_id(event.id)
        if existing is not None:
            if existing.payload != event.payload or existing.event_type != event.event_type:
                raise ValueError("operator event id already exists with different content")
            return existing
        if event.sequence is not None:
            raise ValueError("new operator events must not specify a sequence")
        with self._engine.begin() as connection:
            connection.execute(insert(operator_events).values(**record_values(operator_events, event)))
        stored = self._event_by_id(event.id)
        if stored is None:
            raise RuntimeError("operator event was not readable after insert")
        return stored

    def list_events(self, *, after: int, limit: int) -> tuple[OperatorEvent, ...]:
        if after < 0 or not 1 <= limit <= 500:
            raise ValueError("event cursor or limit is outside bounds")
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(operator_events)
                    .where(operator_events.c.sequence > after)
                    .order_by(operator_events.c.sequence)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return tuple(record_from_row(OperatorEvent, row) for row in rows)

    def acknowledge_event(self, event_id: str, acknowledged_at: datetime) -> OperatorEvent:
        existing = self._event_by_id(event_id)
        if existing is None:
            raise KeyError(f"unknown operator event: {event_id}")
        if existing.acknowledged_at is not None:
            return existing
        with self._engine.begin() as connection:
            connection.execute(
                update(operator_events)
                .where(operator_events.c.id == event_id)
                .values(acknowledged_at=acknowledged_at)
            )
        updated = self._event_by_id(event_id)
        if updated is None:
            raise RuntimeError("operator event disappeared during acknowledgement")
        return updated

    def pending_event_count(self) -> int:
        with self._engine.connect() as connection:
            value = connection.execute(
                select(func.count())
                .select_from(operator_events)
                .where(operator_events.c.acknowledged_at.is_(None))
            ).scalar_one()
        return int(value)

    def pending_intervention_count(self) -> int:
        with self._engine.connect() as connection:
            value = connection.execute(
                select(func.count())
                .select_from(human_interventions)
                .where(human_interventions.c.status == HumanInterventionStatus.OPEN.value)
            ).scalar_one()
        return int(value)

    def latest_event_sequence(self) -> int:
        with self._engine.connect() as connection:
            value = connection.execute(select(func.max(operator_events.c.sequence))).scalar_one()
        return 0 if value is None else int(value)

    def _get_by_external_digest(self, digest: str) -> DevelopmentRequest | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(development_requests).where(
                        development_requests.c.external_reference_digest == digest
                    )
                )
                .mappings()
                .first()
            )
        return None if row is None else record_from_row(DevelopmentRequest, row)

    def _event_by_id(self, event_id: str) -> OperatorEvent | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(select(operator_events).where(operator_events.c.id == event_id))
                .mappings()
                .first()
            )
        return None if row is None else record_from_row(OperatorEvent, row)


