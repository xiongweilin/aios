"""Reconcile control-plane-local execution claims.

World Runtime is not mutated here. This module only repairs the Domain
Controller's own Work/Run projections after process restart.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from .domain_store import utcnow
from .runtime_bridge import DomainWork, PersonalRuntimeBridge

_REPAIR_KIND = "personal-incident-repair"
_BLOCKED_REPAIR_KIND = "personal-incident-repair-blocked"


def _age_seconds(value: object, now: datetime) -> float | None:
    if value is None:
        return None
    try:
        observed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=now.tzinfo)
    return (now - observed).total_seconds()


def reconcile_repair_state(
    bridge: PersonalRuntimeBridge,
    *,
    stale_after_seconds: float,
) -> dict[str, int]:
    now = utcnow()
    counts: Counter[str] = Counter()
    for work in bridge.list_work():
        if work.kind not in {_REPAIR_KIND, _BLOCKED_REPAIR_KIND}:
            continue
        is_blocked = work.kind == _BLOCKED_REPAIR_KIND
        age = _age_seconds(work.updated_at or work.created_at, now)
        stale_running = work.status == "running" and age is not None and age >= stale_after_seconds
        if is_blocked and work.status in {"open", "ready", "running", "pending"}:
            bridge.update_work_status(work.id, "waiting")
            counts["blocked_work_waiting"] += 1
        elif stale_running:
            bridge.update_work_status(work.id, "waiting")
            counts["stale_work_waiting"] += 1

        for run in bridge.list_runs(work.id):
            if run.status != "running" or not (is_blocked or stale_running):
                continue
            bridge.update_run_status(run.id, "interrupted")
            counts["running_runs_interrupted"] += 1

    if counts:
        bridge.journal.append(
            stream="control-plane:reconciliation",
            kind="control-plane.repair-state-reconciled",
            payload={
                "reason": "remove stale domain execution claims without completion proof",
                "counts": dict(counts),
                "stale_after_seconds": stale_after_seconds,
            },
        )
    return dict(counts)


def settle_waiting_execution_claims(
    bridge: PersonalRuntimeBridge,
    work: DomainWork | None,
) -> dict[str, int]:
    if work is None:
        return {}
    current = bridge.get_work(work.id)
    if current is None or current.status not in {"running", "waiting", "pending"}:
        return {}

    counts: Counter[str] = Counter()
    if current.status in {"running", "pending"}:
        bridge.update_work_status(current.id, "waiting")
        counts["waiting_work_settled"] += 1

    for run in bridge.list_runs(current.id):
        if run.status == "running":
            bridge.update_run_status(run.id, "interrupted")
            counts["running_runs_interrupted"] += 1

    if counts:
        bridge.journal.append(
            stream="control-plane:reconciliation",
            kind="control-plane.repair-state-reconciled",
            payload={
                "reason": "controller reached waiting without completion proof",
                "counts": dict(counts),
            },
        )
    return dict(counts)


__all__ = ["reconcile_repair_state", "settle_waiting_execution_claims"]
