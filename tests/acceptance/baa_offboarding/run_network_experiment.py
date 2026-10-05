from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from administrative_orchestrator.authority import (
    ApprovalSatisfaction,
    AuthorityRepository,
    IdentityBinding,
)
from administrative_orchestrator.config import Settings
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AdministrativeRequest,
    CaseStatus,
    Decision,
    DecisionDisposition,
    Delegation,
    FactAssertion,
    FactAuthority,
    FactSnapshot,
    Principal,
    PrincipalKind,
    RoleAssignment,
)
from administrative_orchestrator.effect_provider import (
    ObservationAvailability,
    ObservationFreshness,
    ObservationPresence,
    ProviderExecutionResult,
    RealityObservation,
)
from administrative_orchestrator.governance import GovernanceRepository
from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.effect_common import ConnectorStatus
from administrative_orchestrator.integrations.keycloak_effects import (
    KeycloakEffectConnection,
    KeycloakIdentityDisableVerifier,
    KeycloakIdentityEffectConnector,
    KeycloakSessionVerifier,
)
from administrative_orchestrator.integrations.odoo_effects import (
    OdooEffectConnection,
    OdooEmployeeDeactivateConnector,
    OdooEmployeeDeactivateVerifier,
    OdooEmployeeEffectConnector,
)
from administrative_orchestrator.integrations.world_runtime import (
    WorldRuntimeBridge,
    WorldRuntimeEffectProvider,
)
from administrative_orchestrator.offboarding_execution import OffboardingExecutionEngine
from administrative_orchestrator.persistence import (
    DecisionRow,
    PolicyEvaluationRow,
    SqlStore,
    utcnow,
)
from administrative_orchestrator.policy import OffboardingFacts
from administrative_orchestrator.policy_plane import (
    PolicyRepository,
    compile_offboarding_policy,
    default_offboarding_policy_version,
)
from aios_gate import BAAGatedAIOSProvider

ENTERPRISE = os.environ.get("BAA_ENTERPRISE_BASE_URL", "http://enterprise:19000")
RUNTIME = os.environ.get("BAA_WORLD_RUNTIME_BASE_URL", "http://world-runtime:18086")
RUNTIME_TOKEN = os.environ["BAA_RUNTIME_BEARER_TOKEN"]
SUBJECT = "odoo:hr.employee:42"


def _post(path: str, payload: dict | None = None) -> dict:
    response = httpx.post(
        f"{ENTERPRISE}{path}",
        json=payload or {},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def _get(path: str) -> dict:
    response = httpx.get(f"{ENTERPRISE}{path}", timeout=5)
    response.raise_for_status()
    return response.json()


def _runtime_get(path: str) -> httpx.Response:
    return httpx.get(
        f"{RUNTIME}{path}",
        headers={"Authorization": f"Bearer {RUNTIME_TOKEN}"},
        timeout=5,
    )


def authorized_case(now: datetime) -> tuple[SqlStore, AdministrativeCase]:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authority = AuthorityRepository(store)

    for principal_id in (
        "person:departing",
        "person:successor",
        "person:approver",
    ):
        authority.put_principal(
            Principal(
                principal_id=principal_id,
                kind=PrincipalKind.PERSON,
                display_name=principal_id,
            )
        )

    for principal_id, role in (
        ("person:departing", "manager"),
        ("person:departing", "hr_approver"),
        ("person:successor", "hr_approver"),
        ("person:approver", "hr_approver"),
    ):
        authority.put_role_assignment(
            RoleAssignment(
                principal_id=principal_id,
                role=role,
                organization_scope="org:finance",
                valid_from=now - timedelta(days=30),
            )
        )

    authority.put_identity_binding(
        IdentityBinding(
            provider="keycloak",
            external_subject="kc:departing",
            principal_id="person:departing",
            valid_from=now - timedelta(days=30),
        )
    )
    effective_at = now - timedelta(seconds=5)
    authority.put_delegation(
        Delegation(
            from_principal_id="person:departing",
            to_principal_id="person:successor",
            role="hr_approver",
            organization_scope="org:finance",
            valid_from=now - timedelta(days=5),
            valid_until=now + timedelta(days=30),
        )
    )

    record = default_offboarding_policy_version()
    PolicyRepository(store).put_version(record)
    typed_facts = OffboardingFacts(
        employee_ref=SUBJECT,
        termination_status="termination_scheduled",
        termination_effective_at=effective_at.isoformat(),
        employment_episode_ref="episode:baa-network",
        departing_principal_id="person:departing",
        successor_principal_id="person:successor",
    )
    fact_values = {**typed_facts.model_dump(mode="json"), "active": True}
    assertions = {
        key: FactAssertion(
            value=value,
            authority=FactAuthority.AUTHORITATIVE,
            source="network-fixture",
            owner="hris",
            source_ref=SUBJECT,
            source_version="fixture:v1",
            observed_at=now,
        )
        for key, value in fact_values.items()
        if value is not None
    }

    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="baa-network-acceptance",
        intent="offboard employee 42",
    )
    case = AdministrativeCase(
        case_kind="employee-offboarding",
        requester_principal_id=request.requester_principal_id,
        subject_ref=SUBJECT,
        status=CaseStatus.AUTHORIZED,
        version=4,
        policy_ref=record.policy_ref,
        fact_snapshot=FactSnapshot(
            source="network-fixture",
            owner="hris",
            authority=FactAuthority.AUTHORITATIVE,
            observed_at=now,
            facts=fact_values,
            assertions=assertions,
        ),
    )
    store.create_case(request, case)

    evaluation = compile_offboarding_policy(record).evaluate(typed_facts)
    decision = Decision(
        case_id=case.case_id,
        case_version=case.version - 1,
        authority_epoch=case.authority_epoch,
        principal_id="person:approver",
        decision_role="hr_approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="BAA network acceptance approval",
        policy_ref=record.policy_ref,
        decided_at=now,
    )
    with store.sessions.begin() as db:
        db.add(
            PolicyEvaluationRow(
                case_id=case.case_id,
                case_version=case.version,
                authority_epoch=case.authority_epoch,
                policy_json=evaluation.policy_ref.model_dump(mode="json"),
                evaluation_json=evaluation.model_dump(mode="json"),
                created_at=utcnow(),
            )
        )
        db.add(
            DecisionRow(
                decision_id=decision.decision_id,
                case_id=decision.case_id,
                case_version=decision.case_version,
                authority_epoch=decision.authority_epoch,
                principal_id=decision.principal_id,
                decision_role=decision.decision_role,
                disposition=decision.disposition.value,
                rationale=decision.rationale,
                policy_json=decision.policy_ref.model_dump(mode="json"),
                decided_at=decision.decided_at,
            )
        )

    authority.put_decision_binding(decision, organization_scope="org:finance")
    satisfaction = authority.put_approval_satisfaction(
        ApprovalSatisfaction(
            satisfaction_id=uuid4(),
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            policy_ref=record.policy_ref,
            decision_ids=(decision.decision_id,),
            satisfied_roles=("hr_approver",),
            assessed_at=now,
        )
    )
    GovernanceRepository(store).create_for_approval(
        case,
        satisfaction,
        organization_scope="org:finance",
        fact_dependency_keys=(
            "employee_ref",
            "termination_status",
            "termination_effective_at",
            "employment_episode_ref",
        ),
        expected_change_keys=("active",),
    )
    return store, case


class NetworkReadbackProvider:
    def __init__(self) -> None:
        odoo = OdooEmployeeEffectConnector(
            OdooEffectConnection(
                base_url=f"{ENTERPRISE}/odoo",
                database="fixture",
                username="verifier",
                credential=CredentialRef(
                    "odoo:baa-verifier",
                    "ADMIN_ODOO_VERIFIER_SECRET",
                ),
                deactivate_request_ref_field="x_administrative_deactivate_request_ref",
                timeout_seconds=0.6,
                allow_insecure_http=True,
            )
        )
        keycloak = KeycloakIdentityEffectConnector(
            KeycloakEffectConnection(
                base_url=f"{ENTERPRISE}/keycloak",
                realm="company",
                client_id="verifier",
                credential=CredentialRef(
                    "keycloak:baa-verifier",
                    "ADMIN_KEYCLOAK_VERIFIER_SECRET",
                ),
                timeout_seconds=0.6,
                allow_insecure_http=True,
            )
        )
        self._verifiers = {
            "employee.deactivate": OdooEmployeeDeactivateVerifier(
                OdooEmployeeDeactivateConnector(odoo)
            ),
            "identity.disable": KeycloakIdentityDisableVerifier(keycloak),
            "sessions.revoke": KeycloakSessionVerifier(keycloak),
        }

    def execute(self, effect, payload) -> ProviderExecutionResult:
        del effect, payload
        raise AssertionError("cutover execution must not use readback provider")

    def observe(self, effect) -> RealityObservation:
        verifier = self._verifiers[effect.operation]
        result = asyncio.run(
            verifier.observe(
                subject_ref=effect.subject_ref,
                expected_postcondition={},
            )
        )
        if result.status is not ConnectorStatus.SUCCEEDED:
            return RealityObservation(
                availability=ObservationAvailability.UNAVAILABLE,
                presence=ObservationPresence.UNKNOWN,
                freshness=ObservationFreshness.UNKNOWN,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                error_class=result.error_code or result.status.value,
            )
        observed = dict(result.observed_postcondition or {})
        return RealityObservation(
            availability=ObservationAvailability.AVAILABLE,
            presence=(
                ObservationPresence.PRESENT
                if observed
                else ObservationPresence.ABSENT
            ),
            freshness=ObservationFreshness.CURRENT,
            target_system=effect.target_system,
            operation=effect.operation,
            subject_ref=effect.subject_ref,
            provider_ref=f"network-verifier:{effect.operation}",
            state=observed,
        )


def runtime_settings() -> Settings:
    return Settings(
        _env_file=None,
        runtime_profile="staging",
        auth_mode="oidc",
        oidc_issuer="https://issuer.example.test",
        oidc_audience="administrative-orchestrator",
        world_runtime_mode="cutover",
        world_runtime_base_url=RUNTIME,
        world_runtime_timeout_seconds=3.0,
        world_runtime_principal="service:administrative-orchestrator",
        world_runtime_bearer_token=RUNTIME_TOKEN,
        odoo_base_url=f"{ENTERPRISE}/odoo",
        odoo_database="fixture",
        odoo_verifier_username="verifier",
        odoo_verifier_secret_env="ADMIN_ODOO_VERIFIER_SECRET",
        keycloak_base_url=f"{ENTERPRISE}/keycloak",
        keycloak_realm="company",
        keycloak_verifier_client_id="verifier",
        keycloak_verifier_secret_env="ADMIN_KEYCLOAK_VERIFIER_SECRET",
        connector_timeout_seconds=0.6,
        oidc_allow_insecure_http=True,
    )


def drive_episode(*, fault: bool) -> dict[str, object]:
    _post("/control/reset")
    if fault:
        _post(
            "/control/fault",
            {
                "operation": "identity.disable",
                "mode": "apply_then_delay",
                "delay_seconds": 1.2,
            },
        )

    now = datetime.now(UTC)
    store, case = authorized_case(now)
    bridge = WorldRuntimeBridge(store, runtime_settings())
    provider = WorldRuntimeEffectProvider(NetworkReadbackProvider(), bridge)
    gate = BAAGatedAIOSProvider(
        store,
        provider,
        now=lambda: datetime.now(UTC),
        unresolved_limit=1,
    )
    engine = OffboardingExecutionEngine(
        store,
        gate,
        clock=lambda: datetime.now(UTC),
    )

    states: list[str] = []
    for _ in range(5):
        current = engine.run(case.case_id)
        states.append(current.status.value)
        if current.status is CaseStatus.COMPLETED:
            break

    effects = bridge.execution.list_effects(case.case_id, case.authority_epoch)
    effect_summary = [
        {
            "effect_id": str(item.effect_id),
            "operation": item.operation,
            "status": item.status.value,
        }
        for item in effects
    ]
    metrics = _get("/control/metrics")

    runtime_state = bridge.client.get("/v1/state/export")
    runtime_attempts = {
        str(row.get("key")): dict(row.get("value") or {})
        for row in runtime_state.get("projections", [])
        if row.get("namespace") == "execution.provider-attempt"
    }
    runtime_idempotency = {
        str(row.get("key")): dict(row.get("value") or {})
        for row in runtime_state.get("projections", [])
        if row.get("namespace") == "execution.provider-idempotency"
    }

    identity_effect = next(
        (item for item in effects if item.operation == "identity.disable"),
        None,
    )
    runtime_reconciliation: dict[str, object] | None = None
    expected_identity_key = None
    if fault and identity_effect is not None:
        expected_identity_key = bridge.idempotency_key_for_effect(identity_effect.effect_id)
        if expected_identity_key in runtime_attempts:
            runtime_reconciliation = bridge.client.post(
                f"/v1/reconcile/{expected_identity_key}",
                {},
            )
        else:
            runtime_reconciliation = {
                "status": "provider-attempt-missing",
                "expected_idempotency_key": expected_identity_key,
            }

    bridge.close()
    return {
        "fault": fault,
        "case_statuses": states,
        "completed": states[-1] == CaseStatus.COMPLETED.value,
        "effects": effect_summary,
        "enterprise": metrics,
        "runtime_expected_identity_key": expected_identity_key,
        "runtime_provider_attempts": {
            key: {
                "request_id": value.get("request_id"),
                "provider_id": value.get("provider_id"),
                "capability": value.get("capability"),
                "status": value.get("status"),
            }
            for key, value in runtime_attempts.items()
        },
        "runtime_provider_idempotency": {
            key: {
                "request_id": value.get("request_id"),
                "provider_id": value.get("provider_id"),
                "status": value.get("status"),
                "error": value.get("error"),
            }
            for key, value in runtime_idempotency.items()
        },
        "runtime_reconciliation": runtime_reconciliation,
    }


def validate_runtime_authentication() -> dict[str, int]:
    unauthenticated = httpx.get(f"{RUNTIME}/v1/capabilities", timeout=5)
    authenticated = _runtime_get("/v1/capabilities")
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert authenticated.status_code == 200, authenticated.text
    return {
        "unauthenticated_capabilities_status": unauthenticated.status_code,
        "authenticated_capabilities_status": authenticated.status_code,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-path", required=True)
    args = parser.parse_args()

    auth = validate_runtime_authentication()
    normal = drive_episode(fault=False)
    ambiguous = drive_episode(fault=True)

    assert normal["completed"] is True, normal
    normal_metrics = normal["enterprise"]["metrics"]
    assert normal_metrics.get("identity_disable_writes") == 1, normal_metrics
    assert normal_metrics.get("session_revoke_writes") == 1, normal_metrics
    assert normal_metrics.get("employee_deactivate_writes") == 1, normal_metrics

    assert ambiguous["completed"] is True, ambiguous
    ambiguous_metrics = ambiguous["enterprise"]["metrics"]
    assert ambiguous_metrics.get("identity_disable_writes") == 1, ambiguous_metrics
    assert ambiguous_metrics.get("session_revoke_writes") == 1, ambiguous_metrics
    assert ambiguous_metrics.get("employee_deactivate_writes") == 1, ambiguous_metrics
    assert "reconciling" in ambiguous["case_statuses"], ambiguous["case_statuses"]

    evidence = {
        "status": "passed",
        "aios_commit": os.environ.get("AIOS_EXPERIMENT_COMMIT", ""),
        "baa_commit": os.environ.get("BAA_EXPERIMENT_COMMIT", ""),
        "runtime_authentication": auth,
        "normal": normal,
        "ambiguous_first_effect": ambiguous,
        "qualification": (
            "Docker-network acceptance using real AIOS production connectors and "
            "production World Runtime stack against isolated protocol-compatible fixtures; "
            "not real-provider evidence."
        ),
    }
    path = Path(args.evidence_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
