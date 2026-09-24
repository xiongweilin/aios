from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from administrative_orchestrator.authority import (
    ApprovalSatisfaction,
    AuthorityRepository,
    assess_approval_satisfaction,
    resolve_decision_role,
)
from administrative_orchestrator.bootstrap_foundation import bootstrap_foundation
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AuthorityClass,
    CaseStatus,
    Decision,
    DecisionDisposition,
    Delegation,
    Principal,
    RoleAssignment,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy
from administrative_orchestrator.policy_plane import (
    PolicyRepository,
    compile_onboarding_policy,
    default_onboarding_policy_version,
)
from administrative_orchestrator.service import mint_execution_authorization_from_approval


def _store() -> SqlStore:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    return store


def test_foundation_bootstrap_is_idempotent_and_resolves_policy() -> None:
    store = _store()
    payload = {
        "principals": [
            {"principal_id": "person:hr", "display_name": "HR"},
        ],
        "role_assignments": [
            {
                "principal_id": "person:hr",
                "role": "hr_approver",
                "organization_scope": "*",
            }
        ],
    }
    bootstrap_foundation(store, payload)
    bootstrap_foundation(store, payload)

    current = PolicyRepository(store).resolve_current("employee-onboarding")
    assert current == default_onboarding_policy_version()
    policy = compile_onboarding_policy(current)
    evaluation = policy.evaluate(
        OnboardingFacts(
            employee_ref="employee:new",
            department_ref="department:engineering",
            manager_principal_id="person:manager",
            start_date="2026-09-15",
            employment_type="full-time",
        )
    )
    assert evaluation.required_decision_roles == ("hr_approver",)
    assert AuthorityRepository(store).roles_for(
        "person:hr",
        organization_scope="department:engineering",
    ) == {"hr_approver"}


def test_decision_role_must_come_from_current_role_assignment() -> None:
    store = _store()
    authority = AuthorityRepository(store)
    authority.put_principal(Principal(principal_id="person:hr", display_name="HR"))
    authority.put_principal(Principal(principal_id="person:requester", display_name="Requester"))
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:hr",
            role="hr_approver",
            organization_scope="department:engineering",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    policy_record = default_onboarding_policy_version()
    evaluation = OnboardingPolicy(policy_record.policy_ref).evaluate(
        OnboardingFacts(
            employee_ref="employee:new",
            department_ref="department:engineering",
            manager_principal_id="person:manager",
            start_date="2026-09-15",
            employment_type="full-time",
        )
    )

    assert (
        resolve_decision_role(
            authority,
            principal_id="person:hr",
            evaluation=evaluation,
            organization_scope="department:engineering",
            requested_role=None,
        )
        == "hr_approver"
    )


def test_privileged_approval_requires_two_distinct_current_principals() -> None:
    store = _store()
    authority = AuthorityRepository(store)
    for principal_id in ("person:both", "person:access"):
        authority.put_principal(
            Principal(principal_id=principal_id, display_name=principal_id)
        )
    for role in ("manager", "access_approver"):
        authority.put_role_assignment(
            RoleAssignment(
                principal_id="person:both",
                role=role,
                organization_scope="*",
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:access",
            role="access_approver",
            organization_scope="*",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )

    policy_ref = default_onboarding_policy_version().policy_ref
    evaluation = OnboardingPolicy(policy_ref).evaluate(
        OnboardingFacts(
            employee_ref="employee:new",
            department_ref="department:engineering",
            manager_principal_id="person:both",
            start_date="2026-09-15",
            employment_type="full-time",
            requires_privileged_access=True,
        )
    )
    case_id = uuid4()
    same_person = [
        Decision(
            case_id=case_id,
            case_version=3,
            authority_epoch=2,
            principal_id="person:both",
            decision_role="manager",
            disposition=DecisionDisposition.APPROVE,
            rationale="manager",
            policy_ref=policy_ref,
        ),
        Decision(
            case_id=case_id,
            case_version=4,
            authority_epoch=2,
            principal_id="person:both",
            decision_role="access_approver",
            disposition=DecisionDisposition.APPROVE,
            rationale="access",
            policy_ref=policy_ref,
        ),
    ]
    not_satisfied = assess_approval_satisfaction(
        authority,
        case_id=case_id,
        authority_epoch=2,
        policy_ref=policy_ref,
        evaluation=evaluation,
        decisions=same_person,
        organization_scope="department:engineering",
    )
    assert not_satisfied.satisfied is False

    distinct = same_person[:1] + [
        same_person[1].model_copy(update={"principal_id": "person:access"})
    ]
    satisfied = assess_approval_satisfaction(
        authority,
        case_id=case_id,
        authority_epoch=2,
        policy_ref=policy_ref,
        evaluation=evaluation,
        decisions=distinct,
        organization_scope="department:engineering",
    )
    assert satisfied.satisfied is True
    assert set(satisfied.selected_principal_ids) == {"person:both", "person:access"}
    assert satisfied.satisfaction is not None


def test_expired_role_cannot_satisfy_current_authority() -> None:
    store = _store()
    authority = AuthorityRepository(store)
    authority.put_principal(Principal(principal_id="person:old", display_name="Old HR"))
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:old",
            role="hr_approver",
            organization_scope="*",
            valid_from=datetime.now(UTC) - timedelta(days=3),
            valid_until=datetime.now(UTC) - timedelta(days=1),
        )
    )
    assert authority.roles_for("person:old", organization_scope="*") == set()


def test_delegation_depends_on_source_role_and_delegation_window() -> None:
    store = _store()
    authority = AuthorityRepository(store)
    baseline = datetime(2026, 1, 1, tzinfo=UTC)
    authority.put_principal(Principal(principal_id="person:owner", display_name="Owner"))
    authority.put_principal(
        Principal(principal_id="person:delegate", display_name="Delegate")
    )
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:owner",
            role="hr_approver",
            organization_scope="department:engineering",
            valid_from=baseline,
            valid_until=baseline + timedelta(days=60),
        )
    )
    authority.put_delegation(
        Delegation(
            from_principal_id="person:owner",
            to_principal_id="person:delegate",
            role="hr_approver",
            organization_scope="department:engineering",
            valid_from=baseline + timedelta(days=1),
            valid_until=baseline + timedelta(days=30),
        )
    )
    assert authority.roles_for(
        "person:delegate",
        organization_scope="department:engineering",
        at=baseline + timedelta(days=10),
    ) == {"hr_approver"}
    assert authority.roles_for(
        "person:delegate",
        organization_scope="department:engineering",
        at=baseline + timedelta(days=40),
    ) == set()


def test_execution_authorization_points_to_approval_satisfaction() -> None:
    policy_ref = default_onboarding_policy_version().policy_ref
    case = AdministrativeCase(
        case_kind="employee-onboarding",
        requester_principal_id="person:requester",
        subject_ref="employee:new",
        status=CaseStatus.AUTHORIZED,
        version=5,
        authority_epoch=2,
        policy_ref=policy_ref,
    )
    decision_id = uuid4()
    satisfaction = ApprovalSatisfaction(
        satisfaction_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        policy_ref=policy_ref,
        decision_ids=(decision_id,),
        satisfied_roles=("hr_approver",),
    )
    authorization = mint_execution_authorization_from_approval(
        case,
        satisfaction,
        issuer_principal_id="service:administrative-orchestrator",
        target_system="hris",
        allowed_operations=("employee.create",),
        authority_class=AuthorityClass.EMPLOYMENT,
    )
    assert authorization.approval_satisfaction_id == satisfaction.satisfaction_id
    assert authorization.decision_id is None
