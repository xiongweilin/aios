from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from administrative_orchestrator.authority import (
    AuthorityError,
    AuthorityRepository,
)
from administrative_orchestrator.authority_lifecycle import AuthorityLifecycleRepository
from administrative_orchestrator.domain import (
    Delegation,
    Principal,
    PrincipalKind,
    RoleAssignment,
)
from administrative_orchestrator.persistence import SqlStore

_BASELINE = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)


def _setup():
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authority = AuthorityRepository(store)
    for principal_id in ('person:departing', 'person:successor'):
        authority.put_principal(
            Principal(
                principal_id=principal_id,
                kind=PrincipalKind.PERSON,
                display_name=principal_id,
            )
        )
    assignment = authority.put_role_assignment(
        RoleAssignment(
            assignment_id=uuid4(),
            principal_id='person:departing',
            role='manager',
            organization_scope='*',
            valid_from=_BASELINE,
            valid_until=None,
        )
    )
    delegation = authority.put_delegation(
        Delegation(
            delegation_id=uuid4(),
            from_principal_id='person:departing',
            to_principal_id='person:successor',
            role='manager',
            organization_scope='*',
            valid_from=_BASELINE,
            valid_until=_BASELINE + timedelta(days=30),
        )
    )
    lifecycle = AuthorityLifecycleRepository(store)
    return store, authority, lifecycle, assignment, delegation


def test_expire_role_assignment_ends_current_authority_and_is_idempotent() -> None:
    _, authority, lifecycle, assignment, _ = _setup()
    before = _BASELINE + timedelta(days=1)
    effective_at = _BASELINE + timedelta(days=10)
    assert 'manager' in authority.roles_for(
        'person:departing', organization_scope='*', at=before
    )

    event = lifecycle.expire_role_assignment(
        assignment.assignment_id,
        actor_principal_id='person:admin',
        reason='offboarding effective time reached',
        at=effective_at,
    )
    assert event.event_type == 'role_assignment.expired'
    assert event.payload['role'] == 'manager'
    assert event.payload['valid_until'] == effective_at.isoformat()

    replay = lifecycle.expire_role_assignment(
        assignment.assignment_id,
        actor_principal_id='person:admin',
        reason='offboarding effective time reached',
        at=effective_at,
    )
    assert replay == event
    matching = [
        item for item in lifecycle.list_events() if item.event_id == event.event_id
    ]
    assert len(matching) == 1

    after = effective_at + timedelta(seconds=1)
    assert 'manager' not in authority.roles_for(
        'person:departing', organization_scope='*', at=after
    )
    assert 'manager' in authority.roles_for(
        'person:departing', organization_scope='*', at=before
    )


def test_expire_role_assignment_is_monotonic_and_validates_the_window() -> None:
    _, authority, lifecycle, assignment, _ = _setup()
    late = _BASELINE + timedelta(days=20)
    early = _BASELINE + timedelta(days=10)

    lifecycle.expire_role_assignment(
        assignment.assignment_id,
        actor_principal_id='person:admin',
        reason='late expiry',
        at=late,
    )
    event = lifecycle.expire_role_assignment(
        assignment.assignment_id,
        actor_principal_id='person:admin',
        reason='earlier expiry must not extend',
        at=early,
    )
    assert event.payload['valid_until'] == early.isoformat()

    later = lifecycle.expire_role_assignment(
        assignment.assignment_id,
        actor_principal_id='person:admin',
        reason='a later expiry must not extend the window',
        at=_BASELINE + timedelta(days=25),
    )
    assert later.payload['valid_until'] == early.isoformat()
    assert 'manager' not in authority.roles_for(
        'person:departing',
        organization_scope='*',
        at=_BASELINE + timedelta(days=22),
    )

    with pytest.raises(AuthorityError, match='cannot precede'):
        lifecycle.expire_role_assignment(
            assignment.assignment_id,
            actor_principal_id='person:admin',
            reason='before the window',
            at=_BASELINE - timedelta(seconds=1),
        )
    with pytest.raises(AuthorityError, match='does not exist'):
        lifecycle.expire_role_assignment(
            uuid4(),
            actor_principal_id='person:admin',
            reason='missing target',
        )


def test_expire_delegation_ends_delegated_authority() -> None:
    _, authority, lifecycle, _, delegation = _setup()
    before = _BASELINE + timedelta(days=1)
    effective_at = _BASELINE + timedelta(days=5)
    assert 'manager' in authority.roles_for(
        'person:successor', organization_scope='*', at=before
    )

    event = lifecycle.expire_delegation(
        delegation.delegation_id,
        actor_principal_id='person:admin',
        reason='offboarding effective time reached',
        at=effective_at,
    )
    assert event.event_type == 'delegation.expired'
    assert event.payload['to_principal_id'] == 'person:successor'

    after = effective_at + timedelta(seconds=1)
    assert 'manager' not in authority.roles_for(
        'person:successor', organization_scope='*', at=after
    )
    assert 'manager' in authority.roles_for(
        'person:successor', organization_scope='*', at=before
    )


def test_expire_operations_require_a_reason() -> None:
    _, _, lifecycle, assignment, delegation = _setup()
    with pytest.raises(AuthorityError, match='requires a reason'):
        lifecycle.expire_role_assignment(
            assignment.assignment_id,
            actor_principal_id='person:admin',
            reason='   ',
        )
    with pytest.raises(AuthorityError, match='requires a reason'):
        lifecycle.expire_delegation(
            delegation.delegation_id,
            actor_principal_id='person:admin',
            reason='',
        )


def test_principal_deactivation_is_replay_stable_at_effective_time() -> None:
    _, authority, lifecycle, _, _ = _setup()
    effective_at = _BASELINE + timedelta(days=8)
    first = lifecycle.deactivate_principal(
        "person:departing",
        actor_principal_id="service:administrative-orchestrator",
        reason="offboarding effective time reached",
        at=effective_at,
    )
    second = lifecycle.deactivate_principal(
        "person:departing",
        actor_principal_id="service:administrative-orchestrator",
        reason="offboarding effective time reached",
        at=effective_at,
    )
    assert second == first
    assert authority.get_principal("person:departing") is None
    assert len([item for item in lifecycle.list_events() if item.event_id == first.event_id]) == 1


def test_expire_endpoints_record_events_and_fail_closed(monkeypatch) -> None:
    from types import SimpleNamespace

    from fastapi import HTTPException

    from administrative_orchestrator import operations_api

    _, _, lifecycle, assignment, delegation = _setup()
    monkeypatch.setattr(
        operations_api,
        '_actor',
        lambda request: SimpleNamespace(principal_id='person:admin'),
    )
    monkeypatch.setattr(
        operations_api,
        '_require',
        lambda actor, permission, case=None: None,
    )
    monkeypatch.setattr(operations_api, '_lifecycle', lifecycle)

    role_event = operations_api.expire_role_assignment(
        assignment.assignment_id,
        operations_api.ExpireAuthorityBody(reason='offboarding'),
        None,
    )
    assert role_event.event_type == 'role_assignment.expired'

    delegation_event = operations_api.expire_delegation(
        delegation.delegation_id,
        operations_api.ExpireAuthorityBody(reason='offboarding'),
        None,
    )
    assert delegation_event.event_type == 'delegation.expired'

    with pytest.raises(HTTPException) as excinfo:
        operations_api.expire_role_assignment(
            uuid4(),
            operations_api.ExpireAuthorityBody(reason='missing target'),
            None,
        )
    assert excinfo.value.status_code == 409


def test_expire_event_replay_with_different_reason_fails_closed() -> None:
    _, _, lifecycle, assignment, _ = _setup()
    effective_at = _BASELINE + timedelta(days=3)
    lifecycle.expire_role_assignment(
        assignment.assignment_id,
        actor_principal_id='person:admin',
        reason='first reason',
        at=effective_at,
    )
    with pytest.raises(AuthorityError, match='different semantics'):
        lifecycle.expire_role_assignment(
            assignment.assignment_id,
            actor_principal_id='person:admin',
            reason='different reason',
            at=effective_at,
        )


def test_identity_lifecycle_metrics_cover_expiry_paths() -> None:
    from administrative_orchestrator import observability

    def value(event: str) -> float:
        return observability.IDENTITY_LIFECYCLE.labels(event=event)._value.get()

    before_role = value('role_assignment.expired')
    observability._record_operations_semantics(
        'POST', '/v1/operations/role-assignments/abc/expire', 200
    )
    assert value('role_assignment.expired') == before_role + 1

    before_delegation = value('delegation.expired')
    observability._record_operations_semantics(
        'POST', '/v1/operations/delegations/abc/expire', 200
    )
    assert value('delegation.expired') == before_delegation + 1
