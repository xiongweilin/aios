from __future__ import annotations

import asyncio
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from pydantic import ValidationError
from semantic_language import SemanticKind
from semantic_language import SemanticRef
from .decisions import Decision
from .governance import Mandate
from .responsibility import Responsibility
from .execution import CapabilityRequest
from .execution import CapabilityResult
from .execution import InvocationContext
from .execution import effect_identity_fingerprint
from .execution import effect_identity_payload
from .execution import reconciliation_contract_for
from .ledger import ProjectionVersionConflict
from .ledger import SQLiteLedger
from .runtime import WorldRuntime
from .conformance_support import _RecoverableProvider, _conformance_token, _responsibility, _decision

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
            domain="conformance",
        )
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
                    domain="conformance",
                )
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
            domain="conformance",
        )
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

CHECKS = {
    "ambiguous-effect-never-blind-redispatches": _ambiguous_effect,
    "reconciliation-contract-drift-fails-closed": _reconciliation_drift,
    "discharged-responsibility-rejects-work": _discharged_rejects_work,
    "discharged-responsibility-rejects-effect": _discharged_rejects_effect,
    "effectful-invocation-requires-work": _effect_requires_work,
    "run-must-belong-to-work": _run_belongs_to_work,
    "authorization-required-context-is-enforced": _required_context,
    "effectful-invocation-requires-durable-identity": _effect_requires_identity,
    "effect-identity-rebound-is-rejected": _effect_identity_rebound,
    "capability-request-unknown-field-rejected": _capability_request_unknown_field,
    "effect-identity-cannot-rebind-through-extension-field": _extension_field_rebound,
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
}
