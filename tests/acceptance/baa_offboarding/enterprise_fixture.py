from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any
from urllib.parse import parse_qs

import uvicorn
from fastapi import FastAPI, Request, Response

app = FastAPI(title="BAA enterprise network fixture")

_lock = asyncio.Lock()
_metrics: Counter[str] = Counter()
_events: list[dict[str, Any]] = []
_fault: dict[str, Any] = {}
_employee: dict[str, Any] = {}
_user: dict[str, Any] = {}
_sessions: list[dict[str, Any]] = []


def _reset_state() -> None:
    global _employee, _user, _sessions, _fault
    _metrics.clear()
    _events.clear()
    _fault = {}
    _employee = {
        "id": 42,
        "active": True,
        "x_administrative_deactivate_request_ref": "",
    }
    _user = {
        "id": "user-1",
        "username": "employee-42",
        "email": "employee42@example.test",
        "enabled": True,
        "attributes": {
            "administrative_subject_ref": ["odoo:hr.employee:42"],
        },
    }
    _sessions = [{"id": "session-1"}]


_reset_state()


def _attribute_first(name: str) -> str:
    value = _user.get("attributes", {}).get(name)
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return ""


def _matching_user(q: str | None) -> list[dict[str, Any]]:
    if not q or ":" not in q:
        return [dict(_user)]
    name, value = q.split(":", 1)
    return [dict(_user)] if _attribute_first(name) == value else []


async def _maybe_fault(operation: str) -> None:
    if _fault.get("operation") != operation or _fault.get("consumed"):
        return
    _fault["consumed"] = True
    mode = str(_fault.get("mode") or "")
    if mode == "apply_then_delay":
        delay = float(_fault.get("delay_seconds") or 1.5)
        _events.append({"kind": "fault", "operation": operation, "mode": mode})
        await asyncio.sleep(delay)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/control/reset")
async def reset() -> dict[str, str]:
    async with _lock:
        _reset_state()
    return {"status": "reset"}


@app.post("/control/fault")
async def fault(request: Request) -> dict[str, object]:
    payload = await request.json()
    async with _lock:
        _fault.clear()
        _fault.update(
            {
                "operation": str(payload.get("operation") or ""),
                "mode": str(payload.get("mode") or ""),
                "delay_seconds": float(payload.get("delay_seconds") or 1.5),
                "consumed": False,
            }
        )
    return {"status": "armed", **_fault}


@app.get("/control/metrics")
async def metrics() -> dict[str, object]:
    async with _lock:
        return {
            "metrics": dict(_metrics),
            "events": list(_events),
            "employee": dict(_employee),
            "user": {
                **{key: value for key, value in _user.items() if key != "attributes"},
                "attributes": dict(_user.get("attributes", {})),
            },
            "sessions": list(_sessions),
            "fault": dict(_fault),
        }


@app.post("/keycloak/realms/{realm}/protocol/openid-connect/token")
async def keycloak_token(realm: str, request: Request) -> dict[str, object]:
    del realm
    body = (await request.body()).decode("utf-8")
    values = parse_qs(body)
    client_id = str((values.get("client_id") or ["unknown"])[0])
    _metrics[f"keycloak_token:{client_id}"] += 1
    return {
        "access_token": f"fixture-token:{client_id}",
        "token_type": "Bearer",
        "expires_in": 3600,
    }


@app.get("/keycloak/admin/realms/{realm}/users")
async def keycloak_users(
    realm: str,
    q: str | None = None,
    max: int = 2,
) -> list[dict[str, Any]]:
    del realm, max
    _metrics["keycloak_user_search"] += 1
    return _matching_user(q)


@app.get("/keycloak/admin/realms/{realm}/users/{user_id}")
async def keycloak_user(realm: str, user_id: str) -> dict[str, Any]:
    del realm
    _metrics["keycloak_user_read"] += 1
    if user_id != str(_user["id"]):
        return {}
    return dict(_user)


@app.put("/keycloak/admin/realms/{realm}/users/{user_id}", status_code=204)
async def keycloak_user_update(realm: str, user_id: str, request: Request) -> Response:
    del realm
    payload = await request.json()
    async with _lock:
        if user_id != str(_user["id"]):
            return Response(status_code=404)
        old_attributes = dict(_user.get("attributes", {}))
        new_attributes = dict(payload.get("attributes") or {})
        _user.update(
            {
                "username": payload.get("username") or _user.get("username"),
                "email": payload.get("email") or _user.get("email"),
                "enabled": bool(payload.get("enabled", _user.get("enabled", True))),
                "attributes": new_attributes,
            }
        )
        operation = "keycloak.user.update"
        if payload.get("enabled") is False:
            operation = "identity.disable"
            _metrics["identity_disable_writes"] += 1
        elif (
            new_attributes.get("administrative_session_revoke_request_ref")
            != old_attributes.get("administrative_session_revoke_request_ref")
        ):
            operation = "sessions.marker"
            _metrics["session_marker_writes"] += 1
        _events.append({"kind": "write", "operation": operation})
    await _maybe_fault(operation)
    return Response(status_code=204)


@app.get("/keycloak/admin/realms/{realm}/users/{user_id}/sessions")
async def keycloak_sessions(realm: str, user_id: str) -> list[dict[str, Any]]:
    del realm
    _metrics["keycloak_session_reads"] += 1
    if user_id != str(_user["id"]):
        return []
    return list(_sessions)


@app.post("/keycloak/admin/realms/{realm}/users/{user_id}/logout", status_code=204)
async def keycloak_logout(realm: str, user_id: str) -> Response:
    del realm
    async with _lock:
        if user_id != str(_user["id"]):
            return Response(status_code=404)
        _sessions.clear()
        _metrics["session_revoke_writes"] += 1
        _events.append({"kind": "write", "operation": "sessions.revoke"})
    await _maybe_fault("sessions.revoke")
    return Response(status_code=204)


@app.post("/odoo/jsonrpc")
async def odoo_jsonrpc(request: Request) -> dict[str, object]:
    payload = await request.json()
    params = payload.get("params") if isinstance(payload, dict) else {}
    service = str((params or {}).get("service") or "")
    method = str((params or {}).get("method") or "")
    args = list((params or {}).get("args") or [])
    request_id = payload.get("id")

    if service == "common" and method == "authenticate":
        username = str(args[1]) if len(args) > 1 else ""
        _metrics[f"odoo_auth:{username}"] += 1
        uid = {
            "reader": 11,
            "writer": 12,
            "verifier": 13,
            "financial-writer": 14,
            "financial-verifier": 15,
        }.get(username, 10)
        return {"jsonrpc": "2.0", "id": request_id, "result": uid}

    if service != "object" or method != "execute_kw" or len(args) < 7:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": 400, "message": "unsupported fixture RPC"},
        }

    model = str(args[3])
    operation = str(args[4])
    call_args = list(args[5] or [])
    kwargs = dict(args[6] or {})
    if model != "hr.employee":
        return {"jsonrpc": "2.0", "id": request_id, "result": []}

    if operation == "read":
        _metrics["odoo_employee_reads"] += 1
        ids = list(call_args[0] or []) if call_args else []
        rows = [dict(_employee)] if 42 in ids else []
        fields = list(kwargs.get("fields") or [])
        if fields:
            rows = [
                ({key: row.get(key) for key in fields if key in row} | {"id": row["id"]})
                for row in rows
            ]
        return {"jsonrpc": "2.0", "id": request_id, "result": rows}

    if operation == "search_read":
        _metrics["odoo_employee_searches"] += 1
        domain = list(call_args[0] or []) if call_args else []
        rows: list[dict[str, Any]] = []
        matches = True
        for clause in domain:
            if not isinstance(clause, list) or len(clause) != 3:
                continue
            field, comparator, expected = clause
            if comparator == "=" and _employee.get(str(field)) != expected:
                matches = False
        if matches:
            fields = list(kwargs.get("fields") or [])
            row = {"id": 42}
            for field in fields:
                if field in _employee:
                    row[field] = _employee[field]
            rows = [row]
        return {"jsonrpc": "2.0", "id": request_id, "result": rows}

    if operation == "write":
        ids = list(call_args[0] or []) if call_args else []
        values = dict(call_args[1] or {}) if len(call_args) > 1 else {}
        if 42 not in ids:
            return {"jsonrpc": "2.0", "id": request_id, "result": False}
        async with _lock:
            _employee.update(values)
            op = "odoo.employee.write"
            if values.get("active") is False:
                op = "employee.deactivate"
                _metrics["employee_deactivate_writes"] += 1
            _events.append({"kind": "write", "operation": op})
        await _maybe_fault(op)
        return {"jsonrpc": "2.0", "id": request_id, "result": True}

    return {"jsonrpc": "2.0", "id": request_id, "result": None}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=19000, log_level="warning")
