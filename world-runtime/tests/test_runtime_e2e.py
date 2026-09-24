from pathlib import Path

import world_runtime
import world_runtime.execution as execution_module
import pytest
from semantic_language import Decision, Goal, Mandate, Responsibility, SemanticKind, SemanticRef

from world_runtime import CapabilityRequest, CapabilityResult, WorldRuntime
from world_runtime.execution import InvocationContext, ProviderDescriptor, ProviderHealth


class DeploymentProvider:
    def __init__(self) -> None:
        self._descriptor = ProviderDescriptor(
            id="deployment-provider",
            name="Deployment Provider",
            version="1",
            capabilities=["deploy-change"],
        )
        self.calls = 0

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self, request: CapabilityRequest, context: InvocationContext
    ) -> CapabilityResult:
        del context
        self.calls += 1
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            provider_success=True,
            data={"deployment_id": "d-1"},
            external_ref="deployment:d-1",
        )

    async def cancel(self, request_id: str) -> None:
        del request_id


@pytest.mark.asyncio
async def test_authorized_provider_success_is_not_outcome_or_discharge(tmp_path: Path):
    db = tmp_path / "world.db"
    rt = WorldRuntime.sqlite(db)
    mandate = Mandate(
        id="mandate:1",
        principal="owner",
        scope={"company": "acme"},
        authority_ceiling={"action": "deploy-change", "resource": "checkout"},
    )
    rt.governance.register_mandate(mandate)
    basis = SemanticRef(SemanticKind.EVIDENCE, "evidence:strategy")
    decision = Decision(
        id="decision:1",
        subject="checkout",
        decided_by="owner",
        selected={"target_ref": "goal:1", "operation": "admit-goal"},
        basis_refs=(basis,),
    )
    rt.decisions.record(decision)
    goal = Goal(
        id="goal:1",
        subject="checkout",
        desired_state={"latency_reduction": 0.3},
        basis_refs=(basis,),
    )
    rt.strategy.register_goal(goal, mandate_id=mandate.id, decision_id=decision.id)
    responsibility = Responsibility(
        id="responsibility:1",
        principal="development-controller",
        subject="checkout",
        goal_refs=(goal.ref,),
    )
    rt.responsibility.create(responsibility, domain="development")
    work = rt.execution.admit_work(
        responsibility_id=responsibility.id,
        kind="domain-assignment",
        payload={"goal_id": goal.id},
    )
    auth_decision = Decision(
        id="decision:authorize-deploy",
        subject="checkout",
        decided_by="owner",
        selected={
            "target_ref": "checkout",
            "operation": "authorize-effect",
            "action": "deploy-change",
        },
        basis_refs=(basis,),
    )
    rt.decisions.record(auth_decision)
    auth = rt.governance.issue_authorization(
        principal="development-controller",
        action="deploy-change",
        resource="checkout",
        mandate_id=mandate.id,
        decision_id=auth_decision.id,
    )
    provider = DeploymentProvider()
    rt.registry.register(provider)

    result = await rt.invoke(
        CapabilityRequest(
            capability="deploy-change",
            work_id=work.id,
            principal="development-controller",
            resource="checkout",
            effect_class="write",
            authorization_id=auth.id,
            idempotency_key="deploy:1",
        )
    )
    assert result.provider_success is True
    assert provider.calls == 1
    assert rt.ledger.project_get("strategy.outcome", work.id) is None
    assert rt.responsibility.get(responsibility.id).status == "active"
    attempt = rt.ledger.project_get("execution.provider-attempt", "deploy:1")
    assert attempt is not None
    assert attempt[0]["status"] == "committed"

    rt.close()
    reopened = WorldRuntime.sqlite(db)
    assert reopened.responsibility.get(responsibility.id).status == "active"

    with pytest.raises(PermissionError):
        await reopened.invoke(
            CapabilityRequest(
                capability="missing",
                work_id=work.id,
                principal="development-controller",
                resource="checkout",
                effect_class="write",
                idempotency_key="missing:1",
            )
        )


def test_execution_service_has_no_reality_boundary_api() -> None:
    runtime = WorldRuntime.sqlite()
    assert not hasattr(runtime.execution, "invoke")
    assert not hasattr(runtime.execution, "boundary")
    assert not hasattr(runtime, "boundary")
    assert "ExecutionService" not in world_runtime.__all__
    assert "InProcessRealityBoundary" not in world_runtime.__all__
    assert not hasattr(world_runtime, "ExecutionService")
    assert not hasattr(world_runtime, "InProcessRealityBoundary")
    assert not hasattr(execution_module, "RealityBoundary")
    assert not hasattr(execution_module, "InProcessRealityBoundary")
