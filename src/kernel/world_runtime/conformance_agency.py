from __future__ import annotations

import asyncio
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from semantic_language import SemanticKind
from semantic_language import SemanticRef
from .decisions import Decision
from .governance import Mandate
from .responsibility import Responsibility
from .execution import CapabilityRequest
from .identity import DelegationGrant
from .runtime import WorldRuntime
from .conformance_support import _RecoverableProvider, _conformance_token, _responsibility, _decision
from .conformance_execution import _SharedDispatchProvider, _shared_sqlite_effect_fixture

async def _shared_authority_runtime_effects() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "conformance-shared-runtime-authority.db"
        first, second, _first_context, _second_context, base = (
            _shared_sqlite_effect_fixture(path, key="shared-runtime-authority")
        )
        state: dict[str, Any] = {"invoke_calls": 0, "completed": False}
        first.registry.register(_SharedDispatchProvider(state))
        second.registry.register(_SharedDispatchProvider(state))
        try:
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
            results = await asyncio.gather(
                first.invoke(first_request),
                second.invoke(second_request),
            )
            if any(item.status != "succeeded" for item in results):
                raise AssertionError("distinct effects under shared Authorization did not succeed")
            if int(state["invoke_calls"]) != 2:
                raise AssertionError("distinct effects under shared Authorization were deduplicated")
            authorization = first.ledger.project_get(
                "governance.authorization",
                "authorization:shared-runtime-authority",
            )
            if authorization is None or int(authorization[0].get("uses", 0)) != 2:
                raise AssertionError("shared Authorization use count is incorrect")
        finally:
            first.ledger.close()
            second.ledger.close()

def _shared_authority_domain_starts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "conformance-shared-domain-authority.db"
        first, second, first_context, second_context, base = (
            _shared_sqlite_effect_fixture(path, key="shared-domain-authority")
        )
        try:
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

            def start(runtime: WorldRuntime, key: str, context: Any) -> dict[str, Any]:
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
            if not all(item.get("dispatch_allowed") is True for item in results):
                raise AssertionError("distinct Domain effects were incorrectly fenced")
            if not all(int(item.get("dispatch_generation", 0)) == 1 for item in results):
                raise AssertionError("distinct Domain effects have invalid dispatch generation")
            authorization = first.ledger.project_get(
                "governance.authorization",
                "authorization:shared-domain-authority",
            )
            if authorization is None or int(authorization[0].get("uses", 0)) != 2:
                raise AssertionError("shared Authorization Domain use count is incorrect")
        finally:
            first.ledger.close()
            second.ledger.close()

def _responsibility_dependency_gate() -> None:
    runtime = WorldRuntime.sqlite()
    for identifier, domain in (
        ("responsibility:parent", "operations"),
        ("responsibility:child", "development"),
    ):
        runtime.responsibility.create(
            Responsibility(
                id=identifier,
                principal="service:conformance",
                subject=identifier,
                domain=domain,
            )
        )
    _decision(
        runtime,
        identifier="decision:relate-parent-child",
        target_ref="responsibility:parent",
        operation="relate-responsibility",
        selected={
            "target_responsibility_id": "responsibility:child",
            "relation": "requires",
        },
    )
    runtime.responsibility_graph.create(
        "responsibility:parent",
        "responsibility:child",
        relation="requires",
        decision_id="decision:relate-parent-child",
        basis_refs=("evidence:relation",),
    )
    try:
        runtime.responsibility.assess(
            "responsibility:parent",
            status="satisfied",
            basis_refs=("evidence:parent",),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("unresolved required child allowed parent satisfaction")

    runtime.responsibility.assess(
        "responsibility:child",
        status="satisfied",
        basis_refs=("evidence:child",),
    )
    _decision(
        runtime,
        identifier="decision:discharge-child",
        target_ref="responsibility:child",
        operation="discharge-responsibility",
        selected={"to_status": "discharged"},
    )
    runtime.responsibility.discharge(
        "responsibility:child",
        decision_id="decision:discharge-child",
    )
    if runtime.responsibility.get("responsibility:parent").status != "active":
        raise AssertionError("child discharge silently changed parent status")
    runtime.responsibility.assess(
        "responsibility:parent",
        status="satisfied",
        basis_refs=("evidence:parent-after-child",),
    )

def _responsibility_cycle_gate() -> None:
    runtime = WorldRuntime.sqlite()
    for identifier, domain in (
        ("responsibility:a", "operations"),
        ("responsibility:b", "development"),
        ("responsibility:c", "administrative"),
    ):
        runtime.responsibility.create(
            Responsibility(
                id=identifier,
                principal="service:conformance",
                subject=identifier,
                domain=domain,
            )
        )
    for decision_id, source, target in (
        ("decision:a-b", "responsibility:a", "responsibility:b"),
        ("decision:b-c", "responsibility:b", "responsibility:c"),
    ):
        _decision(
            runtime,
            identifier=decision_id,
            target_ref=source,
            operation="relate-responsibility",
            selected={"target_responsibility_id": target, "relation": "requires"},
        )
        runtime.responsibility_graph.create(
            source,
            target,
            relation="requires",
            decision_id=decision_id,
            basis_refs=(f"evidence:{decision_id}",),
        )
    _decision(
        runtime,
        identifier="decision:c-a",
        target_ref="responsibility:c",
        operation="relate-responsibility",
        selected={"target_responsibility_id": "responsibility:a", "relation": "requires"},
    )
    try:
        runtime.responsibility_graph.create(
            "responsibility:c",
            "responsibility:a",
            relation="requires",
            decision_id="decision:c-a",
            basis_refs=("evidence:cycle",),
        )
    except ValueError:
        return
    raise AssertionError("hard responsibility dependency cycle was accepted")

def _strategic_portfolio_decision_gate() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.governance.register_mandate(
        Mandate(id="mandate:strategy-conformance", principal="service:conformance")
    )
    issue = runtime.portfolio.open_issue(
        issue_id="strategy-issue:conformance",
        subject="company",
        question="Which path should become active?",
        mandate_id="mandate:strategy-conformance",
        basis_refs=("evidence:strategy-issue",),
    )
    option = runtime.portfolio.record_option(
        issue.id,
        option_id="strategic-option:conformance",
        hypothesis={"path": "one"},
        evaluation={"confidence": "medium"},
        basis_refs=("evidence:option",),
    )
    proposal = runtime.portfolio.propose_portfolio(
        issue.id,
        proposal_id="portfolio-proposal:conformance",
        option_ids=(option.id,),
        goal_refs=(),
        resource_budget={},
        basis_refs=("evidence:portfolio",),
    )
    if hasattr(runtime.strategy, "rank_options"):
        raise AssertionError("Runtime still exposes a universal strategic ranking function")
    try:
        runtime.portfolio.activate_portfolio(
            proposal.id,
            decision_id="decision:missing",
        )
    except ValueError:
        if runtime.ledger.project_get("strategy.portfolio-current", issue.id) is not None:
            raise AssertionError("failed activation mutated current portfolio")
        return
    raise AssertionError("portfolio activated without applicable Decision")

def _strategic_resource_budget_gate() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.governance.register_mandate(
        Mandate(id="mandate:budget-conformance", principal="service:conformance")
    )
    issue = runtime.portfolio.open_issue(
        issue_id="strategy-issue:budget",
        subject="company",
        question="How much resource may be allocated?",
        mandate_id="mandate:budget-conformance",
        basis_refs=("evidence:budget-issue",),
    )
    option = runtime.portfolio.record_option(
        issue.id,
        option_id="strategic-option:budget",
        hypothesis={"path": "bounded"},
        evaluation={"confidence": "high"},
        basis_refs=("evidence:budget-option",),
    )
    proposal = runtime.portfolio.propose_portfolio(
        issue.id,
        proposal_id="portfolio-proposal:budget",
        option_ids=(option.id,),
        goal_refs=(),
        resource_budget={"cash": {"amount": 100.0, "unit": "CNY"}},
        basis_refs=("evidence:budget-proposal",),
    )
    _decision(
        runtime,
        identifier="decision:activate-budget",
        target_ref=proposal.id,
        operation="activate-portfolio",
    )
    portfolio = runtime.portfolio.activate_portfolio(
        proposal.id,
        decision_id="decision:activate-budget",
        portfolio_id="portfolio:budget",
    )
    runtime.responsibility.create(
        Responsibility(
            id="responsibility:budget",
            principal="service:conformance",
            subject="spend budget",
            domain="finance",
        )
    )
    _decision(
        runtime,
        identifier="decision:allocate-wrong-unit",
        target_ref=portfolio.id,
        operation="allocate-resource",
        selected={
            "responsibility_id": "responsibility:budget",
            "resource_type": "cash",
            "amount": 10.0,
            "unit": "USD",
        },
    )
    try:
        runtime.portfolio.allocate(
            portfolio.id,
            "responsibility:budget",
            resource_type="cash",
            amount=10.0,
            unit="USD",
            decision_id="decision:allocate-wrong-unit",
            basis_refs=("evidence:wrong-unit",),
        )
    except ValueError:
        state = runtime.ledger.project_get(
            "strategy.portfolio-allocation-state",
            portfolio.id,
        )
        if state is None or state[0].get("used") != {}:
            raise AssertionError("rejected resource allocation changed durable budget")
        return
    raise AssertionError("resource allocation with mismatched unit was accepted")

def _qualification_review_not_invalidation() -> None:
    runtime = WorldRuntime.sqlite()
    decision = Decision(
        id="decision:qualification-subject",
        subject="pricing",
        decided_by="service:conformance",
        selected={"target_ref": "pricing", "operation": "hold"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:decision"),),
    )
    runtime.decisions.record(decision)
    runtime.qualification.register_binding(
        binding_id="qualification-dependency:conformance",
        principal="service:conformance",
        subject_ref=decision.id,
        dependency_ref="policy:pricing",
        dependency_version="v1",
        assumption="pricing policy remains applicable",
        basis_refs=("evidence:policy-v1",),
    )
    reviews = runtime.qualification.observe_dependency_change(
        principal="service:conformance",
        dependency_ref="policy:pricing",
        observed_version="v2",
        basis_refs=("evidence:policy-v2",),
    )
    if len(reviews) != 1:
        raise AssertionError("dependency change did not create targeted review")
    runtime.decisions.assert_current(decision.id)
    if runtime.qualification.get_binding(
        "qualification-dependency:conformance"
    ).status != "active":
        raise AssertionError("dependency change silently invalidated current basis")

def _qualification_action_remains_pending() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.qualification.register_binding(
        binding_id="qualification-dependency:pending",
        principal="service:conformance",
        subject_ref="mandate:pending",
        dependency_ref="authority-source:owner",
        dependency_version="epoch-1",
        assumption="authority source remains current",
        review_policy={"on_change": "reauthorize"},
        basis_refs=("evidence:epoch-1",),
    )
    review = runtime.qualification.observe_dependency_change(
        principal="service:conformance",
        dependency_ref="authority-source:owner",
        observed_version="epoch-2",
        basis_refs=("evidence:epoch-2",),
    )[0]
    runtime.qualification.assess_review(
        review.id,
        disposition="reauthorize",
        basis_refs=("evidence:assessment",),
    )
    pending = runtime.qualification.pending_reviews(
        principal="service:conformance"
    )
    if len(pending) != 1 or pending[0].status != "assessed":
        raise AssertionError("action-requiring review disappeared before owning resolution")
    runtime.qualification.resolve_review(
        review.id,
        resolution_ref="mandate:replacement",
        basis_refs=("evidence:resolution",),
    )
    if runtime.qualification.pending_reviews(principal="service:conformance"):
        raise AssertionError("resolved qualification review remained pending")

def _state_export_root_only() -> None:
    from fastapi.testclient import TestClient
    from .service import create_app

    runtime = WorldRuntime.sqlite(root_principal="principal:owner")
    owner_token = _conformance_token("state-root-owner")
    other_token = _conformance_token("state-root-other")
    delegate_token = _conformance_token("state-root-delegate")
    runtime.identity.bind_bearer_token(
        principal="principal:owner",
        token=owner_token,
        credential_id="credential:state-owner",
    )
    runtime.identity.bind_bearer_token(
        principal="principal:other",
        token=other_token,
        credential_id="credential:state-other",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:delegate",
        token=delegate_token,
        credential_id="credential:state-delegate",
    )
    owner = runtime.identity.authenticate_bearer(f"Bearer {owner_token}")
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:state-export",
            grantor="principal:owner",
            grantee="controller:delegate",
            scope={"resource": "*"},
            authority_ceiling={"action": "*", "resource": "*"},
        ),
        context=owner,
    )
    delegated = TestClient(
        create_app(runtime),
        headers={
            "Authorization": f"Bearer {delegate_token}",
            "X-World-Runtime-Delegation": "delegation:state-export",
        },
    )
    if delegated.get("/v1/state/export").status_code != 403:
        raise AssertionError("delegated controller exported whole-agency state")
    other = TestClient(
        create_app(runtime),
        headers={"Authorization": f"Bearer {other_token}"},
    )
    if other.get("/v1/state/export").status_code != 403:
        raise AssertionError("non-root direct principal exported whole-agency state")
    direct = TestClient(
        create_app(runtime),
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    exported = direct.get("/v1/state/export")
    if exported.status_code != 200:
        raise AssertionError("direct configured root principal could not export state")
    if other.post("/v1/state/import", json=exported.json()).status_code != 403:
        raise AssertionError("non-root direct principal imported whole-agency state")

    disabled = WorldRuntime.sqlite()
    disabled_token = _conformance_token("state-root-disabled")
    disabled.identity.bind_bearer_token(
        principal="principal:owner",
        token=disabled_token,
        credential_id="credential:state-disabled",
    )
    disabled_client = TestClient(
        create_app(disabled),
        headers={"Authorization": f"Bearer {disabled_token}"},
    )
    if disabled_client.get("/v1/state/export").status_code != 403:
        raise AssertionError("unconfigured Runtime allowed whole-agency state export")

def _sensitive_read_requires_authentication() -> None:
    from fastapi.testclient import TestClient
    from .service import create_app

    runtime = WorldRuntime.sqlite()
    runtime.responsibility.create(
        Responsibility(
            id="responsibility:sensitive-read",
            principal="principal:owner",
            subject="private durable state",
            domain="conformance",
        )
    )
    client = TestClient(create_app(runtime))
    response = client.get("/v1/responsibilities/responsibility:sensitive-read")
    if response.status_code != 401:
        raise AssertionError("durable Responsibility read succeeded without authentication")

def _public_command_unknown_field() -> None:
    from fastapi.testclient import TestClient
    from .service import create_app

    runtime = WorldRuntime.sqlite()
    token = _conformance_token("closed-command")
    runtime.identity.bind_bearer_token(
        principal="principal:owner",
        token=token,
        credential_id="credential:closed-command",
    )
    client = TestClient(
        create_app(runtime),
        headers={"Authorization": f"Bearer {token}"},
    )
    response = client.post(
        "/v1/responsibilities",
        json={
            "id": "responsibility:closed-command",
            "principal": "principal:owner",
            "subject": "closed schema",
            "domain": "conformance",
            "undeclared": "must-fail",
        },
    )
    if response.status_code != 422:
        raise AssertionError("public Runtime command silently ignored unknown field")
    if runtime.ledger.project_get(
        "responsibility.current",
        "responsibility:closed-command",
    ) is not None:
        raise AssertionError("invalid public command mutated semantic state")

def _delegated_transition_authority() -> None:
    from fastapi.testclient import TestClient
    from .service import create_app

    runtime = WorldRuntime.sqlite()
    owner_token = _conformance_token("transition-owner")
    delegate_token = _conformance_token("transition-delegate")
    runtime.identity.bind_bearer_token(
        principal="principal:owner",
        token=owner_token,
        credential_id="credential:transition-owner",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:delegate",
        token=delegate_token,
        credential_id="credential:transition-delegate",
    )
    owner = runtime.identity.authenticate_bearer(f"Bearer {owner_token}")
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:no-operation",
            grantor="principal:owner",
            grantee="controller:delegate",
            scope={"resource": "*"},
            authority_ceiling={"action": "*", "resource": "*"},
        ),
        context=owner,
    )
    rejected = TestClient(
        create_app(runtime),
        headers={
            "Authorization": f"Bearer {delegate_token}",
            "X-World-Runtime-Delegation": "delegation:no-operation",
        },
    )
    response = rejected.post(
        "/v1/responsibilities",
        json={
            "id": "responsibility:transition-rejected",
            "principal": "principal:owner",
            "subject": "transition authority",
            "domain": "conformance",
        },
    )
    if response.status_code != 403:
        raise AssertionError("delegated transition succeeded without operation authority")

    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:create-responsibility",
            grantor="principal:owner",
            grantee="controller:delegate",
            scope={"resource": "*"},
            authority_ceiling={
                "operation": "create-responsibility",
                "action": "*",
                "resource": "*",
            },
        ),
        context=owner,
    )
    allowed = TestClient(
        create_app(runtime),
        headers={
            "Authorization": f"Bearer {delegate_token}",
            "X-World-Runtime-Delegation": "delegation:create-responsibility",
        },
    )
    response = allowed.post(
        "/v1/responsibilities",
        json={
            "id": "responsibility:transition-allowed",
            "principal": "principal:owner",
            "subject": "transition authority",
            "domain": "conformance",
        },
    )
    if response.status_code != 200:
        raise AssertionError("explicit delegated operation authority was not accepted")

async def _delegated_effect_ceiling() -> None:
    from fastapi.testclient import TestClient
    from .service import create_app

    runtime = WorldRuntime.sqlite()
    provider = _RecoverableProvider()
    runtime.registry.register(provider)
    owner_token = _conformance_token("effect-owner")
    delegate_token = _conformance_token("effect-delegate")
    runtime.identity.bind_bearer_token(
        principal="principal:owner",
        token=owner_token,
        credential_id="credential:effect-owner",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:delegate",
        token=delegate_token,
        credential_id="credential:effect-delegate",
    )
    owner_context = runtime.identity.authenticate_bearer(f"Bearer {owner_token}")
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:effect-bounded",
            grantor="principal:owner",
            grantee="controller:delegate",
            scope={"resource": "*"},
            authority_ceiling={
                "operation": "invoke-capability",
                "action": "allowed.effect",
                "resource": "resource:1",
            },
        ),
        context=owner_context,
    )
    runtime.responsibility.create(
        Responsibility(
            id="responsibility:effect-bounded",
            principal="principal:owner",
            subject="effect bounded",
            domain="conformance",
        )
    )
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:effect-bounded",
        kind="effect",
        payload={},
    )
    decision = Decision(
        id="decision:effect-bounded",
        subject="resource:1",
        decided_by="principal:owner",
        selected={
            "target_ref": "resource:1",
            "operation": "authorize-effect",
            "action": "conformance.effect",
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:effect-bounded"),),
    )
    runtime.decisions.record_attested(decision, context=owner_context)
    runtime.governance.register_mandate_attested(
        Mandate(
            id="mandate:effect-bounded",
            principal="principal:owner",
            scope={"resource": "resource:1"},
            authority_ceiling={"action": "conformance.effect", "resource": "resource:1"},
        ),
        context=owner_context,
    )
    auth = runtime.governance.issue_authorization_attested(
        context=owner_context,
        principal="principal:owner",
        action="conformance.effect",
        resource="resource:1",
        mandate_id="mandate:effect-bounded",
        decision_id=decision.id,
    )
    client = TestClient(
        create_app(runtime),
        headers={
            "Authorization": f"Bearer {delegate_token}",
            "X-World-Runtime-Delegation": "delegation:effect-bounded",
        },
    )
    response = client.post(
        "/v1/invoke",
        json={
            "id": "request:effect-bounded",
            "capability": "conformance.effect",
            "work_id": work.id,
            "effect_class": "external-effect",
            "principal": "principal:owner",
            "resource": "resource:1",
            "authorization_id": auth.id,
            "idempotency_key": "effect:delegated-ceiling",
        },
    )
    if response.status_code != 403:
        raise AssertionError("delegated actor escaped action/resource effect ceiling")
    if provider.invoke_calls != 0:
        raise AssertionError("disallowed delegated effect reached provider")

def _terminal_work_rejects_run() -> None:
    runtime = WorldRuntime.sqlite()
    _responsibility(runtime, "responsibility:terminal-work")
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:terminal-work",
        kind="test",
        payload={},
    )
    runtime.execution.mark_work_complete(
        work.id,
        evidence_refs=("evidence:terminal-work",),
    )
    try:
        runtime.start_run(work.id, workflow_id="should-not-start")
    except PermissionError:
        return
    raise AssertionError("terminal Work admitted a fresh Run")

async def _terminal_run_replay_only() -> None:
    runtime = WorldRuntime.sqlite()
    provider = _RecoverableProvider()
    runtime.registry.register(provider)
    _responsibility(runtime, "responsibility:terminal-run")
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:terminal-run",
        kind="effect",
        payload={},
    )
    run = runtime.start_run(work.id, workflow_id="terminal")
    _decision(
        runtime,
        identifier="decision:terminal-run",
        target_ref="resource:1",
        operation="authorize-effect",
        selected={"action": "conformance.effect"},
    )
    runtime.governance.register_mandate(
        Mandate(
            id="mandate:terminal-run",
            principal="service:conformance",
            authority_ceiling={"action": "conformance.effect", "resource": "resource:1"},
        )
    )
    auth = runtime.governance.issue_authorization(
        authorization_id="authorization:terminal-run",
        principal="service:conformance",
        action="conformance.effect",
        resource="resource:1",
        mandate_id="mandate:terminal-run",
        decision_id="decision:terminal-run",
    )
    request = CapabilityRequest(
        id="request:terminal-run",
        capability="conformance.effect",
        work_id=work.id,
        run_id=run.id,
        principal="service:conformance",
        resource="resource:1",
        effect_class="external-effect",
        authorization_id=auth.id,
        idempotency_key="effect:terminal-run",
    )
    first = await runtime.invoke(request)
    runtime.execution.update_run_status(run.id, "completed")
    replay = await runtime.invoke(request)
    if first.model_dump(mode="json") != replay.model_dump(mode="json"):
        raise AssertionError("committed replay changed after Run became terminal")
    if provider.invoke_calls != 1:
        raise AssertionError("committed terminal-Run replay redispatched provider")
    fresh = request.model_copy(
        update={
            "id": "request:terminal-run:fresh",
            "idempotency_key": "effect:terminal-run:fresh",
        }
    )
    try:
        await runtime.invoke(fresh)
    except PermissionError:
        if provider.invoke_calls != 1:
            raise AssertionError("rejected terminal-Run effect reached provider")
        return
    raise AssertionError("terminal Run qualified a fresh effect")

async def _provider_result_read_isolation() -> None:
    from fastapi.testclient import TestClient
    from .service import create_app

    runtime = WorldRuntime.sqlite(root_principal="principal:owner")
    provider = _RecoverableProvider()
    runtime.registry.register(provider)
    owner_token = _conformance_token("result-owner")
    actor_token = _conformance_token("result-actor")
    sibling_token = _conformance_token("result-sibling")
    other_token = _conformance_token("result-other")
    for principal, token, credential in (
        ("principal:owner", owner_token, "credential:result-owner"),
        ("controller:actor", actor_token, "credential:result-actor"),
        ("controller:sibling", sibling_token, "credential:result-sibling"),
        ("principal:other", other_token, "credential:result-other"),
    ):
        runtime.identity.bind_bearer_token(
            principal=principal,
            token=token,
            credential_id=credential,
        )
    owner = runtime.identity.authenticate_bearer(f"Bearer {owner_token}")
    for identifier, grantee in (
        ("delegation:result-actor", "controller:actor"),
        ("delegation:result-sibling", "controller:sibling"),
    ):
        runtime.identity.grant_delegation(
            DelegationGrant(
                id=identifier,
                grantor="principal:owner",
                grantee=grantee,
                scope={"resource": "*"},
                authority_ceiling={
                    "operation": "*",
                    "action": "*",
                    "resource": "*",
                },
            ),
            context=owner,
        )

    runtime.responsibility.create(
        Responsibility(
            id="responsibility:result-read",
            principal="principal:owner",
            subject="result read",
            domain="conformance",
        )
    )
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:result-read",
        kind="read",
        payload={},
    )
    actor = TestClient(
        create_app(runtime),
        headers={
            "Authorization": f"Bearer {actor_token}",
            "X-World-Runtime-Delegation": "delegation:result-actor",
        },
    )
    response = actor.post(
        "/v1/invoke",
        json={
            "id": "request:result-read",
            "capability": "conformance.effect",
            "work_id": work.id,
            "effect_class": "read-only",
            "principal": "principal:owner",
        },
    )
    if response.status_code != 200:
        raise AssertionError("owning delegated actor could not create readable result")
    if actor.get("/v1/results/request:result-read").status_code != 200:
        raise AssertionError("owning delegated actor could not read provider result")
    sibling = TestClient(
        create_app(runtime),
        headers={
            "Authorization": f"Bearer {sibling_token}",
            "X-World-Runtime-Delegation": "delegation:result-sibling",
        },
    )
    if sibling.get("/v1/results/request:result-read").status_code != 403:
        raise AssertionError("sibling delegated actor read another actor's provider result")
    other = TestClient(
        create_app(runtime),
        headers={"Authorization": f"Bearer {other_token}"},
    )
    if other.get("/v1/results/request:result-read").status_code != 403:
        raise AssertionError("unrelated principal read provider result")
    direct = TestClient(
        create_app(runtime),
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    if direct.get("/v1/results/request:result-read").status_code != 200:
        raise AssertionError("direct owning principal could not read provider result")


__all__ = [
    "ConformanceResult",
    "SUITE_VERSION",
    "conformance_vectors",
    "run_reference_conformance",
]

CHECKS = {
    "shared-authorization-distinct-runtime-effects-survive-contention": _shared_authority_runtime_effects,
    "shared-authorization-distinct-domain-starts-survive-contention": _shared_authority_domain_starts,
    "responsibility-required-dependency-blocks-parent-satisfaction": _responsibility_dependency_gate,
    "responsibility-hard-dependency-cycle-rejected": _responsibility_cycle_gate,
    "strategic-portfolio-activation-requires-decision": _strategic_portfolio_decision_gate,
    "strategic-resource-budget-unit-is-bound": _strategic_resource_budget_gate,
    "qualification-change-creates-review-not-invalidation": _qualification_review_not_invalidation,
    "qualification-action-assessment-remains-pending": _qualification_action_remains_pending,
    "state-export-requires-direct-root-principal": _state_export_root_only,
    "sensitive-runtime-read-requires-authentication": _sensitive_read_requires_authentication,
    "public-command-unknown-field-rejected": _public_command_unknown_field,
    "delegated-transition-requires-operation-authority": _delegated_transition_authority,
    "delegated-effect-use-respects-action-resource-ceiling": _delegated_effect_ceiling,
    "terminal-work-rejects-fresh-run": _terminal_work_rejects_run,
    "terminal-run-rejects-fresh-invocation-but-replay-survives": _terminal_run_replay_only,
    "provider-result-read-is-principal-actor-bound": _provider_result_read_isolation,
}
