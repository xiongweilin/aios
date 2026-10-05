from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from administrative_orchestrator.authority import (
    ApprovalSatisfaction,
    AuthorityRepository,
    IdentityBinding,
)
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
from administrative_orchestrator.effect_provider import HttpEffectProvider
from administrative_orchestrator.governance import GovernanceRepository
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
from pydantic import SecretStr

PRINCIPAL = "service:administrative-orchestrator"
DELEGATION_ID = "delegation:baa-network-administrative"
NETWORK_CASE_ID = UUID("00000000-0000-4000-8000-00000000baa1")
NETWORK_OBLIGATION_IDS = (
    "ac745a5c-dea4-5a3f-a3a9-6976421ac42f",
    "9738edec-4de4-5b2b-acbc-32eeab008d4c",
    "d2411d33-7bc9-5211-bb62-bb722000cb0c",
)


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
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw.decode("utf-8", errors="replace")}
        return exc.code, parsed


def _wait_ready(url: str, *, token: str | None = None, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    last: object = None
    while time.monotonic() < deadline:
        try:
            status, body = _json_request("GET", url, token=token, timeout=2.0)
            if status == 200:
                return
            last = (status, body)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            last = repr(exc)
        time.sleep(0.5)
    raise RuntimeError(f"endpoint did not become ready: {url}; last={last!r}")


def _sandbox_control(
    sandbox_base: str,
    *,
    lost_ack_once: bool = False,
    read_outage_once: bool = False,
) -> dict[str, Any]:
    status, body = _json_request(
        "POST",
        f"{sandbox_base}/v1/control",
        {
            "lost_ack_once": lost_ack_once,
            "read_outage_once": read_outage_once,
            "reset_effects": True,
        },
    )
    if status != 200:
        raise RuntimeError(f"sandbox control failed: HTTP {status}: {body}")
    return body


def _sandbox_state(sandbox_base: str) -> dict[str, Any]:
    status, body = _json_request("GET", f"{sandbox_base}/v1/control/state")
    if status != 200:
        raise RuntimeError(f"sandbox state failed: HTTP {status}: {body}")
    return body


def _authorized_case(now: datetime) -> tuple[SqlStore, AdministrativeCase]:
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
            external_subject="kc:departing",
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
        employee_ref="odoo:hr.employee:baa-network-42",
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
            source="network-acceptance",
            owner="hris",
            source_ref="odoo:hr.employee:baa-network-42",
            source_version="fixture:v1",
            observed_at=now,
        )
        for key, value in fact_values.items()
        if value is not None
    }

    request = AdministrativeRequest(
        requester_principal_id="person:network-acceptance",
        channel="baa-network-acceptance",
        intent="offboard isolated network fixture",
    )
    case = AdministrativeCase(
        case_id=NETWORK_CASE_ID,
        case_kind="employee-offboarding",
        requester_principal_id=request.requester_principal_id,
        subject_ref="odoo:hr.employee:baa-network-42",
        status=CaseStatus.AUTHORIZED,
        version=4,
        policy_ref=record.policy_ref,
        fact_snapshot=FactSnapshot(
            source="network-acceptance",
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


def _engine(
    *,
    store: SqlStore,
    runtime_base: str,
    sandbox_base: str,
    token: str,
    now: datetime,
) -> tuple[OffboardingExecutionEngine, WorldRuntimeBridge]:
    settings = __import__(
        "administrative_orchestrator.config",
        fromlist=["Settings"],
    ).Settings(
        _env_file=None,
        world_runtime_mode="cutover",
        world_runtime_base_url=runtime_base,
        world_runtime_timeout_seconds=2.0,
        world_runtime_principal=PRINCIPAL,
        world_runtime_bearer_token=SecretStr(token),
        world_runtime_delegation_id=DELEGATION_ID,
    )
    bridge = WorldRuntimeBridge(store, settings)
    fallback = HttpEffectProvider(sandbox_base, timeout_seconds=1.0)
    provider = WorldRuntimeEffectProvider(fallback, bridge)
    gated = BAAGatedAIOSProvider(
        store,
        provider,
        now=lambda: now,
        unresolved_limit=1,
    )
    return OffboardingExecutionEngine(store, gated, clock=lambda: now), bridge


def _probe_runtime_mandate(runtime_base: str, token: str) -> dict[str, Any]:
    payload = {
        "id": f"mandate:baa-network-probe:{uuid4()}",
        "principal": PRINCIPAL,
        "scope": {
            "case_id": str(NETWORK_CASE_ID),
            "authority_epoch": 1,
            "obligation_id": NETWORK_OBLIGATION_IDS[0],
        },
        "authority_ceiling": {
            "action": "administrative.iam.identity.disable.v1",
            "resource": "administrative:iam:employee:baa-network-probe",
        },
    }
    status, body = _json_request(
        "POST",
        f"{runtime_base}/v1/mandates",
        payload,
        token=token,
        delegation_id=DELEGATION_ID,
    )
    if status != 200:
        raise AssertionError(
            "direct Runtime mandate probe failed: "
            f"HTTP {status}: {json.dumps(body, sort_keys=True)}"
        )
    return {
        "http_status": status,
        "status": body.get("status"),
    }


def _run_normal(runtime_base: str, sandbox_base: str, token: str) -> dict[str, Any]:
    _sandbox_control(sandbox_base)
    now = datetime.now(UTC)
    store, case = _authorized_case(now)
    engine, bridge = _engine(
        store=store,
        runtime_base=runtime_base,
        sandbox_base=sandbox_base,
        token=token,
        now=now,
    )
    started = time.perf_counter()
    try:
        result = engine.run(case.case_id)
    finally:
        bridge.close()
    state = _sandbox_state(sandbox_base)
    if result.status is not CaseStatus.COMPLETED:
        raise AssertionError(f"normal network episode did not complete: {result.status}")
    if state["write_count"] != 3 or len(state["effect_ids"]) != 3:
        raise AssertionError(f"normal episode expected three unique writes: {state}")
    return {
        "name": "normal",
        "status": result.status.value,
        "sandbox": state,
        "duration_seconds": time.perf_counter() - started,
    }


def _run_lost_ack(runtime_base: str, sandbox_base: str, token: str) -> dict[str, Any]:
    _sandbox_control(sandbox_base, lost_ack_once=True)
    now = datetime.now(UTC)
    store, case = _authorized_case(now)
    engine, bridge = _engine(
        store=store,
        runtime_base=runtime_base,
        sandbox_base=sandbox_base,
        token=token,
        now=now,
    )
    try:
        first = engine.run(case.case_id)
        first_state = _sandbox_state(sandbox_base)
        if first.status is not CaseStatus.RECONCILING:
            raise AssertionError(f"lost-ACK episode must enter reconciling: {first.status}")
        if first_state["write_count"] != 1:
            raise AssertionError(f"lost-ACK first dispatch must write exactly once: {first_state}")

        time.sleep(2.2)
        second = engine.run(case.case_id)
        second_state = _sandbox_state(sandbox_base)
        if second_state["write_count"] != len(second_state["effect_ids"]):
            raise AssertionError(
                "lost-ACK recovery duplicated at least one reality effect: "
                f"{second_state}"
            )
    finally:
        bridge.close()
    return {
        "name": "lost_ack",
        "first_status": first.status.value,
        "second_status": second.status.value,
        "first_sandbox": first_state,
        "second_sandbox": second_state,
        "duplicate_writes": second_state["write_count"] - len(second_state["effect_ids"]),
    }


def _run_readback_outage(
    runtime_base: str,
    sandbox_base: str,
    token: str,
) -> dict[str, Any]:
    _sandbox_control(sandbox_base, read_outage_once=True)
    now = datetime.now(UTC)
    store, case = _authorized_case(now)
    engine, bridge = _engine(
        store=store,
        runtime_base=runtime_base,
        sandbox_base=sandbox_base,
        token=token,
        now=now,
    )
    try:
        first = engine.run(case.case_id)
        first_state = _sandbox_state(sandbox_base)
        if first.status is not CaseStatus.RECONCILING:
            raise AssertionError(
                f"read-back outage must preserve uncertainty: {first.status}"
            )
        second = engine.run(case.case_id)
        second_state = _sandbox_state(sandbox_base)
        if second_state["write_count"] != len(second_state["effect_ids"]):
            raise AssertionError(
                "read-back recovery duplicated at least one reality effect: "
                f"{second_state}"
            )
    finally:
        bridge.close()
    return {
        "name": "readback_outage",
        "first_status": first.status.value,
        "second_status": second.status.value,
        "first_sandbox": first_state,
        "second_sandbox": second_state,
        "duplicate_writes": second_state["write_count"] - len(second_state["effect_ids"]),
    }


def _run_runtime_bypass(runtime_base: str, sandbox_base: str, token: str) -> dict[str, Any]:
    _sandbox_control(sandbox_base)
    before = _sandbox_state(sandbox_base)
    capability = "administrative.iam.identity.disable.v1"
    payload = {
        "id": f"request:bypass:{uuid4()}",
        "capability": capability,
        "effect_class": "external-effect",
        "principal": PRINCIPAL,
        "actor_ref": PRINCIPAL,
        "resource": "administrative:iam:employee:bypass",
        "resource_ref": "administrative:iam:employee:bypass",
        "subject_version_refs": ["administrative-case:bypass:v1"],
        "idempotency_key": f"administrative-effect:{uuid4()}",
        "parameters": {"subject_ref": "employee:bypass"},
    }
    status, body = _json_request(
        "POST",
        f"{runtime_base}/v1/invoke",
        payload,
        token=token,
        delegation_id=DELEGATION_ID,
    )
    after = _sandbox_state(sandbox_base)
    if status < 400:
        raise AssertionError(f"runtime admitted an un-authorized effect: HTTP {status}: {body}")
    if after["write_count"] != before["write_count"]:
        raise AssertionError("unauthorized Runtime request reached the provider")
    return {
        "name": "runtime_bypass",
        "http_status": status,
        "provider_writes_before": before["write_count"],
        "provider_writes_after": after["write_count"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-base", required=True)
    parser.add_argument("--sandbox-base", required=True)
    parser.add_argument("--runtime-token", required=True)
    parser.add_argument("--evidence-path", required=True)
    args = parser.parse_args()

    _wait_ready(f"{args.sandbox_base}/healthz")
    _wait_ready(f"{args.runtime_base}/healthz")
    status, catalog = _json_request(
        "GET",
        f"{args.runtime_base}/v1/capabilities",
        token=args.runtime_token,
        delegation_id=DELEGATION_ID,
    )
    if status != 200:
        raise RuntimeError(f"Runtime capability catalog unavailable: HTTP {status}: {catalog}")

    mandate_probe = _probe_runtime_mandate(
        args.runtime_base,
        args.runtime_token,
    )

    scenarios = [
        _run_normal(args.runtime_base, args.sandbox_base, args.runtime_token),
        _run_lost_ack(args.runtime_base, args.sandbox_base, args.runtime_token),
        _run_readback_outage(args.runtime_base, args.sandbox_base, args.runtime_token),
        _run_runtime_bypass(args.runtime_base, args.sandbox_base, args.runtime_token),
    ]

    evidence = {
        "status": "passed",
        "generated_at": datetime.now(UTC).isoformat(),
        "qualification": (
            "Networked production-like acceptance with isolated synthetic effects; "
            "not real Odoo/Keycloak evidence."
        ),
        "runtime": {
            "base_url": args.runtime_base,
            "runtime_id": catalog.get("runtime_id"),
            "effect_rule_count": len(catalog.get("effect_rules", [])),
            "mandate_probe": mandate_probe,
        },
        "scenarios": scenarios,
    }
    path = Path(args.evidence_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
