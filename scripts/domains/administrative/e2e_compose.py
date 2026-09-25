from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

API_BASE = os.getenv("ADMIN_E2E_API_BASE", "http://127.0.0.1:8000")
SANDBOX_BASE = os.getenv("ADMIN_E2E_SANDBOX_BASE", "http://127.0.0.1:8010")
TIMEOUT_SECONDS = float(os.getenv("ADMIN_E2E_TIMEOUT_SECONDS", "90"))

REQUESTER = "person:e2e-requester"
HR_APPROVER = "person:e2e-hr-approver"
MANAGER_APPROVER = "person:e2e-manager-approver"
ACCESS_APPROVER = "person:e2e-access-approver"
HR_OPERATOR = "person:e2e-hr-operator"
AUDITOR = "person:e2e-auditor"
PLATFORM_OPERATOR = "person:e2e-platform-operator"


def _request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    principal: str | None = None,
) -> Any:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if principal is not None:
        headers["X-Principal-ID"] = principal
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode())


def _api(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    principal: str,
) -> Any:
    return _request(method, f"{API_BASE}{path}", payload, principal=principal)


def _expect_http_error(
    status: int,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    principal: str | None = None,
) -> None:
    try:
        _request(
            method,
            f"{API_BASE}{path}",
            payload,
            principal=principal,
        )
    except urllib.error.HTTPError as exc:
        assert exc.code == status, (status, exc.code, exc.read().decode())
        return
    raise AssertionError(f"expected HTTP {status} for {method} {path}")


def _wait_json(url: str, predicate, *, description: str, principal: str | None = None) -> Any:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_error: Exception | None = None
    last_value: Any = None
    while time.monotonic() < deadline:
        try:
            last_value = _request("GET", url, principal=principal)
            if predicate(last_value):
                return last_value
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise AssertionError(
        f"timed out waiting for {description}; last_value={last_value!r}; "
        f"last_error={last_error!r}"
    )


def _wait_case(case_id: str, status: str) -> Any:
    return _wait_json(
        f"{API_BASE}/v1/cases/{case_id}",
        lambda value: value.get("status") == status,
        description=f"case {case_id} -> {status}",
        principal=REQUESTER,
    )


def _assert_completed_case(case_id: str, authority_epoch: int, expected_effect_count: int) -> None:
    completed = _wait_case(case_id, "completed")
    assert completed["authority_epoch"] == authority_epoch, completed

    effects = _api("GET", f"/v1/cases/{case_id}/effects", principal=REQUESTER)
    assert len(effects) == expected_effect_count, effects
    assert {item["status"] for item in effects} == {"succeeded"}, effects

    governance = _api("GET", f"/v1/cases/{case_id}/governance", principal=REQUESTER)
    assert governance is not None, governance
    assert governance["authority_epoch"] == authority_epoch, governance

    obligations = _api("GET", f"/v1/cases/{case_id}/obligations", principal=REQUESTER)
    assert obligations is not None, obligations
    assert obligations["governance_basis_id"] == governance["basis_id"], obligations
    assert len(obligations["obligations"]) == expected_effect_count, obligations

    for effect in effects:
        observation = _request(
            "GET",
            f"{SANDBOX_BASE}/v1/effects/{effect['effect_id']}",
        )
        assert observation["found"] is True, observation
        assert observation["target_system"] == effect["target_system"], observation
        assert observation["operation"] == effect["operation"], observation
        assert observation["subject_ref"] == effect["subject_ref"], observation
        assert observation["state"]["active"] is True, observation

    outcomes = _api("GET", f"/v1/cases/{case_id}/outcomes", principal=REQUESTER)
    assert len(outcomes) == expected_effect_count, outcomes
    assert {item["effect_id"] for item in outcomes} == {
        item["effect_id"] for item in effects
    }, outcomes
    assert {item["authority_epoch"] for item in outcomes} == {authority_epoch}, outcomes
    assert all(item["evidence"] for item in outcomes), outcomes

    completion = _api("GET", f"/v1/cases/{case_id}/completion", principal=REQUESTER)
    assert completion["satisfied"] is True, completion
    assert completion["governance_basis_id"] == governance["basis_id"], completion
    assert completion["uncovered_obligation_ids"] == [], completion

    _expect_http_error(403, "GET", f"/v1/cases/{case_id}/audit", principal=REQUESTER)
    audit = _api("GET", f"/v1/cases/{case_id}/audit", principal=AUDITOR)
    event_types = [item["event_type"] for item in audit]
    for required in (
        "case.created",
        "policy.evaluated",
        "decision.recorded",
        "approval.satisfied",
        "authorization.issued",
        "effect.planned",
        "effect.realization_assessed",
        "outcome.confirmed",
        "case.completed",
    ):
        assert required in event_types, (required, event_types)


def _standard_onboarding() -> None:
    payload = {
        "employee_ref": "employee:e2e-new-hire",
        "department_ref": "department:engineering",
        "manager_principal_id": "person:e2e-manager-approver",
        "start_date": "2026-09-15",
        "employment_type": "full-time",
        "requested_systems": [],
        "requires_privileged_access": False,
        "channel": "compose-e2e",
        "source_event_id": "compose-e2e-standard-onboarding-v1",
    }
    created = _api("POST", "/v1/onboarding", payload, principal=REQUESTER)
    case = created["case"]
    assert case["requester_principal_id"] == REQUESTER, case
    assert case["fact_snapshot"]["authority"] == "claim", case
    assert case["status"] == "awaiting_decision", created
    case_id = case["case_id"]
    initial_epoch = case["authority_epoch"]

    replayed = _api("POST", "/v1/onboarding", payload, principal=REQUESTER)
    assert replayed["case"]["case_id"] == case_id, replayed

    _expect_http_error(
        403,
        "POST",
        f"/v1/cases/{case_id}/decisions",
        {"disposition": "approve", "rationale": "forged"},
        principal=REQUESTER,
    )
    _expect_http_error(
        403,
        "POST",
        f"/v1/cases/{case_id}/facts",
        {
            "employee_ref": payload["employee_ref"],
            "department_ref": payload["department_ref"],
            "start_date": payload["start_date"],
            "employment_type": payload["employment_type"],
        },
        principal=REQUESTER,
    )

    decision = _api(
        "POST",
        f"/v1/cases/{case_id}/decisions",
        {
            "role": "hr_approver",
            "disposition": "approve",
            "rationale": "compose e2e HR approval",
        },
        principal=HR_APPROVER,
    )
    assert decision["decision"]["principal_id"] == HR_APPROVER, decision
    assert decision["decision"]["decision_role"] == "hr_approver", decision
    assert decision["approval"]["satisfied"] is True, decision
    assert decision["case"]["status"] == "authorized", decision
    assert decision["case"]["authority_epoch"] == initial_epoch, decision

    _assert_completed_case(case_id, initial_epoch, 2)


def _privileged_onboarding() -> None:
    created = _api(
        "POST",
        "/v1/onboarding",
        {
            "employee_ref": "employee:e2e-privileged-new-hire",
            "department_ref": "department:engineering",
            "manager_principal_id": MANAGER_APPROVER,
            "start_date": "2026-09-16",
            "employment_type": "full-time",
            "requested_systems": ["github"],
            "requires_privileged_access": True,
            "channel": "compose-e2e",
            "source_event_id": "compose-e2e-privileged-onboarding-v1",
        },
        principal=REQUESTER,
    )
    case = created["case"]
    case_id = case["case_id"]
    epoch = case["authority_epoch"]
    assert created["policy_evaluation"]["required_decision_roles"] == [
        "manager",
        "access_approver",
    ], created
    assert created["policy_evaluation"]["require_distinct_decision_principals"] is True

    first = _api(
        "POST",
        f"/v1/cases/{case_id}/decisions",
        {
            "role": "manager",
            "disposition": "approve",
            "rationale": "manager approval",
        },
        principal=MANAGER_APPROVER,
    )
    assert first["approval"]["satisfied"] is False, first
    assert first["approval"]["missing_roles"] == ["access_approver"], first
    assert first["case"]["status"] == "awaiting_decision", first
    assert _api("GET", f"/v1/cases/{case_id}/effects", principal=REQUESTER) == []

    second = _api(
        "POST",
        f"/v1/cases/{case_id}/decisions",
        {
            "role": "access_approver",
            "disposition": "approve",
            "rationale": "access approval",
        },
        principal=ACCESS_APPROVER,
    )
    assert second["approval"]["satisfied"] is True, second
    assert second["case"]["status"] == "authorized", second
    assert second["case"]["authority_epoch"] == epoch, second

    decisions = _api("GET", f"/v1/cases/{case_id}/decisions", principal=REQUESTER)
    assert {(item["principal_id"], item["decision_role"]) for item in decisions} == {
        (MANAGER_APPROVER, "manager"),
        (ACCESS_APPROVER, "access_approver"),
    }
    _assert_completed_case(case_id, epoch, 3)


def main() -> None:
    ready = _wait_json(
        f"{API_BASE}/readyz",
        lambda value: value.get("status") == "ready",
        description="API readiness",
    )
    assert ready["auth_mode"] == "development", ready
    assert ready["authority_enforcement"] == "enabled", ready
    assert ready["resource_authorization"] == "enabled", ready
    _wait_json(
        f"{SANDBOX_BASE}/healthz",
        lambda value: value.get("status") == "ok",
        description="authoritative sandbox readiness",
    )

    _expect_http_error(401, "GET", "/v1/outbox/dead-letter")
    _expect_http_error(403, "GET", "/v1/outbox/dead-letter", principal=REQUESTER)
    assert _api("GET", "/v1/outbox/dead-letter", principal=PLATFORM_OPERATOR) == []

    _standard_onboarding()
    _privileged_onboarding()

    _expect_http_error(
        403,
        "GET",
        "/v1/policies/employee-onboarding/current",
        principal=REQUESTER,
    )
    current_policy = _api(
        "GET",
        "/v1/policies/employee-onboarding/current",
        principal=AUDITOR,
    )
    assert current_policy["version"] == "v1", current_policy

    print(json.dumps({"status": "ok", "policy": current_policy}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
