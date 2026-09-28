from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from autonomous_development.adapters.postgres.experiments import SqlExperimentRepository
from autonomous_development.adapters.postgres.release_decisions import (
    SqlReleaseDecisionRepository,
)
from autonomous_development.domain.canary import CanaryStageDecision
from autonomous_development.domain.enums import (
    CanaryDecisionKind,
    ReleaseDecisionKind,
)
from autonomous_development.domain.models import (
    CanaryStage,
    Experiment,
    ReleaseDecision,
)

pytestmark = pytest.mark.integration




def test_postgres_experiment_stage_decision_is_durable_and_idempotent() -> None:
    database_url = os.environ["AUTODEV_DATABASE_URL"]
    engine = create_engine(database_url)
    repository = SqlExperimentRepository(engine)
    suffix = uuid4().hex
    experiment_id = f"experiment-{suffix}"
    operation_id = f"{experiment_id}:stage:0"
    initial = Experiment(
        id=experiment_id,
        target_id=f"target-{suffix}",
        control_release_id="release-1",
        candidate_deployment_id=f"deployment-{suffix}",
        stages=(
            CanaryStage(10, 60, 100),
            CanaryStage(100, 120, 200),
        ),
    )
    updated = Experiment(
        id=initial.id,
        target_id=initial.target_id,
        control_release_id=initial.control_release_id,
        candidate_deployment_id=initial.candidate_deployment_id,
        stages=initial.stages,
        current_stage_index=1,
    )
    decision = CanaryStageDecision(
        kind=CanaryDecisionKind.ADVANCE,
        experiment_id=experiment_id,
        stage_index=0,
        next_stage_index=1,
        evidence_refs=(f"canary:{suffix}:stage-0",),
        violated_guardrails=(),
        reason="stage passed",
    )

    try:
        repository.add(initial)
        first = repository.commit_stage_decision(
            updated,
            decision,
            expected_stage_index=0,
            operation_id=operation_id,
        )
        replay = repository.commit_stage_decision(
            updated,
            decision,
            expected_stage_index=0,
            operation_id=operation_id,
        )
        engine.dispose()

        reconnected = create_engine(database_url)
        try:
            recovered = SqlExperimentRepository(reconnected)
            persisted = recovered.get(experiment_id)
            history = recovered.list_stage_decisions(experiment_id)
            assert replay == first
            assert persisted == updated
            assert history == (first,)
        finally:
            reconnected.dispose()
    finally:
        engine.dispose()



def test_postgres_release_decision_receipt_survives_reconnect() -> None:
    database_url = os.environ["AUTODEV_DATABASE_URL"]
    engine = create_engine(database_url)
    repository = SqlReleaseDecisionRepository(engine)
    suffix = uuid4().hex
    operation_id = f"release-decision-{suffix}"
    decision = ReleaseDecision(
        kind=ReleaseDecisionKind.PROMOTE,
        cycle_id=f"cycle-{suffix}",
        gate_refs=("static", "tests"),
        evidence_refs=(f"canary:{suffix}:stage-0", f"canary:{suffix}:stage-1"),
        reason="all required evidence passed",
    )

    try:
        first = repository.record(operation_id, decision)
        replay = repository.record(operation_id, decision)
        engine.dispose()

        reconnected = create_engine(database_url)
        try:
            recovered = SqlReleaseDecisionRepository(reconnected).get(operation_id)
            assert replay == first
            assert recovered == first
        finally:
            reconnected.dispose()
    finally:
        engine.dispose()
