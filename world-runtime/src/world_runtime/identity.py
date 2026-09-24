from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .common import utcnow
from .ledger import SemanticLedger


@dataclass(frozen=True, slots=True)
class AuthenticatedRequestContext:
    authenticated_principal: str
    effective_principal: str
    credential_id: str
    authentication_method: str
    authentication_strength: str
    delegation_chain: tuple[str, ...] = ()

    def attestation(self) -> dict[str, Any]:
        return {
            "authenticated_principal": self.authenticated_principal,
            "effective_principal": self.effective_principal,
            "credential_id": self.credential_id,
            "authentication_method": self.authentication_method,
            "authentication_strength": self.authentication_strength,
            "delegation_chain": list(self.delegation_chain),
        }


@dataclass(frozen=True, slots=True)
class DelegationGrant:
    id: str
    grantor: str
    grantee: str
    scope: Mapping[str, Any]
    authority_ceiling: Mapping[str, Any]
    parent_id: str | None = None
    expires_at: datetime | None = None


def _parse_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _constraint_is_narrower(child: object, parent: object) -> bool:
    if parent == "*":
        return True
    if child == "*":
        return parent == "*"
    if isinstance(parent, (list, tuple, set, frozenset)):
        parent_values = set(parent)
        if isinstance(child, (list, tuple, set, frozenset)):
            return set(child) <= parent_values
        return child in parent_values
    return child == parent


def _mapping_is_narrower(child: Mapping[str, Any], parent: Mapping[str, Any]) -> bool:
    if not parent:
        return not child
    for key, value in child.items():
        if key not in parent or not _constraint_is_narrower(value, parent[key]):
            return False
    return True


class IdentityService:
    """Runtime-owned authentication bindings and bounded delegation.

    Raw bearer credentials are never persisted. Only SHA-256 credential digests and
    non-secret authentication metadata are stored in the semantic ledger.
    """

    def __init__(self, ledger: SemanticLedger) -> None:
        self.ledger = ledger

    def bind_bearer_token(
        self,
        *,
        principal: str,
        token: str,
        credential_id: str,
        expires_at: datetime | None = None,
        authentication_strength: str = "bearer",
    ) -> None:
        if not principal.strip() or not credential_id.strip() or not token:
            raise ValueError("credential binding requires principal, credential_id, and token")
        digest = _token_digest(token)
        value = {
            "credential_id": credential_id,
            "principal": principal,
            "token_digest": digest,
            "authentication_method": "bearer",
            "authentication_strength": authentication_strength,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "status": "active",
        }
        existing = self.ledger.project_get("identity.credential", credential_id)
        if existing is not None:
            if existing[0] != value:
                raise ValueError("credential binding identity rebound")
            return
        digest_binding = self.ledger.project_get("identity.token-digest", digest)
        if digest_binding is not None and digest_binding[0].get("credential_id") != credential_id:
            raise ValueError("bearer token is already bound to another credential")
        with self.ledger.transaction():
            self.ledger.project_put("identity.credential", credential_id, value)
            self.ledger.project_put(
                "identity.token-digest",
                digest,
                {"credential_id": credential_id},
            )
            self.ledger.append(
                stream=f"credential:{credential_id}",
                kind="identity.credential.bound",
                payload={
                    key: item
                    for key, item in value.items()
                    if key != "token_digest"
                },
            )

    def revoke_credential(self, credential_id: str, *, reason: str) -> None:
        current = self.ledger.project_get("identity.credential", credential_id)
        if current is None:
            raise KeyError(credential_id)
        value, version = current
        if value.get("status") == "revoked":
            return
        value["status"] = "revoked"
        value["revocation_reason"] = reason
        with self.ledger.transaction():
            self.ledger.project_put(
                "identity.credential",
                credential_id,
                value,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"credential:{credential_id}",
                kind="identity.credential.revoked",
                payload={"credential_id": credential_id, "reason": reason},
            )

    def grant_delegation(
        self,
        grant: DelegationGrant,
        *,
        context: AuthenticatedRequestContext,
    ) -> None:
        if grant.parent_id is None:
            if context.effective_principal != grant.grantor:
                raise PermissionError(
                    "delegation grantor must be the authenticated effective principal"
                )
        else:
            if context.authenticated_principal != grant.grantor:
                raise PermissionError(
                    "child delegation grantor must be the authenticated parent grantee"
                )
            if not context.delegation_chain or context.delegation_chain[0] != grant.parent_id:
                raise PermissionError(
                    "child delegation must derive from the active authenticated parent"
                )
        if grant.grantor == grant.grantee:
            raise ValueError("delegation grantor and grantee must differ")
        if grant.expires_at is not None and grant.expires_at <= utcnow():
            raise PermissionError("cannot create an already expired delegation")

        if grant.parent_id is not None:
            parent = self._current_delegation(grant.parent_id)
            if parent["grantee"] != grant.grantor:
                raise PermissionError("child delegation grantor must be the parent grantee")
            if not _mapping_is_narrower(grant.scope, dict(parent.get("scope", {}))):
                raise PermissionError("child delegation widens parent scope")
            if not _mapping_is_narrower(
                grant.authority_ceiling,
                dict(parent.get("authority_ceiling", {})),
            ):
                raise PermissionError("child delegation widens parent authority ceiling")
            parent_expiry = _parse_datetime(parent.get("expires_at"))
            if (
                parent_expiry is not None
                and grant.expires_at is not None
                and grant.expires_at > parent_expiry
            ):
                raise PermissionError("child delegation cannot outlive parent")

        value = {
            "id": grant.id,
            "grantor": grant.grantor,
            "grantee": grant.grantee,
            "scope": dict(grant.scope),
            "authority_ceiling": dict(grant.authority_ceiling),
            "parent_id": grant.parent_id,
            "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            "status": "active",
        }
        existing = self.ledger.project_get("identity.delegation", grant.id)
        if existing is not None:
            comparable = dict(existing[0])
            comparable.pop("status", None)
            if comparable != {key: value[key] for key in value if key != "status"}:
                raise ValueError("delegation identity rebound")
            return
        with self.ledger.transaction():
            self.ledger.project_put("identity.delegation", grant.id, value)
            self.ledger.append(
                stream=f"delegation:{grant.id}",
                kind="identity.delegation.granted",
                payload=value,
            )

    def revoke_delegation(
        self,
        delegation_id: str,
        *,
        context: AuthenticatedRequestContext,
        reason: str,
    ) -> None:
        current = self.ledger.project_get("identity.delegation", delegation_id)
        if current is None:
            raise KeyError(delegation_id)
        value, version = current
        if context.effective_principal != value["grantor"]:
            raise PermissionError("only the effective grantor may revoke delegation")
        if value.get("status") == "revoked":
            return
        value["status"] = "revoked"
        value["revocation_reason"] = reason
        with self.ledger.transaction():
            self.ledger.project_put(
                "identity.delegation",
                delegation_id,
                value,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"delegation:{delegation_id}",
                kind="identity.delegation.revoked",
                payload={"delegation_id": delegation_id, "reason": reason},
            )

    def authenticate_bearer(
        self,
        authorization_header: str | None,
        *,
        delegation_id: str | None = None,
    ) -> AuthenticatedRequestContext:
        if not authorization_header:
            raise PermissionError("authenticated Runtime request required")
        scheme, separator, token = authorization_header.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token.strip():
            raise PermissionError("Runtime requires Bearer authentication")
        digest = _token_digest(token.strip())
        binding = self.ledger.project_get("identity.token-digest", digest)
        if binding is None:
            raise PermissionError("unknown Runtime credential")
        credential_id = str(binding[0]["credential_id"])
        credential = self.ledger.project_get("identity.credential", credential_id)
        if credential is None:
            raise PermissionError("Runtime credential binding is unavailable")
        value = credential[0]
        if value.get("status") != "active":
            raise PermissionError("Runtime credential is not active")
        if not hmac.compare_digest(str(value.get("token_digest", "")), digest):
            raise PermissionError("Runtime credential digest mismatch")
        expires_at = _parse_datetime(value.get("expires_at"))
        if expires_at is not None and expires_at <= utcnow():
            raise PermissionError("Runtime credential has expired")

        authenticated = str(value["principal"])
        effective = authenticated
        chain: tuple[str, ...] = ()
        if delegation_id is not None:
            chain_values: list[str] = []
            cursor = self._current_delegation(delegation_id)
            if cursor["grantee"] != authenticated:
                raise PermissionError("delegation does not bind authenticated grantee")
            while True:
                chain_values.append(str(cursor["id"]))
                effective = str(cursor["grantor"])
                parent_id = cursor.get("parent_id")
                if not parent_id:
                    break
                parent = self._current_delegation(str(parent_id))
                if parent["grantee"] != cursor["grantor"]:
                    raise PermissionError("delegation chain is discontinuous")
                cursor = parent
            chain = tuple(chain_values)

        return AuthenticatedRequestContext(
            authenticated_principal=authenticated,
            effective_principal=effective,
            credential_id=credential_id,
            authentication_method=str(value.get("authentication_method", "bearer")),
            authentication_strength=str(value.get("authentication_strength", "bearer")),
            delegation_chain=chain,
        )

    def assert_claimed_principal(
        self,
        context: AuthenticatedRequestContext,
        claimed_principal: str,
    ) -> None:
        if claimed_principal != context.effective_principal:
            raise PermissionError("claimed principal is not the authenticated effective principal")

    def assert_delegated_authority(
        self,
        context: AuthenticatedRequestContext,
        *,
        scope: Mapping[str, Any],
        authority_ceiling: Mapping[str, Any],
    ) -> None:
        if not context.delegation_chain:
            return
        leaf = self._current_delegation(context.delegation_chain[0])
        if not _mapping_is_narrower(scope, dict(leaf.get("scope", {}))):
            raise PermissionError("requested scope exceeds delegated scope")
        if not _mapping_is_narrower(
            authority_ceiling,
            dict(leaf.get("authority_ceiling", {})),
        ):
            raise PermissionError("requested authority ceiling exceeds delegation")

    def assert_transition_authority(
        self,
        context: AuthenticatedRequestContext,
        *,
        operation: str,
        resource: str | None = None,
    ) -> None:
        """Qualify one generic Runtime state transition under delegated authority.

        Directly authenticated principals remain their own authority root. Delegated
        callers must carry an explicit operation ceiling; effect action/resource
        authority remains separately qualified by Mandate/Authorization semantics.
        """
        if not operation.strip():
            raise ValueError("Runtime transition operation must be non-empty")
        if not context.delegation_chain:
            return
        leaf = self._current_delegation(context.delegation_chain[0])
        required: dict[str, Any] = {"operation": operation}
        if resource:
            required["resource"] = resource
        if not _mapping_is_narrower(
            required,
            dict(leaf.get("authority_ceiling", {})),
        ):
            raise PermissionError("Runtime transition exceeds delegated authority")

    def _current_delegation(self, delegation_id: str) -> dict[str, Any]:
        current = self.ledger.project_get("identity.delegation", delegation_id)
        if current is None:
            raise PermissionError("required delegation is not recorded")
        value = current[0]
        if value.get("status") != "active":
            raise PermissionError("delegation is not active")
        expires_at = _parse_datetime(value.get("expires_at"))
        if expires_at is not None and expires_at <= utcnow():
            raise PermissionError("delegation has expired")
        parent_id = value.get("parent_id")
        if parent_id:
            self._current_delegation(str(parent_id))
        return value


__all__ = [
    "AuthenticatedRequestContext",
    "DelegationGrant",
    "IdentityService",
]
