from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

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
    ProviderExecutionStatus,
    RealityObservation,
)
from administrative_orchestrator.execution_repository import ExecutionRepository
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
from administrative_orchestrator.obligations import ObligationRepository
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
from administrative_orchestrator.production_verification import (
    complete_readback_postcondition,
)
from aios_gate import BAAGatedAIOSProvider
from baa_protocol.exposure_bridge import (
    ManagedSubjectStateChangeMeasurement,
    assess_metric_bound,
    realized_exposure_for_settlement,
)
from baa_protocol.offboarding import exposure_declaration_for_proposal
from pydantic import SecretStr

CASE_ID = UUID("00000000-0000-4000-8000-00000000baa4")
PRINCIPAL = "service:administrative-orchestrator"
DELEGATION_ID = "delegation:baa-real-products-administrative"
ODOO_DATABASE = "baa_real_e2e"
ODOO_WRITER = "baa-writer"
ODOO_VERIFIER = "baa-verifier"
KEYCLOAK_REALM = "baa-real-e2e"
KEYCLOAK_WRITER = "baa-writer"
KEYCLOAK_VERIFIER = "baa-verifier"
KEYCLOAK_SESSION_CLIENT = "baa-session-client"
KEYCLOAK_USERNAME = "baa-real-e2e-user"
EXPOSURE_METRIC_V1 = "managed-subject-state-change-count-v1"


def _load_acceptance_helper(name: str, relative: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / relative / "run.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load acceptance helper {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json_request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    token: str | None = None,
    delegation_id: str | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if delegation_id:
        headers["X-World-Runtime-Delegation"] = delegation_id
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"raw": raw.decode("utf-8", errors="replace")}
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw.decode("utf-8", errors="replace")}
        return exc.code, parsed


def _wait_ready(url: str, *, timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    last: object = None
    while time.monotonic() < deadline:
        try:
            status, body = _json_request("GET", url, timeout=2.0)
            if status == 200:
                return
            last = (status, body)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            last = repr(exc)
        time.sleep(1.0)
    raise RuntimeError(f"endpoint did not become ready: {url}; last={last!r}")


def _first_attribute(attributes: object, name: str) -> str | None:
    if not isinstance(attributes, dict):
        return None
    value = attributes.get(name)
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    if isinstance(value, str):
        return value
    return None


def _setup_products(
    *,
    odoo_base: str,
    keycloak_base: str,
    odoo_writer_password: str,
    odoo_verifier_password: str,
    keycloak_admin_password: str,
    keycloak_writer_secret: str,
    keycloak_verifier_secret: str,
    keycloak_user_password: str,
) -> tuple[Any, Any, int, str, str]:
    odoo_mod = _load_acceptance_helper("baa_real_e2e_odoo_helper", "real_odoo")
    odoo = odoo_mod.OdooRpc(odoo_base, database=ODOO_DATABASE)
    odoo.wait_ready()
    odoo.authenticate(odoo_mod.ADMIN_LOGIN, odoo_mod.ADMIN_PASSWORD)
    odoo.setup_custom_field()
    writer_group = odoo.create_access_group(
        name="BAA Real E2E Odoo Writer",
        model="hr.employee",
        read=True,
        write=True,
    )
    odoo.grant_model_access(
        group_id=writer_group,
        group_name="BAA Real E2E Odoo Writer",
        model="resource.resource",
        read=True,
        write=True,
    )
    verifier_group = odoo.create_access_group(
        name="BAA Real E2E Odoo Verifier",
        model="hr.employee",
        read=True,
        write=False,
    )
    odoo.create_user(
        login=ODOO_WRITER,
        password=odoo_writer_password,
        group_id=writer_group,
    )
    odoo.create_user(
        login=ODOO_VERIFIER,
        password=odoo_verifier_password,
        group_id=verifier_group,
    )
    employee_id = odoo.create_employee()
    odoo.create_employee("BAA Real E2E Exposure Control Employee")
    subject_ref = f"odoo:hr.employee:{employee_id}"

    keycloak_mod = _load_acceptance_helper(
        "baa_real_e2e_keycloak_helper",
        "real_keycloak",
    )
    keycloak_mod.REALM = KEYCLOAK_REALM
    keycloak_mod.WRITER_CLIENT = KEYCLOAK_WRITER
    keycloak_mod.VERIFIER_CLIENT = KEYCLOAK_VERIFIER
    keycloak_mod.SESSION_CLIENT = KEYCLOAK_SESSION_CLIENT
    keycloak_mod.SUBJECT_REF = subject_ref
    keycloak_mod.USERNAME = KEYCLOAK_USERNAME

    keycloak = keycloak_mod.KeycloakAdmin(
        keycloak_base,
        "admin",
        keycloak_admin_password,
    )
    keycloak.wait_ready()
    keycloak.create_realm()
    keycloak.configure_user_profile()
    writer_client = keycloak.create_service_client(
        KEYCLOAK_WRITER,
        keycloak_writer_secret,
    )
    verifier_client = keycloak.create_service_client(
        KEYCLOAK_VERIFIER,
        keycloak_verifier_secret,
    )
    keycloak.create_session_client()
    keycloak.assign_realm_management_roles(
        writer_client,
        ("manage-users", "view-users", "query-users"),
    )
    keycloak.assign_realm_management_roles(
        verifier_client,
        ("view-users", "query-users"),
    )
    keycloak_user_id = keycloak.create_subject_user(keycloak_user_password)
    keycloak.create_subject_user(
        keycloak_user_password,
        username=f"{KEYCLOAK_USERNAME}-exposure-control",
        subject_ref=f"{subject_ref}:control",
    )
    keycloak.create_user_session(keycloak_user_password)
    if keycloak.active_sessions(keycloak_user_id) < 1:
        raise AssertionError("real E2E requires an active Keycloak session before offboarding")

    verifier_token = keycloak.service_token(KEYCLOAK_VERIFIER, keycloak_verifier_secret)
    forbidden = keycloak.request(
        "POST",
        f"/admin/realms/{KEYCLOAK_REALM}/users",
        token=verifier_token,
        json_body={
            "username": f"should-not-create-{uuid4()}",
            "enabled": True,
        },
    )
    if forbidden.status_code not in {401, 403}:
        raise AssertionError(
            "Keycloak verifier credential unexpectedly has write authority: "
            f"{forbidden.status_code}"
        )

    odoo_write_denied = False
    try:
        changed = odoo.execute_kw(
            login=ODOO_VERIFIER,
            password=odoo_verifier_password,
            model="hr.employee",
            method="write",
            args=[[employee_id], {"name": "forbidden verifier write"}],
        )
        if changed is True:
            raise AssertionError("Odoo verifier credential unexpectedly has write authority")
    except RuntimeError:
        odoo_write_denied = True
    if not odoo_write_denied:
        raise AssertionError("Odoo verifier write denial was not observed")

    return odoo, keycloak, employee_id, keycloak_user_id, subject_ref


def _authorized_case(
    now: datetime,
    *,
    subject_ref: str,
    keycloak_user_id: str,
) -> tuple[SqlStore, AdministrativeCase]:
    effective = now - timedelta(minutes=1)
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
            external_subject=keycloak_user_id,
            principal_id="person:departing",
            valid_from=now - timedelta(days=30),
        )
    )
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
        employee_ref=subject_ref,
        termination_status="termination_scheduled",
        termination_effective_at=effective.isoformat(),
        employment_episode_ref=f"episode:{uuid4()}",
        departing_principal_id="person:departing",
        successor_principal_id="person:successor",
    )
    fact_values = {**typed_facts.model_dump(mode="json"), "active": True}
    assertions = {
        key: FactAssertion(
            value=value,
            authority=FactAuthority.AUTHORITATIVE,
            source="real-product-e2e",
            owner="hris",
            source_ref=subject_ref,
            source_version="ephemeral-product-fixture:v1",
            observed_at=now,
        )
        for key, value in fact_values.items()
        if value is not None
    }

    request = AdministrativeRequest(
        requester_principal_id="person:real-e2e-acceptance",
        channel="baa-real-product-e2e",
        intent="offboard one cross-system ephemeral employee",
    )
    case = AdministrativeCase(
        case_id=CASE_ID,
        case_kind="employee-offboarding",
        requester_principal_id=request.requester_principal_id,
        subject_ref=subject_ref,
        status=CaseStatus.AUTHORIZED,
        version=4,
        policy_ref=record.policy_ref,
        fact_snapshot=FactSnapshot(
            source="real-product-e2e",
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
        rationale="BAA real-product E2E acceptance approval",
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


def _odoo_managed_subject_snapshot(odoo: Any) -> dict[str, dict[str, Any]]:
    rows = odoo.admin(
        "hr.employee",
        "search_read",
        [[]],
        {
            "fields": [
                "id",
                "active",
                "x_administrative_deactivate_request_ref",
            ],
            "context": {"active_test": False},
        },
    )
    if not isinstance(rows, list):
        raise AssertionError("Odoo managed-subject snapshot is not a list")
    snapshot: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), int):
            raise AssertionError(f"malformed Odoo managed-subject row: {row!r}")
        subject_ref = f"odoo:hr.employee:{row['id']}"
        snapshot[subject_ref] = {
            "active": bool(row.get("active", True)),
            "deactivate_request_ref": row.get(
                "x_administrative_deactivate_request_ref"
            )
            or None,
        }
    return snapshot


def _keycloak_managed_subject_snapshot(
    keycloak: Any,
) -> dict[str, dict[str, Any]]:
    users: list[dict[str, Any]] = []
    first = 0
    page_size = 100
    while True:
        response = keycloak.request(
            "GET",
            f"/admin/realms/{KEYCLOAK_REALM}/users",
            params={
                "first": str(first),
                "max": str(page_size),
                "briefRepresentation": "false",
            },
            expected={200},
        )
        batch = response.json()
        if not isinstance(batch, list):
            raise AssertionError("Keycloak managed-subject snapshot is not a list")
        users.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < page_size:
            break
        first += page_size

    snapshot: dict[str, dict[str, Any]] = {}
    for row in users:
        user_id = row.get("id")
        if not isinstance(user_id, str) or not user_id:
            raise AssertionError(f"malformed Keycloak user row: {row!r}")
        detail = keycloak.request(
            "GET",
            f"/admin/realms/{KEYCLOAK_REALM}/users/{user_id}",
            expected={200},
        ).json()
        if not isinstance(detail, dict):
            raise AssertionError(f"malformed Keycloak user detail: {detail!r}")
        attributes = detail.get("attributes")
        subject_ref = _first_attribute(attributes, "administrative_subject_ref")
        if not subject_ref:
            continue
        snapshot[subject_ref] = {
            "enabled": bool(detail.get("enabled", False)),
            "active_sessions": keycloak.active_sessions(user_id),
            "disable_request_ref": _first_attribute(
                attributes,
                "administrative_disable_request_ref",
            ),
            "session_revoke_request_ref": _first_attribute(
                attributes,
                "administrative_session_revoke_request_ref",
            ),
        }
    return snapshot


def _changed_subject_refs(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> list[str]:
    return sorted(
        subject_ref
        for subject_ref in set(before) | set(after)
        if before.get(subject_ref) != after.get(subject_ref)
    )


class RealProductReadbackProvider:
    """Independent product read-back; execution must remain on World Runtime."""

    def __init__(
        self,
        store: SqlStore,
        *,
        odoo_base: str,
        keycloak_base: str,
        odoo_admin: Any,
        keycloak_admin: Any,
        fault_mode: str = "none",
    ) -> None:
        self.store = store
        self.readbacks: list[dict[str, Any]] = []
        self.exposure_measurements: list[dict[str, Any]] = []
        self._measured_effect_ids: set[str] = set()
        self._odoo_admin = odoo_admin
        self._keycloak_admin = keycloak_admin
        self._odoo_scope = _odoo_managed_subject_snapshot(odoo_admin)
        self._keycloak_scope = _keycloak_managed_subject_snapshot(keycloak_admin)
        self.readback_fault_pending = fault_mode == "readback_outage"
        self.odoo = OdooEmployeeDeactivateVerifier(
            OdooEmployeeDeactivateConnector(
                OdooEmployeeEffectConnector(
                    OdooEffectConnection(
                        base_url=odoo_base,
                        database=ODOO_DATABASE,
                        username=ODOO_VERIFIER,
                        credential=CredentialRef(
                            "odoo:baa-real-products-verifier",
                            "BAA_REAL_ODOO_VERIFIER_PASSWORD",
                        ),
                        deactivate_request_ref_field=(
                            "x_administrative_deactivate_request_ref"
                        ),
                        timeout_seconds=5.0,
                        allow_insecure_http=True,
                    )
                )
            )
        )
        keycloak_connector = KeycloakIdentityEffectConnector(
            KeycloakEffectConnection(
                base_url=keycloak_base,
                realm=KEYCLOAK_REALM,
                client_id=KEYCLOAK_VERIFIER,
                credential=CredentialRef(
                    "keycloak:baa-real-products-verifier",
                    "BAA_REAL_KEYCLOAK_VERIFIER_SECRET",
                ),
                subject_ref_attribute="administrative_subject_ref",
                request_ref_attribute="administrative_request_ref",
                disable_request_ref_attribute="administrative_disable_request_ref",
                session_revoke_request_ref_attribute=(
                    "administrative_session_revoke_request_ref"
                ),
                timeout_seconds=5.0,
                allow_insecure_http=True,
            )
        )
        self.keycloak_disable = KeycloakIdentityDisableVerifier(keycloak_connector)
        self.keycloak_sessions = KeycloakSessionVerifier(keycloak_connector)

    def execute(self, effect, payload: dict[str, Any]) -> ProviderExecutionResult:
        del effect, payload
        return ProviderExecutionResult(
            status=ProviderExecutionStatus.FAILED,
            error="real-product fallback execution is forbidden; World Runtime cutover required",
            retryable=False,
        )

    def _expected(self, effect) -> dict[str, Any]:
        obligation_set = ObligationRepository(self.store).get_current(
            effect.case_id,
            effect.authority_epoch,
        )
        if obligation_set is None:
            raise RuntimeError("read-back requires a current obligation set")
        for obligation in obligation_set.obligations:
            if obligation.obligation_id == effect.obligation_id:
                return dict(obligation.expected_postcondition)
        raise RuntimeError("read-back could not resolve effect obligation")

    def _record_exposure_measurement(
        self,
        effect,
        *,
        observed_postcondition: dict[str, Any],
    ) -> None:
        effect_id = str(effect.effect_id)
        if effect_id in self._measured_effect_ids:
            return

        if effect.operation == "employee.deactivate":
            before = self._odoo_scope
            after = _odoo_managed_subject_snapshot(self._odoo_admin)
            self._odoo_scope = after
        elif effect.operation in {"identity.disable", "sessions.revoke"}:
            before = self._keycloak_scope
            after = _keycloak_managed_subject_snapshot(self._keycloak_admin)
            self._keycloak_scope = after
        else:
            raise AssertionError(
                f"unsupported exposure measurement operation: {effect.operation}"
            )

        changed_subject_refs = _changed_subject_refs(before, after)
        if changed_subject_refs != [effect.subject_ref]:
            raise AssertionError(
                "real-product effect changed the wrong managed-subject scope: "
                f"operation={effect.operation!r}, expected={[effect.subject_ref]!r}, "
                f"observed={changed_subject_refs!r}"
            )

        self.exposure_measurements.append(
            {
                "effect_id": effect_id,
                "proposal_id": f"effect:{effect_id}",
                "obligation_id": str(effect.obligation_id),
                "metric_id": EXPOSURE_METRIC_V1,
                "declared_subject_ref": effect.subject_ref,
                "observed_postcondition": dict(observed_postcondition),
                "managed_subject_count_before": len(before),
                "managed_subject_count_after": len(after),
                "changed_subject_refs": changed_subject_refs,
                "realized_exposure": len(changed_subject_refs),
                "scope_complete": True,
            }
        )
        self._measured_effect_ids.add(effect_id)

    def observe(self, effect) -> RealityObservation:
        expected = self._expected(effect)
        if self.readback_fault_pending and effect.operation == "identity.disable":
            self.readback_fault_pending = False
            self.readbacks.append(
                {
                    "effect_id": str(effect.effect_id),
                    "operation": effect.operation,
                    "injected_fault": "readback_outage",
                }
            )
            return RealityObservation(
                availability=ObservationAvailability.UNAVAILABLE,
                presence=ObservationPresence.UNKNOWN,
                freshness=ObservationFreshness.UNKNOWN,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                error_class="InjectedReadbackOutage",
            )
        if effect.operation == "employee.deactivate":
            result = asyncio.run(
                self.odoo.observe(
                    subject_ref=effect.subject_ref,
                    expected_postcondition=expected,
                )
            )
        elif effect.operation == "identity.disable":
            result = asyncio.run(
                self.keycloak_disable.observe(
                    subject_ref=effect.subject_ref,
                    expected_postcondition=expected,
                )
            )
        elif effect.operation == "sessions.revoke":
            result = asyncio.run(
                self.keycloak_sessions.observe(
                    subject_ref=effect.subject_ref,
                    expected_postcondition=expected,
                )
            )
        else:
            raise RuntimeError(f"unsupported real-product read-back: {effect.operation}")

        raw = dict(result.observed_postcondition or {})
        if result.status is ConnectorStatus.UNAVAILABLE:
            return RealityObservation(
                availability=ObservationAvailability.UNAVAILABLE,
                presence=ObservationPresence.UNKNOWN,
                freshness=ObservationFreshness.UNKNOWN,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                error_class=result.error_code or "VerifierUnavailable",
            )
        if result.status is not ConnectorStatus.SUCCEEDED:
            return RealityObservation(
                availability=ObservationAvailability.UNKNOWN,
                presence=ObservationPresence.UNKNOWN,
                freshness=ObservationFreshness.UNKNOWN,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                error_class=result.error_code or result.status.value,
            )

        semantic_view = complete_readback_postcondition(expected, raw)
        self._record_exposure_measurement(
            effect,
            observed_postcondition=semantic_view,
        )
        digest = hashlib.sha256(
            json.dumps(semantic_view, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.readbacks.append(
            {
                "effect_id": str(effect.effect_id),
                "operation": effect.operation,
                "product_observed": raw,
                "semantic_view": semantic_view,
            }
        )
        return RealityObservation(
            availability=ObservationAvailability.AVAILABLE,
            presence=(
                ObservationPresence.PRESENT
                if raw
                else ObservationPresence.ABSENT
            ),
            freshness=ObservationFreshness.CURRENT,
            target_system=effect.target_system,
            operation=effect.operation,
            subject_ref=effect.subject_ref,
            provider_ref=f"real-product-readback:{effect.operation}:{effect.subject_ref}",
            state=semantic_view,
            digest=digest,
        )


def _build_engine(
    *,
    store: SqlStore,
    runtime_base: str,
    odoo_base: str,
    keycloak_base: str,
    runtime_token: str,
    now: datetime,
    odoo_admin: Any,
    keycloak_admin: Any,
    fault_mode: str = "none",
) -> tuple[
    OffboardingExecutionEngine,
    WorldRuntimeBridge,
    BAAGatedAIOSProvider,
    RealProductReadbackProvider,
]:
    settings = Settings(
        _env_file=None,
        world_runtime_mode="cutover",
        world_runtime_base_url=runtime_base,
        world_runtime_timeout_seconds=5.0,
        world_runtime_principal=PRINCIPAL,
        world_runtime_bearer_token=SecretStr(runtime_token),
        world_runtime_delegation_id=DELEGATION_ID,
    )
    bridge = WorldRuntimeBridge(store, settings)
    readback = RealProductReadbackProvider(
        store,
        odoo_base=odoo_base,
        keycloak_base=keycloak_base,
        odoo_admin=odoo_admin,
        keycloak_admin=keycloak_admin,
        fault_mode=fault_mode,
    )
    runtime_provider = WorldRuntimeEffectProvider(readback, bridge)
    gated = BAAGatedAIOSProvider(
        store,
        runtime_provider,
        now=lambda: now,
        unresolved_limit=1,
    )
    return (
        OffboardingExecutionEngine(store, gated, clock=lambda: now),
        bridge,
        gated,
        readback,
    )


def _product_state(
    *,
    odoo: Any,
    keycloak: Any,
    employee_id: int,
    keycloak_user_id: str,
) -> dict[str, Any]:
    employee_rows = odoo.admin(
        "hr.employee",
        "read",
        [[employee_id]],
        {
            "fields": [
                "id",
                "active",
                "x_administrative_deactivate_request_ref",
            ],
            "context": {"active_test": False},
        },
    )
    if not isinstance(employee_rows, list) or len(employee_rows) != 1:
        raise AssertionError("final Odoo employee read failed")
    employee = employee_rows[0]
    user = keycloak.request(
        "GET",
        f"/admin/realms/{KEYCLOAK_REALM}/users/{keycloak_user_id}",
        expected={200},
    ).json()
    if not isinstance(user, dict):
        raise AssertionError("final Keycloak user read failed")
    attributes = user.get("attributes")
    return {
        "odoo": {
            "active": employee.get("active"),
            "deactivate_request_ref": employee.get(
                "x_administrative_deactivate_request_ref"
            ),
        },
        "keycloak": {
            "enabled": user.get("enabled"),
            "active_sessions": keycloak.active_sessions(keycloak_user_id),
            "disable_request_ref": _first_attribute(
                attributes,
                "administrative_disable_request_ref",
            ),
            "session_revoke_request_ref": _first_attribute(
                attributes,
                "administrative_session_revoke_request_ref",
            ),
        },
    }


def _require_final_product_state(product: dict[str, Any]) -> None:
    if product["odoo"]["active"] is not False:
        raise AssertionError(f"Odoo employee still active: {product}")
    if product["keycloak"]["enabled"] is not False:
        raise AssertionError(f"Keycloak identity still enabled: {product}")
    if product["keycloak"]["active_sessions"] != 0:
        raise AssertionError(f"Keycloak sessions remain active: {product}")
    for marker in (
        product["odoo"]["deactivate_request_ref"],
        product["keycloak"]["disable_request_ref"],
        product["keycloak"]["session_revoke_request_ref"],
    ):
        if not isinstance(marker, str) or not marker:
            raise AssertionError(f"durable product request marker missing: {product}")


def _drive_episode(
    engine: OffboardingExecutionEngine,
    case: AdministrativeCase,
    *,
    scenario: str,
    odoo: Any,
    keycloak: Any,
    employee_id: int,
    keycloak_user_id: str,
) -> tuple[AdministrativeCase, list[str], dict[str, Any] | None, bool, float]:
    started = time.perf_counter()
    current = engine.run(case.case_id)
    status_trace = [current.status.value]
    product_after_first: dict[str, Any] | None = None
    marker_stable = True

    if scenario == "normal":
        if current.status is not CaseStatus.COMPLETED:
            raise AssertionError(
                f"normal real-product E2E did not complete in one drive: {current.status}"
            )
    else:
        if current.status is CaseStatus.COMPLETED:
            raise AssertionError(
                f"{scenario} did not preserve the injected uncertainty before recovery"
            )
        product_after_first = _product_state(
            odoo=odoo,
            keycloak=keycloak,
            employee_id=employee_id,
            keycloak_user_id=keycloak_user_id,
        )
        if product_after_first["keycloak"]["enabled"] is not False:
            raise AssertionError(
                f"{scenario} did not commit the real Keycloak disable before uncertainty: "
                f"{product_after_first}"
            )
        first_disable_marker = product_after_first["keycloak"]["disable_request_ref"]
        if not isinstance(first_disable_marker, str) or not first_disable_marker:
            raise AssertionError(
                f"{scenario} lost the durable Keycloak disable request identity"
            )

        for _ in range(8):
            if current.status is CaseStatus.COMPLETED:
                break
            current = engine.run(case.case_id)
            status_trace.append(current.status.value)
        if current.status is not CaseStatus.COMPLETED:
            raise AssertionError(
                f"{scenario} recovery did not converge to completion: {status_trace}"
            )

        recovered_product = _product_state(
            odoo=odoo,
            keycloak=keycloak,
            employee_id=employee_id,
            keycloak_user_id=keycloak_user_id,
        )
        marker_stable = (
            recovered_product["keycloak"]["disable_request_ref"]
            == first_disable_marker
        )
        if not marker_stable:
            raise AssertionError(
                f"{scenario} recovery created a new logical disable request identity: "
                f"before={first_disable_marker!r}, "
                f"after={recovered_product['keycloak']['disable_request_ref']!r}"
            )

    return (
        current,
        status_trace,
        product_after_first,
        marker_stable,
        time.perf_counter() - started,
    )


def _runtime_bypass(
    *,
    runtime_base: str,
    runtime_token: str,
    subject_ref: str,
    odoo: Any,
    keycloak: Any,
    employee_id: int,
    keycloak_user_id: str,
) -> dict[str, Any]:
    before = _product_state(
        odoo=odoo,
        keycloak=keycloak,
        employee_id=employee_id,
        keycloak_user_id=keycloak_user_id,
    )
    if before["odoo"]["active"] is not True:
        raise AssertionError(f"bypass fixture Odoo employee is not initially active: {before}")
    if before["keycloak"]["enabled"] is not True:
        raise AssertionError(f"bypass fixture Keycloak user is not initially enabled: {before}")
    if before["keycloak"]["active_sessions"] < 1:
        raise AssertionError(f"bypass fixture has no active Keycloak session: {before}")

    def post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        status, body = _json_request(
            "POST",
            f"{runtime_base}{path}",
            payload,
            token=runtime_token,
            delegation_id=DELEGATION_ID,
        )
        if status < 200 or status >= 300:
            raise AssertionError(
                f"Runtime bypass setup failed at {path}: HTTP {status}: {body}"
            )
        return body

    responsibility_id = f"responsibility:bypass:{uuid4()}"
    post(
        "/v1/responsibilities",
        {
            "id": responsibility_id,
            "principal": PRINCIPAL,
            "subject": subject_ref,
            "domain": "administrative",
            "scope": {
                "case_id": str(CASE_ID),
                "authority_epoch": 1,
                "obligation_id": "bypass-authorization-test",
            },
        },
    )
    work = post(
        "/v1/work",
        {
            "responsibility_id": responsibility_id,
            "kind": "administrative-effect",
            "payload": {
                "requested_capabilities": [
                    "administrative.iam.identity.disable.v1"
                ],
                "scenario": "runtime-bypass-without-authorization",
            },
        },
    )
    run = post(
        "/v1/runs",
        {
            "work_id": str(work["id"]),
            "workflow_id": "administrative-effect",
        },
    )

    payload = {
        "id": f"request:bypass:{uuid4()}",
        "capability": "administrative.iam.identity.disable.v1",
        "effect_class": "external-effect",
        "principal": PRINCIPAL,
        "actor_ref": PRINCIPAL,
        "work_id": str(work["id"]),
        "run_id": str(run["id"]),
        "resource": f"administrative:iam:{subject_ref}",
        "resource_ref": f"administrative:iam:{subject_ref}",
        "subject_version_refs": [f"administrative-case:{CASE_ID}:v4"],
        "idempotency_key": f"administrative-effect:{uuid4()}",
        "parameters": {"subject_ref": subject_ref},
    }
    status, body = _json_request(
        "POST",
        f"{runtime_base}/v1/invoke",
        payload,
        token=runtime_token,
        delegation_id=DELEGATION_ID,
    )
    after = _product_state(
        odoo=odoo,
        keycloak=keycloak,
        employee_id=employee_id,
        keycloak_user_id=keycloak_user_id,
    )
    detail = str(body.get("detail") or "")
    if status != 403 or "authorization" not in detail.lower():
        raise AssertionError(
            "World Runtime did not reject specifically at the authorization boundary: "
            f"HTTP {status}: {body}"
        )
    if after != before:
        raise AssertionError(
            "unauthorized Runtime invocation changed real product state: "
            f"before={before}, after={after}"
        )
    return {
        "http_status": status,
        "response": body,
        "responsibility_id": responsibility_id,
        "work_id": str(work["id"]),
        "run_id": str(run["id"]),
        "authorization_id": None,
        "authorization_boundary_reached": True,
        "product_state_before": before,
        "product_state_after": after,
        "provider_effect_observed": False,
    }


def _write_evidence(path_value: str, evidence: dict[str, Any]) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        choices=("normal", "lost_ack", "readback_outage", "runtime_bypass"),
        default="normal",
    )
    parser.add_argument("--runtime-base", required=True)
    parser.add_argument("--odoo-base", required=True)
    parser.add_argument("--keycloak-base", required=True)
    parser.add_argument("--runtime-token", required=True)
    parser.add_argument("--evidence-path", required=True)
    args = parser.parse_args()

    _wait_ready(f"{args.runtime_base}/healthz")
    _wait_ready(args.odoo_base)
    _wait_ready(f"{args.keycloak_base}/realms/master")

    odoo_writer_password = os.environ["BAA_REAL_ODOO_WRITER_PASSWORD"]
    odoo_verifier_password = os.environ["BAA_REAL_ODOO_VERIFIER_PASSWORD"]
    keycloak_admin_password = os.environ["BAA_REAL_KEYCLOAK_ADMIN_PASSWORD"]
    keycloak_writer_secret = os.environ["BAA_REAL_KEYCLOAK_WRITER_SECRET"]
    keycloak_verifier_secret = os.environ["BAA_REAL_KEYCLOAK_VERIFIER_SECRET"]
    keycloak_user_password = os.environ["BAA_REAL_KEYCLOAK_USER_PASSWORD"]

    odoo = None
    keycloak = None
    bridge = None
    try:
        (
            odoo,
            keycloak,
            employee_id,
            keycloak_user_id,
            subject_ref,
        ) = _setup_products(
            odoo_base=args.odoo_base,
            keycloak_base=args.keycloak_base,
            odoo_writer_password=odoo_writer_password,
            odoo_verifier_password=odoo_verifier_password,
            keycloak_admin_password=keycloak_admin_password,
            keycloak_writer_secret=keycloak_writer_secret,
            keycloak_verifier_secret=keycloak_verifier_secret,
            keycloak_user_password=keycloak_user_password,
        )

        status, catalog = _json_request(
            "GET",
            f"{args.runtime_base}/v1/capabilities",
            token=args.runtime_token,
            delegation_id=DELEGATION_ID,
        )
        if status != 200:
            raise AssertionError(
                f"World Runtime capability catalog unavailable: HTTP {status}: {catalog}"
            )

        if args.scenario == "runtime_bypass":
            bypass = _runtime_bypass(
                runtime_base=args.runtime_base,
                runtime_token=args.runtime_token,
                subject_ref=subject_ref,
                odoo=odoo,
                keycloak=keycloak,
                employee_id=employee_id,
                keycloak_user_id=keycloak_user_id,
            )
            _write_evidence(
                args.evidence_path,
                {
                    "status": "passed",
                    "scenario": args.scenario,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "qualification": (
                        "Unauthorized World Runtime invocation was rejected before "
                        "changing real ephemeral Keycloak/Odoo state; not production "
                        "tenant evidence."
                    ),
                    "world_runtime": {
                        "runtime_id": catalog.get("runtime_id"),
                        "effect_rule_count": len(catalog.get("effect_rules", [])),
                    },
                    "runtime_bypass": bypass,
                    "credential_separation": {
                        "odoo_writer": ODOO_WRITER,
                        "odoo_verifier": ODOO_VERIFIER,
                        "odoo_verifier_write_denied": True,
                        "keycloak_writer": KEYCLOAK_WRITER,
                        "keycloak_verifier": KEYCLOAK_VERIFIER,
                        "keycloak_verifier_write_denied": True,
                    },
                },
            )
            return

        now = datetime.now(UTC)
        store, case = _authorized_case(
            now,
            subject_ref=subject_ref,
            keycloak_user_id=keycloak_user_id,
        )
        engine, bridge, gated, readback = _build_engine(
            store=store,
            runtime_base=args.runtime_base,
            odoo_base=args.odoo_base,
            keycloak_base=args.keycloak_base,
            runtime_token=args.runtime_token,
            now=now,
            odoo_admin=odoo,
            keycloak_admin=keycloak,
            fault_mode=args.scenario,
        )

        (
            result,
            status_trace,
            product_after_first,
            marker_stable,
            duration,
        ) = _drive_episode(
            engine,
            case,
            scenario=args.scenario,
            odoo=odoo,
            keycloak=keycloak,
            employee_id=employee_id,
            keycloak_user_id=keycloak_user_id,
        )

        product = _product_state(
            odoo=odoo,
            keycloak=keycloak,
            employee_id=employee_id,
            keycloak_user_id=keycloak_user_id,
        )
        _require_final_product_state(product)

        execution = ExecutionRepository(store)
        effects = execution.list_effects(case.case_id, case.authority_epoch)
        outcomes = execution.list_outcomes(case.case_id, case.authority_epoch)
        realizations = execution.list_realizations(case.case_id, case.authority_epoch)
        if len(effects) != 3 or len(outcomes) != 3 or len(realizations) != 3:
            raise AssertionError(
                "real-product E2E requires three effects, realizations, and outcomes: "
                f"{len(effects)=}, {len(realizations)=}, {len(outcomes)=}"
            )

        audit_events = store.list_audit_events(case.case_id)
        audit_event_types = [str(item["event_type"]) for item in audit_events]
        if args.scenario in {"lost_ack", "readback_outage"}:
            required_recovery_events = {
                "case.reconciliation_started",
                "case.reconciliation_resolved_for_execution",
            }
            missing = required_recovery_events - set(audit_event_types)
            if missing:
                raise AssertionError(
                    f"{args.scenario} did not persist the recovery state transition: "
                    f"missing={sorted(missing)}, events={audit_event_types}"
                )

        kernels = list(gated._kernels.values())
        if len(kernels) != 1 or not kernels[0].externally_complete():
            raise AssertionError("BAA kernel did not verify all external obligations")

        if len(readback.exposure_measurements) != 3:
            raise AssertionError(
                "real-product E2E requires one exposure measurement per external effect: "
                f"{readback.exposure_measurements!r}"
            )
        measurement_by_effect = {
            str(item["effect_id"]): item
            for item in readback.exposure_measurements
        }
        admitted_proposals = {
            event.proposal_id
            for event in gated.refinement_trace
            if event.event == "admit"
        }
        exposure_bindings: list[dict[str, Any]] = []
        for effect in effects:
            effect_id = str(effect.effect_id)
            measurement_payload = measurement_by_effect.get(effect_id)
            if measurement_payload is None:
                raise AssertionError(
                    f"missing exposure measurement for effect {effect_id}"
                )
            proposal = gated._proposal_for_refinement(effect)
            declaration = exposure_declaration_for_proposal(proposal)
            measurement = ManagedSubjectStateChangeMeasurement(
                proposal_id=str(measurement_payload["proposal_id"]),
                metric_id=str(measurement_payload["metric_id"]),
                declared_subject_ref=str(
                    measurement_payload["declared_subject_ref"]
                ),
                observed_postcondition=dict(
                    measurement_payload["observed_postcondition"]
                ),
                managed_subject_count_before=int(
                    measurement_payload["managed_subject_count_before"]
                ),
                managed_subject_count_after=int(
                    measurement_payload["managed_subject_count_after"]
                ),
                changed_subject_refs=tuple(
                    str(item)
                    for item in measurement_payload["changed_subject_refs"]
                ),
                scope_complete=bool(measurement_payload["scope_complete"]),
            )
            assessment = assess_metric_bound(declaration, measurement)
            realized = realized_exposure_for_settlement(assessment)
            if proposal.proposal_id not in admitted_proposals:
                raise AssertionError(
                    f"exposure measurement is not tied to an admitted proposal: "
                    f"{proposal.proposal_id}"
                )
            if realized != 1:
                raise AssertionError(
                    f"unexpected realized exposure for {proposal.proposal_id}: {realized}"
                )
            exposure_bindings.append(
                {
                    "effect_id": effect_id,
                    "obligation_id": str(effect.obligation_id),
                    "proposal_id": proposal.proposal_id,
                    "metric_id": declaration.metric_id,
                    "declared_subject_ref": declaration.declared_subject_ref,
                    "exposure_bound": declaration.exposure_bound,
                    "realized_exposure": realized,
                    "assessment_established": assessment.established,
                    "assessment_reason": assessment.reason,
                }
            )

        _write_evidence(
            args.evidence_path,
            {
                "status": "passed",
                "scenario": args.scenario,
                "generated_at": datetime.now(UTC).isoformat(),
                "qualification": (
                    "Single-episode BAA -> AIOS -> World Runtime -> real ephemeral "
                    "Keycloak/Odoo acceptance with independent verifier credentials; "
                    "fault recovery claims concern stable logical request identity, "
                    "not a claim of physical exactly-once delivery; not production "
                    "tenant evidence."
                ),
                "case": {
                    "case_id": str(case.case_id),
                    "subject_ref": subject_ref,
                    "final_status": result.status.value,
                    "status_trace": status_trace,
                    "duration_seconds": duration,
                },
                "recovery": {
                    "product_after_first_run": product_after_first,
                    "disable_request_identity_stable": marker_stable,
                },
                "world_runtime": {
                    "runtime_id": catalog.get("runtime_id"),
                    "effect_rule_count": len(catalog.get("effect_rules", [])),
                },
                "baa": {
                    "kernel_count": len(kernels),
                    "externally_complete": kernels[0].externally_complete(),
                    "effect_knowledge": {
                        obligation_id: state.knowledge.value
                        for obligation_id, state in kernels[0].effects.items()
                    },
                    "admitted_proposal_ids": sorted(admitted_proposals),
                    "exposure_bindings": exposure_bindings,
                },
                "aios": {
                    "effect_count": len(effects),
                    "realization_count": len(realizations),
                    "confirmed_outcome_count": len(outcomes),
                    "audit_event_types": audit_event_types,
                    "effects": [
                        {
                            "effect_id": str(effect.effect_id),
                            "target_system": effect.target_system,
                            "operation": effect.operation,
                            "status": effect.status.value,
                            "provider_ref": effect.provider_ref,
                        }
                        for effect in effects
                    ],
                },
                "product_state": product,
                "independent_readback": readback.readbacks,
                "exposure_measurements": readback.exposure_measurements,
                "credential_separation": {
                    "odoo_writer": ODOO_WRITER,
                    "odoo_verifier": ODOO_VERIFIER,
                    "odoo_verifier_write_denied": True,
                    "keycloak_writer": KEYCLOAK_WRITER,
                    "keycloak_verifier": KEYCLOAK_VERIFIER,
                    "keycloak_verifier_write_denied": True,
                },
            },
        )
    finally:
        if bridge is not None:
            bridge.close()
        if odoo is not None:
            odoo.close()
        if keycloak is not None:
            keycloak.close()


if __name__ == "__main__":
    main()
