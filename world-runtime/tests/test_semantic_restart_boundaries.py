from pathlib import Path

from semantic_language import (
    Claim,
    Decision,
    Evidence,
    Goal,
    Mandate,
    Responsibility,
    SemanticKind,
    SemanticRef,
)

from world_runtime import (
    BeliefVerdict,
    CapabilityRequest,
    CapabilityResult,
    DomainAssignment,
    EvaluatorKind,
    WorldRuntime,
)
from world_runtime.execution import (
    CapabilityRequest as ExecutionCapabilityRequest,
    ProviderDescriptor,
    ProviderHealth,
    effect_identity_fingerprint,
    effect_identity_payload,
    reconciliation_contract_for,
)


def test_restart_after_epistemic_establishment(tmp_path: Path) -> None:
    db = tmp_path / "after-evidence.db"
    runtime = WorldRuntime.sqlite(db)
    claim = Claim(id="claim:restart", subject="x", proposition="x")
    evidence = Evidence(
        id="evidence:restart",
        subject="x",
        source="telemetry",
        content={"x": True},
        metadata={"provenance_class": "primary"},
    )
    runtime.epistemics.record_claim(claim)
    runtime.epistemics.record_evidence(evidence)
    runtime.epistemics.assess(
        claim=claim,
        evidence=evidence,
        verdict=BeliefVerdict.SUPPORTED,
        rationale="verified",
        assessed_by="domain:verifier",
        evaluator_kind=EvaluatorKind.DOMAIN_VERIFIER,
    )
    runtime.close()

    reopened = WorldRuntime.sqlite(db)
    assert reopened.epistemics.current_belief(claim.id)[0] is BeliefVerdict.SUPPORTED
    reopened.close()


def test_restart_after_decision_and_goal_admission(tmp_path: Path) -> None:
    db = tmp_path / "after-goal.db"
    runtime = WorldRuntime.sqlite(db)
    mandate = Mandate(id="mandate:restart", principal="owner")
    runtime.governance.register_mandate(mandate)
    decision = Decision(
        id="decision:restart",
        subject="x",
        decided_by="owner",
        selected={"target_ref": "goal:restart", "operation": "admit-goal"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:basis"),),
    )
    runtime.decisions.record(decision)
    goal = Goal(
        id="goal:restart",
        subject="x",
        desired_state={"done": True},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:basis"),),
    )
    runtime.strategy.register_goal(
        goal,
        mandate_id=mandate.id,
        decision_id=decision.id,
    )
    runtime.close()

    reopened = WorldRuntime.sqlite(db)
    assert reopened.decisions.get(decision.id)["id"] == decision.id
    assert reopened.strategy.get_goal(goal.id)["status"] == "active"
    reopened.close()


def test_restart_after_domain_assignment_acceptance(tmp_path: Path) -> None:
    db = tmp_path / "after-assignment.db"
    runtime = WorldRuntime.sqlite(db)
    responsibility = Responsibility(
        id="responsibility:restart-assignment",
        principal="controller:test",
        subject="bounded work",
    )
    runtime.responsibility.create(responsibility, domain="test-domain")
    assignment = runtime.domains.offer(
        DomainAssignment(
            id="assignment:restart",
            responsibility_ref=responsibility.id,
            domain="test-domain",
            controller="controller:test-domain",
        )
    )
    runtime.domains.report(
        assignment.id,
        kind="accepted",
        report_id="report:restart:accepted",
    )
    runtime.close()

    reopened = WorldRuntime.sqlite(db)
    assert reopened.domains.get(assignment.id).status == "active"
    assert [item.kind for item in reopened.domains.reports(assignment.id)] == ["accepted"]
    reopened.close()


def test_restart_after_outcome_report_before_strategy_assessment(tmp_path: Path) -> None:
    db = tmp_path / "after-outcome.db"
    runtime = WorldRuntime.sqlite(db)
    mandate = Mandate(id="mandate:outcome-restart", principal="owner")
    runtime.governance.register_mandate(mandate)
    decision = Decision(
        id="decision:outcome-restart",
        subject="x",
        decided_by="owner",
        selected={
            "target_ref": "goal:outcome-restart",
            "operation": "admit-goal",
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:basis"),),
    )
    runtime.decisions.record(decision)
    goal = Goal(
        id="goal:outcome-restart",
        subject="x",
        desired_state={"done": True},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:basis"),),
    )
    runtime.strategy.register_goal(
        goal,
        mandate_id=mandate.id,
        decision_id=decision.id,
    )
    responsibility = Responsibility(
        id="responsibility:outcome-restart",
        principal="controller:test",
        subject="produce outcome",
        goal_refs=(goal.ref,),
    )
    runtime.responsibility.create(responsibility, domain="test-domain")
    assignment = runtime.domains.offer(
        DomainAssignment(
            id="assignment:outcome-restart",
            responsibility_ref=responsibility.id,
            domain="test-domain",
            controller="controller:test-domain",
            goal_refs=(goal.id,),
        )
    )
    runtime.domains.report(
        assignment.id,
        kind="accepted",
        report_id="report:outcome-restart:accepted",
    )
    runtime.domains.report(
        assignment.id,
        kind="outcome-candidate",
        report_id="report:outcome-restart:candidate",
        basis_refs=(
            SemanticRef("candidate", "candidate:1", namespace="test-domain"),
        ),
        evidence_refs=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:verified"),
        ),
        outcome_refs=(
            SemanticRef(
                SemanticKind.OUTCOME,
                "outcome:verified",
                namespace="test-domain",
            ),
        ),
    )
    runtime.close()

    reopened = WorldRuntime.sqlite(db)
    reports = reopened.domains.reports(assignment.id)
    assert [item.kind for item in reports] == ["accepted", "outcome-candidate"]
    assert reopened.strategy.latest_assessment(goal.id) is None
    assert reopened.strategy.get_goal(goal.id)["status"] == "active"
    reopened.close()


def test_restart_before_dispatch_has_no_provider_attempt(tmp_path: Path) -> None:
    db = tmp_path / "before-dispatch.db"
    runtime = WorldRuntime.sqlite(db)
    responsibility = Responsibility(
        id="responsibility:before-dispatch",
        principal="controller:test",
        subject="bounded work",
    )
    runtime.responsibility.create(responsibility, domain="test-domain")
    work = runtime.execution.admit_work(
        responsibility_id=responsibility.id,
        kind="restart-boundary",
        payload={},
    )
    run = runtime.start_run(work.id, workflow_id="restart-boundary")
    request = CapabilityRequest(
        capability="read-only:test",
        work_id=work.id,
        run_id=run.id,
        idempotency_key="restart:before-dispatch",
    )
    runtime.close()

    reopened = WorldRuntime.sqlite(db)
    assert reopened.ledger.project_get(
        "execution.provider-attempt",
        request.idempotency_key,
    ) is None
    assert reopened.ledger.project_get(
        "execution.provider-idempotency",
        request.idempotency_key,
    ) is None
    reopened.close()


def test_restart_after_ambiguous_dispatch_reconciles_without_redispatch(
    tmp_path: Path,
) -> None:
    db = tmp_path / "ambiguous-dispatch.db"
    runtime = WorldRuntime.sqlite(db)
    descriptor = ProviderDescriptor(
        id="provider:reconcile",
        name="reconcile",
        version="1",
        capabilities=["reconcile:test"],
        reconciliation_protocol_identity="test.reconcile",
        reconciliation_protocol_version="1",
        reconciliation_repeatability="repeat-safe",
        reconciliation_contract_version="1",
    )
    contract = reconciliation_contract_for(descriptor)
    assert contract is not None
    request = ExecutionCapabilityRequest(
        id="request:restart:ambiguous",
        capability="reconcile:test",
        idempotency_key="restart:ambiguous",
    )
    fingerprint = effect_identity_fingerprint(request)
    runtime.ledger.project_put(
        "execution.effect-identity",
        "restart:ambiguous",
        {
            "idempotency_key": "restart:ambiguous",
            "fingerprint": fingerprint,
            "semantic_request": effect_identity_payload(request),
        },
    )
    runtime.ledger.project_put(
        "execution.provider-attempt",
        "restart:ambiguous",
        {
            "request_id": "request:restart:ambiguous",
            "provider_id": descriptor.id,
            "provider_version": descriptor.version,
            "capability": "reconcile:test",
            "effect_fingerprint": fingerprint,
            "effect_identity": effect_identity_payload(request),
            "status": "started",
            "reconciliation_contract": contract.model_dump(mode="json"),
        },
    )
    runtime.close()

    reopened = WorldRuntime.sqlite(db)

    class Provider:
        def __init__(self, descriptor: ProviderDescriptor) -> None:
            self.invoke_calls = 0
            self.reconcile_calls = 0
            self._descriptor = descriptor

        @property
        def descriptor(self) -> ProviderDescriptor:
            return self._descriptor

        async def health(self) -> ProviderHealth:
            return ProviderHealth(provider_id=self.descriptor.id, available=True)

        async def invoke(self, request, context):
            del context
            self.invoke_calls += 1
            return CapabilityResult(
                request_id=request.id,
                provider_id=self.descriptor.id,
                status="succeeded",
            )

        async def cancel(self, request_id: str) -> None:
            del request_id

        async def reconcile(self, request_id: str):
            self.reconcile_calls += 1
            return CapabilityResult(
                request_id=request_id,
                provider_id=self.descriptor.id,
                status="succeeded",
                reconciled=True,
            )

    provider = Provider(descriptor)
    reopened.registry.register(provider)

    import asyncio

    result = asyncio.run(
        reopened.invoke(
            CapabilityRequest(
                id="request:restart:ambiguous",
                capability="reconcile:test",
                idempotency_key="restart:ambiguous",
            )
        )
    )
    assert result.status == "succeeded"
    assert provider.reconcile_calls == 1
    assert provider.invoke_calls == 0
    reopened.close()
