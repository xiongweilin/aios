from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from control_plane.alert_context import AlertContext
from control_plane.alert_diagnostics import (
    AlertRepair,
    _alert_diagnosis_snapshot,
    _alert_escalation_reason,
    _alert_fingerprint,
    _diagnosis_follow_up,
    _first_structured_value,
    _format_alert_escalation,
    _latest_alert_diagnosis_result,
    _policy_count,
    _structured_text,
)

_STATE = SimpleNamespace(id="state-1")
_VALID_RESULT: dict[str, Any] = {
    "status": "succeeded",
    "message": "SAFETY_CLASS=REVERSIBLE",
}


def _event(type_: str, payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type=type_, payload=payload)


def _decision_event(
    *,
    decision_id: str = "decision-1",
    phase: str = "diagnosis",
    closure: dict[str, Any] | None = None,
) -> SimpleNamespace:
    decision: dict[str, Any] = {
        "id": decision_id,
        "capability": "reason.generate",
        "parameters": {"phase": phase},
    }
    if closure is not None:
        decision["closure"] = closure
    return _event("ControllerDecisionSelected", {"decision": decision})


def _result_event(decision_ref: str = "decision-1", result: Any = _VALID_RESULT) -> SimpleNamespace:
    return _event(
        "ControllerCapabilityResultObserved",
        {"decision_ref": decision_ref, "result": result},
    )


def _policy(
    events: list[SimpleNamespace] | None = None, *, raises: bool = False, **extra: Any
) -> SimpleNamespace:
    items = list(events or [])

    def list_events(_state_id: str) -> list[SimpleNamespace]:
        if raises:
            raise RuntimeError("store unavailable")
        return items

    policy = SimpleNamespace(
        controller=SimpleNamespace(store=SimpleNamespace(list_events=list_events))
    )
    for key, value in extra.items():
        setattr(policy, key, value)
    return policy


def _spec(**overrides: Any) -> AlertRepair:
    values: dict[str, Any] = {
        "fingerprint": "alertmanager:abc",
        "controller_id": "controller-1",
        "title": "DiskFull",
        "description": "disk nearly full",
        "repo": None,
        "project": None,
        "verification_labels": {},
        "maintenance_capability": None,
        "maintenance_parameters": {},
        "alert_context": AlertContext(),
    }
    values.update(overrides)
    return AlertRepair(**values)


def _snapshot(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "diagnosis_status": "valid",
        "safety_class": "reversible",
        "diagnosis_attempts": 1,
        "diagnosis_requested_count": 1,
        "diagnosis_completed_count": 1,
        "diagnosis_valid_count": 1,
        "execution_attempts": 1,
        "blocker": None,
        "proposed_action": "restart-service",
        "rollback": "restore-service",
    }
    values.update(overrides)
    return values


def test_latest_alert_diagnosis_result_falls_back_to_event_store() -> None:
    def failing_getter(_state: SimpleNamespace) -> dict[str, Any]:
        raise RuntimeError("getter unavailable")

    policy = _policy([_decision_event(), _result_event()], _latest_diagnosis_result=failing_getter)

    assert _latest_alert_diagnosis_result(policy, _STATE) == _VALID_RESULT


def test_latest_alert_diagnosis_result_requires_event_store() -> None:
    assert _latest_alert_diagnosis_result(SimpleNamespace(), _STATE) is None
    assert _latest_alert_diagnosis_result(_policy(raises=True), _STATE) is None
    assert _latest_alert_diagnosis_result(_policy([]), None) is None


def test_latest_alert_diagnosis_result_ignores_unmatched_events() -> None:
    policy = _policy(
        [
            _event("Other", {}),
            _event("ControllerDecisionSelected", {"decision": "not-a-dict"}),
            _decision_event(phase="execution"),
        ]
    )

    assert _latest_alert_diagnosis_result(policy, _STATE) is None


def test_latest_alert_diagnosis_result_requires_dict_payload() -> None:
    policy = _policy([_decision_event(), _result_event(result="plain text")])

    assert _latest_alert_diagnosis_result(policy, _STATE) is None


def test_fallback_policy_count_without_bridge_returns_zero() -> None:
    assert _policy_count(_policy([]), _STATE, "_execution_count", "execution") == 0


def test_structured_text_normalises_values() -> None:
    assert _structured_text("  padded  ") == "padded"
    assert _structured_text("   ") is None
    assert _structured_text(7) == "7"
    assert _structured_text(False) == "False"
    assert _structured_text({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'
    assert _structured_text(object()) is None


def test_first_structured_value_reads_metadata_fallback() -> None:
    source = {"metadata": {"next_action": "restart-service"}}

    assert _first_structured_value(source, ("next_action",)) == "restart-service"
    assert _first_structured_value({}, ("next_action",)) is None


def test_diagnosis_follow_up_prefers_result_fields() -> None:
    proposed, rollback = _diagnosis_follow_up(
        _policy([]),
        _STATE,
        {"proposed_action": "drain-node", "rollback": "uncordon-node"},
        _spec(maintenance_capability="restart-service"),
    )

    assert proposed == "drain-node"
    assert rollback == "uncordon-node"


def test_diagnosis_follow_up_uses_closure_then_capability() -> None:
    closure = {"selected_direction": {"action": "restart-service"}}

    proposed, rollback = _diagnosis_follow_up(
        _policy([_decision_event(closure=closure)]), _STATE, None, _spec()
    )

    assert proposed == '{"action": "restart-service"}'
    assert rollback is None

    fallback, _ = _diagnosis_follow_up(
        _policy([]), _STATE, None, _spec(maintenance_capability="restart-service")
    )
    assert fallback == "restart-service"

    unreachable, _ = _diagnosis_follow_up(
        _policy(raises=True), _STATE, None, _spec(maintenance_capability="restart-service")
    )
    assert unreachable == "restart-service"


def test_alert_diagnosis_snapshot_tolerates_failing_hooks() -> None:
    def failing(_state: SimpleNamespace) -> str:
        raise RuntimeError("policy hook unavailable")

    policy = _policy([], safety_class=failing, diagnosis_blocker=failing)

    snapshot = _alert_diagnosis_snapshot(policy, _STATE, _spec())

    assert snapshot["safety_class"] == "unknown"
    assert snapshot["blocker"] is None
    assert snapshot["diagnosis_status"] == "no_valid_diagnosis"
    assert snapshot["execution_attempts"] == 0


def test_alert_diagnosis_snapshot_counts_outcomes() -> None:
    events = [
        _decision_event(decision_id="d1"),
        _result_event(decision_ref="d1"),
        _decision_event(decision_id="d2"),
        _result_event(decision_ref="d2", result={"status": "failed", "message": "timeout"}),
        _decision_event(decision_id="d3", phase="execution"),
    ]
    policy = _policy(
        events,
        _diagnosis_count=lambda _state: 2,
        _execution_count=lambda _state: 3,
    )

    snapshot = _alert_diagnosis_snapshot(policy, _STATE, _spec())

    assert snapshot["diagnosis_status"] == "timeout"
    assert snapshot["diagnosis_completed_count"] == 2
    assert snapshot["diagnosis_valid_count"] == 1
    assert snapshot["execution_attempts"] == 0


def test_alert_diagnosis_snapshot_allows_effect_after_valid_diagnosis() -> None:
    events = [_decision_event(decision_id="d1"), _result_event(decision_ref="d1")]
    policy = _policy(
        events,
        _diagnosis_count=lambda _state: 1,
        _execution_count=lambda _state: 3,
    )

    snapshot = _alert_diagnosis_snapshot(policy, _STATE, _spec())

    assert snapshot["diagnosis_status"] == "valid"
    assert snapshot["execution_attempts"] == 3


def test_alert_escalation_reason_prefers_status_then_blocker() -> None:
    assert _alert_escalation_reason({"diagnosis_status": "timeout"}, "fallback") == "timeout"
    assert (
        _alert_escalation_reason(
            {"diagnosis_status": "valid", "blocker": "irreversible"}, "fallback"
        )
        == "irreversible"
    )
    assert _alert_escalation_reason({"diagnosis_status": "valid"}, "fallback") == "fallback"


def test_format_alert_escalation_covers_every_headline() -> None:
    context = AlertContext(
        status="firing",
        labels={
            "alertname": "DiskFull",
            "instance": "host-1",
            "path": "/var/lib",
            "project": "alpha",
        },
        annotations={"summary": "disk", "description": "nearly full", "detail": "85%"},
        observed_at="2026-09-21T00:00:00Z",
    )
    spec = _spec(alert_context=context)

    invalid = _format_alert_escalation(
        spec,
        work_id="work-1",
        controller_id="controller-1",
        controller_status="blocked",
        snapshot=_snapshot(diagnosis_status="timeout"),
    )
    assert "告警未获得有效 diagnosis (timeout)" in invalid
    assert "instance=host-1" in invalid
    assert "path=/var/lib" in invalid
    assert "project=alpha" in invalid
    assert "observed_at=2026-09-21T00:00:00Z" in invalid
    assert "继续命令: /task controller-1 <明确命令>" in invalid

    irreversible = _format_alert_escalation(
        spec,
        work_id="work-1",
        controller_id="controller-1",
        controller_status="blocked",
        snapshot=_snapshot(blocker="irreversible"),
    )
    assert "不可逆" in irreversible

    dirty = _format_alert_escalation(
        spec,
        work_id="work-1",
        controller_id="controller-1",
        controller_status="blocked",
        snapshot=_snapshot(blocker="dirty-repository"),
    )
    assert "目标仓库不干净" in dirty

    repeated = _format_alert_escalation(
        spec,
        work_id="work-1",
        controller_id="controller-1",
        controller_status="blocked",
        snapshot=_snapshot(diagnosis_attempts=2, execution_attempts=2),
    )
    assert "两轮有效 diagnosis 与执行" in repeated

    unresolved = _format_alert_escalation(
        spec,
        work_id="work-1",
        controller_id="controller-1",
        controller_status="blocked",
        snapshot=_snapshot(),
    )
    assert "已有有效 diagnosis 但仍未解除" in unresolved


def test_alert_fingerprint_prefers_supplied_value() -> None:
    assert _alert_fingerprint({"fingerprint": " abc "}) == "alertmanager:abc"


def test_alert_fingerprint_falls_back_to_stable_labels() -> None:
    fingerprint = _alert_fingerprint(
        {"labels": {"alertname": "DiskFull", "job": "node", "severity": "critical"}}
    )

    assert fingerprint.startswith("labels:")
    assert len(fingerprint) == len("labels:") + 64
