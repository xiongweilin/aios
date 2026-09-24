from pathlib import Path

import pytest
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
from world_runtime.execution import InvocationContext, ProviderDescriptor, ProviderHealth


class GoldenDeploymentProvider:
    def __init__(self) -> None:
        self._descriptor = ProviderDescriptor(
            id="golden-deployment-provider",
            name="Golden Deployment Provider",
            version="1",
            capabilities=["deploy-change"],
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self, request: CapabilityRequest, context: InvocationContext
    ) -> CapabilityResult:
        del context
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            provider_success=True,
            data={"deployment_id": "deployment:checkout-1"},
            external_ref="deployment:checkout-1",
        )

    async def cancel(self, request_id: str) -> None:
        del request_id


@pytest.mark.asyncio
async def test_mandate_to_reality_to_belief_and_strategy_survives_restart(
    tmp_path: Path,
) -> None:
    db = tmp_path / "golden-world.db"
    runtime = WorldRuntime.sqlite(db, runtime_id="runtime:golden-loop")

    mandate = Mandate(
        id="mandate:checkout",
        principal="owner",
        scope={"service": "checkout"},
        authority_ceiling={"deploy-change": "checkout"},
    )
    runtime.governance.register_mandate(mandate)

    claim = Claim(
        id="claim:checkout-latency",
        subject="checkout",
        proposition="p95 latency exceeds 500ms",
    )
    runtime.epistemics.record_claim(claim)
    baseline = Evidence(
        id="evidence:baseline-latency",
        subject="checkout",
        source="production-telemetry",
        content={"p95_ms": 840},
    )
    runtime.epistemics.record_evidence(baseline)
    runtime.epistemics.assess(
        claim=claim,
        evidence=baseline,
        verdict=BeliefVerdict.SUPPORTED,
        rationale="production telemetry establishes the initial condition",
        assessed_by="controller:operations",
        evaluator_kind=EvaluatorKind.DOMAIN_VERIFIER,
    )
    assert runtime.epistemics.current_belief(claim.id)[0] is BeliefVerdict.SUPPORTED

    episode = runtime.cognition.open_episode("checkout")
    runtime.cognition.close_episode(
        episode.id,
        temporary=True,
        basis_refs=(baseline.id,),
    )

    basis = SemanticRef(SemanticKind.EVIDENCE, baseline.id)
    decision = Decision(
        id="decision:optimize-checkout",
        subject="checkout",
        decided_by="owner",
        selected={
            "target_ref": "goal:reduce-checkout-latency",
            "operation": "admit-goal",
            "direction": "reduce-latency",
        },
        basis_refs=(basis,),
    )
    runtime.decisions.record(decision)
    goal = Goal(
        id="goal:reduce-checkout-latency",
        subject="checkout",
        desired_state={"p95_ms": {"lte": 500}},
        basis_refs=(basis,),
    )
    runtime.strategy.register_goal(
        goal,
        mandate_id=mandate.id,
        decision_id=decision.id,
    )

    responsibility = Responsibility(
        id="responsibility:checkout",
        principal="controller:development",
        subject="reduce checkout latency",
        goal_refs=(goal.ref,),
    )
    runtime.responsibility.create(responsibility, domain="development")
    assignment = runtime.domains.offer(
        DomainAssignment(
            id="assignment:checkout",
            responsibility_ref=responsibility.id,
            domain="development",
            controller="controller:autonomous-development",
            mandate_refs=(mandate.id,),
            goal_refs=(goal.id,),
            evidence_requirements=({"kind": "production-telemetry"},),
            review_conditions=({"trigger": "availability-regression"},),
        )
    )
    runtime.domains.report(assignment.id, kind="accepted", report_id="report:accepted")

    work = runtime.execution.admit_work(
        responsibility_id=responsibility.id,
        kind="domain-assignment",
        payload={"assignment_ref": assignment.id},
    )
    run = runtime.execution.start_run(work.id, workflow_id="development:checkout")
    deploy_decision = Decision(
        id="decision:deploy-checkout",
        subject="checkout",
        decided_by="owner",
        selected={
            "target_ref": "checkout",
            "operation": "authorize-effect",
            "action": "deploy-change",
        },
        basis_refs=(basis,),
    )
    runtime.decisions.record(deploy_decision)
    authorization = runtime.governance.issue_authorization(
        principal="controller:development",
        action="deploy-change",
        resource="checkout",
        mandate_id=mandate.id,
        decision_id=deploy_decision.id,
    )
    runtime.registry.register(GoldenDeploymentProvider())
    request = CapabilityRequest(
        capability="deploy-change",
        work_id=work.id,
        run_id=run.id,
        principal="controller:development",
        resource="checkout",
        effect_class="write",
        authorization_id=authorization.id,
        idempotency_key="checkout:deploy:1",
    )
    first_result = await runtime.invoke(request)
    assert first_result.provider_success is True

    post = Evidence(
        id="evidence:post-latency",
        subject="checkout",
        source="production-telemetry",
        content={"p95_ms": 430},
    )
    runtime.epistemics.record_evidence(post)
    runtime.epistemics.assess(
        claim=claim,
        evidence=post,
        verdict=BeliefVerdict.UNSUPPORTED,
        rationale="post-change telemetry contradicts the high-latency claim",
        assessed_by="controller:development",
        evaluator_kind=EvaluatorKind.DOMAIN_VERIFIER,
    )
    assert runtime.epistemics.current_belief(claim.id)[0] is BeliefVerdict.DISPUTED
    runtime.cognition.reopen(
        episode.id,
        reason="new production evidence invalidates the closed problem state",
        basis_refs=(post.id,),
    )

    outcome_ref = "development.outcome:checkout-latency-improved"
    outcome_report = runtime.domains.report(
        assignment.id,
        kind="outcome-candidate",
        basis_refs=(
            SemanticRef("deployment", "deployment:checkout-1", namespace="development"),
        ),
        evidence_refs=(SemanticRef(SemanticKind.EVIDENCE, post.id),),
        outcome_refs=(
            SemanticRef(
                SemanticKind.OUTCOME,
                "checkout-latency-improved",
                namespace="development",
            ),
        ),
        detail={"p95_ms": 430},
        report_id="report:outcome",
    )
    completion = runtime.domains.report(
        assignment.id,
        kind="completion-proposal",
        basis_refs=(
            SemanticRef("release", "release:checkout-1", namespace="development"),
        ),
        evidence_refs=(SemanticRef(SemanticKind.EVIDENCE, post.id),),
        outcome_refs=(
            SemanticRef(
                SemanticKind.OUTCOME,
                "checkout-latency-improved",
                namespace="development",
            ),
        ),
        report_id="report:completion",
    )
    strategy_assessment = runtime.strategy.assess_goal(
        goal.id,
        disposition="stop",
        basis_refs=(post.id, outcome_report.id),
        evidence_refs=(post.id,),
        outcome_refs=(outcome_ref,),
        rationale="verified production telemetry satisfies the target state",
    )
    assert runtime.strategy.get_goal(goal.id)["status"] == "active"
    goal_stop_decision = Decision(
        id="decision:stop-checkout-goal",
        subject="checkout",
        decided_by="owner",
        selected={
            "target_ref": goal.id,
            "operation": "transition-goal",
            "to_status": "stopped",
            "assessment_id": strategy_assessment.id,
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, post.id),),
    )
    runtime.decisions.record(goal_stop_decision)
    runtime.strategy.transition_goal(
        goal.id,
        to_status="stopped",
        assessment_id=strategy_assessment.id,
        decision_id=goal_stop_decision.id,
        basis_refs=(post.id, outcome_report.id),
    )

    runtime.responsibility.assess(
        responsibility.id,
        status="satisfied",
        basis_refs=(post.id, completion.id),
    )
    discharge_decision = Decision(
        id="decision:discharge-checkout",
        subject="checkout",
        decided_by="owner",
        selected={
            "target_ref": responsibility.id,
            "operation": "discharge-responsibility",
            "to_status": "discharged",
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, post.id),),
    )
    runtime.decisions.record(discharge_decision)
    runtime.responsibility.discharge(
        responsibility.id,
        decision_id=discharge_decision.id,
    )
    runtime.close()

    reopened = WorldRuntime.sqlite(db, runtime_id="runtime:golden-loop")
    assert reopened.domains.get(assignment.id).status == "completion-proposed"
    assert reopened.responsibility.get(responsibility.id).status == "discharged"
    assert reopened.epistemics.current_belief(claim.id)[0] is BeliefVerdict.DISPUTED
    cognitive_state = reopened.ledger.project_get("cognition.episode", episode.id)
    assert cognitive_state is not None
    assert cognitive_state[0]["status"] == "open"
    assessment = reopened.strategy.latest_assessment(goal.id)
    assert assessment is not None
    assert assessment.disposition == "stop"
    assert assessment.outcome_refs == (outcome_ref,)
    assert reopened.strategy.get_goal(goal.id)["status"] == "stopped"

    replay = await reopened.invoke(request)
    assert replay.provider_success is True
    observed = [
        event
        for event in reopened.ledger.events(stream=f"provider-request:{request.id}")
        if event.kind == "execution.provider-result.observed"
    ]
    assert len(observed) == 1
    reopened.close()
