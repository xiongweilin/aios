from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from administrative_orchestrator.completion import (
    assess_administrative_completion,
    assess_onboarding_completion,
)
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AdministrativeRequest,
    AuthorityClass,
    ConfirmedOutcome,
    EffectRealizationAssessment,
    EffectRecord,
    EffectReversibility,
    EffectStatus,
    EvidenceRef,
    RealizationDisposition,
)
from administrative_orchestrator.obligations import (
    AdministrativeObligation,
    AdministrativeObligationSet,
    EffectObligationLink,
    ObligationDomainStateFulfillment,
    ObligationError,
    ObligationFulfillmentKind,
    ObligationRepository,
    OnboardingObligationSet,
)
from administrative_orchestrator.persistence import SqlStore


def _store_and_case():
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    request = AdministrativeRequest(
        requester_principal_id="person:test",
        channel="test",
        intent="offboard employee:1",
    )
    case = AdministrativeCase(
        case_kind="employee-offboarding",
        requester_principal_id=request.requester_principal_id,
        subject_ref="employee:1",
    )
    store.create_case(request, case)
    return store, case


def _obligation(
    case,
    governance_basis_id,
    *,
    kind,
    target_system,
    operation,
    fulfillment_kind,
    authority_class,
) -> AdministrativeObligation:
    return AdministrativeObligation(
        obligation_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        kind=kind,
        subject_ref=case.subject_ref,
        target_system=target_system,
        required_operation=operation,
        expected_postcondition={"active": False},
        authority_class=authority_class,
        fulfillment_kind=fulfillment_kind,
    )


def test_administrative_obligation_set_keeps_onboarding_alias() -> None:
    assert OnboardingObligationSet is AdministrativeObligationSet


def test_domain_state_fulfillment_completes_only_domain_state_obligations() -> None:
    store, case = _store_and_case()
    governance_basis_id = uuid4()
    external = _obligation(
        case,
        governance_basis_id,
        kind="iam.identity.disable",
        target_system="iam",
        operation="identity.disable",
        fulfillment_kind=ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED,
        authority_class=AuthorityClass.PRIVILEGED_ACCESS,
    )
    domain_state = _obligation(
        case,
        governance_basis_id,
        kind="administrative.role.expire",
        target_system="administrative",
        operation="role.expire",
        fulfillment_kind=ObligationFulfillmentKind.DOMAIN_STATE_VERIFIED,
        authority_class=AuthorityClass.EMPLOYMENT,
    )
    obligation_set = AdministrativeObligationSet(
        requirement_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        obligations=(external, domain_state),
    )
    repository = ObligationRepository(store)
    repository.put(obligation_set)

    before = assess_administrative_completion(obligation_set, [], [])
    assert before.satisfied is False
    assert before.missing_domain_state_obligation_ids == (domain_state.obligation_id,)
    assert before.uncovered_obligation_ids == (external.obligation_id,)

    with pytest.raises(ObligationError):
        repository.record_domain_state_fulfillment(
            ObligationDomainStateFulfillment(
                fulfillment_id=uuid4(),
                obligation_id=external.obligation_id,
                case_id=case.case_id,
                authority_epoch=case.authority_epoch,
                governance_basis_id=governance_basis_id,
                verified_by="person:operator",
                reason="not allowed on an external obligation",
                observed_state_digest="a" * 64,
            )
        )

    fulfillment = ObligationDomainStateFulfillment(
        fulfillment_id=uuid4(),
        obligation_id=domain_state.obligation_id,
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        verified_by="person:operator",
        reason="role assignment validity ended at the effective time",
        observed_state_digest="b" * 64,
    )
    stored = repository.record_domain_state_fulfillment(fulfillment)
    assert stored == fulfillment
    assert repository.record_domain_state_fulfillment(fulfillment) == fulfillment
    with pytest.raises(ObligationError):
        repository.record_domain_state_fulfillment(
            fulfillment.model_copy(update={"fulfillment_id": uuid4(), "reason": "different"})
        )

    fulfillments = repository.list_domain_state_fulfillments(
        case.case_id, case.authority_epoch
    )
    after_domain_state = assess_administrative_completion(
        obligation_set, [], [], fulfillments=fulfillments
    )
    assert after_domain_state.missing_domain_state_obligation_ids == ()
    assert after_domain_state.satisfied is False

    effect = EffectRecord(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        authorization_id=uuid4(),
        target_system=external.target_system,
        operation=external.required_operation,
        subject_ref=external.subject_ref,
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=external.authority_class,
        status=EffectStatus.SUCCEEDED,
    )
    evidence = EvidenceRef(source='test', owner='test', observed_at=datetime.now(UTC))
    realization = EffectRealizationAssessment(
        effect_id=effect.effect_id,
        disposition=RealizationDisposition.VERIFIED,
        evidence=[evidence],
    )
    outcome = ConfirmedOutcome(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        effect_id=effect.effect_id,
        realization_assessment_id=realization.assessment_id,
        outcome_kind=f"{external.target_system}.{external.required_operation}.verified",
        evidence=[evidence],
    )
    link = EffectObligationLink(
        effect_id=effect.effect_id,
        obligation_id=external.obligation_id,
        governance_basis_id=governance_basis_id,
    )
    final = assess_administrative_completion(
        obligation_set,
        [effect],
        [outcome],
        realizations=[realization],
        links=[link],
        fulfillments=fulfillments,
    )
    assert final.satisfied is True
    assert final.missing_domain_state_obligation_ids == ()
    wrapper = assess_onboarding_completion(
        obligation_set,
        [effect],
        [outcome],
        realizations=[realization],
        links=[link],
        fulfillments=fulfillments,
    )
    assert wrapper == final
