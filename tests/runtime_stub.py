from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

RUNTIME_CONTRACTS = {
    "request_authentication": {"current": "request-authentication-v2"},
    "transition_authority": {"current": "transition-authority-v1"},
    "read_authorization": {"current": "read-authorization-v1"},
    "persistent_responsibility": {"current": "persistent-responsibility-v3"},
    "responsibility_assessment": {"current": "responsibility-assessment-v3"},
    "responsibility_discharge": {"current": "responsibility-discharge-v3"},
    "work_admission": {"current": "work-admission-v4"},
    "decision_record": {"current": "decision-record-v4"},
    "mandate_registration": {"current": "mandate-registration-v4"},
    "authorization_issue": {"current": "authorization-issue-v4"},
    "domain_effect_execution": {"current": "domain-effect-execution-v3"},
    "domain_assignment": {"current": "domain-assignment-v3"},
    "domain_report": {"current": "domain-report-v3"},
}


@dataclass
class RuntimeStub:
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    responsibilities: dict[str, dict[str, Any]] = field(default_factory=dict)
    assignments: dict[str, dict[str, Any]] = field(default_factory=dict)
    work: dict[str, dict[str, Any]] = field(default_factory=dict)
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    effects: dict[str, dict[str, Any]] = field(default_factory=dict)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _payload(self, request: httpx.Request) -> dict[str, Any]:
        if not request.content:
            return {}
        value = json.loads(request.content)
        return dict(value) if isinstance(value, dict) else {}

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        payload = self._payload(request)
        self.calls.append((request.method, path, payload))

        if request.method == "GET" and path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "GET" and path == "/v1/contracts":
            return httpx.Response(
                200,
                json={
                    "runtime_protocol": "4.0",
                    "semantic_language": "0.2.0",
                    "contracts": RUNTIME_CONTRACTS,
                },
            )
        if request.method == "POST" and path == "/v1/responsibilities":
            value = {
                **payload,
                "status": "active",
            }
            self.responsibilities[str(payload["id"])] = value
            return httpx.Response(200, json=value)
        if request.method == "GET" and path.startswith("/v1/responsibilities/"):
            rid = path.rsplit("/", 1)[-1]
            value = self.responsibilities.get(rid)
            if value is None:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json=value)
        if request.method == "POST" and path == "/v1/work":
            work_id = str(payload.get("id") or f"work:{len(self.work) + 1}")
            value = {**payload, "id": work_id, "status": "pending"}
            existing = self.work.get(work_id)
            if existing is not None and existing != value:
                return httpx.Response(409, json={"error": "work identity rebound"})
            self.work[work_id] = value
            return httpx.Response(200, json=value)
        if request.method == "POST" and path == "/v1/runs":
            work_id = str(payload["work_id"])
            workflow_id = str(payload["workflow_id"])
            run_id = f"run:{work_id}:{workflow_id}"
            value = {
                "id": run_id,
                "work_id": work_id,
                "workflow_id": workflow_id,
                "status": "running",
            }
            self.runs[run_id] = value
            return httpx.Response(200, json=value)
        if request.method == "POST" and path == "/v1/mandates":
            return httpx.Response(200, json={"id": payload["id"], "status": "active"})
        if request.method == "POST" and path == "/v1/authorizations":
            return httpx.Response(200, json={"id": payload["id"]})
        if request.method == "POST" and path == "/v1/domain-effects/prepare":
            effect_request = dict(payload.get("request", {}))
            key = str(effect_request.get("idempotency_key", ""))
            current = self.effects.get(key)
            if current is None:
                current = {
                    "grant_id": f"effect-grant:{len(self.effects) + 1}",
                    "idempotency_key": key,
                    "request_id": effect_request.get("id"),
                    "provider_id": payload.get("provider_id"),
                    "provider_version": payload.get("provider_version"),
                    "status": "authorized",
                    "dispatch_generation": 0,
                    "start_allowed": True,
                    "dispatch_allowed": False,
                    "result": None,
                }
                self.effects[key] = current
            return httpx.Response(200, json=current)
        if (
            request.method == "POST"
            and path.startswith("/v1/domain-effects/")
            and path.endswith("/start")
        ):
            key = path.split("/")[3]
            current = self.effects.get(key)
            if current is None:
                return httpx.Response(404)
            if current["status"] != "authorized":
                return httpx.Response(409, json={"error": "already started"})
            current["status"] = "started"
            current["dispatch_generation"] = 1
            current["start_allowed"] = False
            return httpx.Response(200, json={**current, "dispatch_allowed": True})
        if (
            request.method == "POST"
            and path.startswith("/v1/domain-effects/")
            and path.endswith("/result")
        ):
            key = path.split("/")[3]
            current = self.effects.get(key)
            if current is None:
                return httpx.Response(404)
            result = dict(payload.get("result", {}))
            current["status"] = "ambiguous" if result.get("status") == "unknown" else "committed"
            current["start_allowed"] = False
            current["dispatch_allowed"] = False
            current["result"] = result if current["status"] == "committed" else None
            return httpx.Response(200, json=result)
        if request.method == "POST" and path == "/v1/domain-assignments":
            value = {**payload, "status": "offered"}
            self.assignments[str(payload["id"])] = value
            return httpx.Response(200, json=value)
        if (
            request.method == "POST"
            and path.startswith("/v1/domain-assignments/")
            and path.endswith("/reports")
        ):
            assignment_id = path.split("/")[3]
            assignment = self.assignments.setdefault(
                assignment_id,
                {"id": assignment_id, "status": "offered"},
            )
            kind = str(payload.get("kind", ""))
            if kind == "accepted":
                assignment["status"] = "active"
            elif kind == "completion-proposal":
                assignment["status"] = "completion-proposed"
            return httpx.Response(
                200,
                json={
                    **payload,
                    "assignment_status": assignment["status"],
                },
            )
        if request.method == "POST" and path.endswith("/assess"):
            rid = path.split("/")[3]
            self.responsibilities.setdefault(rid, {"id": rid})["status"] = str(
                payload.get("status", "active")
            )
            return httpx.Response(
                200,
                json={
                    "status": payload.get("status"),
                    "assessment_ref": f"assessment:{rid}",
                },
            )
        if request.method == "POST" and path == "/v1/decisions":
            return httpx.Response(200, json=payload)
        if request.method == "POST" and path.endswith("/discharge"):
            rid = path.split("/")[3]
            self.responsibilities.setdefault(rid, {"id": rid})["status"] = "discharged"
            return httpx.Response(
                200,
                json={
                    "status": "discharged",
                    "transition_ref": f"transition:{rid}",
                },
            )
        return httpx.Response(404, json={"error": f"unhandled {request.method} {path}"})


def contract_mismatch_transport() -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/contracts":
            return httpx.Response(
                200,
                json={
                    "runtime_protocol": "1.1",
                    "semantic_language": "0.2.0",
                    "contracts": RUNTIME_CONTRACTS,
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handle)
