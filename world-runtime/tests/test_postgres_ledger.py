from __future__ import annotations

import asyncio
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from semantic_language import Decision, Mandate, Responsibility, SemanticKind, SemanticRef

from world_runtime import WorldRuntime
from world_runtime.postgres_ledger import PostgresLedger
from world_runtime.execution import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)
from world_runtime.ledger import ProjectionVersionConflict


DSN_ENV = "WORLD_RUNTIME_TEST_POSTGRES_DSN"


def _dsn() -> str:
    value = os.getenv(DSN_ENV, "").strip()
    if not value:
        pytest.skip(f"{DSN_ENV} is not configured")
    return value


def _schema(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _drop_schema(dsn: str, schema: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
        )


def _runtime_pair(prefix: str) -> tuple[str, str, WorldRuntime, WorldRuntime]:
    dsn = _dsn()
    schema = _schema(prefix)
    first = WorldRuntime.postgres(dsn, schema=schema, runtime_id=f"{prefix}:a")
    second = WorldRuntime.postgres(dsn, schema=schema, runtime_id=f"{prefix}:b")
    return dsn, schema, first, second


def _create_run(runtime: WorldRuntime, key: str):
    runtime.responsibility.create(
        Responsibility(
            id=f"responsibility:{key}",
            principal="service:test",
            subject=key,
        ),
        domain="test",
    )
    work = runtime.execution.admit_work(
        responsibility_id=f"responsibility:{key}",
        kind="test",
        payload={"key": key},
        work_id=f"work:{key}",
    )
    return runtime.start_run(work.id, workflow_id=key)


def _attested_effect(
    runtime: WorldRuntime,
    *,
    key: str,
) -> tuple[str, object, CapabilityRequest]:
    principal = f"service:{key}"
    token = f"token:{key}:{uuid.uuid4().hex}"
    runtime.identity.bind_bearer_token(
        principal=principal,
        token=token,
        credential_id=f"credential:{key}",
    )
    context = runtime.identity.authenticate_bearer(f"Bearer {token}")
    runtime.responsibility.create(
        Responsibility(
            id=f"responsibility:{key}",
            principal=principal,
            subject=key,
        ),
        domain="test",
    )
    work = runtime.execution.admit_work(
        responsibility_id=f"responsibility:{key}",
        kind="effect",
        payload={"key": key},
        work_id=f"work:{key}",
    )
    runtime.decisions.record_attested(
        Decision(
            id=f"decision:{key}",
            subject=f"resource:{key}",
            decided_by=principal,
            selected={
                "target_ref": f"resource:{key}",
                "operation": "authorize-effect",
                "action": "demo.effect",
            },
            basis_refs=(SemanticRef(SemanticKind.EVIDENCE, f"evidence:{key}"),),
        ),
        context=context,
    )
    runtime.governance.register_mandate_attested(
        Mandate(
            id=f"mandate:{key}",
            principal=principal,
            scope={"resource": f"resource:{key}"},
            authority_ceiling={
                "action": "demo.effect",
                "resource": f"resource:{key}",
            },
        ),
        context=context,
    )
    runtime.governance.issue_authorization_attested(
        context=context,
        authorization_id=f"authorization:{key}",
        principal=principal,
        action="demo.effect",
        resource=f"resource:{key}",
        mandate_id=f"mandate:{key}",
        decision_id=f"decision:{key}",
    )
    return token, context, CapabilityRequest(
        id=f"request:{key}",
        capability="demo.effect",
        work_id=work.id,
        effect_class="external-effect",
        principal=principal,
        actor_ref=principal,
        resource=f"resource:{key}",
        resource_ref=f"resource:{key}",
        authorization_id=f"authorization:{key}",
        idempotency_key=f"effect:{key}",
        parameters={"key": key},
    )


def test_postgres_projection_cas_has_one_cross_connection_winner() -> None:
    dsn = _dsn()
    schema = _schema("projection_cas")
    first = PostgresLedger(dsn, schema=schema)
    second = PostgresLedger(dsn, schema=schema)
    try:
        assert first.project_put("demo", "item", {"winner": None}, expected_version=0) == 1
        barrier = threading.Barrier(2)

        def update(ledger: PostgresLedger, winner: str) -> str:
            barrier.wait()
            try:
                ledger.project_put(
                    "demo",
                    "item",
                    {"winner": winner},
                    expected_version=1,
                )
                return winner
            except ProjectionVersionConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda args: update(*args),
                    [(first, "a"), (second, "b")],
                )
            )

        assert results.count("conflict") == 1
        winner = next(value for value in results if value != "conflict")
        current = first.project_get("demo", "item")
        assert current is not None
        assert current[0] == {"winner": winner}
        assert current[1] == 2
    finally:
        first.close()
        second.close()
        _drop_schema(dsn, schema)


def test_two_runtime_nodes_compete_for_one_run_lease() -> None:
    dsn, schema, first, second = _runtime_pair("run_lease")
    try:
        run = _create_run(first, "shared-run")
        barrier = threading.Barrier(2)

        def acquire(runtime: WorldRuntime, owner: str):
            barrier.wait()
            try:
                return runtime.execution.acquire_run_lease(
                    run.id,
                    owner=owner,
                    ttl_seconds=60,
                )
            except PermissionError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda args: acquire(*args),
                    [(first, "worker:a"), (second, "worker:b")],
                )
            )

        leases = [result for result in results if not isinstance(result, Exception)]
        failures = [result for result in results if isinstance(result, Exception)]
        assert len(leases) == 1
        assert len(failures) == 1
        assert "another owner" in str(failures[0]) or "concurrent race" in str(failures[0])

        current = first.execution.get_run(run.id)
        assert current is not None
        assert current.lease_owner in {"worker:a", "worker:b"}
        assert current.lease_generation == 1
    finally:
        first.ledger.close()
        second.ledger.close()
        _drop_schema(dsn, schema)


def test_two_runtime_nodes_grant_one_domain_provider_dispatch() -> None:
    dsn, schema, first, second = _runtime_pair("domain_start")
    try:
        token, context, request = _attested_effect(first, key="domain-start")
        second_context = second.identity.authenticate_bearer(f"Bearer {token}")

        prepared = first.effect_boundary.prepare(
            request,
            provider_id="provider:domain",
            provider_version="1",
            context=context,
        )
        assert prepared["status"] == "authorized"

        barrier = threading.Barrier(2)

        def start(runtime: WorldRuntime, request_context):
            barrier.wait()
            try:
                return runtime.effect_boundary.start(
                    request.idempotency_key or "",
                    context=request_context,
                )
            except PermissionError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda args: start(*args),
                    [(first, context), (second, second_context)],
                )
            )

        grants = [
            result
            for result in results
            if isinstance(result, dict) and result.get("dispatch_allowed") is True
        ]
        failures = [result for result in results if isinstance(result, Exception)]
        assert len(grants) == 1
        assert len(failures) == 1

        attempt = second.effect_boundary.get(request.idempotency_key or "")
        assert attempt["status"] == "started"
        assert attempt["dispatch_generation"] == 1
        authorization = second.ledger.project_get(
            "governance.authorization",
            "authorization:domain-start",
        )
        assert authorization is not None
        assert authorization[0]["uses"] == 1
    finally:
        first.ledger.close()
        second.ledger.close()
        _drop_schema(dsn, schema)


class ConcurrentProvider:
    _lock = threading.Lock()
    invoke_calls = 0
    completed = False

    def __init__(self) -> None:
        self._descriptor = ProviderDescriptor(
            id="concurrent-provider",
            name="Concurrent Provider",
            version="1",
            capabilities=["demo.effect"],
            reconciliation_protocol_identity="demo.reconcile",
            reconciliation_protocol_version="1",
            reconciliation_repeatability="repeat-safe",
            reconciliation_contract_version="1",
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self,
        request: CapabilityRequest,
        context: InvocationContext,
    ) -> CapabilityResult:
        del context
        with self._lock:
            type(self).invoke_calls += 1
        await asyncio.sleep(0.1)
        type(self).completed = True
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            data={"source": "invoke"},
        )

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        if not type(self).completed:
            return None
        return CapabilityResult(
            request_id=request_id,
            provider_id=self.descriptor.id,
            status="succeeded",
            data={"source": "reconcile"},
        )

    async def cancel(self, request_id: str) -> None:
        del request_id


def test_two_runtime_nodes_dispatch_runtime_provider_once() -> None:
    dsn, schema, first, second = _runtime_pair("provider_attempt")
    try:
        ConcurrentProvider.invoke_calls = 0
        ConcurrentProvider.completed = False
        first.registry.register(ConcurrentProvider())
        second.registry.register(ConcurrentProvider())
        _token, _context, request = _attested_effect(first, key="provider-race")

        barrier = threading.Barrier(2)

        def invoke(runtime: WorldRuntime):
            barrier.wait()
            return asyncio.run(runtime.invoke(request))

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(invoke, [first, second]))

        assert ConcurrentProvider.invoke_calls == 1
        assert any(result.status == "succeeded" for result in results)
        durable = first.ledger.project_get(
            "execution.provider-idempotency",
            "effect:provider-race",
        )
        assert durable is not None
        attempt = first.ledger.project_get(
            "execution.provider-attempt",
            "effect:provider-race",
        )
        assert attempt is not None
        assert attempt[0]["status"] == "committed"
    finally:
        first.ledger.close()
        second.ledger.close()
        _drop_schema(dsn, schema)


def test_state_bundle_round_trips_between_sqlite_and_postgres(tmp_path: Path) -> None:
    dsn = _dsn()
    schema = _schema("bundle")
    source = WorldRuntime.sqlite(tmp_path / "source.db")
    postgres = WorldRuntime.postgres(dsn, schema=schema)
    restored = WorldRuntime.sqlite(tmp_path / "restored.db")
    try:
        source.responsibility.create(
            Responsibility(
                id="responsibility:cross-backend",
                principal="service:test",
                subject="cross-backend",
            ),
            domain="test",
        )
        work = source.execution.admit_work(
            responsibility_id="responsibility:cross-backend",
            kind="bundle",
            payload={"value": 1},
            work_id="work:cross-backend",
        )
        source.start_run(work.id, workflow_id="bundle")

        bundle = source.state_bundle.export()
        postgres.state_bundle.import_bundle(bundle)
        assert postgres.state_bundle.export() == bundle

        restored.state_bundle.import_bundle(postgres.state_bundle.export())
        assert restored.state_bundle.export() == bundle
        assert (
            restored.responsibility.get("responsibility:cross-backend").principal
            == "service:test"
        )
    finally:
        source.ledger.close()
        postgres.ledger.close()
        restored.ledger.close()
        _drop_schema(dsn, schema)


def test_postgres_schemas_isolate_agency_state_with_same_ids() -> None:
    dsn = _dsn()
    schema_a = _schema("agency_a")
    schema_b = _schema("agency_b")
    first = WorldRuntime.postgres(dsn, schema=schema_a, runtime_id="agency:a")
    second = WorldRuntime.postgres(dsn, schema=schema_b, runtime_id="agency:b")
    try:
        first.responsibility.create(
            Responsibility(
                id="responsibility:same-id",
                principal="principal:agency-a",
                subject="agency a",
            ),
            domain="test",
        )
        second.responsibility.create(
            Responsibility(
                id="responsibility:same-id",
                principal="principal:agency-b",
                subject="agency b",
            ),
            domain="test",
        )

        assert (
            first.responsibility.get("responsibility:same-id").principal
            == "principal:agency-a"
        )
        assert (
            second.responsibility.get("responsibility:same-id").principal
            == "principal:agency-b"
        )
        assert first.state_bundle.export() != second.state_bundle.export()
    finally:
        first.ledger.close()
        second.ledger.close()
        _drop_schema(dsn, schema_a)
        _drop_schema(dsn, schema_b)


def test_shared_authorization_allows_distinct_runtime_effects_under_contention() -> None:
    dsn, schema, first, second = _runtime_pair("shared_runtime_authority")
    try:
        ConcurrentProvider.invoke_calls = 0
        ConcurrentProvider.completed = False
        first.registry.register(ConcurrentProvider())
        second.registry.register(ConcurrentProvider())
        _token, _context, base = _attested_effect(first, key="shared-runtime-authority")

        first_request = base.model_copy(
            update={
                "id": "request:shared-runtime-a",
                "idempotency_key": "effect:shared-runtime-a",
                "parameters": {"operation": "a"},
            }
        )
        second_request = base.model_copy(
            update={
                "id": "request:shared-runtime-b",
                "idempotency_key": "effect:shared-runtime-b",
                "parameters": {"operation": "b"},
            }
        )
        barrier = threading.Barrier(2)

        def invoke(runtime: WorldRuntime, request: CapabilityRequest) -> CapabilityResult:
            barrier.wait()
            return asyncio.run(runtime.invoke(request))

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda args: invoke(*args),
                    [(first, first_request), (second, second_request)],
                )
            )

        assert all(result.status == "succeeded" for result in results)
        assert ConcurrentProvider.invoke_calls == 2
        authorization = first.ledger.project_get(
            "governance.authorization",
            "authorization:shared-runtime-authority",
        )
        assert authorization is not None
        assert authorization[0]["uses"] == 2
    finally:
        first.ledger.close()
        second.ledger.close()
        _drop_schema(dsn, schema)


def test_shared_authorization_allows_distinct_domain_starts_under_contention() -> None:
    dsn, schema, first, second = _runtime_pair("shared_domain_authority")
    try:
        token, first_context, base = _attested_effect(first, key="shared-domain-authority")
        second_context = second.identity.authenticate_bearer(f"Bearer {token}")
        first_request = base.model_copy(
            update={
                "id": "request:shared-domain-a",
                "idempotency_key": "effect:shared-domain-a",
                "parameters": {"operation": "a"},
            }
        )
        second_request = base.model_copy(
            update={
                "id": "request:shared-domain-b",
                "idempotency_key": "effect:shared-domain-b",
                "parameters": {"operation": "b"},
            }
        )
        first.effect_boundary.prepare(
            first_request,
            provider_id="provider:domain",
            provider_version="1",
            context=first_context,
        )
        second.effect_boundary.prepare(
            second_request,
            provider_id="provider:domain",
            provider_version="1",
            context=second_context,
        )
        barrier = threading.Barrier(2)

        def start(runtime: WorldRuntime, key: str, context):
            barrier.wait()
            return runtime.effect_boundary.start(key, context=context)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda args: start(*args),
                    [
                        (first, "effect:shared-domain-a", first_context),
                        (second, "effect:shared-domain-b", second_context),
                    ],
                )
            )

        assert all(result["dispatch_allowed"] is True for result in results)
        assert all(result["dispatch_generation"] == 1 for result in results)
        authorization = first.ledger.project_get(
            "governance.authorization",
            "authorization:shared-domain-authority",
        )
        assert authorization is not None
        assert authorization[0]["uses"] == 2
    finally:
        first.ledger.close()
        second.ledger.close()
        _drop_schema(dsn, schema)



def _record_plain_decision(
    runtime: WorldRuntime,
    identifier: str,
    *,
    principal: str,
    target_ref: str,
    operation: str,
    **selected: object,
) -> None:
    runtime.decisions.record(
        Decision(
            id=identifier,
            subject=target_ref,
            decided_by=principal,
            selected={
                "target_ref": target_ref,
                "operation": operation,
                **selected,
            },
            basis_refs=(
                SemanticRef(
                    SemanticKind.EVIDENCE,
                    f"evidence:{identifier}",
                ),
            ),
        )
    )


def test_postgres_1_0_agency_state_survives_reopen_and_sqlite_round_trip(
    tmp_path: Path,
) -> None:
    dsn = _dsn()
    schema = _schema("agency_1_0")
    principal = "service:postgres-agency"
    first = WorldRuntime.postgres(dsn, schema=schema, runtime_id="agency-1.0:first")
    try:
        for identifier, domain in (
            ("responsibility:pg-parent", "coordination"),
            ("responsibility:pg-child", "development"),
        ):
            first.responsibility.create(
                Responsibility(
                    id=identifier,
                    principal=principal,
                    subject=identifier,
                ),
                domain=domain,
            )
        _record_plain_decision(
            first,
            "decision:pg-relate",
            principal=principal,
            target_ref="responsibility:pg-parent",
            operation="relate-responsibility",
            target_responsibility_id="responsibility:pg-child",
            relation="requires",
        )
        first.responsibility_graph.create(
            "responsibility:pg-parent",
            "responsibility:pg-child",
            relation="requires",
            decision_id="decision:pg-relate",
            basis_refs=("evidence:pg-relate",),
            relation_id="responsibility-relation:pg",
        )

        first.governance.register_mandate(
            Mandate(
                id="mandate:pg-strategy",
                principal=principal,
                scope={"subject": "company"},
                authority_ceiling={"action": "*", "resource": "*"},
            )
        )
        issue = first.portfolio.open_issue(
            issue_id="strategy-issue:pg",
            subject="company",
            question="Which bounded strategy remains qualified?",
            mandate_id="mandate:pg-strategy",
            basis_refs=("evidence:pg-issue",),
        )
        option = first.portfolio.record_option(
            issue.id,
            option_id="strategic-option:pg",
            hypothesis={"path": "bounded"},
            evaluation={"confidence": "medium"},
            basis_refs=("evidence:pg-option",),
        )
        proposal = first.portfolio.propose_portfolio(
            issue.id,
            proposal_id="portfolio-proposal:pg",
            option_ids=(option.id,),
            goal_refs=(),
            resource_budget={"cash": {"amount": 100.0, "unit": "CNY"}},
            basis_refs=("evidence:pg-proposal",),
        )
        _record_plain_decision(
            first,
            "decision:pg-activate",
            principal=principal,
            target_ref=proposal.id,
            operation="activate-portfolio",
        )
        first.portfolio.activate_portfolio(
            proposal.id,
            decision_id="decision:pg-activate",
            portfolio_id="portfolio:pg",
        )

        first.qualification.register_dependency(
            dependency_id="qualification-dependency:pg",
            principal=principal,
            subject_ref="portfolio:pg",
            dependency_ref="policy:pg",
            dependency_version="v1",
            assumption="policy remains compatible",
            review_policy={"on_change": "revalidate"},
            basis_refs=("evidence:pg-policy-v1",),
        )
        review = first.qualification.observe_dependency_change(
            principal=principal,
            dependency_ref="policy:pg",
            observed_version="v2",
            basis_refs=("evidence:pg-policy-v2",),
            reason="policy changed",
        )[0]
        first.qualification.assess_review(
            review.id,
            assessment_id="revalidation-assessment:pg",
            disposition="revalidate",
            basis_refs=("evidence:pg-review",),
        )
    finally:
        first.close()

    reopened = WorldRuntime.postgres(dsn, schema=schema, runtime_id="agency-1.0:reopened")
    restored = WorldRuntime.sqlite(tmp_path / "agency-1.0-restored.db")
    try:
        assert reopened.responsibility_graph.get(
            "responsibility-relation:pg"
        ).target_responsibility_id == "responsibility:pg-child"
        assert reopened.portfolio.get_portfolio("portfolio:pg").status == "active"
        pending = reopened.qualification.pending_obligations(principal=principal)
        assert len(pending) == 1
        assert pending[0].status == "assessed"

        bundle = reopened.state_bundle.export()
        assert reopened.state_bundle.validate(bundle).valid is True
        restored.state_bundle.import_bundle(bundle)
        assert restored.state_bundle.export() == bundle
        assert restored.portfolio.get_portfolio("portfolio:pg").resource_budget[
            "cash"
        ].unit == "CNY"
        assert restored.qualification.get_obligation(pending[0].id).status == "assessed"
    finally:
        reopened.close()
        restored.close()
        _drop_schema(dsn, schema)


def test_two_runtime_nodes_cannot_overallocate_one_portfolio_budget() -> None:
    dsn, schema, first, second = _runtime_pair("portfolio_budget")
    principal = "service:portfolio-budget"
    try:
        first.responsibility.create(
            Responsibility(
                id="responsibility:portfolio-budget",
                principal=principal,
                subject="bounded allocation",
            ),
            domain="operations",
        )
        first.governance.register_mandate(
            Mandate(
                id="mandate:portfolio-budget",
                principal=principal,
                scope={"subject": "company"},
                authority_ceiling={"action": "*", "resource": "*"},
            )
        )
        issue = first.portfolio.open_issue(
            issue_id="strategy-issue:portfolio-budget",
            subject="company",
            question="How should the bounded budget be allocated?",
            mandate_id="mandate:portfolio-budget",
            basis_refs=("evidence:portfolio-budget",),
        )
        option = first.portfolio.record_option(
            issue.id,
            option_id="strategic-option:portfolio-budget",
            hypothesis={"path": "bounded"},
            evaluation={"confidence": "high"},
            basis_refs=("evidence:portfolio-budget-option",),
        )
        proposal = first.portfolio.propose_portfolio(
            issue.id,
            proposal_id="portfolio-proposal:portfolio-budget",
            option_ids=(option.id,),
            goal_refs=(),
            resource_budget={"cash": {"amount": 100.0, "unit": "CNY"}},
            basis_refs=("evidence:portfolio-budget-proposal",),
        )
        _record_plain_decision(
            first,
            "decision:portfolio-budget:activate",
            principal=principal,
            target_ref=proposal.id,
            operation="activate-portfolio",
        )
        portfolio = first.portfolio.activate_portfolio(
            proposal.id,
            decision_id="decision:portfolio-budget:activate",
            portfolio_id="portfolio:portfolio-budget",
        )

        for suffix in ("a", "b"):
            _record_plain_decision(
                first,
                f"decision:portfolio-budget:{suffix}",
                principal=principal,
                target_ref=portfolio.id,
                operation="allocate-resource",
                responsibility_id="responsibility:portfolio-budget",
                resource_type="cash",
                amount=60.0,
                unit="CNY",
            )

        barrier = threading.Barrier(2)

        def allocate(runtime: WorldRuntime, suffix: str):
            barrier.wait()
            try:
                return runtime.portfolio.allocate(
                    portfolio.id,
                    "responsibility:portfolio-budget",
                    resource_type="cash",
                    amount=60.0,
                    unit="CNY",
                    decision_id=f"decision:portfolio-budget:{suffix}",
                    basis_refs=(f"evidence:allocation:{suffix}",),
                    allocation_id=f"resource-allocation:{suffix}",
                )
            except (ValueError, ProjectionVersionConflict) as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda args: allocate(*args),
                    [(first, "a"), (second, "b")],
                )
            )

        successes = [item for item in results if not isinstance(item, Exception)]
        failures = [item for item in results if isinstance(item, Exception)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert "exceeds portfolio budget" in str(failures[0])

        state = first.ledger.project_get(
            "strategy.portfolio-allocation-state",
            portfolio.id,
        )
        assert state is not None
        assert state[0]["used"]["cash"] == 60.0
    finally:
        first.close()
        second.close()
        _drop_schema(dsn, schema)
