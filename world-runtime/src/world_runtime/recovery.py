from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .execution import (
    CapabilityResult,
    ProviderRegistry,
    ReconciliationContract,
    reconciliation_contract_for,
)
from .ledger import SemanticLedger


class RecoveryDispositionKind(StrEnum):
    RECONCILE = "reconcile"
    REQUIRE_MANUAL = "require-manual-resolution"


class RecoveryResolutionStatus(StrEnum):
    MANUAL_REQUIRED = "manual-resolution-required"
    RECOVERY_UNAVAILABLE = "recovery-unavailable"
    RECOVERED_SUCCEEDED = "recovered-succeeded"
    RECOVERED_FAILED = "recovered-failed"


@dataclass(frozen=True, slots=True)
class RecoveryDisposition:
    id: str
    idempotency_key: str
    request_id: str
    provider_id: str
    kind: RecoveryDispositionKind
    reason: str


@dataclass(frozen=True, slots=True)
class RecoveryResolution:
    id: str
    idempotency_key: str
    request_id: str
    provider_id: str
    disposition_ref: str
    application_ref: str
    status: RecoveryResolutionStatus
    result: dict[str, Any] | None = None
    reason: str = ""


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()[:32]}"


class RecoveryService:
    """Durable provider-level recovery for one exact historical attempt.

    Recovery never grants a fresh invoke. It may query only the provider recorded
    on the historical attempt, and it never manufactures a domain Outcome.
    """

    def __init__(self, ledger: SemanticLedger, registry: ProviderRegistry) -> None:
        self.ledger = ledger
        self.registry = registry

    def classify(self, idempotency_key: str) -> RecoveryDisposition:
        existing = self.ledger.project_get("recovery.disposition", idempotency_key)
        if existing is not None:
            return self._disposition_from_value(existing[0])

        attempt = self._attempt(idempotency_key)
        provider_id = str(attempt["provider_id"])
        request_id = str(attempt["request_id"])
        raw_historical_contract = attempt.get("reconciliation_contract")
        historical_contract = (
            ReconciliationContract.model_validate(raw_historical_contract)
            if isinstance(raw_historical_contract, dict)
            else None
        )
        try:
            provider = self.registry.get(provider_id)
        except KeyError:
            kind = RecoveryDispositionKind.REQUIRE_MANUAL
            reason = "historical provider is not registered"
        else:
            current_contract = reconciliation_contract_for(provider.descriptor)
            if historical_contract is None:
                kind = RecoveryDispositionKind.REQUIRE_MANUAL
                reason = "historical dispatch has no reconciliation contract"
            elif current_contract is None:
                kind = RecoveryDispositionKind.REQUIRE_MANUAL
                reason = "current provider has no reconciliation contract"
            elif historical_contract != current_contract:
                kind = RecoveryDispositionKind.REQUIRE_MANUAL
                reason = "reconciliation contract drifted from historical dispatch"
            elif historical_contract.repeatability_mode != "repeat-safe":
                kind = RecoveryDispositionKind.REQUIRE_MANUAL
                reason = "historical reconciliation contract is not repeat-safe"
            elif not callable(getattr(provider, "reconcile", None)):
                kind = RecoveryDispositionKind.REQUIRE_MANUAL
                reason = "historical provider exposes no reconciliation capability"
            else:
                kind = RecoveryDispositionKind.RECONCILE
                reason = "historical repeat-safe reconciliation contract matches current provider"

        disposition = RecoveryDisposition(
            id=_stable_id(
                "recovery-disposition",
                idempotency_key,
                request_id,
                provider_id,
                kind.value,
            ),
            idempotency_key=idempotency_key,
            request_id=request_id,
            provider_id=provider_id,
            kind=kind,
            reason=reason,
        )
        value = self._disposition_value(disposition)
        with self.ledger.transaction():
            self.ledger.project_put(
                "recovery.disposition",
                idempotency_key,
                value,
            )
            self.ledger.append(
                stream=f"recovery:{idempotency_key}",
                kind="recovery.disposition.recorded",
                payload=value,
            )
        return disposition

    def inspect(self, idempotency_key: str) -> RecoveryResolution | None:
        row = self.ledger.project_get("recovery.resolution", idempotency_key)
        if row is None:
            return None
        return self._resolution_from_value(row[0])

    async def recover(self, idempotency_key: str) -> CapabilityResult:
        completed = self.ledger.project_get(
            "execution.provider-idempotency",
            idempotency_key,
        )
        if completed is not None:
            return CapabilityResult(**completed[0])

        resolution = self.inspect(idempotency_key)
        if resolution is not None:
            return self._result_from_resolution(resolution)

        disposition = self.classify(idempotency_key)
        application_ref = _stable_id(
            "recovery-application",
            disposition.id,
            disposition.request_id,
        )
        application = self.ledger.project_get(
            "recovery.application",
            idempotency_key,
        )
        if application is not None:
            return CapabilityResult(
                request_id=disposition.request_id,
                provider_id=disposition.provider_id,
                status="unknown",
                error={
                    "code": "AmbiguousRecoveryApplication",
                    "message": (
                        "a durable recovery application already crossed or may have crossed "
                        "the reconciliation boundary; automatic repetition is forbidden"
                    ),
                },
                metadata={
                    "recovery_disposition_ref": disposition.id,
                    "recovery_application_ref": str(application[0]["id"]),
                },
            )

        application_value = {
            "id": application_ref,
            "idempotency_key": idempotency_key,
            "disposition_ref": disposition.id,
            "request_id": disposition.request_id,
            "provider_id": disposition.provider_id,
            "kind": disposition.kind.value,
            "status": "started",
        }
        with self.ledger.transaction():
            self.ledger.project_put(
                "recovery.application",
                idempotency_key,
                application_value,
            )
            self.ledger.append(
                stream=f"recovery:{idempotency_key}",
                kind="recovery.application.started",
                payload=application_value,
            )

        if disposition.kind is RecoveryDispositionKind.REQUIRE_MANUAL:
            resolution = self._commit_resolution(
                disposition,
                application_ref,
                RecoveryResolutionStatus.MANUAL_REQUIRED,
                reason=disposition.reason,
            )
            return self._result_from_resolution(resolution)

        provider = self.registry.get(disposition.provider_id)
        reconcile = getattr(provider, "reconcile", None)
        if not callable(reconcile):
            resolution = self._commit_resolution(
                disposition,
                application_ref,
                RecoveryResolutionStatus.MANUAL_REQUIRED,
                reason="historical provider reconciliation capability disappeared",
            )
            return self._result_from_resolution(resolution)

        try:
            result = await reconcile(disposition.request_id)
        except Exception as exc:
            resolution = self._commit_resolution(
                disposition,
                application_ref,
                RecoveryResolutionStatus.RECOVERY_UNAVAILABLE,
                reason=f"reconciliation failed: {exc}",
            )
            return self._result_from_resolution(resolution)

        if result is None or result.status not in {"succeeded", "failed"}:
            resolution = self._commit_resolution(
                disposition,
                application_ref,
                RecoveryResolutionStatus.RECOVERY_UNAVAILABLE,
                reason="reconciliation did not establish a terminal provider result",
            )
            return self._result_from_resolution(resolution)

        if not result.request_id:
            result = result.model_copy(update={"request_id": disposition.request_id})
        if not result.provider_id:
            result = result.model_copy(update={"provider_id": disposition.provider_id})
        result = result.model_copy(update={"reconciled": True})
        status = (
            RecoveryResolutionStatus.RECOVERED_SUCCEEDED
            if result.status == "succeeded"
            else RecoveryResolutionStatus.RECOVERED_FAILED
        )
        resolution = self._commit_resolution(
            disposition,
            application_ref,
            status,
            result=result,
        )
        return self._result_from_resolution(resolution)

    def _commit_resolution(
        self,
        disposition: RecoveryDisposition,
        application_ref: str,
        status: RecoveryResolutionStatus,
        *,
        result: CapabilityResult | None = None,
        reason: str = "",
    ) -> RecoveryResolution:
        resolution = RecoveryResolution(
            id=_stable_id(
                "recovery-resolution",
                disposition.id,
                application_ref,
                status.value,
            ),
            idempotency_key=disposition.idempotency_key,
            request_id=disposition.request_id,
            provider_id=disposition.provider_id,
            disposition_ref=disposition.id,
            application_ref=application_ref,
            status=status,
            result=result.model_dump(mode="json") if result is not None else None,
            reason=reason,
        )
        value = self._resolution_value(resolution)
        with self.ledger.transaction():
            self.ledger.project_put(
                "recovery.resolution",
                disposition.idempotency_key,
                value,
            )
            current_application = self.ledger.project_get(
                "recovery.application",
                disposition.idempotency_key,
            )
            if current_application is not None:
                application_value, application_version = current_application
                application_value["status"] = "completed"
                application_value["resolution_ref"] = resolution.id
                self.ledger.project_put(
                    "recovery.application",
                    disposition.idempotency_key,
                    application_value,
                    expected_version=application_version,
                )
            if result is not None:
                result_value = result.model_dump(mode="json")
                self.ledger.project_put(
                    "execution.provider-result",
                    disposition.request_id,
                    result_value,
                )
                self.ledger.project_put(
                    "execution.provider-idempotency",
                    disposition.idempotency_key,
                    result_value,
                )
                attempt = self.ledger.project_get(
                    "execution.provider-attempt",
                    disposition.idempotency_key,
                )
                if attempt is not None:
                    attempt_value, attempt_version = attempt
                    attempt_value["status"] = "committed"
                    attempt_value["recovery_resolution_ref"] = resolution.id
                    self.ledger.project_put(
                        "execution.provider-attempt",
                        disposition.idempotency_key,
                        attempt_value,
                        expected_version=attempt_version,
                    )
            self.ledger.append(
                stream=f"recovery:{disposition.idempotency_key}",
                kind="recovery.resolution.recorded",
                payload=value,
            )
        return resolution

    def _attempt(self, idempotency_key: str) -> dict[str, Any]:
        attempt = self.ledger.project_get(
            "execution.provider-attempt",
            idempotency_key,
        )
        if attempt is None:
            raise KeyError("provider attempt not found")
        return attempt[0]

    @staticmethod
    def _result_from_resolution(resolution: RecoveryResolution) -> CapabilityResult:
        if resolution.result is not None:
            return CapabilityResult(**resolution.result)
        code = (
            "ManualResolutionRequired"
            if resolution.status is RecoveryResolutionStatus.MANUAL_REQUIRED
            else "RecoveryUnavailable"
        )
        return CapabilityResult(
            request_id=resolution.request_id,
            provider_id=resolution.provider_id,
            status="unknown",
            error={"code": code, "message": resolution.reason},
            metadata={
                "recovery_disposition_ref": resolution.disposition_ref,
                "recovery_application_ref": resolution.application_ref,
                "recovery_resolution_ref": resolution.id,
                "recovery_status": resolution.status.value,
            },
        )

    @staticmethod
    def _disposition_value(value: RecoveryDisposition) -> dict[str, Any]:
        return {
            "id": value.id,
            "idempotency_key": value.idempotency_key,
            "request_id": value.request_id,
            "provider_id": value.provider_id,
            "kind": value.kind.value,
            "reason": value.reason,
        }

    @staticmethod
    def _disposition_from_value(value: dict[str, Any]) -> RecoveryDisposition:
        return RecoveryDisposition(
            id=str(value["id"]),
            idempotency_key=str(value["idempotency_key"]),
            request_id=str(value["request_id"]),
            provider_id=str(value["provider_id"]),
            kind=RecoveryDispositionKind(str(value["kind"])),
            reason=str(value.get("reason", "")),
        )

    @staticmethod
    def _resolution_value(value: RecoveryResolution) -> dict[str, Any]:
        return {
            "id": value.id,
            "idempotency_key": value.idempotency_key,
            "request_id": value.request_id,
            "provider_id": value.provider_id,
            "disposition_ref": value.disposition_ref,
            "application_ref": value.application_ref,
            "status": value.status.value,
            "result": value.result,
            "reason": value.reason,
        }

    @staticmethod
    def _resolution_from_value(value: dict[str, Any]) -> RecoveryResolution:
        raw_result = value.get("result")
        return RecoveryResolution(
            id=str(value["id"]),
            idempotency_key=str(value["idempotency_key"]),
            request_id=str(value["request_id"]),
            provider_id=str(value["provider_id"]),
            disposition_ref=str(value["disposition_ref"]),
            application_ref=str(value["application_ref"]),
            status=RecoveryResolutionStatus(str(value["status"])),
            result=dict(raw_result) if isinstance(raw_result, dict) else None,
            reason=str(value.get("reason", "")),
        )


__all__ = [
    "RecoveryDisposition",
    "RecoveryDispositionKind",
    "RecoveryResolution",
    "RecoveryResolutionStatus",
    "RecoveryService",
]
