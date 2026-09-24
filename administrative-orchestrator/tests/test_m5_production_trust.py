from __future__ import annotations

from datetime import timedelta

import pytest

from administrative_orchestrator.authority import AuthorityRepository, IdentityBinding
from administrative_orchestrator.authority_lifecycle import AuthorityLifecycleRepository
from administrative_orchestrator.config import Settings
from administrative_orchestrator.domain import (
    AdministrativeRequest,
    FactAuthority,
    FactSnapshot,
    Principal,
    utcnow,
)
from administrative_orchestrator.fact_acquisition import (
    AuthoritativeFactRevalidator,
    merge_authoritative_onboarding_facts,
)
from administrative_orchestrator.fact_history import list_fact_snapshots, persist_fact_snapshot
from administrative_orchestrator.integrations.authoritative_sources import AuthoritativeRecord
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.service import create_case


def _onboarding_case():
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="onboard employee:42",
    )
    snapshot = FactSnapshot(
        source="ingress:test",
        owner=request.requester_principal_id,
        authority=FactAuthority.CLAIM,
        facts={
            "employee_ref": "employee:42",
            "department_ref": "department:claimed",
            "manager_principal_id": "person:manager",
            "start_date": "2026-09-15",
            "employment_type": "employee",
            "requested_systems": ["iam"],
            "requires_privileged_access": False,
        },
    )
    case = create_case(
        request,
        case_kind="employee-onboarding",
        subject_ref="employee:42",
        fact_snapshot=snapshot,
    )
    return request, case


def _authoritative_record(*, department_ref: str = "odoo:hr.department:7", observed_at=None):
    return AuthoritativeRecord.build(
        source="odoo",
        source_ref="odoo:hr.employee:42",
        source_version="2026-09-09T08:00:00Z",
        observed_at=observed_at,
        value={
            "present": True,
            "employee_ref": "employee:42",
            "department_ref": department_ref,
            "start_date": "2026-09-15",
            "employment_type": "employee",
            "manager_ref": "odoo:hr.employee:5",
            "work_email": "employee42@example.test",
            "active": True,
            "employment_state": "open",
        },
    )


def test_authoritative_overlay_does_not_promote_request_only_claims():
    _, case = _onboarding_case()

    merged = merge_authoritative_onboarding_facts(case, _authoritative_record())

    assert merged.authority is FactAuthority.CLAIM
    assert merged.facts["department_ref"] == "odoo:hr.department:7"
    assert merged.assertions["department_ref"].authority is FactAuthority.AUTHORITATIVE
    assert merged.assertions["department_ref"].source == "odoo"
    assert merged.facts["requested_systems"] == ["iam"]
    assert merged.assertions["requested_systems"].authority is FactAuthority.CLAIM
    assert merged.assertions["requested_systems"].source == "ingress:test"


def test_fact_history_preserves_field_level_provenance():
    request, case = _onboarding_case()
    merged = merge_authoritative_onboarding_facts(case, _authoritative_record())
    case = case.model_copy(update={"fact_snapshot": merged})
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    store.create_case(request, case)
    with store.sessions.begin() as db:
        persist_fact_snapshot(db, case)

    restored = list_fact_snapshots(store, case.case_id)

    assert len(restored) == 1
    assert restored[0].assertions["department_ref"].authority is FactAuthority.AUTHORITATIVE
    assert restored[0].assertions["requested_systems"].authority is FactAuthority.CLAIM
    assert restored[0].assertions["department_ref"].source_ref == "odoo:hr.employee:42"


class _FakeHRSource:
    def __init__(self, record: AuthoritativeRecord) -> None:
        self.record = record

    def read_employee(self, employee_ref: str) -> AuthoritativeRecord:
        assert employee_ref == "employee:42"
        return self.record

    def read_department(self, department_ref: str) -> AuthoritativeRecord:  # pragma: no cover
        raise AssertionError(department_ref)

    def read_manager(self, employee_ref: str) -> AuthoritativeRecord:  # pragma: no cover
        raise AssertionError(employee_ref)


def test_authoritative_revalidation_detects_current_truth_change():
    _, case = _onboarding_case()
    merged = merge_authoritative_onboarding_facts(case, _authoritative_record())
    case = case.model_copy(update={"fact_snapshot": merged})
    changed = _authoritative_record(department_ref="odoo:hr.department:9")

    validation = AuthoritativeFactRevalidator(
        _FakeHRSource(changed),
        max_age_seconds=300,
    ).validate(case)

    assert not validation.valid
    assert "authoritative value changed for department_ref" in validation.reasons


def test_authoritative_revalidation_rejects_stale_observation():
    _, case = _onboarding_case()
    merged = merge_authoritative_onboarding_facts(case, _authoritative_record())
    case = case.model_copy(update={"fact_snapshot": merged})
    stale = _authoritative_record(observed_at=utcnow() - timedelta(minutes=10))

    validation = AuthoritativeFactRevalidator(
        _FakeHRSource(stale),
        max_age_seconds=60,
    ).validate(case)

    assert validation.valid is False
    assert validation.reasons == ("authoritative HRIS observation is stale",)


def test_identity_binding_revoke_then_non_overlapping_rebind_is_historical():
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authority = AuthorityRepository(store)
    lifecycle = AuthorityLifecycleRepository(store)
    authority.put_principal(Principal(principal_id="person:alice", display_name="Alice"))
    authority.put_principal(Principal(principal_id="person:bob", display_name="Bob"))
    start = utcnow() - timedelta(minutes=1)
    first = IdentityBinding(
        provider="https://idp.example.test",
        external_subject="subject-1",
        principal_id="person:alice",
        valid_from=start,
    )
    lifecycle.bind_identity(first, actor_principal_id="person:alice", reason="initial binding")
    assert authority.resolve_identity(
        provider=first.provider,
        external_subject=first.external_subject,
    ).principal_id == "person:alice"

    revoked = lifecycle.expire_identity_binding(
        first.binding_id,
        actor_principal_id="person:alice",
        reason="employment transfer",
    )
    assert authority.resolve_identity(
        provider=first.provider,
        external_subject=first.external_subject,
        at=revoked.occurred_at + timedelta(microseconds=1),
    ) is None

    second = IdentityBinding(
        provider=first.provider,
        external_subject=first.external_subject,
        principal_id="person:bob",
        valid_from=revoked.occurred_at + timedelta(microseconds=1),
    )
    lifecycle.bind_identity(second, actor_principal_id="person:alice", reason="controlled rebind")
    resolved = authority.resolve_identity(
        provider=second.provider,
        external_subject=second.external_subject,
        at=second.valid_from + timedelta(microseconds=1),
    )
    assert resolved is not None and resolved.principal_id == "person:bob"
    assert [event.event_type for event in lifecycle.list_events()] == [
        "identity_binding.created",
        "identity_binding.revoked",
        "identity_binding.created",
    ]


def test_identity_binding_rejects_overlapping_semantics_and_deactivation_fails_closed():
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authority = AuthorityRepository(store)
    lifecycle = AuthorityLifecycleRepository(store)
    authority.put_principal(Principal(principal_id="person:alice", display_name="Alice"))
    authority.put_principal(Principal(principal_id="person:bob", display_name="Bob"))
    first = IdentityBinding(
        provider="https://idp.example.test",
        external_subject="subject-1",
        principal_id="person:alice",
        valid_from=utcnow() - timedelta(minutes=1),
    )
    lifecycle.bind_identity(first, actor_principal_id="person:alice", reason="initial binding")

    with pytest.raises(ValueError, match="overlaps"):
        lifecycle.bind_identity(
            IdentityBinding(
                provider=first.provider,
                external_subject=first.external_subject,
                principal_id="person:bob",
                valid_from=utcnow(),
            ),
            actor_principal_id="person:alice",
            reason="invalid overlap",
        )

    lifecycle.deactivate_principal(
        "person:alice",
        actor_principal_id="person:alice",
        reason="offboarded",
    )
    assert authority.resolve_identity(
        provider=first.provider,
        external_subject=first.external_subject,
    ) is None


def test_production_profile_requires_oidc_https_and_asymmetric_algorithms():
    with pytest.raises(ValueError, match="requires ADMIN_AUTH_MODE=oidc"):
        Settings(runtime_profile="production", auth_mode="development")

    with pytest.raises(ValueError, match="must use HTTPS"):
        Settings(
            runtime_profile="production",
            auth_mode="oidc",
            oidc_issuer="http://idp.example.test",
            oidc_audience="administrative-orchestrator",
        )

    with pytest.raises(ValueError, match="restricted to RS256/ES256"):
        Settings(
            runtime_profile="production",
            auth_mode="oidc",
            oidc_issuer="https://idp.example.test",
            oidc_audience="administrative-orchestrator",
            oidc_allowed_algorithms="HS256",
        )

    settings = Settings(
        runtime_profile="production",
        auth_mode="oidc",
        oidc_issuer="https://idp.example.test",
        oidc_audience="administrative-orchestrator",
    )
    assert settings.authority_enforcement_enabled is True
    assert settings.oidc_algorithms == ("RS256", "ES256")
