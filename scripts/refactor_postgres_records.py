from pathlib import Path

ROOT = Path("src/domains/autonomous_development/adapters/postgres")


def write(name: str, content: str) -> None:
    (ROOT / name).write_text(content)


write(
    "records.py",
    '''from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, datetime
from functools import cache
from typing import Any, TypeVar

from pydantic import TypeAdapter
from sqlalchemy import Engine, Table
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

T = TypeVar("T")


@cache
def _adapter(model: type[Any]) -> TypeAdapter[Any]:
    return TypeAdapter(model)


@cache
def _fields(model: type[Any]) -> frozenset[str]:
    return frozenset(field.name for field in fields(model))


def record_values(table: Table, value: object, **extra: object) -> dict[str, object]:
    data = _adapter(type(value)).dump_python(value, mode="python")
    values: dict[str, object] = {}
    for column in table.columns:
        field = column.name.removesuffix("_json")
        if field not in data:
            continue
        item = data[field]
        if item is None and column.primary_key and column.autoincrement:
            continue
        values[column.name] = item
    values.update(extra)
    return values


def record_from_row(model: type[T], row: RowMapping) -> T:
    names = _fields(model)
    values: dict[str, object] = {}
    for column, item in row.items():
        field = str(column).removesuffix("_json")
        if field not in names:
            continue
        if isinstance(item, datetime) and item.tzinfo is None:
            item = item.replace(tzinfo=UTC)
        values[field] = item
    return _adapter(model).validate_python(values)


def load_one(engine: Engine, statement: Any, model: type[T]) -> T | None:
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().first()
    return None if row is None else record_from_row(model, row)


def insert_once(
    engine: Engine,
    statement: Any,
    *,
    load: Callable[[], T | None],
    expected: T,
    conflict: Callable[[], Exception],
) -> T:
    existing = load()
    if existing is not None:
        if existing != expected:
            raise conflict()
        return existing
    try:
        with engine.begin() as connection:
            connection.execute(statement)
    except IntegrityError as exc:
        existing = load()
        if existing is None:
            raise
        if existing != expected:
            raise conflict() from exc
        return existing
    return expected
''',
)


def simple_repository(
    *,
    filename: str,
    model: str,
    protocol: str,
    table: str,
    identifier: str,
    argument: str,
    conflict: str,
) -> None:
    write(
        filename,
        f'''from __future__ import annotations

from sqlalchemy import Engine, insert, select

from autonomous_development.domain.models import {model}
from autonomous_development.ports.persistence import {protocol}

from .records import insert_once, load_one, record_values
from .schema import {table}


class Sql{model}Repository({protocol}):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, {argument}: {model}) -> {model}:
        return insert_once(
            self._engine,
            insert({table}).values(**record_values({table}, {argument})),
            load=lambda: self.get({argument}.{identifier}),
            expected={argument},
            conflict=lambda: ValueError(
                f"{conflict}"
            ),
        )

    def get(self, {identifier}: str) -> {model} | None:
        return load_one(
            self._engine,
            select({table}).where({table}.c.{identifier} == {identifier}),
            {model},
        )
''',
    )


simple_repository(
    filename="proposals.py",
    model="ChangeProposal",
    protocol="ChangeProposalRepository",
    table="change_proposals",
    identifier="id",
    argument="proposal",
    conflict="proposal id already exists with different content: {proposal.id}",
)
simple_repository(
    filename="diagnoses.py",
    model="Diagnosis",
    protocol="DiagnosisRepository",
    table="diagnoses",
    identifier="id",
    argument="diagnosis",
    conflict="diagnosis id already exists with different content: {diagnosis.id}",
)
simple_repository(
    filename="evidence_windows.py",
    model="EvidenceWindow",
    protocol="EvidenceWindowRepository",
    table="evidence_windows",
    identifier="id",
    argument="window",
    conflict="evidence window id already exists with different content: {window.id}",
)

write(
    "request_attributions.py",
    '''from __future__ import annotations

from sqlalchemy import Engine, insert, select

from autonomous_development.domain.models import RequestAttribution
from autonomous_development.ports.persistence import RequestAttributionRepository

from .records import insert_once, load_one, record_values
from .schema import request_attributions


class SqlRequestAttributionRepository(RequestAttributionRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, attribution: RequestAttribution) -> RequestAttribution:
        return insert_once(
            self._engine,
            insert(request_attributions).values(
                **record_values(request_attributions, attribution)
            ),
            load=lambda: self.get(attribution.request_ref),
            expected=attribution,
            conflict=lambda: ValueError(
                "request reference already exists with different attribution: "
                f"{attribution.request_ref}"
            ),
        )

    def get(self, request_ref: str) -> RequestAttribution | None:
        return load_one(
            self._engine,
            select(request_attributions).where(
                request_attributions.c.request_ref == request_ref
            ),
            RequestAttribution,
        )
''',
)

write(
    "feedback.py",
    '''from __future__ import annotations

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
''',
)

write(
    "feedback_triggers.py",
    '''from __future__ import annotations

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
''',
)

p = ROOT / "cycles.py"
c = p.read_text()
if "def _cycle_values(" in c:
    c = c.replace("from sqlalchemy.engine import RowMapping\n", "")
    c = c.replace(
        "from autonomous_development.domain.enums import CycleState, ReleaseDecisionKind\n",
        "from autonomous_development.domain.enums import CycleState\n",
    )
    c = c.replace(
        "from .schema import cycle_transitions, cycles\n",
        "from .records import load_one, record_values\nfrom .schema import cycle_transitions, cycles\n",
    )
    c = c.replace(
        "connection.execute(insert(cycles).values(**_cycle_values(cycle)))",
        "connection.execute(insert(cycles).values(**record_values(cycles, cycle, is_terminal=cycle.state in TERMINAL_STATES)))",
    )
    c = c.replace(
        '''        with self._engine.connect() as connection:
            row = (
                connection.execute(select(cycles).where(cycles.c.id == cycle_id))
                .mappings()
                .first()
            )
        return _cycle_from_row(row) if row is not None else None
''',
        '''        return load_one(
            self._engine, select(cycles).where(cycles.c.id == cycle_id), DevelopmentCycle
        )
''',
    )
    c = c.replace(
        '''        with self._engine.connect() as connection:
            row = connection.execute(
                select(cycles).where(
                    cycles.c.target_id == target_id,
                    cycles.c.is_terminal.is_(False),
                )
            ).mappings().first()
        return _cycle_from_row(row) if row is not None else None
''',
        '''        return load_one(
            self._engine,
            select(cycles).where(
                cycles.c.target_id == target_id, cycles.c.is_terminal.is_(False)
            ),
            DevelopmentCycle,
        )
''',
    )
    c = c.replace(
        '''        with self._engine.connect() as connection:
            row = connection.execute(
                select(cycle_transitions).where(
                    cycle_transitions.c.operation_id == operation_id
                )
            ).mappings().first()
        return _receipt_from_row(row) if row is not None else None
''',
        '''        return load_one(
            self._engine,
            select(cycle_transitions).where(cycle_transitions.c.operation_id == operation_id),
            TransitionReceipt,
        )
''',
    )
    c = c.replace(
        "insert(cycle_transitions).values(**_receipt_values(receipt))",
        "insert(cycle_transitions).values(**record_values(cycle_transitions, receipt))",
    )
    c = c.replace(
        ".values(**_cycle_values(cycle))",
        ".values(**record_values(cycles, cycle, is_terminal=cycle.state in TERMINAL_STATES))",
    )
    c = c[: c.index("\ndef _cycle_values(")] + "\n"
    p.write_text(c)

p = ROOT / "experiments.py"
c = p.read_text()
if "def _experiment_values(" in c:
    c = c.replace("from sqlalchemy.engine import RowMapping\n", "")
    c = c.replace("from autonomous_development.domain.enums import CanaryDecisionKind\n", "")
    c = c.replace(
        "from autonomous_development.domain.models import CanaryStage, Experiment\n",
        "from autonomous_development.domain.models import Experiment\n",
    )
    c = c.replace(
        "from .schema import experiment_stage_operations, experiments\n",
        "from .records import load_one, record_from_row, record_values\n"
        "from .schema import experiment_stage_operations, experiments\n",
    )
    c = c.replace(
        "insert(experiments).values(**_experiment_values(experiment))",
        "insert(experiments).values(**record_values(experiments, experiment))",
    )
    c = c.replace(
        '''        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(experiments).where(experiments.c.id == experiment_id)
                )
                .mappings()
                .first()
            )
        return _experiment_from_row(row) if row is not None else None
''',
        '''        return load_one(
            self._engine, select(experiments).where(experiments.c.id == experiment_id), Experiment
        )
''',
    )
    c = c.replace(
        '''        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(experiment_stage_operations).where(
                        experiment_stage_operations.c.operation_id == operation_id
                    )
                )
                .mappings()
                .first()
            )
        return _receipt_from_row(row) if row is not None else None
''',
        '''        return load_one(
            self._engine,
            select(experiment_stage_operations).where(
                experiment_stage_operations.c.operation_id == operation_id
            ),
            ExperimentStageReceipt,
        )
''',
    )
    c = c.replace(
        "return tuple(_receipt_from_row(row) for row in rows)",
        "return tuple(record_from_row(ExperimentStageReceipt, row) for row in rows)",
    )
    c = c.replace(
        "insert(experiment_stage_operations).values(**_receipt_values(receipt))",
        "insert(experiment_stage_operations).values(**record_values(experiment_stage_operations, receipt))",
    )
    c = c[: c.index("\ndef _experiment_values(")] + "\n"
    p.write_text(c)

p = ROOT / "releases.py"
c = p.read_text()
if "def _release_values(" in c:
    c = c.replace("from datetime import UTC, datetime\n\n", "")
    c = c.replace("from sqlalchemy.engine import RowMapping\n", "")
    c = c.replace(
        "from .schema import (\n",
        "from .records import insert_once, load_one, record_from_row, record_values\n"
        "from .schema import (\n",
    )
    old = '''        existing = self.get(release.id)
        if existing is not None:
            if existing != release:
                raise ValueError(
                    f"release id already exists with different identity: {release.id}"
                )
            return existing
        try:
            with self._engine.begin() as connection:
                connection.execute(insert(released_versions).values(**_release_values(release)))
        except IntegrityError:
            existing = self.get(release.id)
            if existing is None or existing != release:
                raise
            return existing
        return release
'''
    new = '''        return insert_once(
            self._engine,
            insert(released_versions).values(**record_values(released_versions, release)),
            load=lambda: self.get(release.id),
            expected=release,
            conflict=lambda: ValueError(
                f"release id already exists with different identity: {release.id}"
            ),
        )
'''
    c = c.replace(old, new)
    c = c.replace(
        '''        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(released_versions).where(released_versions.c.id == release_id)
                )
                .mappings()
                .first()
            )
        return _release_from_row(row) if row is not None else None
''',
        '''        return load_one(
            self._engine,
            select(released_versions).where(released_versions.c.id == release_id),
            ReleasedVersion,
        )
''',
    )
    c = c.replace(
        "return _release_from_row(row) if row is not None else None",
        "return record_from_row(ReleasedVersion, row) if row is not None else None",
    )
    start = c.index("    def _get_operation(")
    end = c.index("\n\ndef _validate_receipt", start)
    c = (
        c[:start]
        + '''    def _get_operation(self, operation_id: str) -> ServingReleaseReceipt | None:
        return load_one(
            self._engine,
            select(serving_release_operations).where(
                serving_release_operations.c.operation_id == operation_id
            ),
            ServingReleaseReceipt,
        )
'''
        + c[end:]
    )
    c = c[: c.index("\ndef _release_values(")] + "\n"
    p.write_text(c)

p = ROOT / "operator.py"
c = p.read_text()
if "def _request_values(" in c:
    c = c.replace("from sqlalchemy.engine import RowMapping\n", "")
    c = c.replace(
        "from .schema import ",
        "from .records import record_from_row, record_values\nfrom .schema import ",
        1,
    )
    for old, new in (
        ("_request_values(request)", "record_values(development_requests, request)"),
        ("_analysis_values(analysis)", "record_values(requirement_analyses, analysis)"),
        ("_intervention_values(intervention)", "record_values(human_interventions, intervention)"),
        ("_intervention_values(updated)", "record_values(human_interventions, updated)"),
        ("_event_values(event)", "record_values(operator_events, event)"),
    ):
        c = c.replace(old, new)
    c = c.replace(
        "return None if row is None else _request_from_row(row)",
        "return None if row is None else record_from_row(DevelopmentRequest, row)",
    )
    c = c.replace(
        "return None if row is None else _analysis_from_row(row)",
        "return None if row is None else record_from_row(RequirementAnalysis, row)",
    )
    c = c.replace(
        "return None if row is None else _intervention_from_row(row)",
        "return None if row is None else record_from_row(HumanIntervention, row)",
    )
    c = c.replace(
        "return tuple(_intervention_from_row(row) for row in rows)",
        "return tuple(record_from_row(HumanIntervention, row) for row in rows)",
    )
    c = c.replace(
        "return tuple(_event_from_row(row) for row in rows)",
        "return tuple(record_from_row(OperatorEvent, row) for row in rows)",
    )
    c = c.replace(
        "return None if row is None else _event_from_row(row)",
        "return None if row is None else record_from_row(OperatorEvent, row)",
    )
    c = c[: c.index("\ndef _request_values(")] + "\n"
    p.write_text(c)
