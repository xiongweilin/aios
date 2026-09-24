from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from uuid import uuid4


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class CapabilityAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class CapabilityBelief:
    capability_ref: str
    availability: CapabilityAvailability
    can_observe: tuple[str, ...] = ()
    cannot_establish: tuple[str, ...] = ()
    effect_class: str = "read-only"
    expected_cost: float = 0.0
    expected_latency: float = 0.0
    known_failure_modes: tuple[str, ...] = ()
    basis_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_ref.strip():
            raise ValueError("capability belief requires a capability_ref")
        if self.effect_class not in {"read-only", "internal-reversible", "external-effect"}:
            raise ValueError("invalid capability effect_class")
        if self.expected_cost < 0 or self.expected_latency < 0:
            raise ValueError("capability cost/latency cannot be negative")


@dataclass(frozen=True, slots=True)
class WorkingSelfModel:
    capabilities: tuple[CapabilityBelief, ...] = ()
    resources: tuple[tuple[str, float], ...] = ()
    known_blind_spots: tuple[str, ...] = ()
    basis_refs: tuple[str, ...] = ()
    version: int = 1
    id: str = field(default_factory=lambda: _new_id("self_model"))

    def capability(self, capability_ref: str) -> CapabilityBelief | None:
        return next(
            (item for item in self.capabilities if item.capability_ref == capability_ref),
            None,
        )

    def can_attempt(self, capability_ref: str) -> bool:
        belief = self.capability(capability_ref)
        return belief is not None and belief.availability is CapabilityAvailability.AVAILABLE


class SelfModelCalibrator:
    """Recalibrate capability beliefs without granting capability or execution authority."""

    def recalibrate(
        self,
        model: WorkingSelfModel,
        *,
        capability_ref: str,
        availability: CapabilityAvailability,
        evidence_ref: str,
        failure_mode: str | None = None,
    ) -> WorkingSelfModel:
        current = model.capability(capability_ref)
        if current is None:
            updated = CapabilityBelief(
                capability_ref=capability_ref,
                availability=availability,
                known_failure_modes=(failure_mode,) if failure_mode else (),
                basis_refs=(evidence_ref,),
            )
        else:
            failure_modes = current.known_failure_modes
            if failure_mode:
                failure_modes = tuple(dict.fromkeys((*failure_modes, failure_mode)))
            updated = replace(
                current,
                availability=availability,
                known_failure_modes=failure_modes,
                basis_refs=tuple(dict.fromkeys((*current.basis_refs, evidence_ref))),
            )
        capabilities = (
            *(item for item in model.capabilities if item.capability_ref != capability_ref),
            updated,
        )
        return replace(
            model,
            id=_new_id("self_model"),
            version=model.version + 1,
            capabilities=capabilities,
            basis_refs=tuple(dict.fromkeys((*model.basis_refs, evidence_ref))),
        )
