from __future__ import annotations

import pytest
from semantic_language import SemanticKind, SemanticRef

from world_runtime import WorldRuntime
from world_runtime.decisions import Decision
from world_runtime.execution import (
    CapabilityEffectRule,
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)
from world_runtime.identity import DelegationGrant
from world_runtime.responsibility import Responsibility


def test_terminal_responsibility_assessment_requires_basis() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="conformance:responsibility-basis")
    responsibility = Responsibility(
        id="responsibility:conformance-basis",
        principal="principal:owner",
        subject="terminal assessment",
        domain="conformance",
    )
    runtime.responsibility.create(responsibility)

    with pytest.raises(ValueError, match="terminal responsibility assessment requires basis"):
        runtime.responsibility.assess(
            responsibility.id,
            status="satisfied",
            basis_refs=(),
        )

    current = runtime.responsibility.get(responsibility.id)
    assert current is not None and current.status == "active"
    runtime.close()


@pytest.mark.asyncio
async def test_discharged_responsibility_rejects_fresh_effect() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="conformance:discharged-effect")
    provider = _CountingProvider("demo.effect")
    runtime.registry.register(provider)
    runtime.contract_registry.register_effect_rule(
        CapabilityEffectRule(
            capability="demo.effect",
            impact_class="write-local",
            authorization_required=False,
            resource_required=True,
            version_required=False,
        )
    )
    responsibility = Responsibility(
        id="responsibility:discharged-effect",
        principal="principal:owner",
        subject="terminal responsibility",
        domain="conformance",
    )
    runtime.responsibility.create(responsibility)
    work = runtime.execution.admit_work(
        responsibility_id=responsibility.id,
        kind="effect",
        payload={"resource": "repo:one"},
        work_id="work:discharged-effect",
    )
    decision = Decision(
        id="decision:discharged-effect",
        subject=responsibility.id,
        decided_by="principal:owner",
        selected={
            "target_ref": responsibility.id,
            "operation": "discharge-responsibility",
            "to_status": "discharged",
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:discharge"),),
    )
    runtime.decisions.record(decision)
    runtime.responsibility.assess(
        responsibility.id,
        status="satisfied",
        basis_refs=("evidence:assessment",),
    )
    runtime.responsibility.discharge(responsibility.id, decision_id=decision.id)

    with pytest.raises(PermissionError, match="execution requires active responsibility"):
        await runtime.invoke(
            CapabilityRequest(
                id="request:discharged-effect",
                capability="demo.effect",
                work_id=work.id,
                resource_ref="repo:one",
                effect_class="write-local",
                idempotency_key="effect:discharged-effect",
            )
        )

    assert provider.calls == 0
    runtime.close()


def test_work_identity_replays_only_identical_semantics() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="conformance:work-identity")
    responsibility = Responsibility(
        id="responsibility:work-identity",
        principal="principal:owner",
        subject="stable work identity",
        domain="conformance",
    )
    runtime.responsibility.create(responsibility)
    first = runtime.execution.admit_work(
        responsibility_id=responsibility.id,
        kind="effect",
        payload={"resource": "repo:one"},
        work_id="work:stable-conformance",
    )
    replay = runtime.execution.admit_work(
        responsibility_id=responsibility.id,
        kind="effect",
        payload={"resource": "repo:one"},
        work_id="work:stable-conformance",
    )

    assert replay.id == first.id
    with pytest.raises(ValueError, match="work identity rebound"):
        runtime.execution.admit_work(
            responsibility_id=responsibility.id,
            kind="effect",
            payload={"resource": "repo:two"},
            work_id="work:stable-conformance",
        )
    persisted = runtime.get_work(first.id)
    assert persisted is not None
    assert (persisted.id, persisted.responsibility_id, persisted.kind, persisted.payload) == (
        first.id,
        first.responsibility_id,
        first.kind,
        first.payload,
    )
    runtime.close()


@pytest.mark.asyncio
async def test_invocation_run_must_belong_to_the_referenced_work() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="conformance:run-work-binding")
    provider = _CountingProvider("demo.read")
    runtime.registry.register(provider)
    first_work = _admit_work(runtime, "responsibility:first", "work:first")
    other_work = _admit_work(runtime, "responsibility:other", "work:other")
    run = runtime.start_run(first_work.id, workflow_id="first")

    request = CapabilityRequest(
        id="request:foreign-work",
        capability="demo.read",
        work_id=other_work.id,
        run_id=run.id,
    )
    with pytest.raises(PermissionError, match="run does not belong to invocation work"):
        await runtime.invoke(request)

    assert provider.calls == 0
    runtime.close()


def test_revoked_delegation_cannot_authenticate_again() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="conformance:revoked-delegation")
    runtime.identity.bind_bearer_token(
        principal="principal:root",
        token="root-token",
        credential_id="credential:root",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:delegate",
        token="delegate-token",
        credential_id="credential:delegate",
    )
    root = runtime.identity.authenticate_bearer("Bearer root-token")
    grant = DelegationGrant(
        id="delegation:revoked",
        grantor="principal:root",
        grantee="controller:delegate",
        scope={"resource": "repo:one"},
        authority_ceiling={"operation": "admit-work"},
    )
    runtime.identity.grant_delegation(grant, context=root)
    delegated = runtime.identity.authenticate_bearer(
        "Bearer delegate-token",
        delegation_id=grant.id,
    )
    assert delegated.effective_principal == "principal:root"

    runtime.identity.revoke_delegation(grant.id, context=root, reason="test revocation")
    with pytest.raises(PermissionError, match="delegation is not active"):
        runtime.identity.authenticate_bearer(
            "Bearer delegate-token",
            delegation_id=grant.id,
        )
    runtime.close()


def test_delegated_transition_requires_operation_authority() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="conformance:transition-authority")
    context = _delegated_context(
        runtime,
        delegation_id="delegation:transition",
        authority_ceiling={"operation": "admit-work", "resource": "work:one"},
    )

    runtime.identity.assert_transition_authority(
        context,
        operation="admit-work",
        resource="work:one",
    )
    with pytest.raises(PermissionError, match="transition exceeds delegated authority"):
        runtime.identity.assert_transition_authority(
            context,
            operation="create-responsibility",
            resource="work:one",
        )
    runtime.close()


def test_delegated_effect_use_respects_action_and_resource_ceiling() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="conformance:effect-ceiling")
    context = _delegated_context(
        runtime,
        delegation_id="delegation:effect",
        authority_ceiling={"action": "demo.effect", "resource": "repo:allowed"},
    )

    runtime.identity.assert_delegated_authority(
        context,
        scope={},
        authority_ceiling={"action": "demo.effect", "resource": "repo:allowed"},
    )
    with pytest.raises(PermissionError, match="requested authority ceiling exceeds delegation"):
        runtime.identity.assert_delegated_authority(
            context,
            scope={},
            authority_ceiling={"action": "demo.effect", "resource": "repo:outside"},
        )
    runtime.close()


def test_terminal_work_rejects_a_fresh_run() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="conformance:terminal-work")
    work = _admit_work(runtime, "responsibility:terminal-work", "work:terminal")
    runtime.execution.mark_work_complete(work.id, evidence_refs=("evidence:completion",))

    with pytest.raises(PermissionError, match="terminal Work cannot start a fresh Run"):
        runtime.start_run(work.id, workflow_id="after-completion")
    runtime.close()


@pytest.mark.asyncio
async def test_terminal_run_replays_committed_effect_but_rejects_fresh_effect() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="conformance:terminal-run")
    provider = _CountingProvider("demo.effect")
    runtime.registry.register(provider)
    runtime.contract_registry.register_effect_rule(
        CapabilityEffectRule(
            capability="demo.effect",
            impact_class="write-local",
            authorization_required=False,
            resource_required=True,
            version_required=False,
        )
    )
    work = _admit_work(runtime, "responsibility:terminal-run", "work:terminal-run")
    run = runtime.start_run(work.id, workflow_id="terminal-run")
    lease = runtime.execution.acquire_run_lease(run.id, owner="worker:one", ttl_seconds=60)
    request = CapabilityRequest(
        id="request:terminal-run",
        capability="demo.effect",
        work_id=work.id,
        run_id=run.id,
        resource_ref="repo:one",
        effect_class="write-local",
        idempotency_key="effect:terminal-run",
        lease_owner="worker:one",
        lease_generation=lease.lease_generation,
    )
    first = await runtime.invoke(request)
    assert first.status == "succeeded"
    assert provider.calls == 1

    runtime.execution.update_run_status(run.id, "completed")
    replay = await runtime.invoke(request)
    assert replay == first
    assert provider.calls == 1

    fresh = request.model_copy(
        update={"id": "request:terminal-run-fresh", "idempotency_key": "effect:terminal-run-fresh"}
    )
    with pytest.raises(PermissionError, match="fresh invocation requires running Run"):
        await runtime.invoke(fresh)
    assert provider.calls == 1
    runtime.close()


def _admit_work(runtime: WorldRuntime, responsibility_id: str, work_id: str):
    runtime.responsibility.create(
        Responsibility(
            id=responsibility_id,
            principal="principal:owner",
            subject=work_id,
            domain="conformance",
        )
    )
    return runtime.execution.admit_work(
        responsibility_id=responsibility_id,
        kind="effect",
        payload={"work_id": work_id},
        work_id=work_id,
    )


def _delegated_context(
    runtime: WorldRuntime,
    *,
    delegation_id: str,
    authority_ceiling: dict[str, str],
):
    runtime.identity.bind_bearer_token(
        principal="principal:root",
        token=f"root-token:{delegation_id}",
        credential_id=f"credential:root:{delegation_id}",
    )
    runtime.identity.bind_bearer_token(
        principal=f"controller:{delegation_id}",
        token=f"delegate-token:{delegation_id}",
        credential_id=f"credential:delegate:{delegation_id}",
    )
    root = runtime.identity.authenticate_bearer(f"Bearer root-token:{delegation_id}")
    grant = DelegationGrant(
        id=delegation_id,
        grantor="principal:root",
        grantee=f"controller:{delegation_id}",
        scope={},
        authority_ceiling=authority_ceiling,
    )
    runtime.identity.grant_delegation(grant, context=root)
    return runtime.identity.authenticate_bearer(
        f"Bearer delegate-token:{delegation_id}",
        delegation_id=delegation_id,
    )


class _CountingProvider:
    def __init__(self, capability: str) -> None:
        self.calls = 0
        self._descriptor = ProviderDescriptor(
            id="conformance-provider",
            name="Conformance Provider",
            version="1",
            capabilities=[capability],
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
        self.calls += 1
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            data={"calls": self.calls},
        )

    async def cancel(self, request_id: str) -> None:
        del request_id
