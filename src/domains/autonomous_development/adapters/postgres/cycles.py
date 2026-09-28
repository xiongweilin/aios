from __future__ import annotations

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.exc import IntegrityError

from autonomous_development.domain.enums import CycleState
from autonomous_development.domain.models import DevelopmentCycle
from autonomous_development.domain.transitions import TERMINAL_STATES
from autonomous_development.ports.persistence import (
    ConcurrentCycleError,
    ConcurrentUpdateError,
    CycleRepository,
    OperationConflictError,
    TransitionReceipt,
)

from .records import load_one, record_values
from .schema import cycle_transitions, cycles


class SqlCycleRepository(CycleRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, cycle: DevelopmentCycle) -> DevelopmentCycle:
        try:
            with self._engine.begin() as connection:
                connection.execute(insert(cycles).values(**record_values(cycles, cycle, is_terminal=cycle.state in TERMINAL_STATES)))
        except IntegrityError as exc:
            if self.get(cycle.id) is not None:
                raise ValueError(f"cycle already exists: {cycle.id}") from exc
            active = self.find_active_for_target(cycle.target_id)
            if active is not None:
                raise ConcurrentCycleError(
                    f"target {cycle.target_id} already has active cycle {active.id}"
                ) from exc
            raise
        return cycle

    def get(self, cycle_id: str) -> DevelopmentCycle | None:
        return load_one(
            self._engine, select(cycles).where(cycles.c.id == cycle_id), DevelopmentCycle
        )

    def find_active_for_target(self, target_id: str) -> DevelopmentCycle | None:
        return load_one(
            self._engine,
            select(cycles).where(
                cycles.c.target_id == target_id, cycles.c.is_terminal.is_(False)
            ),
            DevelopmentCycle,
        )

    def get_transition(self, operation_id: str) -> TransitionReceipt | None:
        return load_one(
            self._engine,
            select(cycle_transitions).where(cycle_transitions.c.operation_id == operation_id),
            TransitionReceipt,
        )

    def commit_transition(
        self,
        cycle: DevelopmentCycle,
        *,
        expected_version: int,
        operation_id: str,
        expected_to_state: CycleState,
    ) -> TransitionReceipt:
        existing = self.get_transition(operation_id)
        if existing is not None:
            return _validate_existing_receipt(
                existing,
                cycle=cycle,
                expected_version=expected_version,
                expected_to_state=expected_to_state,
            )

        receipt = TransitionReceipt(
            operation_id=operation_id,
            cycle_id=cycle.id,
            from_version=expected_version,
            result_version=cycle.version,
            to_state=expected_to_state,
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(cycle_transitions).values(**record_values(cycle_transitions, receipt))
                )
                result = connection.execute(
                    update(cycles)
                    .where(cycles.c.id == cycle.id, cycles.c.version == expected_version)
                    .values(**record_values(cycles, cycle, is_terminal=cycle.state in TERMINAL_STATES))
                )
                if result.rowcount != 1:
                    raise ConcurrentUpdateError(
                        f"cycle {cycle.id} no longer matches version {expected_version}"
                    )
        except IntegrityError as exc:
            existing = self.get_transition(operation_id)
            if existing is None:
                raise
            try:
                return _validate_existing_receipt(
                    existing,
                    cycle=cycle,
                    expected_version=expected_version,
                    expected_to_state=expected_to_state,
                )
            except OperationConflictError as conflict:
                raise conflict from exc
        return receipt


def _validate_existing_receipt(
    receipt: TransitionReceipt,
    *,
    cycle: DevelopmentCycle,
    expected_version: int,
    expected_to_state: CycleState,
) -> TransitionReceipt:
    if (
        receipt.cycle_id != cycle.id
        or receipt.from_version != expected_version
        or receipt.result_version != cycle.version
        or receipt.to_state is not expected_to_state
    ):
        raise OperationConflictError(
            f"operation id {receipt.operation_id} is already bound to another transition"
        )
    return receipt


