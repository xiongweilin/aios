from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import Field, model_validator

from .domain import EffectRecord, UtcModel, utcnow


class ProviderExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class ProviderExecutionResult(UtcModel):
    status: ProviderExecutionStatus
    provider_ref: str | None = None
    error: str | None = None
    retryable: bool = False


class ObservationAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ObservationPresence(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class ObservationFreshness(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


class RealityObservation(UtcModel):
    availability: ObservationAvailability = ObservationAvailability.AVAILABLE
    presence: ObservationPresence = ObservationPresence.UNKNOWN
    freshness: ObservationFreshness = ObservationFreshness.CURRENT
    target_system: str
    operation: str
    subject_ref: str
    provider_ref: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    digest: str | None = None
    observed_at: datetime = Field(default_factory=utcnow)
    error_class: str | None = None
    # Compatibility input/output for existing sandbox fixtures. Runtime
    # semantics must use availability/presence/freshness instead.
    found: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def map_legacy_found(cls, value: Any) -> Any:
        if isinstance(value, dict) and "presence" not in value and "found" in value:
            copied = dict(value)
            copied["presence"] = (
                ObservationPresence.PRESENT.value
                if copied.get("found") is True
                else ObservationPresence.ABSENT.value
            )
            copied.setdefault("availability", ObservationAvailability.AVAILABLE.value)
            copied.setdefault("freshness", ObservationFreshness.CURRENT.value)
            return copied
        return value

    @model_validator(mode="after")
    def fill_legacy_found(self) -> RealityObservation:
        if self.found is None:
            if self.presence == ObservationPresence.PRESENT:
                self.found = True
            elif self.presence == ObservationPresence.ABSENT:
                self.found = False
        return self


class EffectProvider(Protocol):
    def execute(self, effect: EffectRecord, payload: dict[str, Any]) -> ProviderExecutionResult: ...

    def observe(self, effect: EffectRecord) -> RealityObservation: ...


class HttpEffectProvider:
    """Typed HTTP boundary to a distinct authoritative sandbox/service plane."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def execute(self, effect: EffectRecord, payload: dict[str, Any]) -> ProviderExecutionResult:
        try:
            response = httpx.put(
                f"{self.base_url}/v1/effects/{effect.effect_id}",
                json={
                    "target_system": effect.target_system,
                    "operation": effect.operation,
                    "subject_ref": effect.subject_ref,
                    "payload": payload,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.OUTCOME_UNKNOWN,
                error=str(exc),
                retryable=False,
            )
        except httpx.HTTPStatusError as exc:
            return ProviderExecutionResult(
                status=ProviderExecutionStatus.FAILED,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
                retryable=500 <= exc.response.status_code < 600,
            )

        data = response.json()
        return ProviderExecutionResult(
            status=ProviderExecutionStatus(data.get("status", "succeeded")),
            provider_ref=data.get("provider_ref"),
            error=data.get("error"),
            retryable=bool(data.get("retryable", False)),
        )

    def observe(self, effect: EffectRecord) -> RealityObservation:
        try:
            response = httpx.get(
                f"{self.base_url}/v1/effects/{effect.effect_id}",
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return RealityObservation(
                availability=ObservationAvailability.UNAVAILABLE,
                presence=ObservationPresence.UNKNOWN,
                freshness=ObservationFreshness.UNKNOWN,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                error_class=type(exc).__name__,
            )

        if response.status_code == 404:
            return RealityObservation(
                availability=ObservationAvailability.AVAILABLE,
                presence=ObservationPresence.ABSENT,
                freshness=ObservationFreshness.CURRENT,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return RealityObservation(
                availability=ObservationAvailability.UNAVAILABLE,
                presence=ObservationPresence.UNKNOWN,
                freshness=ObservationFreshness.UNKNOWN,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                error_class=f"http_{exc.response.status_code}",
            )

        try:
            return RealityObservation.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            return RealityObservation(
                availability=ObservationAvailability.UNKNOWN,
                presence=ObservationPresence.UNKNOWN,
                freshness=ObservationFreshness.UNKNOWN,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
                error_class=type(exc).__name__,
            )


__all__ = [
    "EffectProvider",
    "HttpEffectProvider",
    "ObservationAvailability",
    "ObservationFreshness",
    "ObservationPresence",
    "ProviderExecutionResult",
    "ProviderExecutionStatus",
    "RealityObservation",
]
