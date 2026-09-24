from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from semantic_language import Authorization, Mandate, Revision, SemanticKind, SemanticRef

from .common import new_id, utcnow
from .decisions import assert_decision_applies
from .identity import AuthenticatedRequestContext
from .ledger import SemanticLedger
from .lineage import RevisionLineageService


def _parse_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _matches_constraint(specification: object, actual: str) -> bool:
    if specification == "*":
        return True
    if isinstance(specification, str):
        return specification == actual
    if isinstance(specification, (list, tuple, set, frozenset)):
        return any(_matches_constraint(item, actual) for item in specification)
    return False


def _assert_current_mandate_value(value: Mapping[str, Any]) -> None:
    if value.get("status") != "active":
        raise PermissionError("mandate is not active")
    expires_at = _parse_datetime(value.get("expires_at"))
    if expires_at is not None and expires_at <= utcnow():
        raise PermissionError("mandate has expired")


def assert_mandate_current(
    ledger: SemanticLedger,
    mandate_id: str,
) -> Mapping[str, Any]:
    try:
        RevisionLineageService(ledger).assert_current(
            SemanticRef(SemanticKind.MANDATE, mandate_id)
        )
    except ValueError as exc:
        raise PermissionError("mandate has been superseded") from exc
    row = ledger.project_get("governance.mandate", mandate_id)
    if row is None:
        raise PermissionError("required mandate is not recorded")
    value = row[0]
    _assert_current_mandate_value(value)
    return value


def _assert_scope_allows(mandate: Mapping[str, Any], resource: str) -> None:
    scope = dict(mandate.get("scope", {}))
    explicit = None
    if "resource" in scope:
        explicit = scope["resource"]
    elif "resources" in scope:
        explicit = scope["resources"]
    if explicit is not None and not _matches_constraint(explicit, resource):
        raise PermissionError("resource is outside mandate scope")


def _assert_authority_ceiling(
    mandate: Mapping[str, Any],
    *,
    action: str,
    resource: str,
) -> None:
    ceiling = dict(mandate.get("authority_ceiling", {}))
    if not ceiling:
        raise PermissionError("mandate delegates no executable effect authority")

    recognized = False
    if "action" in ceiling:
        recognized = True
        if not _matches_constraint(ceiling["action"], action):
            raise PermissionError("action exceeds mandate authority ceiling")
    if "actions" in ceiling:
        recognized = True
        if not _matches_constraint(ceiling["actions"], action):
            raise PermissionError("action exceeds mandate authority ceiling")
    if "resource" in ceiling:
        recognized = True
        if not _matches_constraint(ceiling["resource"], resource):
            raise PermissionError("resource exceeds mandate authority ceiling")
    if "resources" in ceiling:
        recognized = True
        if not _matches_constraint(ceiling["resources"], resource):
            raise PermissionError("resource exceeds mandate authority ceiling")
    if action in ceiling:
        recognized = True
        if not _matches_constraint(ceiling[action], resource):
            raise PermissionError("resource exceeds action-specific authority ceiling")

    if not recognized:
        raise PermissionError("mandate authority ceiling has no executable rule for requested action")


def _context_value(context: Mapping[str, Any], path: str) -> object:
    value: object = context
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _validate_conditions(conditions: Mapping[str, Any]) -> None:
    if not conditions:
        return
    if set(conditions) != {"required_context"}:
        raise PermissionError(
            "authorization conditions must use executable required_context semantics"
        )
    required = conditions.get("required_context")
    if not isinstance(required, Mapping):
        raise PermissionError(
            "authorization conditions must use executable required_context semantics"
        )
    if any(not str(path).strip() for path in required):
        raise PermissionError("authorization condition path must be non-empty")


def _assert_conditions(
    conditions: Mapping[str, Any],
    *,
    context: Mapping[str, Any] | None,
) -> None:
    _validate_conditions(conditions)
    if not conditions:
        return
    required = conditions["required_context"]
    available = context or {}
    for path, expected in required.items():
        if _context_value(available, str(path)) != expected:
            raise PermissionError(f"authorization condition is not satisfied: {path}")


class GovernanceService:
    def __init__(
        self,
        ledger: SemanticLedger,
        lineage: RevisionLineageService | None = None,
    ) -> None:
        self.ledger = ledger
        self.lineage = lineage or RevisionLineageService(ledger)

    def register_mandate_attested(
        self,
        mandate: Mandate,
        *,
        context: AuthenticatedRequestContext,
    ) -> None:
        if mandate.principal != context.effective_principal:
            raise PermissionError(
                "Mandate.principal must equal the authenticated effective principal"
            )
        self._register_mandate(mandate, attestation=context.attestation())

    def register_mandate(self, mandate: Mandate) -> None:
        self._register_mandate(mandate, attestation=None)

    def _register_mandate(
        self,
        mandate: Mandate,
        *,
        attestation: Mapping[str, Any] | None,
    ) -> None:
        value = {
            "id": mandate.id,
            "principal": mandate.principal,
            "scope": dict(mandate.scope),
            "authority_ceiling": dict(mandate.authority_ceiling),
            "expires_at": mandate.expires_at.isoformat() if mandate.expires_at else None,
            "status": "active",
        }
        existing = self.ledger.project_get("governance.mandate", mandate.id)
        if existing is not None:
            existing_attestation = existing[0].get("issuer_attestation")
            existing_identity = {
                key: existing[0].get(key)
                for key in (
                    "id",
                    "principal",
                    "scope",
                    "authority_ceiling",
                    "expires_at",
                )
            }
            incoming_identity = {
                key: value.get(key)
                for key in (
                    "id",
                    "principal",
                    "scope",
                    "authority_ceiling",
                    "expires_at",
                )
            }
            if existing_identity != incoming_identity:
                raise ValueError("mandate identity rebound")
            if attestation is not None:
                if not isinstance(existing_attestation, Mapping):
                    raise PermissionError(
                        "unattested historical Mandate cannot be adopted by replay"
                    )
                if existing_attestation.get("effective_principal") != attestation.get(
                    "effective_principal"
                ):
                    raise PermissionError(
                        "Mandate replay principal differs from original attestation"
                    )
            return
        if attestation is not None:
            value["issuer_attestation"] = dict(attestation)
        with self.ledger.transaction():
            self.ledger.project_put("governance.mandate", mandate.id, value)
            self.ledger.append(
                stream=f"mandate:{mandate.id}",
                kind="governance.mandate.registered",
                payload=value,
            )

    def revoke_mandate(self, mandate_id: str, *, reason: str) -> None:
        if not reason.strip():
            raise ValueError("mandate revocation requires reason")
        current = self.ledger.project_get("governance.mandate", mandate_id)
        if current is None:
            raise KeyError(mandate_id)
        value, version = current
        if value.get("status") == "revoked":
            if value.get("revocation_reason") != reason:
                raise ValueError("mandate revocation identity rebound")
            return
        updated = dict(value)
        updated["status"] = "revoked"
        updated["revocation_reason"] = reason
        with self.ledger.transaction():
            self.ledger.project_put(
                "governance.mandate",
                mandate_id,
                updated,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"mandate:{mandate_id}",
                kind="governance.mandate.revoked",
                payload={
                    "mandate_id": mandate_id,
                    "reason": reason,
                },
            )

    def supersede_mandate(
        self,
        previous_id: str,
        successor: Mandate,
        revision: Revision,
        *,
        context: AuthenticatedRequestContext | None = None,
    ) -> None:
        previous_ref = SemanticRef(SemanticKind.MANDATE, previous_id)
        if revision.supersedes_ref != previous_ref:
            raise ValueError("Mandate Revision must supersede the selected Mandate")
        if revision.target_ref != successor.ref:
            raise ValueError("Mandate Revision target must be the successor Mandate")

        previous_row = self.ledger.project_get("governance.mandate", previous_id)
        if previous_row is None:
            raise KeyError(previous_id)
        previous, previous_version = previous_row
        _assert_current_mandate_value(previous)
        self.lineage.assert_current(previous_ref)
        if str(previous.get("principal", "")) != successor.principal:
            raise PermissionError("Mandate supersession cannot transfer principal authority")
        if context is not None and context.effective_principal != successor.principal:
            raise PermissionError(
                "Mandate successor principal must equal authenticated effective principal"
            )

        updated_previous = dict(previous)
        updated_previous["status"] = "revoked"
        updated_previous["revocation_reason"] = f"superseded:{successor.id}"
        updated_previous["superseded_by"] = successor.id
        updated_previous["revision_id"] = revision.id

        with self.ledger.transaction():
            if context is None:
                self.register_mandate(successor)
            else:
                self.register_mandate_attested(successor, context=context)
            self.lineage.record(revision)
            self.ledger.project_put(
                "governance.mandate",
                previous_id,
                updated_previous,
                expected_version=previous_version,
            )
            self.ledger.append(
                stream=f"mandate:{previous_id}",
                kind="governance.mandate.superseded",
                payload={
                    "successor_id": successor.id,
                    "revision_id": revision.id,
                    "basis_refs": [ref.id for ref in revision.basis_refs],
                },
            )

    def get_current_mandate(self, mandate_id: str) -> Mapping[str, Any]:
        current = self.lineage.resolve_current(
            SemanticRef(SemanticKind.MANDATE, mandate_id)
        )
        return assert_mandate_current(self.ledger, current.id)

    def issue_authorization_attested(
        self,
        *,
        context: AuthenticatedRequestContext,
        principal: str,
        action: str,
        resource: str,
        mandate_id: str,
        decision_id: str,
        conditions: Mapping[str, Any] | None = None,
        annotations: Mapping[str, Any] | None = None,
        expires_at: datetime | None = None,
        authorization_id: str | None = None,
    ) -> Authorization:
        mandate = assert_mandate_current(self.ledger, mandate_id)
        mandate_attestation = mandate.get("issuer_attestation")
        if not isinstance(mandate_attestation, Mapping):
            raise PermissionError("Mandate is not authenticated under Runtime Protocol 2.0")
        if mandate_attestation.get("effective_principal") != context.effective_principal:
            raise PermissionError("Mandate attestation does not match authorization issuer")
        if str(mandate.get("principal", "")) != context.effective_principal:
            raise PermissionError(
                "Authorization issuer must be the authenticated Mandate principal"
            )
        decision = self.ledger.project_get("decision.current", decision_id)
        if decision is None:
            raise PermissionError("required decision is not recorded")
        decision_attestation = decision[0].get("attestation")
        if not isinstance(decision_attestation, Mapping):
            raise PermissionError("Decision is not authenticated under Runtime Protocol 2.0")
        if decision_attestation.get("effective_principal") != context.effective_principal:
            raise PermissionError("Decision attestation does not match authorization issuer")
        return self._issue_authorization(
            principal=principal,
            action=action,
            resource=resource,
            mandate_id=mandate_id,
            decision_id=decision_id,
            conditions=conditions,
            annotations=annotations,
            expires_at=expires_at,
            authorization_id=authorization_id,
            issuer_attestation=context.attestation(),
        )

    def issue_authorization(
        self,
        *,
        principal: str,
        action: str,
        resource: str,
        mandate_id: str,
        decision_id: str,
        conditions: Mapping[str, Any] | None = None,
        annotations: Mapping[str, Any] | None = None,
        expires_at: datetime | None = None,
        authorization_id: str | None = None,
    ) -> Authorization:
        return self._issue_authorization(
            principal=principal,
            action=action,
            resource=resource,
            mandate_id=mandate_id,
            decision_id=decision_id,
            conditions=conditions,
            annotations=annotations,
            expires_at=expires_at,
            authorization_id=authorization_id,
            issuer_attestation=None,
        )

    def _issue_authorization(
        self,
        *,
        principal: str,
        action: str,
        resource: str,
        mandate_id: str,
        decision_id: str,
        conditions: Mapping[str, Any] | None = None,
        annotations: Mapping[str, Any] | None = None,
        expires_at: datetime | None = None,
        authorization_id: str | None = None,
        issuer_attestation: Mapping[str, Any] | None,
    ) -> Authorization:
        mandate = assert_mandate_current(self.ledger, mandate_id)
        _assert_scope_allows(mandate, resource)
        _assert_authority_ceiling(mandate, action=action, resource=resource)
        assert_decision_applies(
            self.ledger,
            decision_id,
            target_ref=resource,
            operation="authorize-effect",
            expected={"action": action},
        )
        if expires_at is not None and expires_at <= utcnow():
            raise PermissionError("cannot issue an already expired authorization")
        mandate_expiry = _parse_datetime(mandate.get("expires_at"))
        if (
            expires_at is not None
            and mandate_expiry is not None
            and expires_at > mandate_expiry
        ):
            raise PermissionError("authorization cannot outlive its mandate")
        _validate_conditions(dict(conditions or {}))

        auth_id = authorization_id or new_id("authorization")
        value = {
            "id": auth_id,
            "principal": principal,
            "action": action,
            "resource": resource,
            "mandate_id": mandate_id,
            "decision_id": decision_id,
            "conditions": dict(conditions or {}),
            "annotations": dict(annotations or {}),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "status": "active",
            "uses": 0,
        }
        if issuer_attestation is not None:
            value["issuer_attestation"] = dict(issuer_attestation)
        existing = self.ledger.project_get("governance.authorization", auth_id)
        if existing is not None:
            existing_attestation = existing[0].get("issuer_attestation")
            comparable = dict(existing[0])
            comparable.pop("uses", None)
            comparable.pop("issuer_attestation", None)
            incoming = {
                key: value[key]
                for key in value
                if key not in {"uses", "issuer_attestation"}
            }
            if comparable != incoming:
                raise PermissionError("authorization identity rebound")
            if issuer_attestation is not None:
                if not isinstance(existing_attestation, Mapping):
                    raise PermissionError(
                        "unattested historical Authorization cannot be adopted by replay"
                    )
                if existing_attestation.get("effective_principal") != issuer_attestation.get(
                    "effective_principal"
                ):
                    raise PermissionError(
                        "Authorization replay issuer differs from original attestation"
                    )
            return Authorization(
                id=auth_id,
                principal=principal,
                action=action,
                resource=resource,
                conditions=dict(conditions or {}),
                expires_at=expires_at,
            )

        auth = Authorization(
            id=auth_id,
            principal=principal,
            action=action,
            resource=resource,
            conditions=dict(conditions or {}),
            expires_at=expires_at,
        )
        with self.ledger.transaction():
            self.ledger.project_put("governance.authorization", auth.id, value)
            self.ledger.append(
                stream=f"authorization:{auth.id}",
                kind="governance.authorization.issued",
                payload=value,
            )
        return auth

    def revoke_authorization(
        self,
        authorization_id: str,
        *,
        reason: str,
        basis_refs: tuple[str, ...],
    ) -> None:
        if not reason.strip():
            raise ValueError("authorization revocation requires reason")
        if not basis_refs:
            raise ValueError("authorization revocation requires basis refs")
        current = self.ledger.project_get(
            "governance.authorization",
            authorization_id,
        )
        if current is None:
            raise KeyError(authorization_id)
        value, version = current
        if value.get("status") == "revoked":
            if (
                value.get("revocation_reason") != reason
                or tuple(value.get("revocation_basis_refs", ())) != tuple(basis_refs)
            ):
                raise ValueError("authorization revocation identity rebound")
            return
        updated = dict(value)
        updated["status"] = "revoked"
        updated["revocation_reason"] = reason
        updated["revocation_basis_refs"] = list(basis_refs)
        with self.ledger.transaction():
            self.ledger.project_put(
                "governance.authorization",
                authorization_id,
                updated,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"authorization:{authorization_id}",
                kind="governance.authorization.revoked",
                payload={
                    "authorization_id": authorization_id,
                    "reason": reason,
                    "basis_refs": list(basis_refs),
                },
            )

    def assert_usable(
        self,
        authorization_id: str,
        *,
        principal: str,
        action: str,
        resource: str,
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        current = self.ledger.project_get("governance.authorization", authorization_id)
        if current is None:
            raise PermissionError("unknown authorization")
        value = current[0]
        if value["status"] != "active":
            raise PermissionError("authorization is not active")
        expires_at = _parse_datetime(value.get("expires_at"))
        if expires_at is not None and expires_at <= utcnow():
            raise PermissionError("authorization has expired")
        if (value["principal"], value["action"], value["resource"]) != (
            principal,
            action,
            resource,
        ):
            raise PermissionError("authorization does not match requested effect")

        mandate = assert_mandate_current(self.ledger, str(value["mandate_id"]))
        _assert_scope_allows(mandate, resource)
        _assert_authority_ceiling(mandate, action=action, resource=resource)
        assert_decision_applies(
            self.ledger,
            str(value["decision_id"]),
            target_ref=resource,
            operation="authorize-effect",
            expected={"action": action},
        )
        _assert_conditions(dict(value.get("conditions", {})), context=context)
        return value

    def record_use(self, authorization_id: str, *, effect_request_id: str) -> None:
        current = self.ledger.project_get("governance.authorization", authorization_id)
        if current is None:
            raise KeyError(authorization_id)
        value, version = current
        if value.get("status") != "active":
            raise PermissionError("authorization is not active")
        value["uses"] = int(value.get("uses", 0)) + 1
        with self.ledger.transaction():
            self.ledger.project_put(
                "governance.authorization",
                authorization_id,
                value,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"authorization:{authorization_id}",
                kind="governance.authorization.used",
                payload={"effect_request_id": effect_request_id},
            )


__all__ = ["GovernanceService", "assert_mandate_current"]
