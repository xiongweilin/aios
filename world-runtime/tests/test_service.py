import pytest
from fastapi.testclient import TestClient

from world_runtime import WorldRuntime
from world_runtime.execution import (
    CapabilityEffectRule,
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)
from world_runtime.service import create_app



def _client(
    runtime: WorldRuntime,
    *,
    principal: str = "owner",
    token: str | None = None,
) -> TestClient:
    value = token or f"test-token:{principal}"
    runtime.identity.bind_bearer_token(
        principal=principal,
        token=value,
        credential_id=f"credential:{principal}",
    )
    return TestClient(
        create_app(runtime),
        headers={"Authorization": f"Bearer {value}"},
    )


def _attested_authority(
    runtime: WorldRuntime,
    *,
    principal: str,
    decision_id: str,
    mandate_id: str,
    authorization_id: str,
    resource: str,
    action: str,
    conditions: dict[str, object] | None = None,
):
    from semantic_language import Decision, Mandate, SemanticKind, SemanticRef

    context = runtime.identity.authenticate_bearer(f"Bearer test-token:{principal}")
    runtime.decisions.record_attested(
        Decision(
            id=decision_id,
            subject=resource,
            decided_by=principal,
            selected={
                "target_ref": resource,
                "operation": "authorize-effect",
                "action": action,
            },
            basis_refs=(SemanticRef(SemanticKind.EVIDENCE, f"evidence:{decision_id}"),),
        ),
        context=context,
    )
    runtime.governance.register_mandate_attested(
        Mandate(
            id=mandate_id,
            principal=principal,
            authority_ceiling={"action": action, "resource": resource},
        ),
        context=context,
    )
    return runtime.governance.issue_authorization_attested(
        context=context,
        authorization_id=authorization_id,
        principal=principal,
        action=action,
        resource=resource,
        mandate_id=mandate_id,
        decision_id=decision_id,
        conditions=conditions,
    )


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0
        self._descriptor = ProviderDescriptor(
            id="counting",
            name="Counting",
            version="test",
            capabilities=["demo.read"],
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
        self, request: CapabilityRequest, context: InvocationContext
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

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        del request_id
        return None


def test_service_exposes_generic_runtime_surface() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="service-test")
    runtime.contract_registry.register_effect_rule(
        CapabilityEffectRule(
            capability="demo.read",
            impact_class="read",
            authorization_required=False,
            resource_required=False,
            version_required=False,
        )
    )
    provider = CountingProvider()
    runtime.registry.register(provider)
    client = _client(runtime)

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["runtime_id"] == "service-test"
    catalog = client.get("/v1/capabilities")
    assert catalog.status_code == 200
    assert catalog.json()["effect_rules"][0]["capability"] == "demo.read"


@pytest.mark.asyncio
async def test_provider_idempotency_prevents_duplicate_reality_calls() -> None:
    runtime = WorldRuntime.sqlite()
    provider = CountingProvider()
    runtime.registry.register(provider)
    request = CapabilityRequest(
        capability="demo.read",
        idempotency_key="stable-call",
    )

    first = await runtime.invoke(request)
    second = await runtime.invoke(
        request.model_copy(update={"id": "request:replayed"})
    )

    assert first.data == {"calls": 1}
    assert second.data == {"calls": 1}
    assert provider.calls == 1


class ReconciledProvider(CountingProvider):
    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        return CapabilityResult(
            request_id=request_id,
            provider_id=self.descriptor.id,
            status="succeeded",
            reconciled=True,
            data={"source": "reconcile"},
        )


@pytest.mark.asyncio
async def test_ambiguous_attempt_reconciles_without_redispatch() -> None:
    runtime = WorldRuntime.sqlite()
    provider = ReconciledProvider()
    runtime.registry.register(provider)
    request = CapabilityRequest(
        id="request:retry",
        capability="demo.read",
        idempotency_key="stable-effect",
    )
    execution_module = __import__(
        "world_runtime.execution",
        fromlist=["effect_identity_fingerprint", "effect_identity_payload"],
    )
    fingerprint = execution_module.effect_identity_fingerprint(request)
    runtime.ledger.project_put(
        "execution.effect-identity",
        "stable-effect",
        {
            "idempotency_key": "stable-effect",
            "fingerprint": fingerprint,
            "semantic_request": execution_module.effect_identity_payload(request),
        },
    )
    runtime.ledger.project_put(
        "execution.provider-attempt",
        "stable-effect",
        {
            "request_id": "request:effect",
            "provider_id": provider.descriptor.id,
            "provider_version": provider.descriptor.version,
            "capability": "demo.read",
            "effect_fingerprint": fingerprint,
            "effect_identity": execution_module.effect_identity_payload(request),
            "status": "started",
            "reconciliation_contract": {
                "provider_id": provider.descriptor.id,
                "provider_version": provider.descriptor.version,
                "protocol_identity": "demo.reconcile",
                "protocol_version": "1",
                "repeatability_mode": "repeat-safe",
                "contract_version": "1",
                "digest": __import__("world_runtime.execution", fromlist=["reconciliation_contract_for"])
                    .reconciliation_contract_for(provider.descriptor)
                    .digest,
            },
        },
    )

    result = await runtime.invoke(request)

    assert result.status == "succeeded"
    assert result.reconciled is True
    assert result.data == {"source": "reconcile"}
    assert provider.calls == 0


def test_service_enforces_identity_and_governance_qualification() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="service-integrity")
    client = _client(runtime)

    responsibility = {
        "id": "responsibility:http",
        "principal": "owner",
        "subject": "bounded work",
        "domain": "test",
        "scope": {"resource": "resource:http"},
    }
    first = client.post("/v1/responsibilities", json=responsibility)
    assert first.status_code == 200
    replay = client.post("/v1/responsibilities", json=responsibility)
    assert replay.status_code == 200
    rebound = client.post(
        "/v1/responsibilities",
        json={**responsibility, "subject": "different"},
    )
    assert rebound.status_code == 409

    decision_payload = {
        "id": "decision:http",
        "subject": "resource:http",
        "decided_by": "owner",
        "selected": {
            "target_ref": "resource:http",
            "operation": "authorize-effect",
            "action": "demo.effect",
        },
        "basis_refs": ["evidence:http"],
    }
    decision = client.post("/v1/decisions", json=decision_payload)
    assert decision.status_code == 200
    decision_replay = client.post("/v1/decisions", json=decision_payload)
    assert decision_replay.status_code == 200
    decision_rebound = client.post(
        "/v1/decisions",
        json={**decision_payload, "subject": "different"},
    )
    assert decision_rebound.status_code == 409

    mandate_payload = {
        "id": "mandate:http",
        "principal": "owner",
        "scope": {"resource": "resource:http"},
        "authority_ceiling": {
            "action": "demo.effect",
            "resource": "resource:http",
        },
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    mandate = client.post("/v1/mandates", json=mandate_payload)
    assert mandate.status_code == 200
    assert mandate.json()["status"] == "active"
    mandate_replay = client.post("/v1/mandates", json=mandate_payload)
    assert mandate_replay.status_code == 200
    mandate_rebound = client.post(
        "/v1/mandates",
        json={**mandate_payload, "scope": {"resource": "resource:other"}},
    )
    assert mandate_rebound.status_code == 409

    authorization = client.post(
        "/v1/authorizations",
        json={
            "id": "authorization:http",
            "principal": "controller:http",
            "action": "demo.effect",
            "resource": "resource:http",
            "mandate_id": "mandate:http",
            "decision_id": "decision:http",
            "annotations": {"case_id": "case:http"},
            "expires_at": "2098-01-01T00:00:00+00:00",
        },
    )
    assert authorization.status_code == 200
    assert authorization.json()["id"] == "authorization:http"

    unrelated = client.post(
        "/v1/decisions",
        json={
            "id": "decision:http:unrelated",
            "subject": "other",
            "decided_by": "owner",
            "selected": {
                "target_ref": "resource:other",
                "operation": "authorize-effect",
                "action": "demo.effect",
            },
            "basis_refs": ["evidence:http"],
        },
    )
    assert unrelated.status_code == 200
    rejected = client.post(
        "/v1/authorizations",
        json={
            "principal": "controller:http",
            "action": "demo.effect",
            "resource": "resource:http",
            "mandate_id": "mandate:http",
            "decision_id": "decision:http:unrelated",
        },
    )
    assert rejected.status_code == 403


def test_service_rejects_decision_without_basis() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="service-decision-basis")
    client = _client(runtime)
    response = client.post(
        "/v1/decisions",
        json={
            "id": "decision:no-basis",
            "subject": "x",
            "decided_by": "owner",
            "selected": {
                "target_ref": "x",
                "operation": "admit-goal",
            },
            "basis_refs": [],
        },
    )
    assert response.status_code == 400


def test_public_invoke_requires_work_for_effects_and_enforces_required_context() -> None:
    from semantic_language import Responsibility

    runtime = WorldRuntime.sqlite(runtime_id="service-invoke-integrity")
    provider = CountingProvider()
    provider._descriptor = provider.descriptor.model_copy(
        update={"capabilities": ["demo.effect"]}
    )
    runtime.registry.register(provider)
    runtime.responsibility.create(
        Responsibility(
            id="responsibility:http-effect",
            principal="principal:http",
            subject="effect",
        ),
        domain="test",
    )
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:http-effect",
        kind="effect",
        payload={},
    )
    client = _client(runtime, principal="principal:http")
    authorization = _attested_authority(
        runtime,
        principal="principal:http",
        decision_id="decision:http-effect",
        mandate_id="mandate:http-effect",
        authorization_id="authorization:http-effect",
        resource="resource:http",
        action="demo.effect",
        conditions={"required_context": {"request.metadata.change_ticket": "CHG-1"}},
    )

    missing_work = client.post(
        "/v1/invoke",
        json={
            "id": "request:missing-work",
            "capability": "demo.effect",
            "effect_class": "external-effect",
            "principal": "principal:http",
            "resource": "resource:http",
            "authorization_id": authorization.id,
            "idempotency_key": "http-effect:missing-work",
            "metadata": {"change_ticket": "CHG-1"},
        },
    )
    assert missing_work.status_code == 403

    wrong_context = client.post(
        "/v1/invoke",
        json={
            "id": "request:wrong-context",
            "capability": "demo.effect",
            "work_id": work.id,
            "effect_class": "external-effect",
            "principal": "principal:http",
            "resource": "resource:http",
            "authorization_id": authorization.id,
            "idempotency_key": "http-effect:wrong-context",
            "metadata": {"change_ticket": "CHG-2"},
        },
    )
    assert wrong_context.status_code == 403

    accepted = client.post(
        "/v1/invoke",
        json={
            "id": "request:matching-context",
            "capability": "demo.effect",
            "work_id": work.id,
            "effect_class": "external-effect",
            "principal": "principal:http",
            "resource": "resource:http",
            "authorization_id": authorization.id,
            "idempotency_key": "http-effect:matching-context",
            "metadata": {"change_ticket": "CHG-1"},
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "succeeded"


def test_empty_authority_ceiling_is_fail_closed() -> None:
    from semantic_language import Decision, Mandate, SemanticKind, SemanticRef

    runtime = WorldRuntime.sqlite()
    runtime.decisions.record(
        Decision(
            id="decision:empty-ceiling",
            subject="resource:1",
            decided_by="owner",
            selected={
                "target_ref": "resource:1",
                "operation": "authorize-effect",
                "action": "demo.effect",
            },
            basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:1"),),
        )
    )
    runtime.governance.register_mandate(
        Mandate(id="mandate:empty-ceiling", principal="owner")
    )
    with pytest.raises(PermissionError, match="no executable effect authority"):
        runtime.governance.issue_authorization(
            principal="principal",
            action="demo.effect",
            resource="resource:1",
            mandate_id="mandate:empty-ceiling",
            decision_id="decision:empty-ceiling",
        )


def test_public_invoke_requires_durable_identity_and_rejects_rebound() -> None:
    from semantic_language import Responsibility

    runtime = WorldRuntime.sqlite(runtime_id="service-effect-identity")
    provider = CountingProvider()
    provider._descriptor = provider.descriptor.model_copy(
        update={"capabilities": ["demo.effect"]}
    )
    runtime.registry.register(provider)
    runtime.responsibility.create(
        Responsibility(
            id="responsibility:effect-identity",
            principal="principal:http",
            subject="effect identity",
        ),
        domain="test",
    )
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:effect-identity",
        kind="effect",
        payload={},
    )
    client = _client(runtime, principal="principal:http")
    authorization = _attested_authority(
        runtime,
        principal="principal:http",
        decision_id="decision:effect-identity",
        mandate_id="mandate:effect-identity",
        authorization_id="authorization:effect-identity",
        resource="resource:http",
        action="demo.effect",
    )
    base = {
        "capability": "demo.effect",
        "work_id": work.id,
        "effect_class": "external-effect",
        "principal": "principal:http",
        "resource": "resource:http",
        "authorization_id": authorization.id,
    }

    missing = client.post("/v1/invoke", json={**base, "parameters": {"mode": "deploy"}})
    assert missing.status_code == 403

    first = client.post(
        "/v1/invoke",
        json={
            **base,
            "id": "request:effect-identity:first",
            "idempotency_key": "effect:http:1",
            "parameters": {"mode": "deploy"},
        },
    )
    assert first.status_code == 200

    replay = client.post(
        "/v1/invoke",
        json={
            **base,
            "id": "request:effect-identity:replay",
            "idempotency_key": "effect:http:1",
            "parameters": {"mode": "deploy"},
        },
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()

    rebound = client.post(
        "/v1/invoke",
        json={
            **base,
            "id": "request:effect-identity:rebound",
            "idempotency_key": "effect:http:1",
            "parameters": {"mode": "delete"},
        },
    )
    assert rebound.status_code == 409



def test_capability_request_schema_is_closed() -> None:
    schema = CapabilityRequest.model_json_schema()
    assert schema["additionalProperties"] is False
    with pytest.raises(ValueError):
        CapabilityRequest.model_validate(
            {
                "capability": "demo.read",
                "provider_specific_mode": "blue",
            }
        )


def test_public_invoke_rejects_unknown_top_level_field_before_provider() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="service-closed-request")
    provider = CountingProvider()
    runtime.registry.register(provider)
    client = _client(runtime)

    response = client.post(
        "/v1/invoke",
        json={
            "capability": "demo.read",
            "provider_specific_mode": "blue",
        },
    )

    assert response.status_code == 422
    assert provider.calls == 0


def test_extension_field_cannot_rebind_durable_effect_identity() -> None:
    from semantic_language import Responsibility

    runtime = WorldRuntime.sqlite(runtime_id="service-extension-rebound")
    provider = CountingProvider()
    provider._descriptor = provider.descriptor.model_copy(
        update={"capabilities": ["demo.effect"]}
    )
    runtime.registry.register(provider)
    runtime.responsibility.create(
        Responsibility(
            id="responsibility:extension-rebound",
            principal="principal:http",
            subject="extension rebound",
        ),
        domain="test",
    )
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:extension-rebound",
        kind="effect",
        payload={},
    )
    client = _client(runtime, principal="principal:http")
    authorization = _attested_authority(
        runtime,
        principal="principal:http",
        decision_id="decision:extension-rebound",
        mandate_id="mandate:extension-rebound",
        authorization_id="authorization:extension-rebound",
        resource="resource:http",
        action="demo.effect",
    )
    base = {
        "capability": "demo.effect",
        "work_id": work.id,
        "effect_class": "external-effect",
        "principal": "principal:http",
        "resource": "resource:http",
        "authorization_id": authorization.id,
        "idempotency_key": "effect:http:extension-rebound",
        "parameters": {"mode": "deploy"},
    }

    first = client.post("/v1/invoke", json=base)
    assert first.status_code == 200
    assert provider.calls == 1

    invalid_extension = client.post(
        "/v1/invoke",
        json={**base, "provider_specific_mode": "green"},
    )
    assert invalid_extension.status_code == 422
    assert provider.calls == 1



@pytest.mark.asyncio
async def test_preconstructed_request_extra_is_rejected_before_provider() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="service-tainted-request")
    provider = CountingProvider()
    runtime.registry.register(provider)
    clean = CapabilityRequest(capability="demo.read")
    tainted = clean.model_copy(update={"provider_specific_mode": "blue"})

    with pytest.raises(ValueError, match="undeclared fields"):
        await runtime.invoke(tainted)

    assert provider.calls == 0


def test_authority_bearing_http_writes_require_authentication_and_principal_match() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="service-auth-boundary")
    unauthenticated = TestClient(create_app(runtime))

    missing = unauthenticated.post(
        "/v1/responsibilities",
        json={
            "id": "responsibility:missing-auth",
            "principal": "principal:owner",
            "subject": "must authenticate",
            "domain": "test",
        },
    )
    assert missing.status_code == 401

    client = _client(runtime, principal="principal:owner")
    mismatched = client.post(
        "/v1/responsibilities",
        json={
            "id": "responsibility:wrong-principal",
            "principal": "principal:other",
            "subject": "cannot impersonate",
            "domain": "test",
        },
    )
    assert mismatched.status_code == 403


def test_delegation_http_route_separates_authenticated_and_effective_principal() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="service-delegation")
    owner = _client(runtime, principal="principal:owner")
    runtime.identity.bind_bearer_token(
        principal="controller:delegate",
        token="delegate-token",
        credential_id="credential:delegate",
    )

    grant = owner.post(
        "/v1/delegations",
        json={
            "id": "delegation:http",
            "grantor": "principal:owner",
            "grantee": "controller:delegate",
            "scope": {},
            "authority_ceiling": {
                "operation": "create-responsibility",
            },
        },
    )
    assert grant.status_code == 200

    delegated = TestClient(
        create_app(runtime),
        headers={
            "Authorization": "Bearer delegate-token",
            "X-World-Runtime-Delegation": "delegation:http",
        },
    )
    created = delegated.post(
        "/v1/responsibilities",
        json={
            "id": "responsibility:delegated",
            "principal": "principal:owner",
            "subject": "delegated owner work",
            "domain": "test",
        },
    )
    assert created.status_code == 200
    assert runtime.responsibility.get("responsibility:delegated").principal == "principal:owner"

    revoke = owner.post(
        "/v1/delegations/delegation:http/revoke",
        json={"reason": "rotation"},
    )
    assert revoke.status_code == 200

    rejected = delegated.post(
        "/v1/responsibilities",
        json={
            "id": "responsibility:after-revoke",
            "principal": "principal:owner",
            "subject": "revoked delegation",
            "domain": "test",
        },
    )
    assert rejected.status_code == 401


def test_domain_report_requires_the_authenticated_assigned_controller() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="service-domain-authorship")
    owner = _client(runtime, principal="principal:owner")
    runtime.identity.bind_bearer_token(
        principal="controller:assigned",
        token="assigned-token",
        credential_id="credential:assigned",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:other",
        token="other-token",
        credential_id="credential:other",
    )

    responsibility = owner.post(
        "/v1/responsibilities",
        json={
            "id": "responsibility:domain-authorship",
            "principal": "principal:owner",
            "subject": "controller authorship",
            "domain": "test",
        },
    )
    assert responsibility.status_code == 200

    assignment = owner.post(
        "/v1/domain-assignments",
        json={
            "id": "assignment:domain-authorship",
            "responsibility_ref": "responsibility:domain-authorship",
            "domain": "test",
            "controller": "controller:assigned",
        },
    )
    assert assignment.status_code == 200

    other = TestClient(
        create_app(runtime),
        headers={"Authorization": "Bearer other-token"},
    )
    rejected = other.post(
        "/v1/domain-assignments/assignment:domain-authorship/reports",
        json={"id": "report:wrong-controller", "kind": "accepted"},
    )
    assert rejected.status_code == 403

    assigned = TestClient(
        create_app(runtime),
        headers={"Authorization": "Bearer assigned-token"},
    )
    accepted = assigned.post(
        "/v1/domain-assignments/assignment:domain-authorship/reports",
        json={"id": "report:assigned-controller", "kind": "accepted"},
    )
    assert accepted.status_code == 200


def test_reconcile_and_result_endpoints_fail_closed_for_missing_state() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="service-missing-state")
    client = _client(runtime, principal="principal:owner")

    reconcile = client.post("/v1/reconcile/missing-effect")
    assert reconcile.status_code == 404

    missing_result = client.get("/v1/results/missing-request")
    assert missing_result.status_code == 404

    runtime.ledger.project_put(
        "execution.provider-result",
        "request:known",
        {"request_id": "request:known", "status": "succeeded"},
    )
    legacy_unbound = client.get("/v1/results/request:known")
    assert legacy_unbound.status_code == 403

    runtime.ledger.project_put(
        "execution.provider-result-access",
        "request:known",
        {
            "request_id": "request:known",
            "principal": "principal:owner",
            "authenticated_actor": "principal:owner",
            "work_id": None,
            "run_id": None,
        },
    )
    known_result = client.get("/v1/results/request:known")
    assert known_result.status_code == 200
    assert known_result.json()["status"] == "succeeded"

    other = _client(runtime, principal="principal:other")
    assert other.get("/v1/results/request:known").status_code == 403


def test_decision_attestation_rejects_historical_and_wrong_principal() -> None:
    from semantic_language import Decision, SemanticKind, SemanticRef

    runtime = WorldRuntime.sqlite(runtime_id="decision-attestation")
    owner_client = _client(runtime, principal="principal:owner")
    del owner_client
    owner = runtime.identity.authenticate_bearer("Bearer test-token:principal:owner")

    historical = Decision(
        id="decision:historical",
        subject="resource:1",
        decided_by="principal:owner",
        selected={"target_ref": "resource:1", "operation": "observe"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:historical"),),
    )
    runtime.decisions.record(historical)
    with pytest.raises(PermissionError, match="not authenticated"):
        runtime.decisions.assert_attested(historical.id, context=owner)

    attested = Decision(
        id="decision:attested",
        subject="resource:1",
        decided_by="principal:owner",
        selected={"target_ref": "resource:1", "operation": "observe"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:attested"),),
    )
    runtime.decisions.record_attested(attested, context=owner)

    _client(runtime, principal="principal:other")
    other = runtime.identity.authenticate_bearer("Bearer test-token:principal:other")
    with pytest.raises(PermissionError, match="does not match authenticated principal"):
        runtime.decisions.assert_attested(attested.id, context=other)


def test_delegation_http_rejects_grantor_impersonation() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="delegation-impersonation")
    client = _client(runtime, principal="principal:owner")

    response = client.post(
        "/v1/delegations",
        json={
            "id": "delegation:impersonated",
            "grantor": "principal:other",
            "grantee": "controller:delegate",
            "scope": {},
            "authority_ceiling": {},
        },
    )
    assert response.status_code == 403


def test_domain_owned_effect_executes_only_through_runtime_grant() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="service-domain-effect")
    client = _client(runtime, principal="principal:owner")

    responsibility = client.post(
        "/v1/responsibilities",
        json={
            "id": "responsibility:domain-effect",
            "principal": "principal:owner",
            "subject": "own one external effect",
            "domain": "test",
        },
    )
    assert responsibility.status_code == 200

    work_payload = {"resource_ref": "resource:domain-effect"}
    first_work = client.post(
        "/v1/work",
        json={
            "id": "work:domain-effect",
            "responsibility_id": "responsibility:domain-effect",
            "kind": "external-effect",
            "payload": work_payload,
        },
    )
    assert first_work.status_code == 200
    replay_work = client.post(
        "/v1/work",
        json={
            "id": "work:domain-effect",
            "responsibility_id": "responsibility:domain-effect",
            "kind": "external-effect",
            "payload": work_payload,
        },
    )
    assert replay_work.status_code == 200
    assert replay_work.json()["id"] == "work:domain-effect"

    decision = client.post(
        "/v1/decisions",
        json={
            "id": "decision:domain-effect",
            "subject": "resource:domain-effect",
            "decided_by": "principal:owner",
            "selected": {
                "target_ref": "resource:domain-effect",
                "operation": "authorize-effect",
                "action": "test.external.apply",
            },
            "basis_refs": ["evidence:domain-effect"],
        },
    )
    assert decision.status_code == 200

    mandate = client.post(
        "/v1/mandates",
        json={
            "id": "mandate:domain-effect",
            "principal": "principal:owner",
            "scope": {"resource": "resource:domain-effect"},
            "authority_ceiling": {
                "action": "test.external.apply",
                "resource": "resource:domain-effect",
            },
        },
    )
    assert mandate.status_code == 200

    authorization = client.post(
        "/v1/authorizations",
        json={
            "id": "authorization:domain-effect",
            "principal": "principal:owner",
            "action": "test.external.apply",
            "resource": "resource:domain-effect",
            "mandate_id": "mandate:domain-effect",
            "decision_id": "decision:domain-effect",
        },
    )
    assert authorization.status_code == 200

    effect_request = {
        "id": "request:domain-effect",
        "capability": "test.external.apply",
        "work_id": "work:domain-effect",
        "effect_class": "external-effect",
        "principal": "principal:owner",
        "resource": "resource:domain-effect",
        "resource_ref": "resource:domain-effect",
        "authorization_id": "authorization:domain-effect",
        "idempotency_key": "effect:domain-effect",
        "parameters": {"mode": "apply"},
    }
    prepared = client.post(
        "/v1/domain-effects/prepare",
        json={
            "request": effect_request,
            "provider_id": "provider:test-domain",
            "provider_version": "1",
        },
    )
    assert prepared.status_code == 200
    assert prepared.json()["status"] == "authorized"
    assert prepared.json()["start_allowed"] is True
    assert prepared.json()["dispatch_allowed"] is False

    started = client.post("/v1/domain-effects/effect:domain-effect/start")
    assert started.status_code == 200
    assert started.json()["dispatch_allowed"] is True
    generation = started.json()["dispatch_generation"]

    second_start = client.post("/v1/domain-effects/effect:domain-effect/start")
    assert second_start.status_code == 409

    result = client.post(
        "/v1/domain-effects/effect:domain-effect/result",
        json={
            "dispatch_generation": generation,
            "result": {
                "status": "succeeded",
                "evidence_refs": ["evidence:provider-receipt"],
                "data": {"domain_receipt": "receipt:1"},
            },
        },
    )
    assert result.status_code == 200
    assert result.json()["request_id"] == "request:domain-effect"
    assert result.json()["provider_id"] == "provider:test-domain"

    replay = client.post(
        "/v1/domain-effects/prepare",
        json={
            "request": effect_request,
            "provider_id": "provider:test-domain",
            "provider_version": "1",
        },
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "committed"
    assert replay.json()["dispatch_allowed"] is False
    assert replay.json()["result"]["data"]["domain_receipt"] == "receipt:1"


def test_domain_effect_http_fails_closed_across_identity_and_reconciliation_edges() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="service-domain-effect-edges")
    client = _client(runtime, principal="principal:owner")
    assert client.post(
        "/v1/responsibilities",
        json={
            "id": "responsibility:domain-effect-edges",
            "principal": "principal:owner",
            "subject": "exercise reality-boundary edges",
            "domain": "test",
        },
    ).status_code == 200
    work_payload = {"resource_ref": "resource:domain-effect-edges"}
    assert client.post(
        "/v1/work",
        json={
            "id": "work:domain-effect-edges",
            "responsibility_id": "responsibility:domain-effect-edges",
            "kind": "external-effect",
            "payload": work_payload,
        },
    ).status_code == 200
    rebound = client.post(
        "/v1/work",
        json={
            "id": "work:domain-effect-edges",
            "responsibility_id": "responsibility:domain-effect-edges",
            "kind": "external-effect",
            "payload": {"resource_ref": "resource:different"},
        },
    )
    assert rebound.status_code == 409

    assert client.post(
        "/v1/decisions",
        json={
            "id": "decision:domain-effect-edges",
            "subject": "resource:domain-effect-edges",
            "decided_by": "principal:owner",
            "selected": {
                "target_ref": "resource:domain-effect-edges",
                "operation": "authorize-effect",
                "action": "test.external.edges",
            },
            "basis_refs": ["evidence:domain-effect-edges"],
        },
    ).status_code == 200
    assert client.post(
        "/v1/mandates",
        json={
            "id": "mandate:domain-effect-edges",
            "principal": "principal:owner",
            "scope": {"resource": "resource:domain-effect-edges"},
            "authority_ceiling": {
                "action": "test.external.edges",
                "resource": "resource:domain-effect-edges",
            },
        },
    ).status_code == 200
    assert client.post(
        "/v1/authorizations",
        json={
            "id": "authorization:domain-effect-edges",
            "principal": "principal:owner",
            "action": "test.external.edges",
            "resource": "resource:domain-effect-edges",
            "mandate_id": "mandate:domain-effect-edges",
            "decision_id": "decision:domain-effect-edges",
        },
    ).status_code == 200

    base_request = {
        "id": "request:domain-effect-edges",
        "capability": "test.external.edges",
        "work_id": "work:domain-effect-edges",
        "effect_class": "external-effect",
        "principal": "principal:owner",
        "resource": "resource:domain-effect-edges",
        "resource_ref": "resource:domain-effect-edges",
        "authorization_id": "authorization:domain-effect-edges",
        "idempotency_key": "effect:domain-effect-edges",
        "parameters": {"mode": "apply"},
    }

    read_request = dict(base_request)
    read_request["id"] = "request:domain-effect-read"
    read_request["idempotency_key"] = "effect:domain-effect-read"
    read_request["effect_class"] = "read-only"
    read_only = client.post(
        "/v1/domain-effects/prepare",
        json={
            "request": read_request,
            "provider_id": "provider:test",
            "provider_version": "1",
        },
    )
    assert read_only.status_code == 400

    forged = dict(base_request)
    forged["actor_ref"] = "controller:forged"
    forged_actor = client.post(
        "/v1/domain-effects/prepare",
        json={
            "request": forged,
            "provider_id": "provider:test",
            "provider_version": "1",
        },
    )
    assert forged_actor.status_code == 403

    prepared = client.post(
        "/v1/domain-effects/prepare",
        json={
            "request": base_request,
            "provider_id": "provider:test",
            "provider_version": "1",
        },
    )
    assert prepared.status_code == 200
    assert prepared.json()["status"] == "authorized"

    current = client.get("/v1/domain-effects/effect:domain-effect-edges")
    assert current.status_code == 200
    assert current.json()["start_allowed"] is True

    provider_rebound = client.post(
        "/v1/domain-effects/prepare",
        json={
            "request": base_request,
            "provider_id": "provider:other",
            "provider_version": "1",
        },
    )
    assert provider_rebound.status_code == 409

    started = client.post("/v1/domain-effects/effect:domain-effect-edges/start")
    assert started.status_code == 200
    generation = started.json()["dispatch_generation"]

    stale = client.post(
        "/v1/domain-effects/effect:domain-effect-edges/result",
        json={
            "dispatch_generation": generation + 1,
            "result": {"status": "succeeded"},
        },
    )
    assert stale.status_code == 409

    unknown = client.post(
        "/v1/domain-effects/effect:domain-effect-edges/result",
        json={
            "dispatch_generation": generation,
            "result": {
                "status": "unknown",
                "error": {"code": "ack-lost"},
            },
        },
    )
    assert unknown.status_code == 200
    assert unknown.json()["status"] == "unknown"

    ambiguous = client.get("/v1/domain-effects/effect:domain-effect-edges")
    assert ambiguous.status_code == 200
    assert ambiguous.json()["status"] == "ambiguous"
    assert ambiguous.json()["dispatch_allowed"] is False
    assert client.post(
        "/v1/domain-effects/effect:domain-effect-edges/start"
    ).status_code == 409

    reconciled = client.post(
        "/v1/domain-effects/effect:domain-effect-edges/result",
        json={
            "dispatch_generation": generation,
            "result": {
                "status": "succeeded",
                "reconciled": True,
                "external_operation_ref": "external:domain-effect-edges",
            },
        },
    )
    assert reconciled.status_code == 200
    assert reconciled.json()["reconciled"] is True

    replay = client.post(
        "/v1/domain-effects/prepare",
        json={
            "request": base_request,
            "provider_id": "provider:test",
            "provider_version": "1",
        },
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "committed"
    assert replay.json()["dispatch_allowed"] is False



def test_service_exposes_authenticated_responsibility_graph_lifecycle() -> None:
    runtime = WorldRuntime.sqlite()
    client = _client(runtime)

    for identifier, domain in (
        ("responsibility:parent", "operations"),
        ("responsibility:child", "development"),
    ):
        response = client.post(
            "/v1/responsibilities",
            json={
                "id": identifier,
                "principal": "owner",
                "subject": identifier,
                "domain": domain,
                "scope": {},
            },
        )
        assert response.status_code == 200

    relate = client.post(
        "/v1/decisions",
        json={
            "id": "decision:relate",
            "subject": "responsibility:parent",
            "decided_by": "owner",
            "selected": {
                "target_ref": "responsibility:parent",
                "operation": "relate-responsibility",
                "target_responsibility_id": "responsibility:child",
                "relation": "requires",
            },
            "basis_refs": ["evidence:relate"],
        },
    )
    assert relate.status_code == 200

    created = client.post(
        "/v1/responsibilities/responsibility:parent/relations",
        json={
            "id": "responsibility-relation:service",
            "target_responsibility_id": "responsibility:child",
            "relation": "requires",
            "decision_id": "decision:relate",
            "basis_refs": ["evidence:relate"],
        },
    )
    assert created.status_code == 200
    assert created.json()["relation"] == "requires"

    listed = client.get("/v1/responsibilities/responsibility:parent/relations")
    assert listed.status_code == 200
    assert listed.json()["relations"][0]["id"] == "responsibility-relation:service"

    retire_decision = client.post(
        "/v1/decisions",
        json={
            "id": "decision:retire-relation",
            "subject": "responsibility-relation:service",
            "decided_by": "owner",
            "selected": {
                "target_ref": "responsibility-relation:service",
                "operation": "retire-responsibility-relation",
            },
            "basis_refs": ["evidence:retire-relation"],
        },
    )
    assert retire_decision.status_code == 200

    retired = client.post(
        "/v1/responsibility-relations/responsibility-relation:service/retire",
        json={
            "decision_id": "decision:retire-relation",
            "basis_refs": ["evidence:retire-relation"],
        },
    )
    assert retired.status_code == 200
    assert retired.json()["status"] == "retired"

    listed = client.get("/v1/responsibilities/responsibility:parent/relations")
    assert listed.status_code == 200
    assert listed.json()["relations"][0]["status"] == "retired"


def test_service_responsibility_graph_rejects_unattested_decision() -> None:
    runtime = WorldRuntime.sqlite()
    client = _client(runtime)
    for identifier in ("responsibility:a", "responsibility:b"):
        assert client.post(
            "/v1/responsibilities",
            json={
                "id": identifier,
                "principal": "owner",
                "subject": identifier,
                "domain": "test",
                "scope": {},
            },
        ).status_code == 200

    from semantic_language import Decision, SemanticKind, SemanticRef

    runtime.decisions.record(
        Decision(
            id="decision:unattested-relation",
            subject="responsibility:a",
            decided_by="owner",
            selected={
                "target_ref": "responsibility:a",
                "operation": "relate-responsibility",
                "target_responsibility_id": "responsibility:b",
                "relation": "requires",
            },
            basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:unattested"),),
        )
    )
    response = client.post(
        "/v1/responsibilities/responsibility:a/relations",
        json={
            "target_responsibility_id": "responsibility:b",
            "relation": "requires",
            "decision_id": "decision:unattested-relation",
            "basis_refs": ["evidence:unattested"],
        },
    )
    assert response.status_code == 403
