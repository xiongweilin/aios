from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from administrative_orchestrator.domain import (
    AdministrativeCase,
    AdministrativeRequest,
    AuthorityClass,
    CaseStatus,
    ConfirmedOutcome,
    EffectRealizationAssessment,
    EffectRecord,
    EffectReversibility,
    EffectStatus,
    EvidenceRef,
    ExecutionAuthorization,
    PolicyRef,
    RealizationDisposition,
)
from administrative_orchestrator.execution_repository import ExecutionRepository
from administrative_orchestrator.obligations import (
    AdministrativeObligation,
    AdministrativeObligationSet,
    ObligationRepository,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.responsibility_discharge import (
    AdministrativeResponsibilityDischargeService,
    ResponsibilityDischargeStatus,
)

NOW = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)


def _fixture(*, completed: bool = True):
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    policy = PolicyRef(
        policy_id="employee-offboarding",
        version="v1",
        owner="administrative-orchestrator",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="offboard employee:1",
        received_at=NOW,
    )
    case = AdministrativeCase(
        case_kind="employee-offboarding",
        requester_principal_id=request.requester_principal_id,
        subject_ref="employee:1",
        status=CaseStatus.COMPLETED if completed else CaseStatus.VERIFYING,
        version=4,
        authority_epoch=2,
        policy_ref=policy,
        updated_at=NOW,
    )
    store.create_case(request, case)

    governance_basis_id = uuid4()
    obligation = AdministrativeObligation(
        obligation_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        kind="iam.identity.disable",
        subject_ref=case.subject_ref,
        target_system="iam",
        required_operation="identity.disable",
        expected_postcondition={"enabled": False},
        authority_class=AuthorityClass.PRIVILEGED_ACCESS,
    )
    obligation_set = AdministrativeObligationSet(
        requirement_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        obligations=(obligation,),
    )
    obligations = ObligationRepository(store)
    obligations.put(obligation_set)

    authorization = ExecutionAuthorization(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        approval_satisfaction_id=uuid4(),
        issuer_principal_id="service:administrative-orchestrator",
        target_system="iam",
        subject_ref=case.subject_ref,
        allowed_operations=("identity.disable",),
        authority_class=obligation.authority_class,
        policy_ref=policy,
        issued_at=NOW,
    )
    execution = ExecutionRepository(store)
    execution.put_authorization(authorization)
    effect = EffectRecord(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        authorization_id=authorization.authorization_id,
        obligation_id=obligation.obligation_id,
        governance_basis_id=governance_basis_id,
        target_system=obligation.target_system,
        operation=obligation.required_operation,
        subject_ref=obligation.subject_ref,
        reversibility=EffectReversibility.IRREVERSIBLE,
        authority_class=obligation.authority_class,
        status=EffectStatus.SUCCEEDED,
        created_at=NOW,
        updated_at=NOW,
    )
    execution.put_effect(effect)
    obligations.link_effect(effect, obligation)
    evidence = EvidenceRef(
        source="test-verifier",
        owner="test",
        observed_at=NOW,
        digest="digest:1",
    )
    realization = EffectRealizationAssessment(
        effect_id=effect.effect_id,
        disposition=RealizationDisposition.VERIFIED,
        evidence=[evidence],
        assessed_at=NOW,
    )
    execution.put_realization(realization, case_id=case.case_id)
    execution.put_outcome(
        ConfirmedOutcome(
            case_id=case.case_id,
            case_version=case.version,
            authority_epoch=case.authority_epoch,
            effect_id=effect.effect_id,
            realization_assessment_id=realization.assessment_id,
            outcome_kind="iam.identity.disable.verified",
            evidence=[evidence],
            confirmed_at=NOW,
        )
    )
    return store, case, obligation, effect


class FakeRuntimeBridge:
    cutover = True

    def __init__(self) -> None:
        self.statuses: dict[str, str] = {}
        self.discharge_calls: list[str] = []

    def responsibility_ref_for_effect(self, effect_id):
        ref = f"responsibility:test:{effect_id}"
        self.statuses.setdefault(ref, "active")
        return ref

    def responsibility_status(self, responsibility_ref: str) -> str:
        return self.statuses[responsibility_ref]

    def discharge_responsibility(
        self,
        responsibility_ref: str,
        *,
        decision_ref: str,
        decided_by: str,
        subject_ref: str,
        basis_refs: tuple[str, ...],
    ):
        assert decided_by == "service:administrative-orchestrator"
        assert subject_ref == "employee:1"
        assert basis_refs
        self.discharge_calls.append(responsibility_ref)
        self.statuses[responsibility_ref] = "discharged"
        return ("assessment:runtime", decision_ref, "transition:runtime")


def test_completed_case_discharges_current_runtime_responsibility_once() -> None:
    store, case, obligation, effect = _fixture()
    bridge = FakeRuntimeBridge()
    service = AdministrativeResponsibilityDischargeService(store, bridge)

    first = service.discharge(case)
    second = service.discharge(case)

    expected_ref = bridge.responsibility_ref_for_effect(effect.effect_id)
    assert first.status is ResponsibilityDischargeStatus.DISCHARGED
    assert first.responsibility_refs == (expected_ref,)
    assert first.discharged_refs == (expected_ref,)
    assert first.assessment_refs == ((expected_ref, "assessment:runtime"),)
    assert first.transition_refs == ((expected_ref, "transition:runtime"),)
    assert obligation.obligation_id in service.project_responsibility_set(
        case,
        ObligationRepository(store).get_current(case.case_id, case.authority_epoch),
    )[0].obligation_ids
    assert second.status is ResponsibilityDischargeStatus.DISCHARGED
    assert bridge.discharge_calls == [expected_ref]


def test_case_must_be_completed_before_runtime_discharge() -> None:
    store, case, _obligation, _effect = _fixture(completed=False)
    bridge = FakeRuntimeBridge()
    result = AdministrativeResponsibilityDischargeService(store, bridge).discharge(case)

    assert result.status is ResponsibilityDischargeStatus.PENDING
    assert result.blocker == "case_not_completed"
    assert bridge.discharge_calls == []
