from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .authority import AuthorityRepository, IdentityBinding
from .config import get_settings
from .domain import Delegation, Principal, PrincipalKind, RoleAssignment
from .persistence import SqlStore
from .policy_plane import (
    PolicyRepository,
    default_commitment_policy_version,
    default_expense_policy_version,
    default_invoice_ap_policy_version,
    default_offboarding_policy_version,
    default_onboarding_policy_version,
    default_procurement_policy_version,
)

_BASELINE = datetime(2026, 1, 1, tzinfo=UTC)


def _stable_uuid(kind: str, *parts: str):
    return uuid5(NAMESPACE_URL, f"administrative:bootstrap:{kind}:" + ":".join(parts))


def bootstrap_foundation(store: SqlStore, payload: dict[str, Any] | None = None) -> None:
    authority = AuthorityRepository(store)
    policies = PolicyRepository(store)
    policies.put_version(default_onboarding_policy_version())
    policies.put_version(default_offboarding_policy_version())
    policies.put_version(default_procurement_policy_version())
    policies.put_version(default_invoice_ap_policy_version())
    policies.put_version(default_expense_policy_version())
    policies.put_version(default_commitment_policy_version())

    payload = payload or {}
    for item in payload.get("principals", []):
        authority.put_principal(
            Principal(
                principal_id=item["principal_id"],
                display_name=item.get("display_name", item["principal_id"]),
                kind=PrincipalKind(item.get("kind", "person")),
            ),
            active=bool(item.get("active", True)),
        )

    for item in payload.get("identity_bindings", []):
        principal_id = item["principal_id"]
        authority.put_identity_binding(
            IdentityBinding(
                binding_id=_stable_uuid(
                    "identity",
                    item["provider"],
                    item["external_subject"],
                    principal_id,
                ),
                provider=item["provider"],
                external_subject=item["external_subject"],
                principal_id=principal_id,
                valid_from=_parse_time(item.get("valid_from")) or _BASELINE,
                valid_until=_parse_time(item.get("valid_until")),
            )
        )

    for item in payload.get("role_assignments", []):
        principal_id = item["principal_id"]
        role = item["role"]
        scope = item.get("organization_scope", "*")
        authority.put_role_assignment(
            RoleAssignment(
                assignment_id=_stable_uuid("role", principal_id, role, scope),
                principal_id=principal_id,
                role=role,
                organization_scope=scope,
                valid_from=_parse_time(item.get("valid_from")) or _BASELINE,
                valid_until=_parse_time(item.get("valid_until")),
            )
        )

    for item in payload.get("delegations", []):
        source = item["from_principal_id"]
        target = item["to_principal_id"]
        role = item["role"]
        scope = item.get("organization_scope", "*")
        valid_from = _parse_time(item.get("valid_from")) or _BASELINE
        valid_until = _parse_time(item.get("valid_until"))
        if valid_until is None:
            raise ValueError("bootstrap delegation requires valid_until")
        authority.put_delegation(
            Delegation(
                delegation_id=_stable_uuid("delegation", source, target, role, scope),
                from_principal_id=source,
                to_principal_id=target,
                role=role,
                organization_scope=scope,
                valid_from=valid_from,
                valid_until=valid_until,
            )
        )


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def main() -> int:
    settings = get_settings()
    store = SqlStore(settings.database_url)
    payload = json.loads(settings.bootstrap_authority_json) if settings.bootstrap_authority_json else {}
    if not isinstance(payload, dict):
        raise ValueError("ADMIN_BOOTSTRAP_AUTHORITY_JSON must decode to an object")
    bootstrap_foundation(store, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
