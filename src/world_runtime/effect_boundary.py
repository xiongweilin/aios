from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .common import new_id
from .execution import (
    CapabilityRequest,
    CapabilityResult,
    EffectIdentityReboundError,
    ExecutionService,
)
from .identity import AuthenticatedRequestContext
from .ledger import LedgerConcurrencyConflict, SemanticLedger


class DomainEffectBoundaryService:
    """Durable authorization boundary for Domain-owned providers.

    Runtime owns effect legality, identity and dispatch fencing. The Domain
    Controller owns the concrete provider and domain-specific outcome meaning.
    """

    def __init__(self, ledger: SemanticLedger, execution: ExecutionService) -> None:
        self.ledger = ledger
        self.execution = execution

    def prepare(
        self,
        request: CapabilityRequest,
        *,
        provider_id: str,
        provider_version: str,
        context: AuthenticatedRequestContext,
    ) -> dict[str, Any]:
        if request.effect_class in {"read", "read-only"}:
            raise ValueError("domain effect boundary accepts only reality-changing effects")
        if not request.idempotency_key:
            raise PermissionError("domain effect requires durable idempotency_key")
        if not provider_id.strip() or not provider_version.strip():
            raise ValueError("domain effect provider identity must be explicit")
        if request.principal != context.effective_principal:
            raise PermissionError("domain effect principal must equal authenticated effective principal")
        if request.actor_ref != context.authenticated_principal:
            raise PermissionError("domain effect actor_ref must equal authenticated principal")
        self._assert_attested_authorization(request, context)

        fingerprint = self.execution.validate_effect_identity(
            request,
            result_projection="execution.domain-effect-idempotency",
        )
        assert fingerprint is not None
        key = request.idempotency_key
        completed = self.ledger.project_get("execution.domain-effect-idempotency", key)
        attempt = self.ledger.project_get("execution.domain-effect-attempt", key)

        if attempt is not None:
            value = attempt[0]
            self._assert_attempt_binding(
                value,
                provider_id=provider_id,
                provider_version=provider_version,
                context=context,
                fingerprint=fingerprint,
            )
            result = completed[0] if completed is not None else None
            return self._grant_view(value, result=result)

        if completed is not None:
            raise EffectIdentityReboundError(
                "domain effect result exists without a durable attempt"
            )

        self.execution.prepare_invocation(
            request,
            authorization_required=True,
            record_authorization_use=False,
        )
        value = {
            "grant_id": new_id("effect-grant"),
            "idempotency_key": key,
            "request_id": request.id,
            "capability": request.capability,
            "provider_id": provider_id,
            "provider_version": provider_version,
            "effect_fingerprint": fingerprint,
            "effect_identity": request.model_dump(mode="json"),
            "authenticated_actor": context.authenticated_principal,
            "effective_principal": context.effective_principal,
            "status": "authorized",
            "dispatch_generation": 0,
        }
        try:
            with self.ledger.transaction():
                self.ledger.project_put(
                    "execution.domain-effect-attempt",
                    key,
                    value,
                    expected_version=0,
                )
                self.execution.bind_effect_identity(
                    request,
                    fingerprint=fingerprint,
                )
                self.ledger.append(
                    stream=f"domain-effect:{key}",
                    kind="execution.domain-effect.authorized",
                    payload={
                        "grant_id": value["grant_id"],
                        "request_id": request.id,
                        "capability": request.capability,
                        "provider_id": provider_id,
                        "effect_fingerprint": fingerprint,
                        "authenticated_actor": context.authenticated_principal,
                        "effective_principal": context.effective_principal,
                    },
                )
        except LedgerConcurrencyConflict:
            attempt = self.ledger.project_get("execution.domain-effect-attempt", key)
            if attempt is None:
                raise
            existing = attempt[0]
            self._assert_attempt_binding(
                existing,
                provider_id=provider_id,
                provider_version=provider_version,
                context=context,
                fingerprint=fingerprint,
            )
            completed = self.ledger.project_get("execution.domain-effect-idempotency", key)
            return self._grant_view(
                existing,
                result=completed[0] if completed is not None else None,
            )
        return self._grant_view(value)

    def start(
        self,
        idempotency_key: str,
        *,
        context: AuthenticatedRequestContext,
    ) -> dict[str, Any]:
        for start_attempt in range(3):
            try:
                with self.ledger.transaction():
                    current = self.ledger.project_get(
                        "execution.domain-effect-attempt",
                        idempotency_key,
                    )
                    if current is None:
                        raise KeyError(idempotency_key)
                    value, version = current
                    self._assert_actor(value, context)
                    if value.get("status") != "authorized":
                        raise PermissionError(
                            "domain effect dispatch is not fresh; reconcile instead of redispatching"
                        )

                    request = CapabilityRequest.model_validate(value["effect_identity"])
                    self.execution.prepare_invocation(
                        request,
                        authorization_required=True,
                        record_authorization_use=False,
                    )

                    started = dict(value)
                    started["status"] = "started"
                    started["dispatch_generation"] = int(
                        value.get("dispatch_generation", 0)
                    ) + 1
                    self.ledger.project_put(
                        "execution.domain-effect-attempt",
                        idempotency_key,
                        started,
                        expected_version=version,
                    )
                    if request.authorization_id:
                        self.execution.governance.record_use(
                            request.authorization_id,
                            effect_request_id=request.id,
                        )
                    self.ledger.append(
                        stream=f"domain-effect:{idempotency_key}",
                        kind="execution.domain-effect.started",
                        payload={
                            "grant_id": started["grant_id"],
                            "request_id": started["request_id"],
                            "dispatch_generation": started["dispatch_generation"],
                            "authenticated_actor": context.authenticated_principal,
                        },
                    )
                return self._grant_view(started, dispatch_allowed=True)
            except LedgerConcurrencyConflict as exc:
                latest = self.ledger.project_get(
                    "execution.domain-effect-attempt",
                    idempotency_key,
                )
                if latest is None:
                    raise KeyError(idempotency_key) from exc
                self._assert_actor(latest[0], context)
                if latest[0].get("status") != "authorized":
                    raise PermissionError(
                        "domain effect dispatch race lost; reconcile instead of redispatching"
                    ) from exc
                if start_attempt == 2:
                    raise PermissionError(
                        "domain effect dispatch could not acquire durable authority"
                    ) from exc
        raise AssertionError("unreachable domain effect start retry state")

    def record_result(
        self,
        idempotency_key: str,
        result: CapabilityResult,
        *,
        dispatch_generation: int,
        context: AuthenticatedRequestContext,
    ) -> CapabilityResult:
        current = self.ledger.project_get("execution.domain-effect-attempt", idempotency_key)
        if current is None:
            raise KeyError(idempotency_key)
        value, version = current
        self._assert_actor(value, context)
        expected_generation = int(value.get("dispatch_generation", 0))
        if dispatch_generation != expected_generation or dispatch_generation <= 0:
            raise PermissionError("domain effect result has stale dispatch generation")

        status = str(value.get("status", ""))
        existing = self.ledger.project_get("execution.domain-effect-idempotency", idempotency_key)
        if status == "committed":
            if existing is None:
                raise RuntimeError("committed domain effect is missing its durable result")
            stored = CapabilityResult(**existing[0])
            candidate = self._normalize_result(value, result)
            if stored.model_dump(mode="json") != candidate.model_dump(mode="json"):
                raise EffectIdentityReboundError("committed domain effect result rebound")
            return stored

        if status not in {"started", "ambiguous"}:
            raise PermissionError("domain effect result requires a started dispatch")

        normalized = self._normalize_result(value, result)
        if status == "ambiguous":
            if not normalized.reconciled or normalized.status == "unknown":
                raise PermissionError(
                    "ambiguous domain effect requires a reconciled final result"
                )
        elif normalized.status == "unknown" and normalized.reconciled:
            raise ValueError("unknown result cannot claim reconciliation")

        result_value = normalized.model_dump(mode="json")
        final_status = "ambiguous" if normalized.status == "unknown" else "committed"
        value["status"] = final_status

        try:
            with self.ledger.transaction():
                self.ledger.project_put(
                    "execution.domain-effect-attempt",
                    idempotency_key,
                    value,
                    expected_version=version,
                )
                self.ledger.project_put(
                    "execution.provider-result",
                    str(value["request_id"]),
                    result_value,
                )
                effect_identity = dict(value.get("effect_identity", {}))
                self.ledger.project_put(
                    "execution.provider-result-access",
                    str(value["request_id"]),
                    {
                        "request_id": str(value["request_id"]),
                        "principal": value.get("effective_principal"),
                        "authenticated_actor": value.get("authenticated_actor"),
                        "work_id": effect_identity.get("work_id"),
                        "run_id": effect_identity.get("run_id"),
                    },
                )
                if final_status == "committed":
                    self.ledger.project_put(
                        "execution.domain-effect-idempotency",
                        idempotency_key,
                        result_value,
                    )
                self.ledger.append(
                    stream=f"domain-effect:{idempotency_key}",
                    kind=(
                        "execution.domain-effect.reconciled"
                        if status == "ambiguous"
                        else "execution.domain-effect.result-observed"
                    ),
                    payload={
                        "grant_id": value["grant_id"],
                        "request_id": value["request_id"],
                        "provider_id": value["provider_id"],
                        "status": normalized.status,
                        "reconciled": normalized.reconciled,
                        "dispatch_generation": dispatch_generation,
                        "result": result_value,
                    },
                )
        except LedgerConcurrencyConflict as exc:
            latest = self.ledger.project_get(
                "execution.domain-effect-attempt",
                idempotency_key,
            )
            if latest is None:
                raise KeyError(idempotency_key) from exc
            self._assert_actor(latest[0], context)
            latest_result = self.ledger.project_get(
                "execution.provider-result",
                str(latest[0]["request_id"]),
            )
            if latest_result is not None:
                stored = CapabilityResult(**latest_result[0])
                candidate = self._normalize_result(latest[0], result)
                if stored.model_dump(mode="json") == candidate.model_dump(mode="json"):
                    return stored
            if latest[0].get("status") == "committed":
                raise EffectIdentityReboundError(
                    "committed domain effect result rebound"
                ) from exc
            raise PermissionError(
                "domain effect result race lost; reconcile current durable state"
            ) from exc
        return normalized

    def get(self, idempotency_key: str) -> dict[str, Any]:
        attempt = self.ledger.project_get("execution.domain-effect-attempt", idempotency_key)
        if attempt is None:
            raise KeyError(idempotency_key)
        result = self.ledger.project_get("execution.domain-effect-idempotency", idempotency_key)
        return self._grant_view(attempt[0], result=result[0] if result is not None else None)

    def _assert_attested_authorization(
        self,
        request: CapabilityRequest,
        context: AuthenticatedRequestContext,
    ) -> None:
        if not request.authorization_id:
            raise PermissionError("domain effect requires authorization")
        current = self.ledger.project_get(
            "governance.authorization",
            request.authorization_id,
        )
        if current is None:
            raise PermissionError("unknown authorization")
        attestation = current[0].get("issuer_attestation")
        if not isinstance(attestation, Mapping):
            raise PermissionError(
                "Authorization is not authenticated under Runtime Protocol 2.x"
            )
        if attestation.get("effective_principal") != context.effective_principal:
            raise PermissionError(
                "Authorization attestation does not match domain effect principal"
            )

    @staticmethod
    def _assert_actor(
        value: Mapping[str, Any],
        context: AuthenticatedRequestContext,
    ) -> None:
        if value.get("authenticated_actor") != context.authenticated_principal:
            raise PermissionError("domain effect attempt belongs to another authenticated actor")
        if value.get("effective_principal") != context.effective_principal:
            raise PermissionError("domain effect attempt belongs to another effective principal")

    def _assert_attempt_binding(
        self,
        value: Mapping[str, Any],
        *,
        provider_id: str,
        provider_version: str,
        context: AuthenticatedRequestContext,
        fingerprint: str,
    ) -> None:
        self._assert_actor(value, context)
        if value.get("provider_id") != provider_id or value.get("provider_version") != provider_version:
            raise EffectIdentityReboundError("domain effect provider identity rebound")
        if value.get("effect_fingerprint") != fingerprint:
            raise EffectIdentityReboundError("domain effect semantic identity rebound")

    @staticmethod
    def _normalize_result(
        attempt: Mapping[str, Any],
        result: CapabilityResult,
    ) -> CapabilityResult:
        request_id = str(attempt["request_id"])
        provider_id = str(attempt["provider_id"])
        if result.request_id and result.request_id != request_id:
            raise EffectIdentityReboundError("domain effect result request identity rebound")
        if result.provider_id and result.provider_id != provider_id:
            raise EffectIdentityReboundError("domain effect result provider identity rebound")
        return result.model_copy(
            update={
                "request_id": request_id,
                "provider_id": provider_id,
            }
        )

    @staticmethod
    def _grant_view(
        value: Mapping[str, Any],
        *,
        result: Mapping[str, Any] | None = None,
        dispatch_allowed: bool = False,
    ) -> dict[str, Any]:
        status = str(value.get("status", ""))
        return {
            "grant_id": str(value["grant_id"]),
            "idempotency_key": str(value["idempotency_key"]),
            "request_id": str(value["request_id"]),
            "provider_id": str(value["provider_id"]),
            "provider_version": str(value["provider_version"]),
            "status": status,
            "dispatch_generation": int(value.get("dispatch_generation", 0)),
            "start_allowed": status == "authorized",
            "dispatch_allowed": dispatch_allowed,
            "result": dict(result) if result is not None else None,
        }


__all__ = ["DomainEffectBoundaryService"]
