from __future__ import annotations

from semantic_language import SemanticKind
from semantic_language import SemanticRef
from .decisions import Decision
from .governance import Mandate
from .identity import DelegationGrant
from .runtime import WorldRuntime
from .conformance_support import _RecoverableProvider, _conformance_token, _responsibility, _decision

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

CHECKS = {
    "responsibility-terminal-assessment-requires-basis": _terminal_basis,
    "responsibility-discharge-requires-satisfied-and-decision": _discharge_gate,
    "authorization-requires-active-mandate-and-decision": _authorization_admission,
    "authorization-use-is-exact-scope": _authorization_scope,
    "decision-applicability-is-required": _decision_applicability,
    "identity-rebound-is-rejected": _identity_rebound,
    "expired-mandate-is-not-current": _expired_mandate,
    "expired-authorization-is-not-usable": _expired_authorization,
    "empty-authority-ceiling-delegates-no-effect": _empty_authority_ceiling,
    "authority-bearing-http-requires-authentication": _http_requires_authentication,
    "claimed-principal-cannot-override-authenticated-identity": _claimed_principal_mismatch,
    "revoked-delegation-cannot-act": _revoked_delegation,
    "unattested-decision-cannot-be-adopted": _unattested_decision_not_adopted,
    "unattested-authorization-cannot-execute-over-http": _unattested_authorization_not_http,
    "delegation-cannot-widen-authority": _delegation_cannot_widen,
    "revoked-credential-cannot-authenticate": _revoked_credential,
    "bounded-subdelegation-preserves-root-authority": _bounded_subdelegation,
}
