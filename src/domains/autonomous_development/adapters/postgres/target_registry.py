from __future__ import annotations

from sqlalchemy import Engine, insert, select

from autonomous_development.domain.models import (
    DevelopmentTarget,
    MutationPolicy,
    ProductObjectiveRevision,
)
from autonomous_development.ports.persistence import ObjectiveRepository, TargetRepository

from .records import insert_once, load_one, record_from_row, record_values
from .schema import development_targets, product_objective_revisions


class SqlTargetRepository(TargetRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, target: DevelopmentTarget) -> DevelopmentTarget:
        return insert_once(
            self._engine,
            insert(development_targets).values(**_target_values(target)),
            load=lambda: self.get(target.id),
            expected=target,
            conflict=lambda: ValueError(
                f"target id already exists with different content: {target.id}"
            ),
        )

    def get(self, target_id: str) -> DevelopmentTarget | None:
        return load_one(
            self._engine,
            select(development_targets).where(development_targets.c.id == target_id),
            DevelopmentTarget,
            transform=_target_from_row,
        )

    def list_all(self) -> tuple[DevelopmentTarget, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(development_targets).order_by(development_targets.c.id)
                )
                .mappings()
                .all()
            )
        return tuple(_target_from_row(row) for row in rows)


class SqlObjectiveRepository(ObjectiveRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, objective: ProductObjectiveRevision) -> ProductObjectiveRevision:
        return insert_once(
            self._engine,
            insert(product_objective_revisions).values(**_objective_values(objective)),
            load=lambda: self.get(objective.id),
            expected=objective,
            conflict=lambda: ValueError(
                f"objective id already exists with different content: {objective.id}"
            ),
        )

    def get(self, objective_id: str) -> ProductObjectiveRevision | None:
        return load_one(
            self._engine,
            select(product_objective_revisions).where(
                product_objective_revisions.c.id == objective_id
            ),
            ProductObjectiveRevision,
            transform=_objective_from_row,
        )


def _policy_values(policy: MutationPolicy) -> dict[str, object]:
    return {
        "allowed_paths_json": list(policy.allowed_paths),
        "forbidden_paths_json": list(policy.forbidden_paths),
        "max_changed_files": policy.max_changed_files,
        "max_implementation_attempts": policy.max_implementation_attempts,
    }


def _policy(row: object) -> MutationPolicy:
    return record_from_row(
        MutationPolicy,
        row,
        rename={
            "allowed_paths_json": "allowed_paths",
            "forbidden_paths_json": "forbidden_paths",
        },
    )


def _target_values(target: DevelopmentTarget) -> dict[str, object]:
    return record_values(
        development_targets,
        target,
        mutation_policy=None,
        **_policy_values(target.mutation_policy),
    )


def _objective_values(objective: ProductObjectiveRevision) -> dict[str, object]:
    return record_values(
        product_objective_revisions,
        objective,
        mutation_policy=None,
        **_policy_values(objective.mutation_policy),
    )


def _target_from_row(row: object) -> DevelopmentTarget:
    return record_from_row(DevelopmentTarget, row, mutation_policy=_policy(row))


def _objective_from_row(row: object) -> ProductObjectiveRevision:
    return record_from_row(ProductObjectiveRevision, row, mutation_policy=_policy(row))
