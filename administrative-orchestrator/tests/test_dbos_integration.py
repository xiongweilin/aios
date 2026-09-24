from __future__ import annotations

import os
import secrets
import time
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID

import psycopg
import pytest
from sqlalchemy import create_engine, func, select

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.domain import (
    AdministrativeRequest,
    CaseStatus,
    Decision,
    DecisionDisposition,
    FactSnapshot,
    PolicyRef,
)
from administrative_orchestrator.effect_provider import (
    ProviderExecutionResult,
    ProviderExecutionStatus,
    RealityObservation,
)
from administrative_orchestrator.execution_repository import ExecutionRepository
from administrative_orchestrator.messaging import claim_outbox, mark_dispatched
from administrative_orchestrator.persistence import Base, OutcomeRow, SqlStore
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy
from administrative_orchestrator.service import (
    apply_policy_evaluation,
    create_case,
    record_decision,
    start_policy_evaluation,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork
from administrative_orchestrator.workflows.relay import (
    execute_outbox_action,
    plan_outbox_action,
)

pytestmark = pytest.mark.skipif(
    os.getenv("ADMIN_RUN_DBOS_INTEGRATION") != "1",
    reason="set ADMIN_RUN_DBOS_INTEGRATION=1 to run PostgreSQL/DBOS integration",
)

PG_ADMIN_URL = os.getenv(
    "ADMIN_TEST_PG_ADMIN_URL",
    "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
)


class FakeAuthoritativeProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.realized: dict[UUID, tuple[tuple[str, str, str], dict]] = {}

    def execute(self, effect, payload):
        self.calls += 1
        identity = (effect.target_system, effect.operation, effect.subject_ref)
        prior = self.realized.get(effect.effect_id)
        if prior is not None and prior[0] != identity:
            raise AssertionError("effect id reused with different provider semantics")
        self.realized[effect.effect_id] = (identity, dict(payload))
        return ProviderExecutionResult(
            status=ProviderExecutionStatus.SUCCEEDED,
            provider_ref=f"fake:{effect.effect_id}",
        )

    def observe(self, effect):
        prior = self.realized.get(effect.effect_id)
        if prior is None:
            return RealityObservation(
                found=False,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
            )
        return RealityObservation(
            found=True,
            target_system=effect.target_system,
            operation=effect.operation,
            subject_ref=effect.subject_ref,
            provider_ref=f"fake:{effect.effect_id}",
            state={"active": True, "payload": prior[1]},
            digest=f"digest:{effect.effect_id}",
        )


def _create_database(name: str) -> None:
    with psycopg.connect(PG_ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')


def _drop_database(name: str) -> None:
    with psycopg.connect(PG_ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _wait_until(predicate, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("condition did not become true before timeout")


def _relay_all(store: SqlStore) -> int:
    events = claim_outbox(store, batch=50, lease_seconds=30)
    for event in events:
        execute_outbox_action(plan_outbox_action(event))
        mark_dispatched(store, event.event_id)
    return len(events)


def test_worker_restart_recovers_waiting_onboarding_and_effects_are_once(monkeypatch) -> None:
    from dbos import DBOS, DBOSConfig

    token = secrets.token_hex(4)
    app_db = f"admin_dbos_app_{token}"
    sys_db = f"admin_dbos_sys_{token}"
    _create_database(app_db)
    _create_database(sys_db)
    app_url = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{app_db}"
    sys_url = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{sys_db}"
    app_engine = create_engine(app_url, pool_pre_ping=True)
    Base.metadata.create_all(app_engine)
    fake = FakeAuthoritativeProvider()

    monkeypatch.setenv("ADMIN_DATABASE_URL", app_url)
    monkeypatch.setenv("ADMIN_WORKER_DATABASE_URL", app_url)
    monkeypatch.setenv("ADMIN_DBOS_SYSTEM_DATABASE_URL", sys_url)
    monkeypatch.setenv("ADMIN_EXTERNAL_EFFECTS_ENABLED", "true")
    get_settings.cache_clear()

    config = DBOSConfig(
        name="admin-orchestrator-test",
        system_database_url=sys_url,
        application_database_url=app_url,
        log_level="WARNING",
        dbos_system_schema="dbos",
    )

    try:
        DBOS(config=config)
        from administrative_orchestrator.workflows import definitions

        monkeypatch.setattr(definitions, "HttpEffectProvider", lambda *args, **kwargs: fake)
        DBOS.launch()

        store = SqlStore(app_url)
        uow = AdministrativeUnitOfWork(store)
        facts = OnboardingFacts(
            employee_ref="employee:new",
            department_ref="department:engineering",
            manager_principal_id="person:manager",
            start_date="2026-09-15",
            employment_type="full-time",
        )
        request = AdministrativeRequest(
            requester_principal_id="person:requester",
            channel="integration-test",
            intent="onboard employee:new",
        )
        original = create_case(
            request,
            case_kind="employee-onboarding",
            subject_ref="employee:new",
            fact_snapshot=FactSnapshot(
                source="integration-test",
                owner="integration-test",
                facts=facts.model_dump(mode="json"),
            ),
        )
        uow.create_case(request, original)
        ready = start_policy_evaluation(original)
        policy_ref = PolicyRef(
            policy_id="employee-onboarding",
            version="v0.1",
            owner="integration-test",
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
        evaluation = OnboardingPolicy(policy_ref).evaluate(facts)
        awaiting = apply_policy_evaluation(ready, evaluation)
        uow.apply_policy_transition(original, awaiting, evaluation)

        assert _relay_all(store) == 1
        _wait_until(lambda: DBOS.get_workflow_status(str(awaiting.case_id)) is not None)

        current = store.get_case(awaiting.case_id)
        assert current is not None
        decision = Decision(
            case_id=current.case_id,
            case_version=current.version,
            authority_epoch=current.authority_epoch,
            principal_id="person:hr-approver",
            disposition=DecisionDisposition.APPROVE,
            rationale="integration approval",
            policy_ref=policy_ref,
        )
        authorized = record_decision(current, decision)
        uow.apply_decision_transition(current, authorized, decision)

        DBOS.destroy()
        DBOS(config=config)
        DBOS.launch()

        assert _relay_all(store) == 1
        DBOS.resume_workflows([str(authorized.case_id)])
        _wait_until(
            lambda: (store.get_case(authorized.case_id) or authorized).status
            == CaseStatus.COMPLETED,
            timeout=60,
        )

        completed = store.get_case(authorized.case_id)
        assert completed is not None
        assert completed.status == CaseStatus.COMPLETED
        effects = ExecutionRepository(store).list_effects(
            completed.case_id,
            completed.authority_epoch,
        )
        assert len(effects) == 2
        assert fake.calls == 2

        with store.sessions() as db:
            outcome_count = db.execute(
                select(func.count())
                .select_from(OutcomeRow)
                .where(OutcomeRow.case_id == completed.case_id)
            ).scalar_one()
        assert outcome_count == 2
    finally:
        with suppress(Exception):
            DBOS.destroy()
        get_settings.cache_clear()
        app_engine.dispose()
        _drop_database(app_db)
        _drop_database(sys_db)
