from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from administrative_orchestrator.domain import CaseStatus
from administrative_orchestrator.workflows import definitions
from administrative_orchestrator.workflows.protocol import (
    NORMAL_WAKE_TIMEOUT_SECONDS,
    RECONCILIATION_POLL_SECONDS,
)

_NOW = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)


def _settings(*, external: bool, runtime: str = "disabled"):
    return SimpleNamespace(
        worker_database_url=None,
        database_url="sqlite://",
        sandbox_base_url="http://sandbox",
        provider_timeout_seconds=1.0,
        world_runtime_mode=runtime,
        external_effects_enabled=external,
        authoritative_fact_max_age_seconds=300,
    )


def _case(status: CaseStatus):
    return SimpleNamespace(
        case_id=uuid4(),
        case_kind="employee-offboarding",
        status=status,
        version=4,
        authority_epoch=2,
    )


def test_drive_offboarding_rejects_missing_case(monkeypatch) -> None:
    monkeypatch.setattr(definitions, "get_settings", lambda: _settings(external=False))
    monkeypatch.setattr(
        definitions, "SqlStore", lambda url: SimpleNamespace(get_case=lambda case_id: None)
    )
    with pytest.raises(ValueError, match="not found"):
        definitions.drive_offboarding_case_step.__wrapped__(str(uuid4()))


def test_drive_offboarding_persists_future_wait_while_effects_disabled(
    monkeypatch,
) -> None:
    case = _case(CaseStatus.AUTHORIZED)
    waiting = _case(CaseStatus.WAITING)
    waiting.case_id = case.case_id
    store = SimpleNamespace(get_case=lambda case_id: case)
    calls: list[object] = []

    class _Engine:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

        def run(self, case_id):
            calls.append(case_id)
            return waiting

    monkeypatch.setattr(definitions, "get_settings", lambda: _settings(external=False))
    monkeypatch.setattr(definitions, "SqlStore", lambda url: store)
    monkeypatch.setattr(definitions, "OffboardingExecutionEngine", _Engine)
    monkeypatch.setattr(definitions, "build_hris_source", lambda settings: None)
    monkeypatch.setattr(definitions, "authoritative_effective_time", lambda value: _NOW + timedelta(hours=1))
    monkeypatch.setattr(definitions, "utcnow", lambda: _NOW)

    state = definitions.drive_offboarding_case_step.__wrapped__(str(case.case_id))

    assert state["status"] == CaseStatus.WAITING.value
    assert state["next_qualified_action_at"] == (_NOW + timedelta(hours=1)).isoformat()
    assert calls[-1] == case.case_id


def test_drive_offboarding_keeps_past_due_case_safe_when_effects_disabled(
    monkeypatch,
) -> None:
    case = _case(CaseStatus.WAITING)
    store = SimpleNamespace(get_case=lambda case_id: case)
    monkeypatch.setattr(definitions, "get_settings", lambda: _settings(external=False))
    monkeypatch.setattr(definitions, "SqlStore", lambda url: store)
    monkeypatch.setattr(definitions, "build_hris_source", lambda settings: None)
    monkeypatch.setattr(definitions, "authoritative_effective_time", lambda value: _NOW)
    monkeypatch.setattr(definitions, "utcnow", lambda: _NOW + timedelta(seconds=1))

    state = definitions.drive_offboarding_case_step.__wrapped__(str(case.case_id))

    assert state["status"] == CaseStatus.WAITING.value
    assert state["reason"] == "external_effects_disabled"


def test_drive_offboarding_selects_production_trust_and_runtime_cutover(
    monkeypatch,
) -> None:
    case = _case(CaseStatus.AUTHORIZED)
    completed = _case(CaseStatus.COMPLETED)
    completed.case_id = case.case_id
    store = SimpleNamespace(get_case=lambda case_id: case)
    provider = object()
    wrapped_provider = object()
    source = object()
    captured: dict[str, object] = {}

    class _Bridge:
        cutover = True

        def __init__(self, actual_store, settings):
            captured["bridge_store"] = actual_store
            captured["bridge_settings"] = settings

    class _ProductionEngine:
        def __init__(self, actual_store, actual_provider, **kwargs):
            captured["engine"] = (actual_store, actual_provider, kwargs)

        def run(self, case_id):
            return completed

    monkeypatch.setattr(
        definitions, "get_settings", lambda: _settings(external=True, runtime="cutover")
    )
    monkeypatch.setattr(definitions, "SqlStore", lambda url: store)
    monkeypatch.setattr(definitions, "HttpEffectProvider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(definitions, "WorldRuntimeBridge", _Bridge)
    monkeypatch.setattr(
        definitions,
        "WorldRuntimeEffectProvider",
        lambda actual, bridge: wrapped_provider,
    )
    monkeypatch.setattr(definitions, "build_hris_source", lambda settings: source)
    monkeypatch.setattr(
        definitions, "ProductionTrustOffboardingExecutionEngine", _ProductionEngine
    )
    monkeypatch.setattr(
        definitions,
        "AdministrativeResponsibilityDischargeService",
        lambda store, bridge: SimpleNamespace(
            discharge=lambda actual_case: SimpleNamespace(
                status=SimpleNamespace(value="discharged"),
                responsibility_refs=(),
                discharged_refs=(),
                assessment_refs=(),
                decision_refs=(),
                transition_refs=(),
                completion=SimpleNamespace(model_dump=lambda mode: {}),
                blocker=None,
            )
        ),
    )
    monkeypatch.setattr(definitions, "authoritative_effective_time", lambda value: _NOW)

    state = definitions.drive_offboarding_case_step.__wrapped__(str(case.case_id))

    assert state["status"] == CaseStatus.COMPLETED.value
    assert state["responsibility_status"] == "discharged"
    assert captured["bridge_store"] is store
    assert captured["engine"][1] is wrapped_provider
    assert captured["engine"][2]["hris_source"] is source


def test_offboarding_workflow_returns_terminal_state(monkeypatch) -> None:
    terminal = {
        "status": CaseStatus.COMPLETED.value,
        "case_id": "case:1",
        "responsibility_status": "discharged",
    }
    monkeypatch.setattr(definitions, "drive_offboarding_case_step", lambda case_id: terminal)
    assert definitions.offboarding_case_workflow.__wrapped__(case_id="case:1") == terminal


def test_completed_case_with_active_responsibilities_is_not_terminal() -> None:
    assert not definitions._offboarding_is_terminal(
        {
            "status": CaseStatus.COMPLETED.value,
            "responsibility_status": "pending",
        }
    )
    assert definitions._offboarding_is_terminal(
        {
            "status": CaseStatus.COMPLETED.value,
            "responsibility_status": "discharged",
        }
    )


def test_offboarding_timeout_fallbacks(monkeypatch) -> None:
    monkeypatch.setattr(definitions, "utcnow", lambda: _NOW)
    assert definitions._offboarding_wake_timeout(
        {"status": CaseStatus.RECONCILING.value}
    ) == RECONCILIATION_POLL_SECONDS
    assert definitions._offboarding_wake_timeout(
        {"status": CaseStatus.AUTHORIZED.value}
    ) == NORMAL_WAKE_TIMEOUT_SECONDS
    assert definitions._offboarding_wake_timeout(
        {"status": CaseStatus.WAITING.value, "next_qualified_action_at": "bad"}
    ) == NORMAL_WAKE_TIMEOUT_SECONDS
    assert definitions._offboarding_wake_timeout(
        {
            "status": CaseStatus.WAITING.value,
            "next_qualified_action_at": (_NOW - timedelta(seconds=1)).isoformat(),
        }
    ) == 0.1
