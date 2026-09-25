from datetime import UTC, datetime, timedelta

import pytest

from world_runtime import WorldRuntime
from world_runtime.identity import DelegationGrant


def _bind(
    runtime: WorldRuntime,
    principal: str,
    token: str,
    credential_id: str,
    *,
    expires_at: datetime | None = None,
) -> None:
    runtime.identity.bind_bearer_token(
        principal=principal,
        token=token,
        credential_id=credential_id,
        expires_at=expires_at,
    )


def test_bearer_authentication_fails_closed_for_missing_malformed_unknown_and_expired() -> None:
    runtime = WorldRuntime.sqlite()

    with pytest.raises(PermissionError, match="authenticated Runtime request required"):
        runtime.identity.authenticate_bearer(None)
    with pytest.raises(PermissionError, match="requires Bearer authentication"):
        runtime.identity.authenticate_bearer("Basic abc")
    with pytest.raises(PermissionError, match="unknown Runtime credential"):
        runtime.identity.authenticate_bearer("Bearer unknown")

    _bind(
        runtime,
        "principal:expired",
        "expired-token",
        "credential:expired",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(PermissionError, match="expired"):
        runtime.identity.authenticate_bearer("Bearer expired-token")


def test_bearer_binding_is_immutable_and_token_is_single_bound() -> None:
    runtime = WorldRuntime.sqlite()
    _bind(runtime, "principal:one", "shared-token", "credential:one")

    _bind(runtime, "principal:one", "shared-token", "credential:one")

    with pytest.raises(ValueError, match="identity rebound"):
        _bind(runtime, "principal:two", "other-token", "credential:one")
    with pytest.raises(ValueError, match="already bound"):
        _bind(runtime, "principal:two", "shared-token", "credential:two")


def test_revoked_credential_is_rejected_and_revocation_is_idempotent() -> None:
    runtime = WorldRuntime.sqlite()
    _bind(runtime, "principal:owner", "owner-token", "credential:owner")

    context = runtime.identity.authenticate_bearer("Bearer owner-token")
    assert context.authenticated_principal == "principal:owner"
    assert context.effective_principal == "principal:owner"

    runtime.identity.revoke_credential("credential:owner", reason="rotation")
    runtime.identity.revoke_credential("credential:owner", reason="rotation")

    with pytest.raises(PermissionError, match="not active"):
        runtime.identity.authenticate_bearer("Bearer owner-token")


def test_delegation_chain_establishes_root_effective_principal_and_cannot_widen() -> None:
    runtime = WorldRuntime.sqlite()
    _bind(runtime, "principal:root", "root-token", "credential:root")
    _bind(runtime, "controller:middle", "middle-token", "credential:middle")
    _bind(runtime, "controller:leaf", "leaf-token", "credential:leaf")

    root = runtime.identity.authenticate_bearer("Bearer root-token")
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:root-middle",
            grantor="principal:root",
            grantee="controller:middle",
            scope={"resource": "*", "region": ["jp", "us"]},
            authority_ceiling={"action": ["read", "deploy"], "resource": "*"},
            expires_at=datetime.now(UTC) + timedelta(hours=2),
        ),
        context=root,
    )
    middle = runtime.identity.authenticate_bearer(
        "Bearer middle-token",
        delegation_id="delegation:root-middle",
    )
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:middle-leaf",
            grantor="controller:middle",
            grantee="controller:leaf",
            scope={"resource": "resource:1", "region": "jp"},
            authority_ceiling={"action": "deploy", "resource": "resource:1"},
            parent_id="delegation:root-middle",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        context=middle,
    )

    leaf = runtime.identity.authenticate_bearer(
        "Bearer leaf-token",
        delegation_id="delegation:middle-leaf",
    )
    assert leaf.authenticated_principal == "controller:leaf"
    assert leaf.effective_principal == "principal:root"
    assert leaf.delegation_chain == (
        "delegation:middle-leaf",
        "delegation:root-middle",
    )

    runtime.identity.assert_delegated_authority(
        leaf,
        scope={"resource": "resource:1"},
        authority_ceiling={"action": "deploy", "resource": "resource:1"},
    )
    with pytest.raises(PermissionError, match="scope exceeds"):
        runtime.identity.assert_delegated_authority(
            leaf,
            scope={"resource": "resource:2"},
            authority_ceiling={"action": "deploy", "resource": "resource:1"},
        )
    with pytest.raises(PermissionError, match="authority ceiling exceeds"):
        runtime.identity.assert_delegated_authority(
            leaf,
            scope={"resource": "resource:1"},
            authority_ceiling={"action": "delete", "resource": "resource:1"},
        )


def test_child_delegation_must_be_narrower_and_not_outlive_parent() -> None:
    runtime = WorldRuntime.sqlite()
    _bind(runtime, "principal:root", "root-token", "credential:root")
    _bind(runtime, "controller:middle", "middle-token", "credential:middle")

    root = runtime.identity.authenticate_bearer("Bearer root-token")
    parent_expiry = datetime.now(UTC) + timedelta(minutes=30)
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:parent",
            grantor="principal:root",
            grantee="controller:middle",
            scope={"resource": "resource:1"},
            authority_ceiling={"action": "deploy", "resource": "resource:1"},
            expires_at=parent_expiry,
        ),
        context=root,
    )
    middle = runtime.identity.authenticate_bearer(
        "Bearer middle-token",
        delegation_id="delegation:parent",
    )

    with pytest.raises(PermissionError, match="widens parent scope"):
        runtime.identity.grant_delegation(
            DelegationGrant(
                id="delegation:wider",
                grantor="controller:middle",
                grantee="controller:leaf",
                scope={"resource": "*"},
                authority_ceiling={"action": "deploy", "resource": "resource:1"},
                parent_id="delegation:parent",
            ),
            context=middle,
        )
    with pytest.raises(PermissionError, match="outlive parent"):
        runtime.identity.grant_delegation(
            DelegationGrant(
                id="delegation:too-long",
                grantor="controller:middle",
                grantee="controller:leaf",
                scope={"resource": "resource:1"},
                authority_ceiling={"action": "deploy", "resource": "resource:1"},
                parent_id="delegation:parent",
                expires_at=parent_expiry + timedelta(minutes=1),
            ),
            context=middle,
        )


def test_only_effective_grantor_can_revoke_delegation() -> None:
    runtime = WorldRuntime.sqlite()
    _bind(runtime, "principal:owner", "owner-token", "credential:owner")
    _bind(runtime, "controller:delegate", "delegate-token", "credential:delegate")

    owner = runtime.identity.authenticate_bearer("Bearer owner-token")
    delegate = runtime.identity.authenticate_bearer("Bearer delegate-token")
    runtime.identity.grant_delegation(
        DelegationGrant(
            id="delegation:revoke",
            grantor="principal:owner",
            grantee="controller:delegate",
            scope={},
            authority_ceiling={},
        ),
        context=owner,
    )

    with pytest.raises(PermissionError, match="effective grantor"):
        runtime.identity.revoke_delegation(
            "delegation:revoke",
            context=delegate,
            reason="not-authorized",
        )

    runtime.identity.revoke_delegation(
        "delegation:revoke",
        context=owner,
        reason="rotation",
    )
    with pytest.raises(PermissionError, match="not active"):
        runtime.identity.authenticate_bearer(
            "Bearer delegate-token",
            delegation_id="delegation:revoke",
        )
