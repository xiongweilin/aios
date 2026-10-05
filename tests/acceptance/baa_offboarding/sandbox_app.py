from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="BAA Offboarding Network Sandbox")

_effects: dict[str, dict[str, Any]] = {}
_write_count = 0
_lost_ack_remaining = 0
_read_outage_remaining = 0


class FaultControl(BaseModel):
    lost_ack_once: bool = False
    read_outage_once: bool = False
    reset_effects: bool = True


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/control")
async def control(payload: FaultControl) -> dict[str, Any]:
    global _lost_ack_remaining, _read_outage_remaining, _write_count
    if payload.reset_effects:
        _effects.clear()
        _write_count = 0
    _lost_ack_remaining = 1 if payload.lost_ack_once else 0
    _read_outage_remaining = 1 if payload.read_outage_once else 0
    return await state()


@app.get("/v1/control/state")
async def state() -> dict[str, Any]:
    return {
        "write_count": _write_count,
        "effect_ids": sorted(_effects),
        "lost_ack_remaining": _lost_ack_remaining,
        "read_outage_remaining": _read_outage_remaining,
    }


@app.put("/v1/effects/{effect_id}")
async def execute(effect_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    global _write_count, _lost_ack_remaining

    target_system = str(payload.get("target_system") or "")
    operation = str(payload.get("operation") or "")
    subject_ref = str(payload.get("subject_ref") or "")
    parameters = payload.get("payload")
    if not target_system or not operation or not subject_ref or not isinstance(parameters, dict):
        raise HTTPException(status_code=400, detail="closed effect payload required")

    observed: dict[str, Any] = {
        "target_system": target_system,
        "operation": operation,
        "subject_ref": subject_ref,
    }
    if operation == "employee.deactivate":
        observed["active"] = False
    elif operation == "identity.disable":
        observed["enabled"] = False
    elif operation == "sessions.revoke":
        observed["active_sessions"] = 0
    else:
        raise HTTPException(status_code=409, detail="operation outside offboarding fixture")

    _effects[effect_id] = observed
    _write_count += 1

    if _lost_ack_remaining:
        _lost_ack_remaining -= 1
        await asyncio.sleep(2.0)

    return {
        "status": "succeeded",
        "provider_ref": f"sandbox:{effect_id}",
    }


@app.get("/v1/effects/{effect_id}")
async def observe(effect_id: str) -> dict[str, Any]:
    global _read_outage_remaining
    if _read_outage_remaining:
        _read_outage_remaining -= 1
        raise HTTPException(status_code=503, detail="simulated read-back outage")

    value = _effects.get(effect_id)
    if value is None:
        raise HTTPException(status_code=404, detail="effect not found")
    return {
        "availability": "available",
        "presence": "present",
        "freshness": "current",
        "found": True,
        "provider_ref": f"sandbox:{effect_id}",
        "state": value,
        **value,
    }
