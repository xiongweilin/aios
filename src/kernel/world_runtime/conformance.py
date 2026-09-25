from __future__ import annotations

import asyncio
import json
import secrets
from importlib.resources import files
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from semantic_language import (
    Decision,
    Goal,
    Mandate,
    Responsibility,
    Revision,
    SemanticKind,
    SemanticRef,
)

from .execution import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
    effect_identity_fingerprint,
    effect_identity_payload,
    reconciliation_contract_for,
)
from .identity import DelegationGrant
from .ledger import ProjectionVersionConflict, SQLiteLedger
from .ontology import SemanticTypeDefinition
from .runtime import WorldRuntime


SUITE_VERSION = "world-runtime-conformance-v11"

_CONFORMANCE_TOKENS: dict[str, str] = {}


def _conformance_token(name: str) -> str:
    value = _CONFORMANCE_TOKENS.get(name)
    if value is None:
        value = secrets.token_urlsafe(32)
        _CONFORMANCE_TOKENS[name] = value
    return value


def conformance_vectors() -> dict[str, Any]:
    resource = files("world_runtime.contracts").joinpath("vectors.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if value.get("suite_version") != SUITE_VERSION:
        raise ValueError("World Runtime conformance suite version mismatch")
    if not isinstance(value.get("vectors"), list) or not value["vectors"]:
        raise ValueError("World Runtime conformance vectors are unavailable")
    return value


@dataclass(frozen=True, slots=True)
class ConformanceResult:
    vector_id: str
    passed: bool
    detail: str = ""


class _RecoverableProvider:
    def __init__(self) -> None:
        self.invoke_calls = 0
        self.reconcile_calls = 0
        self._descriptor = ProviderDescriptor(
            id="conformance-provider",
            name="Conformance Provider",
            version="1",
            capabilities=["conformance.effect"],
            reconciliation_protocol_identity="conformance.reconcile",
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
        self.invoke_calls += 1
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
        )

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        self.reconcile_calls += 1
        return CapabilityResult(
            request_id=request_id,
            provider_id=self.descriptor.id,
            status="succeeded",
            reconciled=True,
        )


async def run_reference_conformance() -> tuple[ConformanceResult, ...]:
    checks: dict[str, Callable[[], Any]] = {
        "responsibility-terminal-assessment-requires-basis": _terminal_basis,
        "responsibility-discharge-requires-satisfied-and-decision": _discharge_gate,
        "authorization-requires-active-mandate-and-decision": _authorization_admission,
        "authorization-use-is-exact-scope": _authorization_scope,
        "ambiguous-effect-never-blind-redispatches": _ambiguous_effect,
        "reconciliation-contract-drift-fails-closed": _reconciliation_drift,
        "runtime-state-survives-restart": _restart,
        "portable-state-rejects-dangling-graph": _dangling_bundle,
        "decision-applicability-is-required": _decision_applicability,
        "identity-rebound-is-rejected": _identity_rebound,
        "expired-mandate-is-not-current": _expired_mandate,
        "expired-authorization-is-not-usable": _expired_authorization,
        "empty-authority-ceiling-delegates-no-effect": _empty_authority_ceiling,
        "discharged-responsibility-rejects-work": _discharged_rejects_work,
        "discharged-responsibility-rejects-effect": _discharged_rejects_effect,
        "effectful-invocation-requires-work": _effect_requires_work,
        "run-must-belong-to-work": _run_belongs_to_work,
        "authorization-required-context-is-enforced": _required_context,
        "effectful-invocation-requires-durable-identity": _effect_requires_identity,
        "effect-identity-rebound-is-rejected": _effect_identity_rebound,
        "capability-request-unknown-field-rejected": _capability_request_unknown_field,
        "effect-identity-cannot-rebind-through-extension-field": _extension_field_rebound,
        "authority-bearing-http-requires-authentication": _http_requires_authentication,
        "claimed-principal-cannot-override-authenticated-identity": _claimed_principal_mismatch,
        "revoked-delegation-cannot-act": _revoked_delegation,
        "unattested-decision-cannot-be-adopted": _unattested_decision_not_adopted,
        "unattested-authorization-cannot-execute-over-http": _unattested_authorization_not_http,
        "delegation-cannot-widen-authority": _delegation_cannot_widen,
        "revoked-credential-cannot-authenticate": _revoked_credential,
        "bounded-subdelegation-preserves-root-authority": _bounded_subdelegation,
        "stable-work-identity-is-replayable": _stable_work_identity,
        "domain-effect-requires-start-before-dispatch": _domain_effect_prepare_requires_start,
        "domain-effect-start-is-single-use": _domain_effect_start_single_use,
        "ambiguous-domain-effect-blocks-redispatch": _domain_effect_ambiguous_replay,
        "domain-effect-result-identity-is-bound": _domain_effect_result_identity,
        "domain-effect-start-revalidates-current-authority": _domain_effect_start_revalidates_authority,
        "projection-cas-cross-connection-single-winner": _projection_cas_cross_connection,
        "run-lease-cross-runtime-single-owner": _run_lease_cross_runtime,
        "domain-effect-start-cross-runtime-single-dispatch": _domain_effect_start_cross_runtime,
        "provider-attempt-cross-runtime-single-dispatch": _provider_attempt_cross_runtime,
        "shared-authorization-distinct-runtime-effects-survive-contention": _shared_authority_runtime_effects,
        "shared-authorization-distinct-domain-starts-survive-contention": _shared_authority_domain_starts,
        "institutional-lineage-rejects-historical-branch": _institutional_lineage_rejects_branch,
        "superseded-decision-is-not-currently-applicable": _superseded_decision_not_current,
        "ontology-version-change-requires-revision": _ontology_version_requires_revision,
        "experience-applicability-requires-qualified-current-head": _experience_current_applicability,
        "superseded-mandate-cannot-qualify-current-authority": _superseded_mandate_not_current,
        "goal-successor-requires-revision-required-and-explicit-decision": _goal_successor_gate,
        "revoked-decision-is-not-currently-applicable": _revoked_decision_not_current,
        "revoked-authorization-is-not-usable": _revoked_authorization_not_usable,
        "strategy-reassessment-requires-explicit-lineage": _strategy_reassessment_requires_lineage,
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
    results: list[ConformanceResult] = []
    for vector in conformance_vectors()["vectors"]:
        vector_id = str(vector["id"])
        try:
            outcome = checks[vector_id]()
            if hasattr(outcome, "__await__"):
                await outcome
        except Exception as exc:
            results.append(ConformanceResult(vector_id, False, str(exc)))
        else:
            results.append(ConformanceResult(vector_id, True))
    return tuple(results)


def _responsibility(runtime: WorldRuntime, identifier: str = "responsibility:conformance") -> None:
    runtime.responsibility.create(
        Responsibility(
            id=identifier,
            principal="service:conformance",
            subject="conformance",
        ),
        domain="conformance",
    )


def _decision(
    runtime: WorldRuntime,
    identifier: str = "decision:conformance",
    *,
    target_ref: str = "resource:1",
    operation: str = "authorize-effect",
    selected: dict[str, object] | None = None,
) -> None:
    runtime.decisions.record(
        Decision(
            id=identifier,
            subject="conformance",
            decided_by="service:conformance",
            selected={
                "target_ref": target_ref,
                "operation": operation,
                **dict(selected or {}),
            },
            basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:conformance"),),
        )
    )


def _terminal_basis() -> None:
    runtime = WorldRuntime.sqlite()
    _responsibility(runtime)
    try:
        runtime.responsibility.assess(
            "responsibility:conformance",
            status="satisfied",
            basis_refs=(),
        )
    except ValueError:
        return
    raise AssertionError("terminal responsibility assessment accepted without basis")


def _discharge_gate() -> None:
    runtime = WorldRuntime.sqlite()
    _responsibility(runtime)
    try:
        runtime.responsibility.discharge(
            "responsibility:conformance",
            decision_id="decision:missing",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("active responsibility discharged")
    runtime.responsibility.assess(
        "responsibility:conformance",
        status="satisfied",
        basis_refs=("evidence:conformance",),
    )
    try:
        runtime.responsibility.discharge(
            "responsibility:conformance",
            decision_id="decision:missing",
        )
    except ValueError:
        return
    raise AssertionError("responsibility discharged without Decision")


def _authorization_admission() -> None:
    runtime = WorldRuntime.sqlite()
    try:
        runtime.governance.issue_authorization(
            principal="service:conformance",
            action="conformance.effect",
            resource="resource:1",
            mandate_id="mandate:missing",
            decision_id="decision:missing",
        )
    except PermissionError:
        return
    raise AssertionError("authorization issued without mandate/decision")


def _authorized_runtime() -> WorldRuntime:
    runtime = WorldRuntime.sqlite()
    _decision(runtime, selected={"action": "conformance.effect"})
    runtime.governance.register_mandate(
        Mandate(
            id="mandate:conformance",
            principal="service:conformance",
            authority_ceiling={"action": "*", "resource": "*"},
        )
    )
    runtime.governance.issue_authorization(
        authorization_id="authorization:conformance",
        principal="service:conformance",
        action="conformance.effect",
        resource="resource:1",
        mandate_id="mandate:conformance",
        decision_id="decision:conformance",
    )
    return runtime


def _authorization_scope() -> None:
    runtime = _authorized_runtime()
    try:
        runtime.governance.assert_usable(
            "authorization:conformance",
            principal="service:conformance",
            action="conformance.effect",
            resource="resource:2",
        )
    except PermissionError:
        return
    raise AssertionError("authorization scope rebound was accepted")


async def _ambiguous_effect() -> None:
    runtime = WorldRuntime.sqlite()
    provider = _RecoverableProvider()
    runtime.registry.register(provider)
    contract = reconciliation_contract_for(provider.descriptor)
    assert contract is not None
    request = CapabilityRequest(
        id="request:conformance-effect",
        capability="conformance.effect",
        work_id="work:historical-conformance",
        effect_class="external-effect",
        idempotency_key="conformance-effect",
    )
    fingerprint = effect_identity_fingerprint(request)
    runtime.ledger.project_put(
        "execution.effect-identity",
        request.idempotency_key,
        {
            "idempotency_key": request.idempotency_key,
            "fingerprint": fingerprint,
            "semantic_request": effect_identity_payload(request),
        },
    )
    runtime.ledger.project_put(
        "execution.provider-attempt",
        request.idempotency_key,
        {
            "request_id": request.id,
            "provider_id": provider.descriptor.id,
            "provider_version": provider.descriptor.version,
            "capability": request.capability,
            "effect_fingerprint": fingerprint,
            "effect_identity": effect_identity_payload(request),
            "status": "started",
            "reconciliation_contract": contract.model_dump(mode="json"),
        },
    )
    result = await runtime.invoke(request)
    if result.status != "succeeded" or provider.reconcile_calls != 1:
        raise AssertionError("ambiguous historical attempt did not reconcile")
    if provider.invoke_calls != 0:
        raise AssertionError("ambiguous historical attempt was blindly redispatched")


async def _reconciliation_drift() -> None:
    runtime = WorldRuntime.sqlite()
    provider = _RecoverableProvider()
    runtime.registry.register(provider)
    contract = reconciliation_contract_for(provider.descriptor)
    assert contract is not None
    runtime.ledger.project_put(
        "execution.provider-attempt",
        "conformance-drift",
        {
            "request_id": "request:conformance-drift",
            "provider_id": provider.descriptor.id,
            "provider_version": provider.descriptor.version,
            "capability": "conformance.effect",
            "status": "started",
            "reconciliation_contract": contract.model_dump(mode="json"),
        },
    )
    provider._descriptor = provider.descriptor.model_copy(
        update={"reconciliation_protocol_version": "2"}
    )
    result = await runtime.recovery.recover("conformance-drift")
    if result.status != "unknown":
        raise AssertionError("drifted reconciliation contract did not fail closed")
    if provider.reconcile_calls != 0:
        raise AssertionError("drifted reconciliation contract still queried provider")


def _restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "runtime.db"
        runtime = WorldRuntime.sqlite(path)
        _responsibility(runtime, "responsibility:restart")
        work = runtime.execution.admit_work(
            responsibility_id="responsibility:restart",
            kind="restart",
            payload={},
        )
        run = runtime.start_run(work.id, workflow_id="restart")
        runtime.close()

        reopened = WorldRuntime.sqlite(path)
        if reopened.responsibility.get("responsibility:restart").principal != "service:conformance":
            raise AssertionError("responsibility identity was not durable")
        runs = reopened.list_runs(work.id)
        if len(runs) != 1 or runs[0].id != run.id:
            raise AssertionError("run identity was not durable")
        reopened.close()


def _dangling_bundle() -> None:
    runtime = WorldRuntime.sqlite()
    _responsibility(runtime)
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:conformance",
        kind="bundle",
        payload={},
    )
    bundle = runtime.state_bundle.export()
    bundle["projections"] = [
        row
        for row in bundle["projections"]
        if row["namespace"] != "responsibility.current"
    ]
    payload = {
        "bundle_version": bundle["bundle_version"],
        "events": bundle["events"],
        "projections": bundle["projections"],
    }
    import hashlib

    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    bundle["manifest"]["projection_count"] = len(bundle["projections"])
    bundle["manifest"]["digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    validation = runtime.state_bundle.validate(bundle)
    if validation.valid:
        raise AssertionError(f"dangling Work graph accepted: {work.id}")


def _decision_applicability() -> None:
    runtime = WorldRuntime.sqlite()
    _responsibility(runtime)
    runtime.responsibility.assess(
        "responsibility:conformance",
        status="satisfied",
        basis_refs=("evidence:conformance",),
    )
    _decision(
        runtime,
        identifier="decision:unrelated",
        target_ref="responsibility:other",
        operation="discharge-responsibility",
        selected={"to_status": "discharged"},
    )
    try:
        runtime.responsibility.discharge(
            "responsibility:conformance",
            decision_id="decision:unrelated",
        )
    except ValueError:
        return
    raise AssertionError("unrelated Decision discharged responsibility")


def _identity_rebound() -> None:
    runtime = WorldRuntime.sqlite()
    _decision(
        runtime,
        identifier="decision:identity",
        target_ref="resource:1",
        operation="authorize-effect",
        selected={"action": "conformance.effect"},
    )
    try:
        runtime.decisions.record(
            Decision(
                id="decision:identity",
                subject="different",
                decided_by="service:conformance",
                selected={
                    "target_ref": "resource:2",
                    "operation": "authorize-effect",
                    "action": "conformance.effect",
                },
                basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:other"),),
            )
        )
    except ValueError:
        return
    raise AssertionError("Decision identity rebound was accepted")


def _expired_mandate() -> None:
    from datetime import timedelta
    from .common import utcnow

    runtime = WorldRuntime.sqlite()
    _decision(runtime, selected={"action": "conformance.effect"})
    runtime.governance.register_mandate(
        Mandate(
            id="mandate:expired",
            principal="service:conformance",
            authority_ceiling={"action": "*", "resource": "*"},
            expires_at=utcnow() - timedelta(seconds=1),
        )
    )
    try:
        runtime.governance.issue_authorization(
            principal="service:conformance",
            action="conformance.effect",
            resource="resource:1",
            mandate_id="mandate:expired",
            decision_id="decision:conformance",
        )
    except PermissionError:
        return
    raise AssertionError("expired Mandate issued Authorization")


def _expired_authorization() -> None:
    runtime = _authorized_runtime()
    row = runtime.ledger.project_get("governance.authorization", "authorization:conformance")
    assert row is not None
    value, version = row
    value["expires_at"] = "2000-01-01T00:00:00+00:00"
    runtime.ledger.project_put(
        "governance.authorization",
        "authorization:conformance",
        value,
        expected_version=version,
    )
    try:
        runtime.governance.assert_usable(
            "authorization:conformance",
            principal="service:conformance",
            action="conformance.effect",
            resource="resource:1",
        )
    except PermissionError:
        return
    raise AssertionError("expired Authorization remained usable")


def _empty_authority_ceiling() -> None:
    runtime = WorldRuntime.sqlite()
    _decision(runtime, selected={"action": "conformance.effect"})
    runtime.governance.register_mandate(
        Mandate(id="mandate:empty-ceiling", principal="service:conformance")
    )
    try:
        runtime.governance.issue_authorization(
            principal="service:conformance",
            action="conformance.effect",
            resource="resource:1",
            mandate_id="mandate:empty-ceiling",
            decision_id="decision:conformance",
        )
    except PermissionError:
        return
    raise AssertionError("empty authority ceiling delegated executable effect authority")


def _discharged_responsibility(runtime: WorldRuntime, identifier: str) -> str:
    _responsibility(runtime, identifier)
    work = runtime.execution.admit_work(
        responsibility_id=identifier,
        kind="conformance",
        payload={},
    )
    runtime.responsibility.assess(
        identifier,
        status="satisfied",
        basis_refs=("evidence:conformance",),
    )
    _decision(
        runtime,
        identifier=f"decision:discharge:{identifier}",
        target_ref=identifier,
        operation="discharge-responsibility",
        selected={"to_status": "discharged"},
    )
    runtime.responsibility.discharge(
        identifier,
        decision_id=f"decision:discharge:{identifier}",
    )
    return work.id


def _discharged_rejects_work() -> None:
    runtime = WorldRuntime.sqlite()
    _discharged_responsibility(runtime, "responsibility:discharged-work")
    try:
        runtime.execution.admit_work(
            responsibility_id="responsibility:discharged-work",
            kind="late",
            payload={},
        )
    except ValueError:
        return
    raise AssertionError("discharged Responsibility admitted new Work")


async def _discharged_rejects_effect() -> None:
    runtime = WorldRuntime.sqlite()
    work_id = _discharged_responsibility(runtime, "responsibility:discharged-effect")
    try:
        await runtime.invoke(
            CapabilityRequest(
                capability="conformance.effect",
                work_id=work_id,
                effect_class="external-effect",
                idempotency_key="conformance:discharged-effect",
            )
        )
    except PermissionError:
        return
    raise AssertionError("discharged Responsibility executed fresh effect")


async def _effect_requires_work() -> None:
    runtime = WorldRuntime.sqlite()
    try:
        await runtime.invoke(
            CapabilityRequest(
                capability="conformance.effect",
                effect_class="external-effect",
                idempotency_key="conformance:missing-work",
            )
        )
    except PermissionError:
        return
    raise AssertionError("effectful invocation executed without Work")


async def _run_belongs_to_work() -> None:
    runtime = WorldRuntime.sqlite()
    _responsibility(runtime, "responsibility:run-binding")
    work_a = runtime.execution.admit_work(
        responsibility_id="responsibility:run-binding",
        kind="a",
        payload={},
    )
    work_b = runtime.execution.admit_work(
        responsibility_id="responsibility:run-binding",
        kind="b",
        payload={},
    )
    run = runtime.start_run(work_a.id, workflow_id="a")
    try:
        await runtime.invoke(
            CapabilityRequest(
                capability="conformance.read",
                work_id=work_b.id,
                run_id=run.id,
                effect_class="read",
            )
        )
    except PermissionError:
        return
    raise AssertionError("Run was accepted under unrelated Work")


async def _required_context() -> None:
    runtime = WorldRuntime.sqlite()
    provider = _RecoverableProvider()
    runtime.registry.register(provider)
    _responsibility(runtime, "responsibility:required-context")
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:required-context",
        kind="effect",
        payload={},
    )
    _decision(
        runtime,
        identifier="decision:required-context",
        target_ref="resource:1",
        operation="authorize-effect",
        selected={"action": "conformance.effect"},
    )
    runtime.governance.register_mandate(
        Mandate(
            id="mandate:required-context",
            principal="service:conformance",
            authority_ceiling={"action": "conformance.effect", "resource": "resource:1"},
        )
    )
    runtime.governance.issue_authorization(
        authorization_id="authorization:required-context",
        principal="service:conformance",
        action="conformance.effect",
        resource="resource:1",
        mandate_id="mandate:required-context",
        decision_id="decision:required-context",
        conditions={"required_context": {"request.metadata.change_ticket": "CHG-1"}},
    )
    try:
        await runtime.invoke(
            CapabilityRequest(
                capability="conformance.effect",
                work_id=work.id,
                effect_class="external-effect",
                principal="service:conformance",
                resource="resource:1",
                authorization_id="authorization:required-context",
                idempotency_key="conformance:required-context:wrong",
                metadata={"change_ticket": "CHG-2"},
            )
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("required_context mismatch was accepted")
    result = await runtime.invoke(
        CapabilityRequest(
            capability="conformance.effect",
            work_id=work.id,
            effect_class="external-effect",
            principal="service:conformance",
            resource="resource:1",
            authorization_id="authorization:required-context",
            idempotency_key="conformance:required-context:ok",
            metadata={"change_ticket": "CHG-1"},
        )
    )
    if result.status != "succeeded":
        raise AssertionError("required_context matching invocation failed")


async def _effect_requires_identity() -> None:
    runtime = WorldRuntime.sqlite()
    provider = _RecoverableProvider()
    runtime.registry.register(provider)
    _responsibility(runtime, "responsibility:durable-effect")
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:durable-effect",
        kind="effect",
        payload={},
    )
    try:
        await runtime.invoke(
            CapabilityRequest(
                capability="conformance.effect",
                work_id=work.id,
                effect_class="external-effect",
            )
        )
    except PermissionError as exc:
        if "durable idempotency_key" not in str(exc):
            raise
        return
    raise AssertionError("effectful invocation without durable identity was accepted")


async def _effect_identity_rebound() -> None:
    runtime = WorldRuntime.sqlite()
    provider = _RecoverableProvider()
    runtime.registry.register(provider)
    _responsibility(runtime, "responsibility:effect-rebound")
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:effect-rebound",
        kind="effect",
        payload={},
    )
    _decision(
        runtime,
        identifier="decision:effect-rebound",
        target_ref="resource:1",
        operation="authorize-effect",
        selected={"action": "conformance.effect"},
    )
    runtime.governance.register_mandate(
        Mandate(
            id="mandate:effect-rebound",
            principal="service:conformance",
            authority_ceiling={"action": "conformance.effect", "resource": "resource:1"},
        )
    )
    runtime.governance.issue_authorization(
        authorization_id="authorization:effect-rebound",
        principal="service:conformance",
        action="conformance.effect",
        resource="resource:1",
        mandate_id="mandate:effect-rebound",
        decision_id="decision:effect-rebound",
    )
    base = CapabilityRequest(
        capability="conformance.effect",
        work_id=work.id,
        effect_class="external-effect",
        principal="service:conformance",
        resource="resource:1",
        authorization_id="authorization:effect-rebound",
        idempotency_key="effect:conformance-rebound",
        parameters={"mode": "deploy"},
    )
    result = await runtime.invoke(base)
    if result.status != "succeeded":
        raise AssertionError("baseline effect failed")
    try:
        await runtime.invoke(base.model_copy(update={"parameters": {"mode": "delete"}}))
    except ValueError as exc:
        if "identity rebound" not in str(exc):
            raise
    else:
        raise AssertionError("effect identity rebound was accepted")
    if provider.invoke_calls != 1:
        raise AssertionError("rebound triggered provider execution")


def _capability_request_unknown_field() -> None:
    payload = {
        "capability": "conformance.effect",
        "idempotency_key": "effect:unknown-field",
        "provider_specific_mode": "blue",
    }
    try:
        CapabilityRequest.model_validate(payload)
    except ValidationError:
        return
    raise AssertionError("undeclared CapabilityRequest field was accepted")


async def _extension_field_rebound() -> None:
    runtime = WorldRuntime.sqlite()
    provider = _RecoverableProvider()
    runtime.registry.register(provider)
    _responsibility(runtime, "responsibility:extension-rebound")
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:extension-rebound",
        kind="effect",
        payload={},
    )
    _decision(
        runtime,
        identifier="decision:extension-rebound",
        target_ref="resource:1",
        operation="authorize-effect",
        selected={"action": "conformance.effect"},
    )
    runtime.governance.register_mandate(
        Mandate(
            id="mandate:extension-rebound",
            principal="service:conformance",
            authority_ceiling={
                "action": "conformance.effect",
                "resource": "resource:1",
            },
        )
    )
    runtime.governance.issue_authorization(
        authorization_id="authorization:extension-rebound",
        principal="service:conformance",
        action="conformance.effect",
        resource="resource:1",
        mandate_id="mandate:extension-rebound",
        decision_id="decision:extension-rebound",
    )
    base_payload = {
        "capability": "conformance.effect",
        "work_id": work.id,
        "effect_class": "external-effect",
        "principal": "service:conformance",
        "resource": "resource:1",
        "authorization_id": "authorization:extension-rebound",
        "idempotency_key": "effect:extension-rebound",
        "parameters": {"mode": "deploy"},
    }
    baseline = CapabilityRequest.model_validate(base_payload)
    result = await runtime.invoke(baseline)
    if result.status != "succeeded":
        raise AssertionError("baseline effect failed")
    tainted = baseline.model_copy(update={"provider_specific_mode": "green"})
    try:
        await runtime.invoke(tainted)
    except ValueError as exc:
        if "undeclared fields" not in str(exc):
            raise
    else:
        raise AssertionError("preconstructed extension field bypassed Runtime boundary")
    if provider.invoke_calls != 1:
        raise AssertionError("invalid extension triggered provider execution")


def _http_requires_authentication() -> None:
    from fastapi.testclient import TestClient
    from .service import create_app

    runtime = WorldRuntime.sqlite()
    client = TestClient(create_app(runtime))
    response = client.post(
        "/v1/decisions",
        json={
            "id": "decision:unauthenticated",
            "subject": "x",
            "decided_by": "service:conformance",
            "selected": {"target_ref": "x", "operation": "admit-goal"},
            "basis_refs": ["evidence:conformance"],
        },
    )
    if response.status_code != 401:
        raise AssertionError("authority-bearing HTTP command accepted without authentication")
    if runtime.ledger.project_get("decision.current", "decision:unauthenticated") is not None:
        raise AssertionError("unauthenticated command mutated semantic state")


def _claimed_principal_mismatch() -> None:
    from fastapi.testclient import TestClient
    from .service import create_app

    runtime = WorldRuntime.sqlite()
    runtime.identity.bind_bearer_token(
        principal="principal:alice",
        token=_conformance_token("alice"),
        credential_id="credential:alice",
    )
    client = TestClient(
        create_app(runtime),
        headers={"Authorization": f"Bearer {_conformance_token('alice')}"},
    )
    response = client.post(
        "/v1/decisions",
        json={
            "id": "decision:forged",
            "subject": "x",
            "decided_by": "principal:bob",
            "selected": {"target_ref": "x", "operation": "admit-goal"},
            "basis_refs": ["evidence:conformance"],
        },
    )
    if response.status_code != 403:
        raise AssertionError("caller forged Decision.decided_by")
    if runtime.ledger.project_get("decision.current", "decision:forged") is not None:
        raise AssertionError("forged Decision mutated semantic state")


def _revoked_delegation() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.identity.bind_bearer_token(
        principal="principal:delegate",
        token=_conformance_token("delegate"),
        credential_id="credential:delegate",
    )
    runtime.identity.bind_bearer_token(
        principal="principal:owner",
        token=_conformance_token("owner"),
        credential_id="credential:owner",
    )
    owner = runtime.identity.authenticate_bearer(f"Bearer {_conformance_token('owner')}")
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:owner-to-delegate",
            grantor="principal:owner",
            grantee="principal:delegate",
            scope={"resource": "*"},
            authority_ceiling={"action": "*", "resource": "*"},
        ),
        context=owner,
    )
    delegated = runtime.identity.authenticate_bearer(
        f"Bearer {_conformance_token('delegate')}",
        delegation_id="delegation:owner-to-delegate",
    )
    if delegated.effective_principal != "principal:owner":
        raise AssertionError("delegation did not establish effective principal")
    runtime.identity.revoke_delegation(
        "delegation:owner-to-delegate",
        context=owner,
        reason="conformance",
    )
    try:
        runtime.identity.authenticate_bearer(
            f"Bearer {_conformance_token('delegate')}",
            delegation_id="delegation:owner-to-delegate",
        )
    except PermissionError:
        return
    raise AssertionError("revoked delegation remained usable")


def _unattested_decision_not_adopted() -> None:
    from fastapi.testclient import TestClient
    from .service import create_app

    runtime = WorldRuntime.sqlite()
    decision = Decision(
        id="decision:historical-unattested",
        subject="resource:1",
        decided_by="principal:owner",
        selected={
            "target_ref": "resource:1",
            "operation": "authorize-effect",
            "action": "conformance.effect",
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:historical"),),
    )
    runtime.decisions.record(decision)
    runtime.identity.bind_bearer_token(
        principal="principal:owner",
        token=_conformance_token("historical-owner"),
        credential_id="credential:historical-owner",
    )
    client = TestClient(
        create_app(runtime),
        headers={"Authorization": f"Bearer {_conformance_token('historical-owner')}"},
    )
    response = client.post(
        "/v1/decisions",
        json={
            "id": decision.id,
            "subject": decision.subject,
            "decided_by": decision.decided_by,
            "selected": dict(decision.selected),
            "basis_refs": ["evidence:historical"],
        },
    )
    if response.status_code != 403:
        raise AssertionError("historical unattested Decision was retroactively adopted")
    stored = runtime.decisions.get(decision.id)
    if "attestation" in stored:
        raise AssertionError("historical Decision acquired retroactive attestation")


async def _unattested_authorization_not_http() -> None:
    from fastapi.testclient import TestClient
    from .service import create_app

    runtime = WorldRuntime.sqlite()
    provider = _RecoverableProvider()
    runtime.registry.register(provider)
    _responsibility(runtime, "responsibility:historical-auth")
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:historical-auth",
        kind="effect",
        payload={},
    )
    _decision(
        runtime,
        identifier="decision:historical-auth",
        selected={"action": "conformance.effect"},
    )
    runtime.governance.register_mandate(
        Mandate(
            id="mandate:historical-auth",
            principal="service:conformance",
            authority_ceiling={"action": "conformance.effect", "resource": "resource:1"},
        )
    )
    runtime.governance.issue_authorization(
        authorization_id="authorization:historical-auth",
        principal="service:conformance",
        action="conformance.effect",
        resource="resource:1",
        mandate_id="mandate:historical-auth",
        decision_id="decision:historical-auth",
    )
    runtime.identity.bind_bearer_token(
        principal="service:conformance",
        token=_conformance_token("historical-service"),
        credential_id="credential:historical-service",
    )
    client = TestClient(
        create_app(runtime),
        headers={"Authorization": f"Bearer {_conformance_token('historical-service')}"},
    )
    response = client.post(
        "/v1/invoke",
        json={
            "id": "request:historical-auth",
            "capability": "conformance.effect",
            "work_id": work.id,
            "effect_class": "external-effect",
            "principal": "service:conformance",
            "resource": "resource:1",
            "authorization_id": "authorization:historical-auth",
            "idempotency_key": "effect:historical-auth",
        },
    )
    if response.status_code != 403:
        raise AssertionError("historical unattested Authorization executed over HTTP")
    if provider.invoke_calls != 0:
        raise AssertionError("unattested Authorization reached provider dispatch")


def _delegation_cannot_widen() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.identity.bind_bearer_token(
        principal="principal:owner",
        token=_conformance_token("delegation-owner"),
        credential_id="credential:delegation-owner",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:delegate",
        token=_conformance_token("delegation-controller"),
        credential_id="credential:delegation-controller",
    )
    owner = runtime.identity.authenticate_bearer(f"Bearer {_conformance_token('delegation-owner')}")
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:bounded",
            grantor="principal:owner",
            grantee="controller:delegate",
            scope={"resource": "resource:1"},
            authority_ceiling={"action": "deploy", "resource": "resource:1"},
        ),
        context=owner,
    )
    delegated = runtime.identity.authenticate_bearer(
        f"Bearer {_conformance_token('delegation-controller')}",
        delegation_id="delegation:bounded",
    )
    try:
        runtime.identity.assert_delegated_authority(
            delegated,
            scope={"resource": "resource:2"},
            authority_ceiling={"action": "deploy", "resource": "resource:2"},
        )
    except PermissionError:
        return
    raise AssertionError("delegated actor widened its authority")


def _bounded_subdelegation() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.identity.bind_bearer_token(
        principal="principal:root",
        token=_conformance_token("subdelegation-root"),
        credential_id="credential:subdelegation-root",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:middle",
        token=_conformance_token("subdelegation-middle"),
        credential_id="credential:subdelegation-middle",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:leaf",
        token=_conformance_token("subdelegation-leaf"),
        credential_id="credential:subdelegation-leaf",
    )
    root = runtime.identity.authenticate_bearer(f"Bearer {_conformance_token('subdelegation-root')}")
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:root-middle",
            grantor="principal:root",
            grantee="controller:middle",
            scope={"resource": "*"},
            authority_ceiling={"action": "*", "resource": "*"},
        ),
        context=root,
    )
    middle = runtime.identity.authenticate_bearer(
        f"Bearer {_conformance_token('subdelegation-middle')}",
        delegation_id="delegation:root-middle",
    )
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:middle-leaf",
            grantor="controller:middle",
            grantee="controller:leaf",
            scope={"resource": "resource:1"},
            authority_ceiling={"action": "deploy", "resource": "resource:1"},
            parent_id="delegation:root-middle",
        ),
        context=middle,
    )
    leaf = runtime.identity.authenticate_bearer(
        f"Bearer {_conformance_token('subdelegation-leaf')}",
        delegation_id="delegation:middle-leaf",
    )
    if leaf.effective_principal != "principal:root":
        raise AssertionError("subdelegation did not preserve root effective principal")
    runtime.identity.assert_delegated_authority(
        leaf,
        scope={"resource": "resource:1"},
        authority_ceiling={"action": "deploy", "resource": "resource:1"},
    )


def _revoked_credential() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.identity.bind_bearer_token(
        principal="principal:credential-owner",
        token=_conformance_token("revocable"),
        credential_id="credential:revocable",
    )
    runtime.identity.authenticate_bearer(f"Bearer {_conformance_token('revocable')}")
    runtime.identity.revoke_credential("credential:revocable", reason="conformance")
    try:
        runtime.identity.authenticate_bearer(f"Bearer {_conformance_token('revocable')}")
    except PermissionError:
        return
    raise AssertionError("revoked Runtime credential remained usable")


def _attested_domain_effect_fixture(
    *,
    key: str,
) -> tuple[WorldRuntime, Any, CapabilityRequest]:
    runtime = WorldRuntime.sqlite()
    token_name = f"domain-effect-{key}"
    runtime.identity.bind_bearer_token(
        principal="service:conformance",
        token=_conformance_token(token_name),
        credential_id=f"credential:{key}",
    )
    context = runtime.identity.authenticate_bearer(
        f"Bearer {_conformance_token(token_name)}"
    )
    runtime.responsibility.create(
        Responsibility(
            id=f"responsibility:{key}",
            principal="service:conformance",
            subject="domain effect conformance",
        ),
        domain="conformance",
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
            subject="resource:1",
            decided_by="service:conformance",
            selected={
                "target_ref": "resource:1",
                "operation": "authorize-effect",
                "action": "conformance.domain-effect",
            },
            basis_refs=(SemanticRef(SemanticKind.EVIDENCE, f"evidence:{key}"),),
        ),
        context=context,
    )
    runtime.governance.register_mandate_attested(
        Mandate(
            id=f"mandate:{key}",
            principal="service:conformance",
            scope={"resource": "resource:1"},
            authority_ceiling={
                "action": "conformance.domain-effect",
                "resource": "resource:1",
            },
        ),
        context=context,
    )
    runtime.governance.issue_authorization_attested(
        context=context,
        authorization_id=f"authorization:{key}",
        principal="service:conformance",
        action="conformance.domain-effect",
        resource="resource:1",
        mandate_id=f"mandate:{key}",
        decision_id=f"decision:{key}",
    )
    request = CapabilityRequest(
        id=f"request:{key}",
        capability="conformance.domain-effect",
        work_id=work.id,
        effect_class="external-effect",
        principal="service:conformance",
        actor_ref="service:conformance",
        resource="resource:1",
        resource_ref="resource:1",
        authorization_id=f"authorization:{key}",
        idempotency_key=f"effect:{key}",
        parameters={"mode": "apply"},
    )
    return runtime, context, request


def _stable_work_identity() -> None:
    runtime = WorldRuntime.sqlite()
    _responsibility(runtime, "responsibility:stable-work")
    first = runtime.execution.admit_work(
        responsibility_id="responsibility:stable-work",
        kind="effect",
        payload={"mode": "same"},
        work_id="work:stable",
    )
    replay = runtime.execution.admit_work(
        responsibility_id="responsibility:stable-work",
        kind="effect",
        payload={"mode": "same"},
        work_id="work:stable",
    )
    if replay.id != first.id:
        raise AssertionError("stable Work identity did not replay")
    try:
        runtime.execution.admit_work(
            responsibility_id="responsibility:stable-work",
            kind="effect",
            payload={"mode": "different"},
            work_id="work:stable",
        )
    except ValueError:
        return
    raise AssertionError("stable Work identity rebound was accepted")


def _domain_effect_prepare_requires_start() -> None:
    runtime, context, request = _attested_domain_effect_fixture(key="prepare-start")
    prepared = runtime.effect_boundary.prepare(
        request,
        provider_id="provider:domain",
        provider_version="1",
        context=context,
    )
    if prepared["status"] != "authorized":
        raise AssertionError("fresh domain effect was not authorized")
    if prepared["dispatch_allowed"] is not False or prepared["start_allowed"] is not True:
        raise AssertionError("prepare granted provider dispatch before start")
    if runtime.ledger.project_get(
        "execution.domain-effect-idempotency",
        request.idempotency_key,
    ) is not None:
        raise AssertionError("prepare fabricated a provider result")


def _domain_effect_start_single_use() -> None:
    runtime, context, request = _attested_domain_effect_fixture(key="single-start")
    runtime.effect_boundary.prepare(
        request,
        provider_id="provider:domain",
        provider_version="1",
        context=context,
    )
    started = runtime.effect_boundary.start(request.idempotency_key or "", context=context)
    if started["dispatch_allowed"] is not True or started["dispatch_generation"] != 1:
        raise AssertionError("first start did not grant one dispatch")
    try:
        runtime.effect_boundary.start(request.idempotency_key or "", context=context)
    except PermissionError:
        replay = runtime.effect_boundary.get(request.idempotency_key or "")
        if replay["dispatch_allowed"] is not False:
            raise AssertionError("replayed domain effect regranted dispatch")
        return
    raise AssertionError("domain effect start was reusable")


def _domain_effect_ambiguous_replay() -> None:
    runtime, context, request = _attested_domain_effect_fixture(key="ambiguous-domain")
    runtime.effect_boundary.prepare(
        request,
        provider_id="provider:domain",
        provider_version="1",
        context=context,
    )
    started = runtime.effect_boundary.start(request.idempotency_key or "", context=context)
    runtime.effect_boundary.record_result(
        request.idempotency_key or "",
        CapabilityResult(status="unknown", error={"code": "ack-lost"}),
        dispatch_generation=int(started["dispatch_generation"]),
        context=context,
    )
    replay = runtime.effect_boundary.prepare(
        request,
        provider_id="provider:domain",
        provider_version="1",
        context=context,
    )
    if replay["status"] != "ambiguous" or replay["dispatch_allowed"] is not False:
        raise AssertionError("ambiguous domain effect permitted redispatch")
    resolved = runtime.effect_boundary.record_result(
        request.idempotency_key or "",
        CapabilityResult(
            status="succeeded",
            reconciled=True,
            external_operation_ref="external:1",
        ),
        dispatch_generation=int(started["dispatch_generation"]),
        context=context,
    )
    if resolved.status != "succeeded" or not resolved.reconciled:
        raise AssertionError("ambiguous domain effect did not reconcile")


def _domain_effect_result_identity() -> None:
    runtime, context, request = _attested_domain_effect_fixture(key="result-binding")
    runtime.effect_boundary.prepare(
        request,
        provider_id="provider:domain",
        provider_version="1",
        context=context,
    )
    started = runtime.effect_boundary.start(request.idempotency_key or "", context=context)
    try:
        runtime.effect_boundary.record_result(
            request.idempotency_key or "",
            CapabilityResult(
                request_id="request:other",
                provider_id="provider:domain",
                status="succeeded",
            ),
            dispatch_generation=int(started["dispatch_generation"]),
            context=context,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("domain effect request identity rebound was accepted")
    try:
        runtime.effect_boundary.record_result(
            request.idempotency_key or "",
            CapabilityResult(
                request_id=request.id,
                provider_id="provider:other",
                status="succeeded",
            ),
            dispatch_generation=int(started["dispatch_generation"]),
            context=context,
        )
    except ValueError:
        return
    raise AssertionError("domain effect provider identity rebound was accepted")


def _domain_effect_start_revalidates_authority() -> None:
    runtime, context, request = _attested_domain_effect_fixture(key="authority-revalidation")
    prepared = runtime.effect_boundary.prepare(
        request,
        provider_id="provider:domain",
        provider_version="1",
        context=context,
    )
    if prepared["status"] != "authorized":
        raise AssertionError("domain effect did not reach prepared state")
    runtime.governance.revoke_mandate(
        "mandate:authority-revalidation",
        reason="conformance",
    )
    try:
        runtime.effect_boundary.start(request.idempotency_key or "", context=context)
    except PermissionError:
        attempt = runtime.effect_boundary.get(request.idempotency_key or "")
        if attempt["status"] != "authorized" or attempt["dispatch_allowed"] is not False:
            raise AssertionError("failed start mutated dispatch state")
        authorization = runtime.ledger.project_get(
            "governance.authorization",
            "authorization:authority-revalidation",
        )
        if authorization is None or int(authorization[0].get("uses", 0)) != 0:
            raise AssertionError("failed start consumed Authorization")
        return
    raise AssertionError("revoked Mandate still granted Domain provider dispatch")


def _projection_cas_cross_connection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "conformance-cas.db"
        first = SQLiteLedger(path)
        second = SQLiteLedger(path)
        try:
            first.project_put("conformance.cas", "item", {"winner": None}, expected_version=0)
            barrier = threading.Barrier(2)

            def update(ledger: SQLiteLedger, winner: str) -> str:
                barrier.wait()
                try:
                    ledger.project_put(
                        "conformance.cas",
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
            if results.count("conflict") != 1:
                raise AssertionError("projection CAS did not produce exactly one loser")
            current = first.project_get("conformance.cas", "item")
            if current is None or current[1] != 2:
                raise AssertionError("projection CAS final version is invalid")
        finally:
            first.close()
            second.close()


def _run_lease_cross_runtime() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "conformance-lease.db"
        first = WorldRuntime.sqlite(path, runtime_id="conformance-node:a")
        second = WorldRuntime.sqlite(path, runtime_id="conformance-node:b")
        try:
            first.responsibility.create(
                Responsibility(
                    id="responsibility:cross-runtime-lease",
                    principal="service:conformance",
                    subject="cross runtime lease",
                ),
                domain="conformance",
            )
            work = first.execution.admit_work(
                responsibility_id="responsibility:cross-runtime-lease",
                kind="conformance",
                payload={},
                work_id="work:cross-runtime-lease",
            )
            run = first.start_run(work.id, workflow_id="conformance")
            barrier = threading.Barrier(2)

            def acquire(runtime: WorldRuntime, owner: str) -> object:
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
            winners = [item for item in results if not isinstance(item, Exception)]
            losers = [item for item in results if isinstance(item, Exception)]
            if len(winners) != 1 or len(losers) != 1:
                raise AssertionError("cross-runtime Run lease did not have one winner")
            current = first.execution.get_run(run.id)
            if current is None or current.lease_generation != 1:
                raise AssertionError("cross-runtime Run lease generation is invalid")
        finally:
            first.ledger.close()
            second.ledger.close()


def _shared_sqlite_effect_fixture(
    path: Path,
    *,
    key: str,
) -> tuple[WorldRuntime, WorldRuntime, Any, Any, CapabilityRequest]:
    first = WorldRuntime.sqlite(path, runtime_id=f"{key}:a")
    second = WorldRuntime.sqlite(path, runtime_id=f"{key}:b")
    principal = f"service:{key}"
    token = _conformance_token(f"shared-{key}")
    first.identity.bind_bearer_token(
        principal=principal,
        token=token,
        credential_id=f"credential:{key}",
    )
    first_context = first.identity.authenticate_bearer(f"Bearer {token}")
    second_context = second.identity.authenticate_bearer(f"Bearer {token}")
    first.responsibility.create(
        Responsibility(
            id=f"responsibility:{key}",
            principal=principal,
            subject=key,
        ),
        domain="conformance",
    )
    work = first.execution.admit_work(
        responsibility_id=f"responsibility:{key}",
        kind="effect",
        payload={"key": key},
        work_id=f"work:{key}",
    )
    first.decisions.record_attested(
        Decision(
            id=f"decision:{key}",
            subject=f"resource:{key}",
            decided_by=principal,
            selected={
                "target_ref": f"resource:{key}",
                "operation": "authorize-effect",
                "action": "conformance.effect",
            },
            basis_refs=(SemanticRef(SemanticKind.EVIDENCE, f"evidence:{key}"),),
        ),
        context=first_context,
    )
    first.governance.register_mandate_attested(
        Mandate(
            id=f"mandate:{key}",
            principal=principal,
            scope={"resource": f"resource:{key}"},
            authority_ceiling={
                "action": "conformance.effect",
                "resource": f"resource:{key}",
            },
        ),
        context=first_context,
    )
    first.governance.issue_authorization_attested(
        context=first_context,
        authorization_id=f"authorization:{key}",
        principal=principal,
        action="conformance.effect",
        resource=f"resource:{key}",
        mandate_id=f"mandate:{key}",
        decision_id=f"decision:{key}",
    )
    request = CapabilityRequest(
        id=f"request:{key}",
        capability="conformance.effect",
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
    return first, second, first_context, second_context, request


def _domain_effect_start_cross_runtime() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "conformance-domain-start.db"
        first, second, first_context, second_context, request = (
            _shared_sqlite_effect_fixture(path, key="cross-runtime-domain")
        )
        try:
            first.effect_boundary.prepare(
                request,
                provider_id="provider:domain",
                provider_version="1",
                context=first_context,
            )
            barrier = threading.Barrier(2)

            def start(runtime: WorldRuntime, context: Any) -> object:
                barrier.wait()
                try:
                    return runtime.effect_boundary.start(
                        request.idempotency_key or "",
                        context=context,
                    )
                except PermissionError as exc:
                    return exc

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda args: start(*args),
                        [(first, first_context), (second, second_context)],
                    )
                )
            grants = [
                item
                for item in results
                if isinstance(item, dict) and item.get("dispatch_allowed") is True
            ]
            if len(grants) != 1:
                raise AssertionError("cross-runtime Domain effect granted multiple dispatches")
            authorization = first.ledger.project_get(
                "governance.authorization",
                "authorization:cross-runtime-domain",
            )
            if authorization is None or int(authorization[0].get("uses", 0)) != 1:
                raise AssertionError("cross-runtime Domain start consumed authority incorrectly")
        finally:
            first.ledger.close()
            second.ledger.close()


class _SharedDispatchProvider(_RecoverableProvider):
    def __init__(self, state: dict[str, Any]) -> None:
        super().__init__()
        self.state = state

    async def invoke(
        self,
        request: CapabilityRequest,
        context: InvocationContext,
    ) -> CapabilityResult:
        del context
        self.state["invoke_calls"] = int(self.state.get("invoke_calls", 0)) + 1
        await asyncio.sleep(0.05)
        self.state["completed"] = True
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
        )

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        if not self.state.get("completed"):
            return None
        return CapabilityResult(
            request_id=request_id,
            provider_id=self.descriptor.id,
            status="succeeded",
            reconciled=True,
        )


async def _provider_attempt_cross_runtime() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "conformance-provider-attempt.db"
        first, second, _first_context, _second_context, request = (
            _shared_sqlite_effect_fixture(path, key="cross-runtime-provider")
        )
        state: dict[str, Any] = {"invoke_calls": 0, "completed": False}
        first.registry.register(_SharedDispatchProvider(state))
        second.registry.register(_SharedDispatchProvider(state))
        try:
            results = await asyncio.gather(
                first.invoke(request),
                second.invoke(request),
                return_exceptions=True,
            )
            if int(state["invoke_calls"]) != 1:
                raise AssertionError("cross-runtime provider dispatched more than once")
            if not any(
                isinstance(item, CapabilityResult) and item.status == "succeeded"
                for item in results
            ):
                raise AssertionError("cross-runtime provider had no successful owner")
            attempt = first.ledger.project_get(
                "execution.provider-attempt",
                request.idempotency_key or "",
            )
            if attempt is None or attempt[0].get("status") != "committed":
                raise AssertionError("provider reservation did not reach committed state")
        finally:
            first.ledger.close()
            second.ledger.close()


def _institutional_revision(
    identifier: str,
    *,
    target: SemanticRef,
    previous: SemanticRef,
) -> Revision:
    return Revision(
        id=identifier,
        target_ref=target,
        supersedes_ref=previous,
        reason="conformance successor",
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, f"evidence:{identifier}"),),
    )


def _institutional_lineage_rejects_branch() -> None:
    runtime = WorldRuntime.sqlite()
    root = SemanticRef(SemanticKind.DECISION, "decision:lineage-root")
    current = SemanticRef(SemanticKind.DECISION, "decision:lineage-current")
    branch = SemanticRef(SemanticKind.DECISION, "decision:lineage-branch")
    runtime.lineage.record(
        _institutional_revision(
            "revision:lineage-current",
            target=current,
            previous=root,
        )
    )
    try:
        runtime.lineage.record(
            _institutional_revision(
                "revision:lineage-branch",
                target=branch,
                previous=root,
            )
        )
    except ValueError:
        if runtime.lineage.resolve_current(root) != current:
            raise AssertionError("lineage branch rejection changed current head")
        return
    raise AssertionError("historical lineage root admitted a second branch")


def _superseded_decision_not_current() -> None:
    runtime = WorldRuntime.sqlite()
    old = Decision(
        id="decision:institutional-old",
        subject="resource:institutional",
        decided_by="owner",
        selected={
            "target_ref": "resource:institutional",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:decision-old"),
        ),
    )
    new = Decision(
        id="decision:institutional-new",
        subject="resource:institutional",
        decided_by="owner",
        selected={
            "target_ref": "resource:institutional",
            "operation": "authorize-effect",
            "action": "deploy",
            "policy_version": "2",
        },
        basis_refs=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:decision-new"),
        ),
    )
    runtime.decisions.record(old)
    runtime.decisions.supersede(
        old.id,
        new,
        _institutional_revision(
            "revision:decision-current",
            target=new.ref,
            previous=old.ref,
        ),
    )
    if runtime.decisions.get(old.id)["id"] != old.id:
        raise AssertionError("historical Decision was not preserved")
    if runtime.decisions.get_current(old.id)["id"] != new.id:
        raise AssertionError("Decision lineage did not resolve successor")
    try:
        runtime.decisions.assert_current(old.id)
    except ValueError:
        return
    raise AssertionError("superseded Decision remained currently applicable")


def _ontology_version_requires_revision() -> None:
    runtime = WorldRuntime.sqlite()
    first = SemanticTypeDefinition(
        name="conformance-type",
        owner="domain:conformance",
        version="1",
        description="first",
    )
    second = SemanticTypeDefinition(
        name="conformance-type",
        owner="domain:conformance",
        version="2",
        description="second",
    )
    runtime.ontology.register(first)
    try:
        runtime.ontology.register(second)
    except ValueError:
        pass
    else:
        raise AssertionError("ontology version changed without explicit Revision")

    runtime.ontology.supersede(
        second,
        _institutional_revision(
            "revision:ontology-version",
            target=runtime.ontology.definition_ref(second),
            previous=runtime.ontology.definition_ref(first),
        ),
    )
    if runtime.ontology.resolve("conformance-type") != second:
        raise AssertionError("ontology current version did not advance")
    if runtime.ontology.resolve_version("conformance-type", "1") != first:
        raise AssertionError("ontology historical version was lost")


def _experience_current_applicability() -> None:
    runtime = WorldRuntime.sqlite()
    old = runtime.memory.propose(
        scope={"service": "conformance"},
        lesson={"mode": "old"},
        basis_refs=("evidence:experience-old",),
    )
    runtime.memory.qualify(old.id, assessment_refs=("assessment:old",))
    runtime.memory.invalidate(
        old.id,
        reason="environment changed",
        basis_refs=("evidence:experience-invalidated",),
    )
    if runtime.memory.is_applicable(old.id):
        raise AssertionError("invalidated Experience remained applicable")
    runtime.memory.reopen(
        old.id,
        reason="new evaluation",
        basis_refs=("evidence:experience-reopen",),
    )
    runtime.memory.qualify(old.id, assessment_refs=("assessment:old-requalified",))

    successor = runtime.memory.propose(
        scope={"service": "conformance"},
        lesson={"mode": "new"},
        basis_refs=("evidence:experience-new",),
    )
    runtime.memory.qualify(successor.id, assessment_refs=("assessment:new",))
    runtime.memory.supersede(
        old.id,
        successor.id,
        _institutional_revision(
            "revision:experience",
            target=runtime.memory.experience_ref(successor.id),
            previous=runtime.memory.experience_ref(old.id),
        ),
    )
    if runtime.memory.is_applicable(old.id):
        raise AssertionError("superseded Experience remained applicable")
    if not runtime.memory.is_applicable(successor.id):
        raise AssertionError("qualified current Experience is not applicable")


def _superseded_mandate_not_current() -> None:
    runtime = WorldRuntime.sqlite()
    old = Mandate(
        id="mandate:institutional-old",
        principal="owner",
        scope={"resource": "resource:institutional"},
        authority_ceiling={
            "action": "deploy",
            "resource": "resource:institutional",
        },
    )
    runtime.governance.register_mandate(old)
    decision = Decision(
        id="decision:institutional-authorize",
        subject="resource:institutional",
        decided_by="owner",
        selected={
            "target_ref": "resource:institutional",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:institutional-authorize"),
        ),
    )
    runtime.decisions.record(decision)
    authorization = runtime.governance.issue_authorization(
        authorization_id="authorization:institutional-old",
        principal="owner",
        action="deploy",
        resource="resource:institutional",
        mandate_id=old.id,
        decision_id=decision.id,
    )
    successor = Mandate(
        id="mandate:institutional-new",
        principal="owner",
        scope={"resource": "resource:institutional"},
        authority_ceiling={
            "actions": ["deploy", "rollback"],
            "resource": "resource:institutional",
        },
    )
    runtime.governance.supersede_mandate(
        old.id,
        successor,
        _institutional_revision(
            "revision:mandate-current",
            target=successor.ref,
            previous=old.ref,
        ),
    )
    historical = runtime.ledger.project_get(
        "governance.authorization",
        authorization.id,
    )
    if historical is None or historical[0].get("mandate_id") != old.id:
        raise AssertionError("historical Authorization was not preserved")
    try:
        runtime.governance.assert_usable(
            authorization.id,
            principal="owner",
            action="deploy",
            resource="resource:institutional",
        )
    except PermissionError:
        return
    raise AssertionError("Authorization through superseded Mandate remained current")


def _goal_successor_gate() -> None:
    runtime = WorldRuntime.sqlite()
    mandate = Mandate(id="mandate:goal-lineage", principal="owner")
    runtime.governance.register_mandate(mandate)
    old = Goal(
        id="goal:institutional-old",
        subject="service",
        desired_state={"state": "old"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-old"),),
    )
    admit_old = Decision(
        id="decision:goal-old-admit",
        subject="service",
        decided_by="owner",
        selected={"target_ref": old.id, "operation": "admit-goal"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-old-admit"),),
    )
    runtime.decisions.record(admit_old)
    runtime.strategy.register_goal(
        old,
        mandate_id=mandate.id,
        decision_id=admit_old.id,
    )
    successor = Goal(
        id="goal:institutional-new",
        subject="service",
        desired_state={"state": "new"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-new"),),
    )
    admit_new = Decision(
        id="decision:goal-new-admit",
        subject="service",
        decided_by="owner",
        selected={
            "target_ref": successor.id,
            "operation": "admit-goal",
            "supersedes_goal_id": old.id,
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-new-admit"),),
    )
    runtime.decisions.record(admit_new)
    revision = _institutional_revision(
        "revision:goal-successor",
        target=successor.ref,
        previous=old.ref,
    )
    try:
        runtime.strategy.supersede_goal(
            old.id,
            successor,
            revision,
            mandate_id=mandate.id,
            decision_id=admit_new.id,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("active Goal was superseded before revision-required state")

    assessment = runtime.strategy.assess_goal(
        old.id,
        disposition="revise",
        basis_refs=("evidence:goal-revise",),
    )
    require_revision = Decision(
        id="decision:goal-revision-required",
        subject="service",
        decided_by="owner",
        selected={
            "target_ref": old.id,
            "operation": "transition-goal",
            "to_status": "revision-required",
            "assessment_id": assessment.id,
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-revise"),),
    )
    runtime.decisions.record(require_revision)
    runtime.strategy.transition_goal(
        old.id,
        to_status="revision-required",
        assessment_id=assessment.id,
        decision_id=require_revision.id,
        basis_refs=("evidence:goal-revise",),
    )
    runtime.strategy.supersede_goal(
        old.id,
        successor,
        revision,
        mandate_id=mandate.id,
        decision_id=admit_new.id,
    )
    if runtime.strategy.get_current_goal(old.id)["id"] != successor.id:
        raise AssertionError("Goal successor did not become current")
    if runtime.strategy.get_goal(old.id)["status"] != "retired":
        raise AssertionError("superseded Goal did not become historical/retired")


def _revoked_decision_not_current() -> None:
    runtime = WorldRuntime.sqlite()
    decision = Decision(
        id="decision:revoked-current",
        subject="resource:revoked",
        decided_by="owner",
        selected={
            "target_ref": "resource:revoked",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:decision-revocable"),
        ),
    )
    runtime.decisions.record(decision)
    runtime.decisions.revoke(
        decision.id,
        reason="institutional policy withdrawn",
        basis_refs=("evidence:decision-revoked",),
    )
    if runtime.decisions.get(decision.id)["id"] != decision.id:
        raise AssertionError("revoked Decision history was lost")
    try:
        runtime.decisions.assert_current(decision.id)
    except ValueError:
        events = runtime.ledger.events(stream=f"decision:{decision.id}")
        if not events or events[-1].kind != "decision.revoked":
            raise AssertionError("Decision revocation history was not durable")
        return
    raise AssertionError("revoked Decision remained currently applicable")


def _revoked_authorization_not_usable() -> None:
    runtime = WorldRuntime.sqlite()
    mandate = Mandate(
        id="mandate:authorization-revocation",
        principal="owner",
        scope={"resource": "resource:authorization-revocation"},
        authority_ceiling={
            "action": "deploy",
            "resource": "resource:authorization-revocation",
        },
    )
    runtime.governance.register_mandate(mandate)
    decision = Decision(
        id="decision:authorization-revocation",
        subject="resource:authorization-revocation",
        decided_by="owner",
        selected={
            "target_ref": "resource:authorization-revocation",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:authorization-revocation"),
        ),
    )
    runtime.decisions.record(decision)
    authorization = runtime.governance.issue_authorization(
        authorization_id="authorization:revocation",
        principal="owner",
        action="deploy",
        resource="resource:authorization-revocation",
        mandate_id=mandate.id,
        decision_id=decision.id,
    )
    runtime.governance.record_use(
        authorization.id,
        effect_request_id="request:before-revocation",
    )
    runtime.governance.revoke_authorization(
        authorization.id,
        reason="delegated authority ended",
        basis_refs=("evidence:authorization-ended",),
    )
    stored = runtime.ledger.project_get(
        "governance.authorization",
        authorization.id,
    )
    if stored is None or stored[0].get("uses") != 1:
        raise AssertionError("Authorization history was not preserved")
    try:
        runtime.governance.assert_usable(
            authorization.id,
            principal="owner",
            action="deploy",
            resource="resource:authorization-revocation",
        )
    except PermissionError:
        try:
            runtime.governance.record_use(
                authorization.id,
                effect_request_id="request:after-revocation",
            )
        except PermissionError:
            return
        raise AssertionError("revoked Authorization accepted a later use record")
    raise AssertionError("revoked Authorization remained usable")


def _strategy_reassessment_requires_lineage() -> None:
    runtime = WorldRuntime.sqlite()
    mandate = Mandate(id="mandate:strategy-reassessment", principal="owner")
    runtime.governance.register_mandate(mandate)
    goal = Goal(
        id="goal:strategy-reassessment",
        subject="service",
        desired_state={"state": "improve"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-assessment"),),
    )
    admit = Decision(
        id="decision:strategy-reassessment-admit",
        subject="service",
        decided_by="owner",
        selected={"target_ref": goal.id, "operation": "admit-goal"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-admit"),),
    )
    runtime.decisions.record(admit)
    runtime.strategy.register_goal(
        goal,
        mandate_id=mandate.id,
        decision_id=admit.id,
    )
    first = runtime.strategy.assess_goal(
        goal.id,
        disposition="continue",
        basis_refs=("evidence:assessment-first",),
    )
    try:
        runtime.strategy.assess_goal(
            goal.id,
            disposition="revise",
            basis_refs=("evidence:assessment-second",),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("StrategyAssessment silently overwrote current assessment")

    second = runtime.strategy.assess_goal(
        goal.id,
        disposition="revise",
        basis_refs=("evidence:assessment-second",),
        supersedes_assessment_id=first.id,
        revision_reason="new evidence changes strategic disposition",
        revision_basis_refs=("evidence:assessment-second",),
    )
    if runtime.strategy.get_assessment(first.id).id != first.id:
        raise AssertionError("historical StrategyAssessment was lost")
    if runtime.strategy.get_current_assessment(first.id).id != second.id:
        raise AssertionError("StrategyAssessment lineage did not advance current head")
    if runtime.strategy.latest_assessment(goal.id).id != second.id:
        raise AssertionError("Goal latest StrategyAssessment did not advance")


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
            ),
            domain=domain,
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
            ),
            domain=domain,
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
        ),
        domain="finance",
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
    runtime.qualification.register_dependency(
        dependency_id="qualification-dependency:conformance",
        principal="service:conformance",
        subject_ref=decision.id,
        dependency_ref="policy:pricing",
        dependency_version="v1",
        assumption="pricing policy remains applicable",
        basis_refs=("evidence:policy-v1",),
    )
    obligations = runtime.qualification.observe_dependency_change(
        principal="service:conformance",
        dependency_ref="policy:pricing",
        observed_version="v2",
        basis_refs=("evidence:policy-v2",),
    )
    if len(obligations) != 1:
        raise AssertionError("dependency change did not create targeted review")
    runtime.decisions.assert_current(decision.id)
    if runtime.qualification.get_dependency(
        "qualification-dependency:conformance"
    ).status != "active":
        raise AssertionError("dependency change silently invalidated current basis")


def _qualification_action_remains_pending() -> None:
    runtime = WorldRuntime.sqlite()
    runtime.qualification.register_dependency(
        dependency_id="qualification-dependency:pending",
        principal="service:conformance",
        subject_ref="mandate:pending",
        dependency_ref="authority-source:owner",
        dependency_version="epoch-1",
        assumption="authority source remains current",
        review_policy={"on_change": "reauthorize"},
        basis_refs=("evidence:epoch-1",),
    )
    obligation = runtime.qualification.observe_dependency_change(
        principal="service:conformance",
        dependency_ref="authority-source:owner",
        observed_version="epoch-2",
        basis_refs=("evidence:epoch-2",),
    )[0]
    runtime.qualification.assess_review(
        obligation.id,
        disposition="reauthorize",
        basis_refs=("evidence:assessment",),
    )
    pending = runtime.qualification.pending_obligations(
        principal="service:conformance"
    )
    if len(pending) != 1 or pending[0].status != "assessed":
        raise AssertionError("action-requiring review disappeared before owning resolution")
    runtime.qualification.resolve_review(
        obligation.id,
        resolution_ref="mandate:replacement",
        basis_refs=("evidence:resolution",),
    )
    if runtime.qualification.pending_obligations(principal="service:conformance"):
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
        ),
        domain="conformance",
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
        ),
        domain="conformance",
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
        ),
        domain="conformance",
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