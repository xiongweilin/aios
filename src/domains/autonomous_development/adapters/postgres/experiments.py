from __future__ import annotations

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.exc import IntegrityError

from autonomous_development.domain.canary import CanaryStageDecision
from autonomous_development.domain.models import Experiment
from autonomous_development.ports.persistence import (
    ConcurrentUpdateError,
    ExperimentRepository,
    ExperimentStageReceipt,
    OperationConflictError,
)

from .records import load_one, record_from_row, record_values
from .schema import experiment_stage_operations, experiments


class SqlExperimentRepository(ExperimentRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, experiment: Experiment) -> Experiment:
        try:
            with self._engine.begin() as connection:
                connection.execute(insert(experiments).values(**record_values(experiments, experiment)))
        except IntegrityError as exc:
            if self.get(experiment.id) is not None:
                raise ValueError(f"experiment already exists: {experiment.id}") from exc
            raise
        return experiment

    def get(self, experiment_id: str) -> Experiment | None:
        return load_one(
            self._engine, select(experiments).where(experiments.c.id == experiment_id), Experiment
        )

    def get_stage_decision(self, operation_id: str) -> ExperimentStageReceipt | None:
        return load_one(
            self._engine,
            select(experiment_stage_operations).where(
                experiment_stage_operations.c.operation_id == operation_id
            ),
            ExperimentStageReceipt,
        )

    def list_stage_decisions(
        self,
        experiment_id: str,
    ) -> tuple[ExperimentStageReceipt, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(experiment_stage_operations)
                    .where(experiment_stage_operations.c.experiment_id == experiment_id)
                    .order_by(experiment_stage_operations.c.sequence_id)
                )
                .mappings()
                .all()
            )
        return tuple(record_from_row(ExperimentStageReceipt, row) for row in rows)

    def commit_stage_decision(
        self,
        experiment: Experiment,
        decision: CanaryStageDecision,
        *,
        expected_stage_index: int,
        operation_id: str,
    ) -> ExperimentStageReceipt:
        if decision.experiment_id != experiment.id:
            raise ValueError("canary decision belongs to another experiment")
        if decision.stage_index != expected_stage_index:
            raise ValueError("canary decision stage does not match expected stage")

        receipt = ExperimentStageReceipt(
            operation_id=operation_id,
            experiment_id=experiment.id,
            stage_index=expected_stage_index,
            result_stage_index=experiment.current_stage_index,
            decision_kind=decision.kind,
            evidence_refs=decision.evidence_refs,
            violated_guardrails=decision.violated_guardrails,
            reason=decision.reason,
        )
        existing = self.get_stage_decision(operation_id)
        if existing is not None:
            return _validate_existing_receipt(existing, receipt)

        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(experiment_stage_operations).values(**record_values(experiment_stage_operations, receipt))
                )
                result = connection.execute(
                    update(experiments)
                    .where(
                        experiments.c.id == experiment.id,
                        experiments.c.current_stage_index == expected_stage_index,
                    )
                    .values(current_stage_index=experiment.current_stage_index)
                )
                if result.rowcount != 1:
                    raise ConcurrentUpdateError(
                        f"experiment {experiment.id} no longer matches stage "
                        f"{expected_stage_index}"
                    )
        except IntegrityError as exc:
            existing = self.get_stage_decision(operation_id)
            if existing is None:
                raise
            try:
                return _validate_existing_receipt(existing, receipt)
            except OperationConflictError as conflict:
                raise conflict from exc
        return receipt


def _validate_existing_receipt(
    existing: ExperimentStageReceipt,
    requested: ExperimentStageReceipt,
) -> ExperimentStageReceipt:
    if existing != requested:
        raise OperationConflictError(
            f"operation id {requested.operation_id} is already bound to another canary decision"
        )
    return existing


