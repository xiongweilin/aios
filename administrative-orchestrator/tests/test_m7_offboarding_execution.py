from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from administrative_orchestrator.authority import (
    ApprovalSatisfaction,
    AuthorityRepository,
    IdentityBinding,
)
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AdministrativeRequest,
    CaseStatus,
    Decision,
    DecisionDisposition,
    Delegation,
    FactAssertion,
    FactAuthority,
    FactSnapshot,
    Principal,
    PrincipalKind,
    RoleAssignment,
)
from administrative_orchestrator.effect_provider import (
    ProviderExecutionResult,
    ProviderExecutionStatus,
    RealityObservation,
)
from administrative_orchestrator.execution_repository import ExecutionRepository
from administrative_orchestrator.governance import GovernanceRepository
from administrative_orchestrator.integrations.authoritative_sources import (
    AuthoritativeRecord,
)
from administrative_orchestrator.obligations import ObligationRepository
from administrative_orchestrator.offboarding_execution import (
    OffboardingExecutionEngine,
    ProductionTrustOffboardingExecutionEngine,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import OffboardingFacts
from administrative_orchestrator.policy_plane import (
    PolicyRepository,
    compile_offboarding_policy,
    default_offboarding_policy_version,
)
from administrative_orchestrator.transfer import (
    TransferRequirementRepository,
    TransferRequirementStatus,
)

_NOW = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)
_EFFECTIVE = _NOW + timedelta(hours=2)


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class _Provider:
    def __init__(self, on_execute=None) -> None:
        self.execute_calls = 0
        self.operations: list[str] = []
        self.observations: dict[str, RealityObservation] = {}
        self.on_execute = on_execute

    def execute(self, effect, payload):
        self.execute_calls += 1
        self.operations.append(effect.operation)
        if self.on_execute is not None:
            self.on_execute(effect)
        expected_payload = {
            key: payload[key]
            for key in (
                "employee_ref",
                "employment_episode_ref",
                "termination_status",
                "termination_effective_at",
            )
            if payload.get(key) is not None
        }
        state = {
            "target_system": effect.target_system,
            "operation": effect.operation,
            "subject_ref": effect.subject_ref,
            "payload": expected_payload,
        }
        if effect.operation == "employee.deactivate":
            state["active"] = False
        elif effect.operation == "identity.disable":
            state["enabled"] = False
        elif effect.operation == "sessions.revoke":
            state["active_sessions"] = 0
        observation = RealityObservation(
            found=True,
            target_system=effect.target_system,
            operation=effect.operation,
            subject_ref=effect.subject_ref,
            provider_ref=f"provider:{effect.effect_id}",
            state=state,
            digest=f"digest:{effect.effect_id}",
            observed_at=_EFFECTIVE + timedelta(seconds=1),
        )
        self.observations[str(effect.effect_id)] = observation
        return ProviderExecutionResult(
            status=ProviderExecutionStatus.SUCCEEDED,
            provider_ref=observation.provider_ref,
        )

    def observe(self, effect):
        return self.observations[str(effect.effect_id)]


def _authorized_case(*, successor: str | None):
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authority = AuthorityRepository(store)
    for principal_id in (
        "person:departing",
        "person:successor",
        "person:approver",
    ):
        authority.put_principal(
            Principal(
                principal_id=principal_id,
                kind=PrincipalKind.PERSON,
                display_name=principal_id,
            )
        )
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:departing",
            role="manager",
            organization_scope="org:finance",
            valid_from=_NOW - timedelta(days=30),
        )
    )
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:departing",
            role="hr_approver",
            organization_scope="org:finance",
            valid_from=_NOW - timedelta(days=30),
        )
    )
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:successor",
            role="hr_approver",
            organization_scope="org:finance",
            valid_from=_NOW - timedelta(days=30),
        )
    )
    authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:approver",
            role="hr_approver",
            organization_scope="org:finance",
            valid_from=_NOW - timedelta(days=30),
        )
    )
    authority.put_identity_binding(
        IdentityBinding(
            provider="keycloak",
            external_subject="kc:departing",
            principal_id="person:departing",
            valid_from=_NOW - timedelta(days=30),
        )
    )
    authority.put_delegation(
        Delegation(
            from_principal_id="person:departing",
            to_principal_id="person:successor",
            role="hr_approver",
            organization_scope="org:finance",
            valid_from=_NOW - timedelta(days=5),
            valid_until=_EFFECTIVE + timedelta(days=30),
        )
    )

    record = default_offboarding_policy_version()
    PolicyRepository(store).put_version(record)
    typed_facts = OffboardingFacts(
        employee_ref="odoo:hr.employee:42",
        termination_status="termination_scheduled",
        termination_effective_at=_EFFECTIVE.isoformat(),
        employment_episode_ref="episode:1",
        departing_principal_id="person:departing",
        successor_principal_id=successor,
    )
    fact_values = {**typed_facts.model_dump(mode="json"), "active": True}
    assertions = {
        key: FactAssertion(
            value=value,
            authority=FactAuthority.AUTHORITATIVE,
            source="odoo",
            owner="hris",
            source_ref="odoo:hr.employee:42",
            source_version="source:v1",
            observed_at=_NOW,
        )
        for key, value in fact_values.items()
        if value is not None
    }
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="offboard employee 42",
    )
    case = AdministrativeCase(
        case_kind="employee-offboarding",
        requester_principal_id=request.requester_principal_id,
        subject_ref="odoo:hr.employee:42",
        status=CaseStatus.AUTHORIZED,
        version=4,
        policy_ref=record.policy_ref,
        fact_snapshot=FactSnapshot(
            source="odoo",
            owner="hris",
            authority=FactAuthority.AUTHORITATIVE,
            observed_at=_NOW,
            facts=fact_values,
            assertions=assertions,
        ),
    )
    store.create_case(request, case)
    evaluation = compile_offboarding_policy(record).evaluate(typed_facts)
    store.append_policy_evaluation(
        case.case_id, case.version, case.authority_epoch, evaluation
    )
    decision = Decision(
        case_id=case.case_id,
        case_version=case.version - 1,
        authority_epoch=case.authority_epoch,
        principal_id="person:approver",
        decision_role="hr_approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="approved",
        policy_ref=record.policy_ref,
        decided_at=_NOW,
    )
    store.append_decision(decision)
    authority.put_decision_binding(decision, organization_scope="org:finance")
    satisfaction = authority.put_approval_satisfaction(
        ApprovalSatisfaction(
            satisfaction_id=uuid4(),
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            policy_ref=record.policy_ref,
            decision_ids=(decision.decision_id,),
            satisfied_roles=("hr_approver",),
            assessed_at=_NOW,
        )
    )
    GovernanceRepository(store).create_for_approval(
        case,
        satisfaction,
        organization_scope="org:finance",
        fact_dependency_keys=(
            "employee_ref",
            "termination_status",
            "termination_effective_at",
            "employment_episode_ref",
        ),
        expected_change_keys=("active",),
    )
    return store, authority, case


def test_waits_without_effects_then_completes_full_lifecycle() -> None:
    store, authority, case = _authorized_case(successor="person:successor")
    clock = _Clock(_NOW)
    manager_during_external: list[bool] = []
    provider = _Provider(
        on_execute=lambda effect: manager_during_external.append(
            "manager"
            in authority.roles_for(
                "person:successor",
                organization_scope="org:finance",
                at=_EFFECTIVE + timedelta(seconds=1),
            )
        )
    )
    engine = OffboardingExecutionEngine(store, provider, clock=clock)

    waiting = engine.run(case.case_id)
    assert waiting.status is CaseStatus.WAITING
    assert provider.execute_calls == 0
    assert ExecutionRepository(store).list_effects(case.case_id, case.authority_epoch) == []
    assert authority.get_principal("person:departing") is not None
    assert "manager" in authority.roles_for(
        "person:departing", organization_scope="org:finance", at=_NOW
    )
    assert engine.lifecycle.list_events() == []

    clock.value = _EFFECTIVE + timedelta(seconds=1)
    completed = engine.run(case.case_id)
    assert completed.status is CaseStatus.COMPLETED
    assert provider.execute_calls == 3
    assert provider.operations == [
        "identity.disable",
        "sessions.revoke",
        "employee.deactivate",
    ]
    assert manager_during_external == [False, False, False]
    assert authority.get_principal("person:departing") is None
    assert authority.roles_for(
        "person:departing", organization_scope="org:finance", at=clock.value
    ) == set()
    assert "manager" in authority.roles_for(
        "person:successor", organization_scope="org:finance", at=clock.value
    )
    requirements = TransferRequirementRepository(store).list_for_case(
        case.case_id, case.authority_epoch
    )
    assert any(
        item.status is TransferRequirementStatus.FULFILLED for item in requirements
    )
    obligation_set = ObligationRepository(store).get_current(
        case.case_id, case.authority_epoch
    )
    assert obligation_set is not None
    fulfillments = ObligationRepository(store).list_domain_state_fulfillments(
        case.case_id, case.authority_epoch
    )
    assert len(fulfillments) == len(
        [
            item
            for item in obligation_set.obligations
            if item.fulfillment_kind.value == "domain_state_verified"
        ]
    )

    replay = engine.run(case.case_id)
    assert replay.status is CaseStatus.COMPLETED
    assert provider.execute_calls == 3


def test_replay_reuses_frozen_obligations_after_partial_domain_planning() -> None:
    store, _authority, case = _authorized_case(successor="person:successor")
    engine = OffboardingExecutionEngine(
        store,
        _Provider(),
        clock=_Clock(_EFFECTIVE + timedelta(seconds=1)),
    )

    engine._plan_current_effects(case)
    first = ObligationRepository(store).get_current(case.case_id, case.authority_epoch)
    assert first is not None
    assert len(first.obligations) > 4

    # Domain-state fulfillment has already changed the authority graph. A
    # retry must keep the immutable obligation set for this authority epoch
    # instead of deriving a smaller set from the mutated graph.
    engine._plan_current_effects(case)

    replayed = ObligationRepository(store).get_current(
        case.case_id, case.authority_epoch
    )
    assert replayed == first


def test_missing_successor_does_not_block_security_revocation() -> None:
    store, authority, case = _authorized_case(successor=None)
    provider = _Provider()
    clock = _Clock(_EFFECTIVE + timedelta(seconds=1))
    current = OffboardingExecutionEngine(store, provider, clock=clock).run(case.case_id)

    assert current.status is CaseStatus.REOPEN_REQUIRED
    assert current.reopen_reason is not None
    assert current.reopen_reason.value == "authority_unresolved"
    assert provider.execute_calls == 3
    assert authority.get_principal("person:departing") is None
    assert authority.roles_for(
        "person:departing", organization_scope="org:finance", at=clock.value
    ) == set()
    requirements = TransferRequirementRepository(store).list_for_case(
        case.case_id, case.authority_epoch
    )
    manager = next(item for item in requirements if item.role == "manager")
    assert manager.status is TransferRequirementStatus.SUCCESSOR_MISSING
    assert not any(
        item.status is TransferRequirementStatus.FULFILLED for item in requirements
    )
    version = current.version
    replay = OffboardingExecutionEngine(store, provider, clock=clock).run(case.case_id)
    assert replay.status is CaseStatus.REOPEN_REQUIRED
    assert replay.version == version
    assert provider.execute_calls == 3


def test_production_revalidation_allows_expected_hris_active_change() -> None:
    store, _, case = _authorized_case(successor="person:successor")
    provider = _Provider()

    class _Source:
        def read_employee(self, employee_ref: str):
            assert employee_ref == "odoo:hr.employee:42"
            return AuthoritativeRecord.build(
                source="odoo",
                source_ref="odoo:hr.employee:42",
                source_version="source:v2",
                observed_at=datetime.now(UTC),
                value={
                    **case.fact_snapshot.facts,
                    "present": True,
                    "active": provider.execute_calls == 0,
                },
            )

    completed = ProductionTrustOffboardingExecutionEngine(
        store,
        provider,
        hris_source=_Source(),
        max_fact_age_seconds=300,
        clock=_Clock(_EFFECTIVE + timedelta(seconds=1)),
    ).run(case.case_id)
    assert completed.status is CaseStatus.COMPLETED


def test_successor_is_requalified_before_transfer() -> None:
    store, authority, case = _authorized_case(successor="person:successor")

    def deactivate_successor(effect) -> None:
        if effect.operation == "employee.deactivate":
            authority.put_principal(
                Principal(
                    principal_id="person:successor",
                    kind=PrincipalKind.PERSON,
                    display_name="person:successor",
                ),
                active=False,
            )

    provider = _Provider(on_execute=deactivate_successor)
    current = OffboardingExecutionEngine(
        store,
        provider,
        clock=_Clock(_EFFECTIVE + timedelta(seconds=1)),
    ).run(case.case_id)

    assert current.status is CaseStatus.REOPEN_REQUIRED
    requirements = TransferRequirementRepository(store).list_for_case(
        case.case_id, case.authority_epoch
    )
    manager = next(item for item in requirements if item.role == "manager")
    assert manager.status is TransferRequirementStatus.SUCCESSOR_QUALIFIED


@pytest.mark.parametrize(
    "changed",
    [
        {"termination_status": "termination_cancelled"},
        {
            "termination_effective_at": (
                _EFFECTIVE + timedelta(days=1)
            ).isoformat()
        },
        {"employment_episode_ref": "episode:2"},
    ],
)
def test_wake_revalidation_blocks_changed_or_rebound_employment(changed) -> None:
    store, authority, case = _authorized_case(successor="person:successor")
    provider = _Provider()

    class _ChangedSource:
        def read_employee(self, employee_ref: str):
            return AuthoritativeRecord.build(
                source="odoo",
                source_ref=employee_ref,
                source_version="source:changed",
                observed_at=datetime.now(UTC),
                value={**case.fact_snapshot.facts, **changed, "present": True},
            )

    engine = ProductionTrustOffboardingExecutionEngine(
        store,
        provider,
        hris_source=_ChangedSource(),
        max_fact_age_seconds=300,
        clock=_Clock(_EFFECTIVE + timedelta(seconds=1)),
    )
    reopened = engine.run(case.case_id)

    assert reopened.status is CaseStatus.REOPEN_REQUIRED
    assert provider.execute_calls == 0
    assert ExecutionRepository(store).list_effects(case.case_id, case.authority_epoch) == []
    assert authority.get_principal("person:departing") is not None
    assert "manager" in authority.roles_for(
        "person:departing",
        organization_scope="org:finance",
        at=_EFFECTIVE + timedelta(seconds=1),
    )
