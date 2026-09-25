from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .domain import EffectRecord
from .effect_provider import (
    ObservationAvailability,
    ObservationFreshness,
    ObservationPresence,
    RealityObservation,
)


class VerificationDisposition(StrEnum):
    VERIFIED = "verified"
    ABSENT = "absent"
    NOT_FOUND = "absent"  # compatibility alias
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    STALE = "stale"


class SemanticVerificationResult(BaseModel):
    disposition: VerificationDisposition
    reason: str
    differences: dict[str, Any] = Field(default_factory=dict)


def verify_onboarding_observation(
    effect: EffectRecord,
    observation: RealityObservation,
    facts: dict[str, Any] | None = None,
    *,
    expected_postcondition: dict[str, Any] | None = None,
) -> SemanticVerificationResult:
    """Verify fresh authoritative reality against a frozen business postcondition."""
    if observation.availability == ObservationAvailability.UNAVAILABLE:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.UNAVAILABLE,
            reason="authoritative reality source is currently unavailable",
        )
    if observation.availability == ObservationAvailability.UNKNOWN:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.UNKNOWN,
            reason="observation did not establish whether authoritative reality was available",
        )
    if observation.freshness == ObservationFreshness.STALE:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.STALE,
            reason="authoritative observation is stale",
        )
    if observation.freshness == ObservationFreshness.UNKNOWN:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.UNKNOWN,
            reason="authoritative observation freshness is unknown",
        )
    if observation.presence == ObservationPresence.ABSENT:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.ABSENT,
            reason="authoritative source explicitly reports that the realization is absent",
        )
    if observation.presence != ObservationPresence.PRESENT:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.UNKNOWN,
            reason="observation does not establish realization presence",
        )

    expected = expected_postcondition or _legacy_expected_postcondition(effect, facts or {})
    differences: dict[str, Any] = {}
    for field in ("target_system", "operation", "subject_ref"):
        expected_value = expected.get(field, getattr(effect, field))
        actual = getattr(observation, field)
        if actual != expected_value:
            differences[field] = {"expected": expected_value, "actual": actual}

    state = observation.state
    if "active" in expected and state.get("active") != expected["active"]:
        differences["active"] = {"expected": expected["active"], "actual": state.get("active")}

    expected_payload = expected.get("payload", {})
    payload = state.get("payload")
    if expected_payload:
        if not isinstance(payload, dict):
            differences["payload"] = {
                "expected": "mapping",
                "actual": type(payload).__name__,
            }
        else:
            for field, expected_value in expected_payload.items():
                if payload.get(field) != expected_value:
                    differences[f"payload.{field}"] = {
                        "expected": expected_value,
                        "actual": payload.get(field),
                    }

    if isinstance(payload, dict) and payload.get("employee_ref") != effect.subject_ref:
        differences["payload.employee_ref"] = {
            "expected": effect.subject_ref,
            "actual": payload.get("employee_ref"),
        }

    if expected.get("requested_system") is not None:
        requested = tuple((facts or {}).get("requested_systems") or ())
        expected_system = expected["requested_system"]
        if requested and expected_system not in requested:
            differences["requested_systems"] = {
                "expected_contains": expected_system,
                "actual": list(requested),
            }

    if differences:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.MISMATCH,
            reason="authoritative reality does not satisfy the frozen onboarding postcondition",
            differences=differences,
        )

    return SemanticVerificationResult(
        disposition=VerificationDisposition.VERIFIED,
        reason="fresh authoritative reality satisfies the frozen onboarding postcondition",
    )


def verify_financial_observation(
    effect: EffectRecord,
    observation: RealityObservation,
    facts: dict[str, Any] | None = None,
    *,
    expected_postcondition: dict[str, Any] | None = None,
) -> SemanticVerificationResult:
    """Verify a bounded ERP preparation result without permitting settlement."""
    del facts
    if observation.availability == ObservationAvailability.UNAVAILABLE:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.UNAVAILABLE,
            reason="authoritative ERP reality source is currently unavailable",
        )
    if observation.availability == ObservationAvailability.UNKNOWN:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.UNKNOWN,
            reason="ERP observation did not establish authoritative availability",
        )
    if observation.freshness == ObservationFreshness.STALE:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.STALE,
            reason="authoritative ERP observation is stale",
        )
    if observation.freshness == ObservationFreshness.UNKNOWN:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.UNKNOWN,
            reason="ERP observation freshness is unknown",
        )
    if observation.presence == ObservationPresence.ABSENT:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.ABSENT,
            reason="authoritative ERP source reports that the preparation is absent",
        )
    if observation.presence != ObservationPresence.PRESENT:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.UNKNOWN,
            reason="ERP observation does not establish preparation presence",
        )

    expected = expected_postcondition or {
        "target_system": effect.target_system,
        "operation": effect.operation,
        "subject_ref": effect.subject_ref,
    }
    differences: dict[str, Any] = {}
    for field in ("target_system", "operation", "subject_ref"):
        expected_value = expected.get(field, getattr(effect, field))
        actual = getattr(observation, field)
        if actual != expected_value:
            differences[field] = {"expected": expected_value, "actual": actual}

    state = observation.state
    expected_payload = expected.get("payload", {})
    payload = state.get("payload")
    if expected_payload:
        if not isinstance(payload, dict):
            differences["payload"] = {
                "expected": "mapping",
                "actual": type(payload).__name__,
            }
        else:
            for field, expected_value in expected_payload.items():
                if payload.get(field) != expected_value:
                    differences[f"payload.{field}"] = {
                        "expected": expected_value,
                        "actual": payload.get(field),
                    }

    if expected.get("settlement") == "forbidden":
        settlement = state.get("settlement")
        if settlement in {"paid", "settled", "executed"} or state.get(
            "settlement_executed"
        ) is True:
            differences["settlement"] = {
                "expected": "not settled",
                "actual": settlement or True,
            }

    if differences:
        return SemanticVerificationResult(
            disposition=VerificationDisposition.MISMATCH,
            reason="authoritative ERP reality does not satisfy the frozen preparation postcondition",
            differences=differences,
        )
    return SemanticVerificationResult(
        disposition=VerificationDisposition.VERIFIED,
        reason="fresh authoritative ERP reality satisfies the frozen preparation postcondition",
    )


def _legacy_expected_postcondition(effect: EffectRecord, facts: dict[str, Any]) -> dict[str, Any]:
    expected_payload = {
        field: facts.get(field)
        for field in (
            "employee_ref",
            "department_ref",
            "manager_principal_id",
            "start_date",
            "employment_type",
        )
        if facts.get(field) is not None
    }
    expected: dict[str, Any] = {
        "target_system": effect.target_system,
        "operation": effect.operation,
        "subject_ref": effect.subject_ref,
        "active": True,
        "payload": expected_payload,
    }
    if effect.operation == "account.provision":
        expected["requested_system"] = effect.target_system
    return expected


__all__ = [
    "SemanticVerificationResult",
    "VerificationDisposition",
    "verify_financial_observation",
    "verify_onboarding_observation",
]
