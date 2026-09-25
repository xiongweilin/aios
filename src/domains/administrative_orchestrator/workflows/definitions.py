from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from dbos import DBOS

from ..commitment_models import CommitmentState
from ..commitment_service import MeetingCommitmentService
from ..config import get_settings
from ..domain import CaseStatus, utcnow
from ..effect_provider import EffectProvider, HttpEffectProvider
from ..fact_acquisition import build_hris_source
from ..financial_execution import FINANCIAL_CASE_KINDS, FinancialExecutionEngine
from ..integrations.world_runtime import WorldRuntimeBridge, WorldRuntimeEffectProvider
from ..observability import record_responsibility_discharge
from ..offboarding_execution import (
    OffboardingExecutionEngine,
    ProductionTrustOffboardingExecutionEngine,
)
from ..onboarding_execution import OnboardingExecutionEngine
from ..persistence import SqlStore
from ..production_trust_execution import ProductionTrustOnboardingExecutionEngine
from ..responsibility_discharge import (
    AdministrativeResponsibilityDischargeService,
    ResponsibilityDischargeResult,
)
from ..service import authoritative_effective_time
from .protocol import (
    CASE_CHANGED_TOPIC,
    NORMAL_WAKE_TIMEOUT_SECONDS,
    RECONCILIATION_POLL_SECONDS,
)

TERMINAL_STATUSES = frozenset(
    {
        CaseStatus.COMPLETED.value,
        CaseStatus.CANCELLED.value,
        CaseStatus.FAILED.value,
    }
)


@DBOS.step(name="administrative_drive_onboarding_case")
def drive_onboarding_case_step(case_id: str) -> dict[str, Any]:
    """Drive one durable business transition with capability-scoped reality ownership."""
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)
    case = store.get_case(UUID(case_id))
    if case is None:
        raise ValueError(f"administrative case {case_id} not found")

    if case.status in {
        CaseStatus.AUTHORIZED,
        CaseStatus.EXECUTING,
        CaseStatus.VERIFYING,
        CaseStatus.RECONCILING,
    }:
        runtime_bridge: WorldRuntimeBridge | None = None
        if settings.world_runtime_mode != "disabled":
            runtime_bridge = WorldRuntimeBridge(store, settings)

        if not settings.external_effects_enabled:
            return {
                "case_id": case_id,
                "status": CaseStatus.WAITING.value,
                "case_version": case.version,
                "authority_epoch": case.authority_epoch,
                "reason": "external_effects_disabled",
            }
        provider: EffectProvider = HttpEffectProvider(
            settings.sandbox_base_url,
            timeout_seconds=settings.provider_timeout_seconds,
        )
        if runtime_bridge is not None and runtime_bridge.cutover:
            provider = WorldRuntimeEffectProvider(provider, runtime_bridge)

        if case.case_kind in FINANCIAL_CASE_KINDS:
            engine = FinancialExecutionEngine(store, provider)
        else:
            hris_source = build_hris_source(settings)
        if case.case_kind not in FINANCIAL_CASE_KINDS and hris_source is None:
            engine = OnboardingExecutionEngine(store, provider)
        elif case.case_kind not in FINANCIAL_CASE_KINDS:
            engine = ProductionTrustOnboardingExecutionEngine(
                store,
                provider,
                hris_source=hris_source,
                max_fact_age_seconds=settings.authoritative_fact_max_age_seconds,
            )
        case = engine.run(UUID(case_id))

    return {
        "case_id": case_id,
        "status": case.status.value,
        "case_version": case.version,
        "authority_epoch": case.authority_epoch,
    }


@DBOS.workflow(name="administrative_onboarding_case_v1")
def onboarding_case_workflow(*, case_id: str) -> dict[str, Any]:
    """Durably wait and re-drive one AdministrativeCase until terminal.

    DBOS owns waiting/replay only. AdministrativeCase remains the sole business
    state machine and all authority/effect semantics stay outside this module.
    """
    while True:
        state = drive_onboarding_case_step(case_id)
        status = str(state["status"])
        if status in TERMINAL_STATUSES:
            return state

        timeout = (
            RECONCILIATION_POLL_SECONDS
            if status == CaseStatus.RECONCILING.value
            else NORMAL_WAKE_TIMEOUT_SECONDS
        )
        DBOS.recv(topic=CASE_CHANGED_TOPIC, timeout_seconds=timeout)


@DBOS.step(name="administrative_drive_meeting_commitment_case")
def drive_meeting_commitment_case_step(case_id: str) -> dict[str, Any]:
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)
    service = MeetingCommitmentService(store, settings=settings)
    commitment = service.repository.get_commitment(UUID(case_id))
    case = store.get_case(UUID(case_id))
    if commitment is None or case is None:
        raise ValueError(f"meeting commitment case {case_id} not found")
    if commitment.state is CommitmentState.FULFILLED:
        if commitment.responsibility_ref:
            try:
                commitment = service.discharge_responsibility(UUID(case_id))
            except Exception as exc:  # fail closed; Kernel owns retry/reconciliation
                return {
                    "case_id": case_id,
                    "status": case.status.value,
                    "responsibility_status": "pending",
                    "responsibility_blocker": type(exc).__name__,
                }
        return {
            "case_id": case_id,
            "status": case.status.value,
            "commitment_state": commitment.state.value,
            "responsibility_status": (
                "discharged" if commitment.responsibility_transition_ref else "pending"
            ),
        }
    return service.drive(UUID(case_id))


@DBOS.workflow(name="administrative_meeting_commitment_case_v1")
def meeting_commitment_case_workflow(*, case_id: str) -> dict[str, Any]:
    while True:
        state = drive_meeting_commitment_case_step(case_id)
        if state.get("responsibility_status") == "discharged":
            return state
        if state.get("status") in {CaseStatus.CANCELLED.value, CaseStatus.FAILED.value}:
            return state
        DBOS.recv(topic=CASE_CHANGED_TOPIC, timeout_seconds=NORMAL_WAKE_TIMEOUT_SECONDS)


@DBOS.step(name="administrative_drive_offboarding_case")
def drive_offboarding_case_step(case_id: str) -> dict[str, Any]:
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)
    case = store.get_case(UUID(case_id))
    if case is None:
        raise ValueError(f"administrative case {case_id} not found")

    runtime_bridge: WorldRuntimeBridge | None = None
    provider: EffectProvider = HttpEffectProvider(
        settings.sandbox_base_url,
        timeout_seconds=settings.provider_timeout_seconds,
    )
    if settings.world_runtime_mode != "disabled":
        runtime_bridge = WorldRuntimeBridge(store, settings)
        if runtime_bridge.cutover:
            provider = WorldRuntimeEffectProvider(provider, runtime_bridge)

    hris_source = build_hris_source(settings)
    if hris_source is None:
        engine = OffboardingExecutionEngine(store, provider)
    else:
        engine = ProductionTrustOffboardingExecutionEngine(
            store,
            provider,
            hris_source=hris_source,
            max_fact_age_seconds=settings.authoritative_fact_max_age_seconds,
        )

    effective_at = authoritative_effective_time(case)
    before_effective = effective_at is not None and effective_at > utcnow()
    if settings.external_effects_enabled or before_effective:
        case = engine.run(UUID(case_id))
    elif case.status in {
        CaseStatus.AUTHORIZED,
        CaseStatus.WAITING,
        CaseStatus.EXECUTING,
        CaseStatus.VERIFYING,
        CaseStatus.RECONCILING,
    }:
        return {
            "case_id": case_id,
            "status": case.status.value,
            "case_version": case.version,
            "authority_epoch": case.authority_epoch,
            "reason": "external_effects_disabled",
            "next_qualified_action_at": effective_at.isoformat() if effective_at else None,
        }

    state: dict[str, Any] = {
        "case_id": case_id,
        "status": case.status.value,
        "case_version": case.version,
        "authority_epoch": case.authority_epoch,
        "next_qualified_action_at": effective_at.isoformat() if effective_at else None,
    }
    if case.status is CaseStatus.COMPLETED:
        if runtime_bridge is None:
            record_responsibility_discharge(result="pending")
            state.update(
                {
                    "responsibility_status": "pending",
                    "responsibility_blocker": "kernel_discharge_bridge_unavailable",
                }
            )
        else:
            discharge = AdministrativeResponsibilityDischargeService(store, runtime_bridge).discharge(
                case
            )
            record_responsibility_discharge(result=discharge.status.value)
            state.update(_responsibility_state(discharge))
    return state


@DBOS.workflow(name="administrative_offboarding_case_v1")
def offboarding_case_workflow(*, case_id: str) -> dict[str, Any]:
    while True:
        state = drive_offboarding_case_step(case_id)
        if _offboarding_is_terminal(state):
            return state
        timeout = _offboarding_wake_timeout(state)
        DBOS.recv(topic=CASE_CHANGED_TOPIC, timeout_seconds=timeout)


def _offboarding_wake_timeout(state: dict[str, Any]) -> float:
    status = str(state["status"])
    if status == CaseStatus.RECONCILING.value:
        return RECONCILIATION_POLL_SECONDS
    if status != CaseStatus.WAITING.value:
        return NORMAL_WAKE_TIMEOUT_SECONDS
    raw = state.get("next_qualified_action_at")
    if not isinstance(raw, str) or not raw:
        return NORMAL_WAKE_TIMEOUT_SECONDS
    try:
        target = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return NORMAL_WAKE_TIMEOUT_SECONDS
    seconds = (target - utcnow()).total_seconds()
    return max(0.1, seconds)


def _offboarding_is_terminal(state: dict[str, Any]) -> bool:
    status = str(state.get("status"))
    if status in {CaseStatus.CANCELLED.value, CaseStatus.FAILED.value}:
        return True
    return (
        status == CaseStatus.COMPLETED.value
        and state.get("responsibility_status") == "discharged"
    )


def _responsibility_state(result: ResponsibilityDischargeResult) -> dict[str, Any]:
    return {
        "responsibility_status": result.status.value,
        "responsibility_refs": list(result.responsibility_refs),
        "discharged_responsibility_refs": list(result.discharged_refs),
        "responsibility_assessment_refs": dict(result.assessment_refs),
        "responsibility_decision_refs": dict(result.decision_refs),
        "responsibility_transition_refs": dict(result.transition_refs),
        "completion_assessment": result.completion.model_dump(mode="json"),
        "responsibility_blocker": result.blocker,
    }


__all__ = [
    "drive_offboarding_case_step",
    "drive_onboarding_case_step",
    "offboarding_case_workflow",
    "_offboarding_is_terminal",
    "onboarding_case_workflow",
    "drive_meeting_commitment_case_step",
    "meeting_commitment_case_workflow",
    "_offboarding_wake_timeout",
]
