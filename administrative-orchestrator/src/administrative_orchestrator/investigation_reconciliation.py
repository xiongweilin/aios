from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from .config import Settings
from .domain import EffectStatus
from .execution_repository import ExecutionRepository
from .integrations.world_runtime import WorldRuntimeBoundaryError, WorldRuntimeBridge
from .persistence import SqlStore


class WorldRuntimeReconciliationVerificationError(RuntimeError):
    pass


class WorldRuntimeReconciliationVerifier(Protocol):
    def verify(
        self,
        case_id: UUID,
        authority_epoch: int,
        reconciliation_ref: str,
    ) -> None:
        """Prove that Runtime reconciliation reached a terminal provider result."""


class UnavailableWorldRuntimeReconciliationVerifier:
    def verify(
        self,
        case_id: UUID,
        authority_epoch: int,
        reconciliation_ref: str,
    ) -> None:
        del case_id, authority_epoch, reconciliation_ref
        raise WorldRuntimeReconciliationVerificationError(
            "World Runtime reconciliation verifier is unavailable"
        )


@dataclass(frozen=True, slots=True)
class LocalWorldRuntimeReconciliationVerifier:
    """Bind a caller reference to one persisted Administrative effect and Runtime attempt."""

    store: SqlStore
    settings: Settings

    def verify(
        self,
        case_id: UUID,
        authority_epoch: int,
        reconciliation_ref: str,
    ) -> None:
        reference = reconciliation_ref.strip()
        if not reference:
            raise WorldRuntimeReconciliationVerificationError(
                "World Runtime reconciliation reference must not be blank"
            )
        repository = ExecutionRepository(self.store)
        effects = repository.list_effects(case_id, authority_epoch)
        bridge = WorldRuntimeBridge(self.store, self.settings)
        try:
            effect = next(
                (
                    item
                    for item in effects
                    if reference
                    in {
                        bridge.request_ref_for_effect(item.effect_id),
                        item.provider_ref or "",
                    }
                    or reference.endswith(
                        ":" + bridge.request_ref_for_effect(item.effect_id)
                    )
                ),
                None,
            )
            if effect is None:
                raise WorldRuntimeReconciliationVerificationError(
                    "Runtime reconciliation reference is not bound to this case"
                )
            if effect.status is not EffectStatus.OUTCOME_UNKNOWN:
                raise WorldRuntimeReconciliationVerificationError(
                    "Runtime reconciliation reference is not an outcome-unknown target"
                )
            try:
                result = bridge.reconcile_effect(effect.effect_id)
            except WorldRuntimeBoundaryError as exc:
                raise WorldRuntimeReconciliationVerificationError(
                    "World Runtime reconciliation resolution is unavailable"
                ) from exc
        finally:
            bridge.close()

        status = str(result.get("status", "unknown"))
        if status not in {"succeeded", "failed"}:
            raise WorldRuntimeReconciliationVerificationError(
                "World Runtime reconciliation has not reached a terminal result"
            )


__all__ = [
    "LocalWorldRuntimeReconciliationVerifier",
    "UnavailableWorldRuntimeReconciliationVerifier",
    "WorldRuntimeReconciliationVerificationError",
    "WorldRuntimeReconciliationVerifier",
]
