from __future__ import annotations

from uuid import uuid4

import pytest

from administrative_orchestrator.completion import assess_administrative_completion
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
from administrative_orchestrator.execution_repository import (
    ExecutionConflict,
    ExecutionRepository,
)
from administrative_orchestrator.intake.artifacts import FilesystemArtifactStore
from administrative_orchestrator.intake.documents import (
    DocumentAttachmentProcessor,
    DocumentErrorCode,
    DocumentParseError,
    DocumentProcessingStatus,
    MessageAttachment,
)
from administrative_orchestrator.obligations import (
    AdministrativeObligation,
    AdministrativeObligationSet,
    EffectObligationLink,
    ObligationFulfillmentKind,
)
from administrative_orchestrator.persistence import SqlStore


def _case() -> AdministrativeCase:
    return AdministrativeCase(
        case_kind="procurement-request",
        requester_principal_id="person:requester",
        subject_ref="transaction:one",
        status=CaseStatus.AUTHORIZED,
    )


def _obligations(case: AdministrativeCase) -> tuple[AdministrativeObligationSet, AdministrativeObligation]:
    obligation = AdministrativeObligation(
        obligation_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=uuid4(),
        kind="erp.purchase_order.create_draft",
        subject_ref=case.subject_ref,
        target_system="erp",
        required_operation="purchase_order.create_draft",
        expected_postcondition={"state": "draft"},
        authority_class=AuthorityClass.FINANCIAL,
        fulfillment_kind=ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED,
    )
    return (
        AdministrativeObligationSet(
            requirement_id=uuid4(),
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            governance_basis_id=obligation.governance_basis_id,
            obligations=(obligation,),
        ),
        obligation,
    )


def _effect(case: AdministrativeCase, obligation: AdministrativeObligation) -> EffectRecord:
    return EffectRecord(
        effect_id=uuid4(),
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        authorization_id=uuid4(),
        target_system=obligation.target_system,
        operation=obligation.required_operation,
        subject_ref=obligation.subject_ref,
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=obligation.authority_class,
        status=EffectStatus.SUCCEEDED,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _outcome(case: AdministrativeCase, effect: EffectRecord, kind: str) -> ConfirmedOutcome:
    return ConfirmedOutcome(
        outcome_id=uuid4(),
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        effect_id=effect.effect_id,
        realization_assessment_id=uuid4(),
        outcome_kind=kind,
        evidence=[
            EvidenceRef(
                source="test",
                owner="test",
                observed_at=case.updated_at,
            )
        ],
        confirmed_at=case.updated_at,
    )


def _realization(effect: EffectRecord) -> EffectRealizationAssessment:
    return EffectRealizationAssessment(
        assessment_id=uuid4(),
        effect_id=effect.effect_id,
        disposition=RealizationDisposition.VERIFIED,
        evidence=[
            EvidenceRef(
                source="test",
                owner="test",
                observed_at=effect.updated_at,
            )
        ],
        assessed_at=effect.updated_at,
    )


def test_completion_binds_exact_outcome_kind_to_the_linked_effect() -> None:
    case = _case()
    obligation_set, obligation = _obligations(case)
    effect_a = _effect(case, obligation)
    effect_b = _effect(case, obligation)
    expected_kind = "erp.purchase_order.create_draft.verified"
    assessment = assess_administrative_completion(
        obligation_set,
        [effect_a, effect_b],
        [_outcome(case, effect_a, "erp.purchase_order.confirm.verified"), _outcome(case, effect_b, expected_kind)],
        links=[
            EffectObligationLink(
                effect_id=effect_a.effect_id,
                obligation_id=obligation.obligation_id,
                governance_basis_id=obligation.governance_basis_id,
            )
        ],
    )
    assert not assessment.satisfied
    assert expected_kind in assessment.missing_outcome_kinds


def test_completion_rejects_crossed_outcome_kinds_between_effects() -> None:
    case = _case()
    governance_basis_id = uuid4()
    obligation_a = AdministrativeObligation(
        obligation_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        kind="erp.purchase_order.create_draft",
        subject_ref="transaction:a",
        target_system="erp",
        required_operation="purchase_order.create_draft",
        expected_postcondition={},
        authority_class=AuthorityClass.FINANCIAL,
    )
    obligation_b = obligation_a.model_copy(
        update={
            "obligation_id": uuid4(),
            "kind": "erp.vendor_bill.create_draft",
            "subject_ref": "transaction:b",
            "required_operation": "vendor_bill.create_draft",
        }
    )
    obligation_set = AdministrativeObligationSet(
        requirement_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        obligations=(obligation_a, obligation_b),
    )
    effect_a = _effect(case, obligation_a)
    effect_b = _effect(case, obligation_b)
    realization_a = _realization(effect_a)
    realization_b = _realization(effect_b)
    outcome_a = _outcome(
        case,
        effect_a,
        "erp.vendor_bill.create_draft.verified",
    ).model_copy(update={"realization_assessment_id": realization_a.assessment_id})
    outcome_b = _outcome(
        case,
        effect_b,
        "erp.purchase_order.create_draft.verified",
    ).model_copy(update={"realization_assessment_id": realization_b.assessment_id})
    assessment = assess_administrative_completion(
        obligation_set,
        [effect_a, effect_b],
        [outcome_a, outcome_b],
        realizations=[realization_a, realization_b],
        links=[
            EffectObligationLink(
                effect_id=effect_a.effect_id,
                obligation_id=obligation_a.obligation_id,
                governance_basis_id=governance_basis_id,
            ),
            EffectObligationLink(
                effect_id=effect_b.effect_id,
                obligation_id=obligation_b.obligation_id,
                governance_basis_id=governance_basis_id,
            ),
        ],
    )
    assert not assessment.satisfied
    assert set(assessment.missing_outcome_kinds) == {
        "erp.purchase_order.create_draft.verified",
        "erp.vendor_bill.create_draft.verified",
    }


def test_completion_rejects_outcome_with_cross_effect_realization() -> None:
    case = _case()
    obligation_set, obligation = _obligations(case)
    effect = _effect(case, obligation)
    other_effect = _effect(case, obligation)
    realization = _realization(other_effect)
    outcome = _outcome(
        case,
        effect,
        "erp.purchase_order.create_draft.verified",
    ).model_copy(update={"realization_assessment_id": realization.assessment_id})
    assessment = assess_administrative_completion(
        obligation_set,
        [effect],
        [outcome],
        realizations=[realization],
        links=[
            EffectObligationLink(
                effect_id=effect.effect_id,
                obligation_id=obligation.obligation_id,
                governance_basis_id=obligation.governance_basis_id,
            )
        ],
    )
    assert not assessment.satisfied
    assert assessment.missing_realization_obligation_ids == (
        obligation.obligation_id,
    )


def test_repository_rejects_outcome_with_cross_effect_realization() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    request = AdministrativeRequest(
        requester_principal_id="person:test",
        channel="test",
        intent="m8 repository invariant",
    )
    case = _case()
    store.create_case(request, case)
    policy = PolicyRef(
        policy_id="m8-test",
        version="v1",
        owner="test",
        effective_from=case.created_at,
    )
    authorization = ExecutionAuthorization(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        approval_satisfaction_id=uuid4(),
        issuer_principal_id="service:test",
        target_system="erp",
        subject_ref=case.subject_ref,
        allowed_operations=("purchase_order.create_draft",),
        authority_class=AuthorityClass.FINANCIAL,
        policy_ref=policy,
    )
    repository = ExecutionRepository(store)
    repository.put_authorization(authorization)
    _, obligation = _obligations(case)
    effect_a = repository.put_effect(
        _effect(case, obligation).model_copy(
            update={"authorization_id": authorization.authorization_id}
        )
    )
    effect_b = repository.put_effect(
        _effect(case, obligation).model_copy(
            update={"authorization_id": authorization.authorization_id}
        )
    )
    realization_b = _realization(effect_b)
    repository.put_realization(realization_b, case_id=case.case_id)
    with pytest.raises(ExecutionConflict, match="different effect"):
        repository.put_outcome(
            _outcome(
                case,
                effect_a,
                "erp.purchase_order.create_draft.verified",
            ).model_copy(
                update={"realization_assessment_id": realization_b.assessment_id}
            )
        )


def test_document_parser_failure_uses_bounded_error_without_exception_text(tmp_path) -> None:
    class FailingParser:
        def parse(self, attachment, content):
            del attachment, content
            raise DocumentParseError(
                "parser dependency is unavailable",
                code=DocumentErrorCode.PARSER_UNAVAILABLE,
            )

    attachment = MessageAttachment(
        attachment_ref="document-1",
        message_ref="message-1",
        source_system="test",
        tenant_ref="tenant:test",
        source_event_ref="event-1",
        filename="document.txt",
        mime_type="text/plain",
        content=b"safe test document",
    )
    result = DocumentAttachmentProcessor(
        FilesystemArtifactStore(tmp_path / "artifacts"),
        FailingParser(),
    ).process(attachment)
    assert result.status is DocumentProcessingStatus.FAILED
    assert result.error_code == DocumentErrorCode.PARSER_UNAVAILABLE.value
    assert result.error_message == "parser dependency is unavailable"
    assert "document" not in result.error_message
