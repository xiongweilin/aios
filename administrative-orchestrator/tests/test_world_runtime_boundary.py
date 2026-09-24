from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from administrative_orchestrator.config import Settings
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AuthorityClass,
    CaseStatus,
    EffectRecord,
    EffectReversibility,
)
from administrative_orchestrator.effect_provider import (
    ObservationAvailability,
    ObservationFreshness,
    ObservationPresence,
    ProviderExecutionStatus,
    RealityObservation,
)
from administrative_orchestrator.integrations.world_runtime import (
    WorldRuntimeBoundaryError,
    WorldRuntimeBridge,
    WorldRuntimeEffectProvider,
    _effect_matches_current_execution,
    capability_for_effect,
)
from administrative_orchestrator.persistence import SqlStore

NOW = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)


def _runtime_catalog() -> dict:
    return {
        "runtime_protocol": WorldRuntimeBridge.REQUIRED_RUNTIME_PROTOCOL,
        "semantic_language": WorldRuntimeBridge.REQUIRED_SEMANTIC_LANGUAGE,
        "contracts": {
            name: {"current": current}
            for name, current in WorldRuntimeBridge.REQUIRED_CONTRACTS.items()
        },
    }


def _effect() -> EffectRecord:
    return EffectRecord(
        effect_id=uuid4(),
        case_id=uuid4(),
        case_version=3,
        authority_epoch=2,
        authorization_id=uuid4(),
        obligation_id=uuid4(),
        governance_basis_id=uuid4(),
        target_system="hris",
        operation="employee.create",
        subject_ref="employee:runtime-test",
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=AuthorityClass.EMPLOYMENT,
        created_at=NOW,
        updated_at=NOW,
    )


def test_planned_effect_remains_current_across_execution_lifecycle_transition() -> None:
    effect = _effect()
    executing = AdministrativeCase(
        case_id=effect.case_id,
        case_kind="employee-onboarding",
        requester_principal_id="person:requester",
        subject_ref=effect.subject_ref,
        status=CaseStatus.EXECUTING,
        version=effect.case_version + 1,
        authority_epoch=effect.authority_epoch,
        created_at=NOW,
        updated_at=NOW,
    )
    assert _effect_matches_current_execution(executing, effect) is True

    assert _effect_matches_current_execution(
        executing.model_copy(
            update={
                "status": CaseStatus.AUTHORIZED,
                "version": effect.case_version,
            }
        ),
        effect,
    ) is False
    assert _effect_matches_current_execution(
        executing.model_copy(update={"version": effect.case_version + 2}),
        effect,
    ) is False
    assert _effect_matches_current_execution(
        executing.model_copy(
            update={"authority_epoch": effect.authority_epoch + 1}
        ),
        effect,
    ) is False
    assert _effect_matches_current_execution(
        executing.model_copy(update={"case_id": uuid4()}),
        effect,
    ) is False


def test_runtime_context_rejects_effect_outside_current_execution_transition(
    monkeypatch,
) -> None:
    effect = _effect()
    stale_case = AdministrativeCase(
        case_id=effect.case_id,
        case_kind="employee-onboarding",
        requester_principal_id="person:requester",
        subject_ref=effect.subject_ref,
        status=CaseStatus.AUTHORIZED,
        version=effect.case_version,
        authority_epoch=effect.authority_epoch,
        created_at=NOW,
        updated_at=NOW,
    )
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    monkeypatch.setattr(store, "get_case", lambda case_id: stale_case)
    bridge = WorldRuntimeBridge(
        store,
        Settings(
            _env_file=None,
            world_runtime_mode="cutover",
            world_runtime_base_url="http://runtime.test",
        ),
    )
    try:
        with pytest.raises(
            WorldRuntimeBoundaryError,
            match="effect is stale against the current Administrative case",
        ):
            bridge._context(effect)
    finally:
        bridge.close()


def test_runtime_context_accepts_planned_effect_in_current_execution_state() -> None:
    effect = _effect()
    executing = AdministrativeCase(
        case_id=effect.case_id,
        case_kind="employee-onboarding",
        requester_principal_id="person:requester",
        subject_ref=effect.subject_ref,
        status=CaseStatus.EXECUTING,
        version=effect.case_version + 1,
        authority_epoch=effect.authority_epoch,
        created_at=NOW,
        updated_at=NOW,
    )
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    bridge = WorldRuntimeBridge(
        store,
        Settings(
            _env_file=None,
            world_runtime_mode="cutover",
            world_runtime_base_url="http://runtime.test",
        ),
    )
    bridge.store = SimpleNamespace(get_case=lambda case_id: executing)
    bridge.execution = SimpleNamespace(
        get_authorization=lambda authorization_id: SimpleNamespace(
            case_id=effect.case_id,
            authority_epoch=effect.authority_epoch,
            target_system=effect.target_system,
            allowed_operations=(effect.operation,),
            subject_ref=effect.subject_ref,
            revoked_at=None,
            issuer_principal_id="service:administrative-orchestrator",
        )
    )
    bridge.governance = SimpleNamespace(
        get_current_for_case=lambda case_id, authority_epoch: SimpleNamespace(
            basis_id=effect.governance_basis_id
        ),
        revalidate=lambda basis, case: SimpleNamespace(valid=True, reasons=()),
    )
    bridge.obligations = SimpleNamespace(
        get_current=lambda case_id, authority_epoch: SimpleNamespace(
            obligations=(
                SimpleNamespace(
                    obligation_id=effect.obligation_id,
                    target_system=effect.target_system,
                    required_operation=effect.operation,
                    subject_ref=effect.subject_ref,
                    governance_basis_id=effect.governance_basis_id,
                    expected_postcondition={"active": True},
                ),
            )
        )
    )

    context = bridge._context(effect)
    assert context == {
        "issuer_principal_id": "service:administrative-orchestrator",
        "expected_postcondition": {"active": True},
    }

    bridge.store = SimpleNamespace(
        get_case=lambda case_id: executing.model_copy(
            update={"version": effect.case_version + 2}
        )
    )
    try:
        bridge._context(effect)
    except WorldRuntimeBoundaryError as exc:
        assert "effect is stale" in str(exc)
    else:
        raise AssertionError("stale effect must fail closed")
    finally:
        bridge.close()


def test_bridge_compiles_governed_effect_to_runtime_contract(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/v1/contracts":
            return httpx.Response(200, json=_runtime_catalog())
        payload = __import__("json").loads(request.content or b"{}")
        calls.append((request.url.path, payload))
        if request.url.path == "/v1/domain-assignments":
            return httpx.Response(
                200,
                json={"id": payload.get("id"), "status": "offered"},
            )
        if request.url.path.startswith("/v1/domain-assignments/") and request.url.path.endswith("/reports"):
            return httpx.Response(
                200,
                json={
                    "id": payload.get("id"),
                    "kind": payload.get("kind"),
                    "assignment_status": "active",
                },
            )
        responses = {
            "/v1/responsibilities": {"id": payload.get("id", "resp"), "status": "active"},
            "/v1/work": {"id": "work:test", "status": "admitted"},
            "/v1/runs": {"id": "run:test", "status": "running"},
            "/v1/decisions": {"id": payload.get("id", "decision:test")},
            "/v1/mandates": {"id": payload.get("id", "mandate:test"), "status": "active"},
            "/v1/authorizations": {"id": payload.get("id", "authorization:test")},
            "/v1/invoke": {
                "request_id": payload.get("id"),
                "provider_id": "provider:test",
                "status": "succeeded",
                "external_operation_ref": "external:test",
            },
        }
        return httpx.Response(200, json=responses[request.url.path])

    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    bridge = WorldRuntimeBridge(
        store,
        Settings(
            _env_file=None,
            world_runtime_mode="cutover",
            world_runtime_base_url="http://runtime.test",
        ),
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(
        bridge,
        "_context",
        lambda effect: {
            "issuer_principal_id": "service:administrative",
            "expected_postcondition": {"active": True},
        },
    )
    effect = _effect()
    result = bridge.execute_effect(effect, {"employee_ref": effect.subject_ref})

    assert result.status is ProviderExecutionStatus.SUCCEEDED
    assert result.provider_ref == "external:test"
    decision = next(payload for path, payload in calls if path == "/v1/decisions")
    authorization = next(payload for path, payload in calls if path == "/v1/authorizations")
    invoke = next(payload for path, payload in calls if path == "/v1/invoke")
    assert decision["selected"]["target_ref"].startswith("administrative:hris:")
    assert decision["selected"]["operation"] == "authorize-effect"
    assert decision["selected"]["action"] == "administrative.hris.employee.create.v1"
    assert "conditions" not in authorization or authorization["conditions"] == {}
    assert authorization["annotations"]["administrative_authorization_id"] == str(effect.authorization_id)
    assert invoke["capability"] == "administrative.hris.employee.create.v1"
    assert invoke["idempotency_key"] == f"administrative-effect:{effect.effect_id}"
    assert invoke["authorization_id"].startswith("authorization_admin_")
    assert capability_for_effect(effect) == invoke["capability"]
    paths = [path for path, _ in calls]
    assert paths[0] == "/v1/responsibilities"
    assert paths[1] == "/v1/domain-assignments"
    assert paths[2].startswith("/v1/domain-assignments/")
    assert paths[2].endswith("/reports")
    assert paths[3:] == [
        "/v1/work",
        "/v1/runs",
        "/v1/decisions",
        "/v1/mandates",
        "/v1/authorizations",
        "/v1/invoke",
    ]
    bridge.close()


def test_runtime_execute_does_not_replace_domain_readback(monkeypatch):
    effect = _effect()
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    bridge = WorldRuntimeBridge(
        store,
        Settings(
            _env_file=None,
            world_runtime_mode="cutover",
            world_runtime_base_url="http://runtime.test",
        ),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                500,
                request=request,
                json={"detail": "not used by observe"},
            )
        ),
    )

    class Fallback:
        def execute(self, effect, payload):
            del effect, payload
            raise AssertionError("cutover execution must not use fallback")

        def observe(self, effect):
            return RealityObservation(
                availability=ObservationAvailability.AVAILABLE,
                presence=ObservationPresence.PRESENT,
                freshness=ObservationFreshness.CURRENT,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                provider_ref="domain-readback:test",
                state={"active": True},
                observed_at=NOW,
            )

    provider = WorldRuntimeEffectProvider(Fallback(), bridge)
    observation = provider.observe(effect)
    assert observation.provider_ref == "domain-readback:test"
    assert observation.state == {"active": True}
    bridge.close()


def test_provision_responsibility_creates_and_accepts_domain_assignment() -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/v1/contracts":
            return httpx.Response(200, json=_runtime_catalog())
        payload = __import__("json").loads(request.content or b"{}")
        calls.append((request.url.path, payload))
        if request.url.path == "/v1/responsibilities":
            return httpx.Response(200, json={"id": payload["id"], "status": "active"})
        if request.url.path == "/v1/domain-assignments":
            return httpx.Response(200, json={"id": payload["id"], "status": "offered"})
        if request.url.path.endswith("/reports"):
            return httpx.Response(
                200,
                json={
                    "id": payload["id"],
                    "kind": payload["kind"],
                    "assignment_status": "active",
                },
            )
        return httpx.Response(404)

    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    bridge = WorldRuntimeBridge(
        store,
        Settings(
            _env_file=None,
            world_runtime_mode="cutover",
            world_runtime_base_url="http://runtime.test",
        ),
        transport=httpx.MockTransport(handler),
    )
    bridge.provision_responsibility(
        responsibility_ref="responsibility:admin:1",
        principal="service:administrative",
        subject="employee:onboard:1",
        scope={"case_id": "case:1"},
    )

    paths = [path for path, _ in calls]
    assert paths == [
        "/v1/responsibilities",
        "/v1/domain-assignments",
        "/v1/domain-assignments/administrative-assignment:responsibility:admin:1/reports",
    ]
    assert calls[-1][1]["kind"] == "accepted"
    bridge.close()


def test_discharge_backfills_offered_assignment_before_completion() -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/v1/contracts":
            return httpx.Response(200, json=_runtime_catalog())
        payload = __import__("json").loads(request.content or b"{}")
        calls.append((request.url.path, payload))
        path = request.url.path
        if request.method == "GET" and path.startswith("/v1/domain-assignments/"):
            return httpx.Response(404, json={"detail": "domain assignment not found"})
        if path == "/v1/domain-assignments":
            return httpx.Response(
                200,
                json={
                    "id": payload["id"],
                    "responsibility_ref": payload["responsibility_ref"],
                    "domain": payload["domain"],
                    "controller": payload["controller"],
                    "status": "offered",
                },
            )
        if path.endswith("/reports"):
            return httpx.Response(
                200,
                json={
                    "id": payload["id"],
                    "kind": payload["kind"],
                    "assignment_status": (
                        "completion-proposed"
                        if payload["kind"] == "completion-proposal"
                        else "active"
                    ),
                },
            )
        if path.endswith("/assess"):
            return httpx.Response(
                200,
                json={"status": "satisfied", "assessment_ref": "assessment:admin:1"},
            )
        if path == "/v1/decisions":
            return httpx.Response(200, json={"id": payload["id"]})
        if path.endswith("/discharge"):
            return httpx.Response(
                200,
                json={"status": "discharged", "transition_ref": "transition:admin:1"},
            )
        return httpx.Response(404)

    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    bridge = WorldRuntimeBridge(
        store,
        Settings(
            _env_file=None,
            world_runtime_mode="cutover",
            world_runtime_base_url="http://runtime.test",
        ),
        transport=httpx.MockTransport(handler),
    )

    result = bridge.discharge_responsibility(
        "responsibility:admin:2",
        decision_ref="decision:admin:2",
        decided_by="service:administrative",
        subject_ref="employee:2",
        basis_refs=("evidence:verified:2",),
    )

    assert result == (
        "assessment:admin:1",
        "decision:admin:2",
        "transition:admin:1",
    )
    reports = [
        payload
        for path, payload in calls
        if path.endswith("/reports")
    ]
    assert [payload["kind"] for payload in reports] == ["accepted", "completion-proposal"]
    completion = reports[-1]
    discharge_decision = next(
        payload
        for path, payload in calls
        if path == "/v1/decisions" and payload["id"] == "decision:admin:2"
    )
    assert discharge_decision["selected"] == {
        "target_ref": "responsibility:admin:2",
        "operation": "discharge-responsibility",
        "to_status": "discharged",
    }
    assert completion["basis_refs"] == [
        {
            "kind": "administrative-subject",
            "id": "employee:2",
            "namespace": "administrative",
            "version": "0.1",
        }
    ]
    assert completion["evidence_refs"] == [
        {
            "kind": "evidence",
            "id": "evidence:verified:2",
            "namespace": "universal",
            "version": "0.1",
        }
    ]
    bridge.close()


def test_discharge_reuses_existing_active_assignment_without_reoffer() -> None:
    calls: list[tuple[str, dict]] = []
    responsibility_ref = "responsibility:admin:existing"
    assignment_ref = (
        "administrative-assignment:responsibility:admin:existing"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content or b"{}")
        calls.append((request.url.path, payload))
        path = request.url.path
        if request.method == "GET" and path == "/v1/contracts":
            return httpx.Response(200, json=_runtime_catalog())
        if request.method == "GET" and path == f"/v1/domain-assignments/{assignment_ref}":
            return httpx.Response(
                200,
                json={
                    "id": assignment_ref,
                    "responsibility_ref": responsibility_ref,
                    "domain": "administrative",
                    "controller": "controller:administrative-orchestrator",
                    "authority_refs": ["administrative-authorization:existing"],
                    "evidence_requirements": [{"kind": "readback"}],
                    "review_conditions": [{"trigger": "authority-epoch-change"}],
                    "status": "active",
                },
            )
        if path.endswith("/reports"):
            return httpx.Response(
                200,
                json={
                    "id": payload["id"],
                    "kind": payload["kind"],
                    "assignment_status": "completion-proposed",
                },
            )
        if path.endswith("/assess"):
            return httpx.Response(
                200,
                json={
                    "status": "satisfied",
                    "assessment_ref": "assessment:admin:existing",
                },
            )
        if path == "/v1/decisions":
            return httpx.Response(200, json={"id": payload["id"]})
        if path.endswith("/discharge"):
            return httpx.Response(
                200,
                json={
                    "status": "discharged",
                    "transition_ref": "transition:admin:existing",
                },
            )
        if path == "/v1/domain-assignments":
            raise AssertionError("existing assignment must not be re-offered")
        return httpx.Response(404)

    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    bridge = WorldRuntimeBridge(
        store,
        Settings(
            _env_file=None,
            world_runtime_mode="cutover",
            world_runtime_base_url="http://runtime.test",
        ),
        transport=httpx.MockTransport(handler),
    )

    result = bridge.discharge_responsibility(
        responsibility_ref,
        decision_ref="decision:admin:existing",
        decided_by="service:administrative",
        subject_ref="employee:existing",
        basis_refs=("evidence:verified:existing",),
    )

    assert result == (
        "assessment:admin:existing",
        "decision:admin:existing",
        "transition:admin:existing",
    )
    assert not any(path == "/v1/domain-assignments" for path, _ in calls)
    reports = [payload for path, payload in calls if path.endswith("/reports")]
    assert [payload["kind"] for payload in reports] == ["completion-proposal"]
    bridge.close()


def test_contract_handshake_fails_closed_on_domain_report_drift() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/contracts":
            payload = _runtime_catalog()
            payload["contracts"]["domain_report"] = {"current": "domain-report-v1"}
            return httpx.Response(200, json=payload)
        return httpx.Response(404)

    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    bridge = WorldRuntimeBridge(
        store,
        Settings(
            _env_file=None,
            world_runtime_mode="cutover",
            world_runtime_base_url="http://runtime.test",
        ),
        transport=httpx.MockTransport(handler),
    )

    try:
        bridge.provision_responsibility(
            responsibility_ref="responsibility:drift",
            principal="service:administrative",
            subject="drift",
            scope={},
        )
    except Exception as exc:
        assert "contract mismatch for domain_report" in str(exc)
    else:
        raise AssertionError("Administrative must fail closed on Runtime contract drift")
    finally:
        bridge.close()
