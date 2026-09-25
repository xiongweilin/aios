from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from administrative_orchestrator.admission import IntakeAssessmentService
from administrative_orchestrator.authority import ApprovalSatisfaction
from administrative_orchestrator.domain import (
    AdministrativeRequest,
    CaseStatus,
    Decision,
    DecisionDisposition,
    FactSnapshot,
    PolicyRef,
    Principal,
    PrincipalKind,
    ReopenReason,
    RoleAssignment,
)
from administrative_orchestrator.effect_provider import (
    ProviderExecutionResult,
    ProviderExecutionStatus,
    RealityObservation,
)
from administrative_orchestrator.financial import (
    AdministrativeCaseEvidenceLink,
    ExpenseFacts,
    ExpensePolicy,
    InvoiceFacts,
    InvoiceLine,
    Money,
    ProcurementFacts,
    ProcurementPolicy,
    TransactionQualificationAssessment,
    TransactionQualificationResult,
    VendorMasterRecord,
    qualify_invoice_transaction,
)
from administrative_orchestrator.financial_admission import (
    CandidateExpenseAdmissionService,
    CandidateProcurementAdmissionService,
)
from administrative_orchestrator.financial_execution import FinancialExecutionEngine
from administrative_orchestrator.governance import GovernanceRepository
from administrative_orchestrator.intake.models import (
    CandidateAdministrativeRequest,
    CandidateAuthority,
    CandidateFactAssertion,
    IntakeDisposition,
    IntakeReceipt,
    IntakeVerificationStatus,
    SourceArtifact,
)
from administrative_orchestrator.intake.repository import IntakeRepository
from administrative_orchestrator.messaging import claim_outbox
from administrative_orchestrator.obligations import (
    ObligationRepository,
    derive_financial_obligations,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import PolicyDisposition
from administrative_orchestrator.policy_plane import (
    PolicyRepository,
    default_expense_policy_version,
    default_procurement_policy_version,
)
from administrative_orchestrator.service import (
    apply_policy_evaluation,
    create_case,
    record_decision,
    start_policy_evaluation,
)
from administrative_orchestrator.transaction_repository import (
    TransactionRecordConflict,
    TransactionRepository,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_financial_observation,
)


def _financial_case():
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="procure equipment",
    )
    facts = ProcurementFacts(
        description="laptop",
        requested_quantity=Decimal("2"),
        estimated_amount=Money(amount=Decimal("1200.00"), currency="USD"),
        candidate_vendor="Acme",
        vendor_ref="odoo:res.partner:42",
        cost_center="engineering",
    )
    case = create_case(
        request,
        case_kind="procurement-request",
        subject_ref="transaction:1",
        fact_snapshot=FactSnapshot(
            source="intake:test",
            owner="reviewer:1",
            observed_at=datetime(2026, 9, 12, tzinfo=UTC),
            facts=facts.model_dump(mode="json"),
        ),
    ).model_copy(
        update={
            "policy_ref": PolicyRef(
                policy_id="procurement-request",
                version="v1",
                owner="test",
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            )
        }
    )
    return request, case, facts


def test_money_rejects_float_and_financial_obligation_is_bounded() -> None:
    with pytest.raises(ValueError, match="binary floats"):
        Money(amount=1.2, currency="USD")

    _, case, facts = _financial_case()
    evaluation = ProcurementPolicy(case.policy_ref).evaluate(facts)
    obligations = derive_financial_obligations(
        case,
        evaluation,
        governance_basis_id=uuid4(),
    )
    assert {item.required_operation for item in obligations.obligations} == {
        "purchase_order.create_draft",
        "purchase_order.confirm",
    }
    assert all(
        item.expected_postcondition["settlement"] == "forbidden"
        for item in obligations.obligations
    )


def test_persisted_financial_obligations_keep_dispatch_order() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    request, case, facts = _financial_case()
    store.create_case(request, case)
    evaluation = ProcurementPolicy(case.policy_ref).evaluate(facts)
    expected = derive_financial_obligations(
        case,
        evaluation,
        governance_basis_id=uuid4(),
    )

    repository = ObligationRepository(store)
    repository.put(expected)

    restored = repository.get_current(case.case_id, case.authority_epoch)
    assert restored == expected
    assert [item.required_operation for item in restored.obligations] == [
        "purchase_order.create_draft",
        "purchase_order.confirm",
    ]


def test_transaction_evidence_and_assessment_are_idempotent() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    intake = IntakeRepository(store)
    request, case, _ = _financial_case()
    store.create_case(request, case)
    artifact = intake.append_source_artifact(
        SourceArtifact(
            source_kind="test",
            source_system="test",
            tenant_ref="tenant:test",
            canonical_source_ref="test:artifact:1",
            source_event_ref="event:1",
            content_digest="a" * 64,
            storage_ref="sha256:" + "a" * 64,
            size=10,
            authenticity_class="test",
            retention_class="m8",
        )
    )
    repository = TransactionRepository(store)
    link = AdministrativeCaseEvidenceLink(
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        artifact_ref=artifact.artifact_id,
        declared_role="quote",
        source="human-review",
        linked_by="person:reviewer",
    )
    assert repository.append_evidence_link(link) == link
    assert repository.append_evidence_link(link.model_copy(update={"link_id": uuid4()})) == link

    assessment = TransactionQualificationAssessment(
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        assessment_kind="vendor_qualification",
        input_refs=(str(artifact.artifact_id),),
        rule_ref="m8-vendor-master-v1",
        result=TransactionQualificationResult.QUALIFIED,
    )
    assert repository.append_assessment(assessment) == assessment
    assert repository.list_assessments(case.case_id, case.authority_epoch) == [assessment]
    wakeups = claim_outbox(store)
    assert len(wakeups) == 1
    assert wakeups[0].event_type == "workflow.case_changed"
    assert wakeups[0].payload["cause"] == "qualification_assessment"
    assert repository.append_assessment(assessment) == assessment
    assert claim_outbox(store) == []


def test_financial_verification_rejects_settlement() -> None:
    _, case, facts = _financial_case()
    evaluation = ProcurementPolicy(case.policy_ref).evaluate(facts)
    obligation = next(
        item for item in derive_financial_obligations(case, evaluation, governance_basis_id=uuid4()).obligations
        if item.required_operation == "purchase_order.create_draft"
    )
    effect = type(
        "Effect",
        (),
        {
            "target_system": "erp",
            "operation": "purchase_order.create_draft",
            "subject_ref": case.subject_ref,
        },
    )()
    observation = RealityObservation(
        target_system="erp",
        operation="purchase_order.create_draft",
        subject_ref=case.subject_ref,
        found=True,
        state={"payload": dict(obligation.expected_postcondition["payload"]), "settlement": "paid"},
    )
    result = verify_financial_observation(
        effect,
        observation,
        expected_postcondition=obligation.expected_postcondition,
    )
    assert result.disposition is VerificationDisposition.MISMATCH


def test_invoice_qualification_is_deterministic_and_blocks_duplicates_or_mismatch() -> None:
    case_id = uuid4()
    invoice = InvoiceFacts(
        vendor_name="Acme",
        vendor_tax_id="TAX-1",
        invoice_number="INV-1",
        invoice_date="2026-09-12",
        total=Money(amount=Decimal("100.00"), currency="USD"),
        po_number="PO-1",
        line_items=(
            InvoiceLine(
                description="service",
                quantity=Decimal("2"),
                unit_price=Money(amount=Decimal("50.00"), currency="USD"),
            ),
        ),
    )
    vendor = VendorMasterRecord(vendor_ref="odoo:res.partner:7", legal_name="Acme", tax_id="TAX-1")
    po = {
        "vendor_ref": vendor.vendor_ref,
        "vendor_tax_id": vendor.tax_id,
        "currency": "USD",
        "po_number": "PO-1",
        "total": "100.00",
        "receipt_ref": "receipt:1",
        "line_items": [
            {"quantity": "2", "unit_price": "50.00", "currency": "USD"}
        ],
    }
    receipt = {
        "receipt_ref": "receipt:1",
        "line_items": [{"quantity": "2"}],
    }
    summary, assessments = qualify_invoice_transaction(
        case_id=case_id,
        authority_epoch=1,
        invoice=invoice,
        vendor_records=(vendor,),
        purchase_order=po,
        receipt=receipt,
        existing_invoices=(),
        input_refs=("artifact:invoice:1", "erp:po:1", "erp:receipt:1"),
        rule_ref="m8-invoice-qualification-v1",
    )
    assert summary.result is TransactionQualificationResult.QUALIFIED
    assert {item.assessment_kind for item in assessments} == {
        "vendor_qualification",
        "duplicate_invoice_check",
        "three_way_match",
    }

    duplicate, _ = qualify_invoice_transaction(
        case_id=case_id,
        authority_epoch=1,
        invoice=invoice,
        vendor_records=(vendor,),
        purchase_order=po,
        receipt=receipt,
        existing_invoices=(
            {"vendor_ref": vendor.vendor_ref, "invoice_number": "INV-1"},
        ),
        input_refs=("artifact:invoice:1",),
        rule_ref="m8-invoice-qualification-v1",
    )
    assert duplicate.result is TransactionQualificationResult.DUPLICATE

    mismatch_po = {**po, "total": "101.00"}
    mismatch, _ = qualify_invoice_transaction(
        case_id=case_id,
        authority_epoch=1,
        invoice=invoice,
        vendor_records=(vendor,),
        purchase_order=mismatch_po,
        receipt=receipt,
        existing_invoices=(),
        input_refs=("artifact:invoice:1",),
        rule_ref="m8-invoice-qualification-v1",
    )
    assert mismatch.result is TransactionQualificationResult.MISMATCH


def test_human_admitted_procurement_candidate_preserves_claim_authority() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = IntakeRepository(store)
    source_ref = uuid4()
    values = {
        "description": "laptop",
        "requested_quantity": "2",
        "estimated_amount": {"amount": "1200.00", "currency": "USD"},
        "candidate_vendor": "Acme",
        "vendor_ref": "odoo:res.partner:42",
        "cost_center": "engineering",
    }
    fact_refs = []
    for key, value in values.items():
        fact = CandidateFactAssertion(
            fact_key=key,
            value=value,
            authority=CandidateAuthority.CLAIM,
            source_refs=(source_ref,),
            no_evidence_reason="human-confirmed candidate fixture",
        )
        repository.append_candidate_fact(fact)
        fact_refs.append(fact.candidate_fact_id)
    candidate = CandidateAdministrativeRequest(
        conversation_ref="test/m8/procurement",
        interpretation_refs=(uuid4(),),
        candidate_requester="person:requester",
        candidate_intent="buy laptops",
        candidate_fact_refs=tuple(fact_refs),
        source_refs=(source_ref,),
    )
    repository.append_candidate_request(candidate)
    repository.persist_intake_receipt(
        IntakeReceipt(
            source_system="test",
            tenant_ref="tenant:m8",
            source_event_id="m8-procurement-1",
            verification_status=IntakeVerificationStatus.VERIFIED,
            artifact_ref=source_ref,
            delivery_digest="b" * 64,
        )
    )
    assessment = IntakeAssessmentService(repository).finalize_human(
        candidate.candidate_id,
        IntakeDisposition.ADMIT,
        reviewer_principal_id="person:reviewer",
        basis={"reviewed": True},
    )
    PolicyRepository(store).put_version(default_procurement_policy_version())
    result = CandidateProcurementAdmissionService(store, repository).promote_and_evaluate(
        candidate,
        assessment,
        source_system="test",
        tenant_ref="tenant:m8",
        source_event_id="m8-procurement-1",
        requester_principal_id="person:requester",
        subject_ref="transaction:m8-1",
    )
    assert result.case.case_kind == "procurement-request"
    assert result.policy_evaluation.required_decision_roles == ("procurement_approver",)
    assert result.case.fact_snapshot is not None
    assert all(
        assertion.authority.value == "claim"
        for assertion in result.case.fact_snapshot.assertions.values()
    )


def test_human_admitted_expense_candidate_evaluates_typed_policy() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = IntakeRepository(store)
    source_ref = uuid4()
    values = {
        "employee_ref": "employee:m8",
        "merchant": "M8 Acme Office Supplies",
        "expense_date": "2026-09-12",
        "amount": {"amount": "42.00", "currency": "USD"},
        "category": "office",
        "receipt_ref": "artifact:receipt:m8",
    }
    fact_refs = []
    for key, value in values.items():
        fact = CandidateFactAssertion(
            fact_key=key,
            value=value,
            authority=CandidateAuthority.CLAIM,
            source_refs=(source_ref,),
            no_evidence_reason="human-confirmed candidate fixture",
        )
        repository.append_candidate_fact(fact)
        fact_refs.append(fact.candidate_fact_id)
    candidate = CandidateAdministrativeRequest(
        conversation_ref="test/m8/expense",
        interpretation_refs=(uuid4(),),
        candidate_requester="person:requester",
        candidate_intent="prepare expense reimbursement",
        candidate_fact_refs=tuple(fact_refs),
        source_refs=(source_ref,),
    )
    repository.append_candidate_request(candidate)
    repository.persist_intake_receipt(
        IntakeReceipt(
            source_system="test",
            tenant_ref="tenant:m8",
            source_event_id="m8-expense-1",
            verification_status=IntakeVerificationStatus.VERIFIED,
            artifact_ref=source_ref,
            delivery_digest="c" * 64,
        )
    )
    assessment = IntakeAssessmentService(repository).finalize_human(
        candidate.candidate_id,
        IntakeDisposition.ADMIT,
        reviewer_principal_id="person:reviewer",
        basis={"reviewed": True},
    )
    PolicyRepository(store).put_version(default_expense_policy_version())
    result = CandidateExpenseAdmissionService(store, repository).promote_and_evaluate(
        candidate,
        assessment,
        source_system="test",
        tenant_ref="tenant:m8",
        source_event_id="m8-expense-1",
        requester_principal_id="person:requester",
        subject_ref="employee:m8",
    )
    assert result.case.case_kind == "expense-reimbursement"
    assert result.policy_evaluation.required_decision_roles == ("finance_approver",)


def test_expense_policy_blocks_over_limit_and_missing_receipt() -> None:
    policy_ref = PolicyRef(
        policy_id="expense-reimbursement",
        version="v1",
        owner="test",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    policy = ExpensePolicy(policy_ref)
    over_limit = ExpenseFacts(
        employee_ref="employee:m8",
        merchant="M8 merchant",
        expense_date="2026-09-12",
        amount=Money(amount=Decimal("1001.00"), currency="USD"),
        category="office",
        business_purpose="M8 staging",
        receipt_ref="artifact:receipt:m8",
    )
    missing_receipt = over_limit.model_copy(
        update={
            "amount": Money(amount=Decimal("42.00"), currency="USD"),
            "receipt_ref": None,
        }
    )

    over_limit_evaluation = policy.evaluate(over_limit)
    missing_receipt_evaluation = policy.evaluate(missing_receipt)

    assert over_limit_evaluation.disposition is PolicyDisposition.REOPEN_REQUIRED
    assert over_limit_evaluation.reopen_reason is ReopenReason.SCOPE_EXPANSION
    assert missing_receipt_evaluation.disposition is PolicyDisposition.NEED_MORE_FACTS
    assert "receipt_ref" in missing_receipt_evaluation.missing_facts


class _FinancialProvider:
    def __init__(self) -> None:
        self.observations: dict[str, RealityObservation] = {}
        self.payloads: dict[str, dict] = {}

    def execute(self, effect, payload):
        self.payloads[str(effect.effect_id)] = dict(payload)
        observation = RealityObservation(
            target_system=effect.target_system,
            operation=effect.operation,
            subject_ref=effect.subject_ref,
            found=True,
            state={"payload": dict(payload), "settlement": "forbidden"},
            provider_ref=f"odoo:{effect.effect_id}",
        )
        self.observations[str(effect.effect_id)] = observation
        return ProviderExecutionResult(
            status=ProviderExecutionStatus.SUCCEEDED,
            provider_ref=observation.provider_ref,
        )

    def observe(self, effect):
        return self.observations[str(effect.effect_id)]


def test_financial_execution_completes_only_the_bounded_erp_effects() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    uow = AdministrativeUnitOfWork(store)
    request, original, facts = _financial_case()
    policy_ref = original.policy_ref
    store.create_case(request, original)
    ready = start_policy_evaluation(original)
    evaluation = ProcurementPolicy(policy_ref).evaluate(facts)
    awaiting = apply_policy_evaluation(ready, evaluation)
    uow.apply_policy_transition(original, awaiting, evaluation)
    decision = Decision(
        case_id=awaiting.case_id,
        case_version=awaiting.version,
        authority_epoch=awaiting.authority_epoch,
        principal_id="person:approver",
        decision_role="procurement_approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="bounded transaction preparation approved",
        policy_ref=policy_ref,
    )
    authorized = record_decision(awaiting, decision)
    uow.apply_decision_transition(
        awaiting,
        authorized,
        decision,
        organization_scope="*",
    )
    TransactionRepository(store).append_assessment(
        TransactionQualificationAssessment(
            case_id=authorized.case_id,
            authority_epoch=authorized.authority_epoch,
            assessment_kind="vendor_qualification",
            input_refs=("vendor:42",),
            rule_ref="m8-vendor-master-v1",
            result=TransactionQualificationResult.QUALIFIED,
        )
    )

    provider = _FinancialProvider()
    completed = FinancialExecutionEngine(store, provider).run(
        authorized.case_id
    )
    assert completed.status is CaseStatus.COMPLETED
    obligation_set = ObligationRepository(store).get_current(
        completed.case_id, completed.authority_epoch
    )
    assert obligation_set is not None
    assert {item.required_operation for item in obligation_set.obligations} == {
        "purchase_order.create_draft",
        "purchase_order.confirm",
    }
    assert any("purchase_order_ref" in payload for payload in provider.payloads.values())


def test_financial_execution_waits_for_qualification_then_replays() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    uow = AdministrativeUnitOfWork(store)
    request, original, facts = _financial_case()
    store.create_case(request, original)
    ready = start_policy_evaluation(original)
    evaluation = ProcurementPolicy(original.policy_ref).evaluate(facts)
    awaiting = apply_policy_evaluation(ready, evaluation)
    uow.apply_policy_transition(original, awaiting, evaluation)
    decision = Decision(
        case_id=awaiting.case_id,
        case_version=awaiting.version,
        authority_epoch=awaiting.authority_epoch,
        principal_id="person:approver",
        decision_role="procurement_approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="bounded transaction preparation approved",
        policy_ref=original.policy_ref,
    )
    authorized = record_decision(awaiting, decision)
    uow.apply_decision_transition(
        awaiting,
        authorized,
        decision,
        organization_scope="*",
    )

    provider = _FinancialProvider()
    waiting = FinancialExecutionEngine(store, provider).run(authorized.case_id)
    assert waiting.status is CaseStatus.AUTHORIZED
    assert provider.payloads == {}
    assert ObligationRepository(store).get_current(
        waiting.case_id, waiting.authority_epoch
    ) is None

    TransactionRepository(store).append_assessment(
        TransactionQualificationAssessment(
            case_id=waiting.case_id,
            authority_epoch=waiting.authority_epoch,
            assessment_kind="vendor_qualification",
            input_refs=("vendor:42",),
            rule_ref="m8-vendor-master-v1",
            result=TransactionQualificationResult.QUALIFIED,
        )
    )
    completed = FinancialExecutionEngine(store, provider).run(waiting.case_id)
    assert completed.status is CaseStatus.COMPLETED
    assert len(provider.payloads) == 2


def test_superseding_mismatch_cannot_satisfy_financial_gate() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    uow = AdministrativeUnitOfWork(store)
    request, original, facts = _financial_case()
    store.create_case(request, original)
    ready = start_policy_evaluation(original)
    evaluation = ProcurementPolicy(original.policy_ref).evaluate(facts)
    awaiting = apply_policy_evaluation(ready, evaluation)
    uow.apply_policy_transition(original, awaiting, evaluation)
    decision = Decision(
        case_id=awaiting.case_id,
        case_version=awaiting.version,
        authority_epoch=awaiting.authority_epoch,
        principal_id="person:approver",
        decision_role="procurement_approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="bounded transaction preparation approved",
        policy_ref=original.policy_ref,
    )
    authorized = record_decision(awaiting, decision)
    uow.apply_decision_transition(
        awaiting,
        authorized,
        decision,
        organization_scope="*",
    )

    repository = TransactionRepository(store)
    qualified = repository.append_assessment(
        TransactionQualificationAssessment(
            case_id=authorized.case_id,
            authority_epoch=authorized.authority_epoch,
            assessment_kind="vendor_qualification",
            input_refs=("vendor:42",),
            rule_ref="m8-vendor-master-v1",
            result=TransactionQualificationResult.QUALIFIED,
        )
    )
    mismatch = repository.append_assessment(
        TransactionQualificationAssessment(
            case_id=authorized.case_id,
            authority_epoch=authorized.authority_epoch,
            assessment_kind="vendor_qualification",
            supersedes_assessment_id=qualified.assessment_id,
            input_refs=("vendor:42",),
            rule_ref="m8-vendor-master-v1",
            result=TransactionQualificationResult.MISMATCH,
            blocking_reasons=("vendor record changed",),
        )
    )
    assert mismatch.supersedes_assessment_id == qualified.assessment_id
    assert [item.assessment_id for item in repository.list_current_assessments(
        authorized.case_id, authorized.authority_epoch
    )] == [mismatch.assessment_id]

    provider = _FinancialProvider()
    blocked = FinancialExecutionEngine(store, provider).run(authorized.case_id)
    assert blocked.status is CaseStatus.AUTHORIZED
    assert provider.payloads == {}
    assert ObligationRepository(store).get_current(
        blocked.case_id, blocked.authority_epoch
    ) is None


def test_new_same_kind_qualification_requires_explicit_supersession() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    request, original, _ = _financial_case()
    store.create_case(request, original)
    repository = TransactionRepository(store)
    assessment = TransactionQualificationAssessment(
        case_id=original.case_id,
        authority_epoch=original.authority_epoch,
        assessment_kind="vendor_qualification",
        input_refs=("vendor:42",),
        rule_ref="m8-vendor-master-v1",
        result=TransactionQualificationResult.QUALIFIED,
    )
    repository.append_assessment(assessment)
    with pytest.raises(TransactionRecordConflict, match="must supersede"):
        repository.append_assessment(
            assessment.model_copy(update={"assessment_id": uuid4()})
        )


def test_bound_governance_basis_becomes_stale_after_qualification_supersession() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    PolicyRepository(store).put_version(
        default_procurement_policy_version().model_copy(update={"owner": "test"})
    )
    uow = AdministrativeUnitOfWork(store)
    uow.authority.put_principal(
        Principal(
            principal_id="person:approver",
            kind=PrincipalKind.PERSON,
            display_name="approver",
        )
    )
    uow.authority.put_role_assignment(
        RoleAssignment(
            principal_id="person:approver",
            role="procurement_approver",
            organization_scope="*",
            valid_from=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    request, original, facts = _financial_case()
    store.create_case(request, original)
    ready = start_policy_evaluation(original)
    evaluation = ProcurementPolicy(original.policy_ref).evaluate(facts)
    awaiting = apply_policy_evaluation(ready, evaluation)
    uow.apply_policy_transition(original, awaiting, evaluation)
    decision = Decision(
        case_id=awaiting.case_id,
        case_version=awaiting.version,
        authority_epoch=awaiting.authority_epoch,
        principal_id="person:approver",
        decision_role="procurement_approver",
        disposition=DecisionDisposition.APPROVE,
        rationale="bounded transaction preparation approved",
        policy_ref=original.policy_ref,
    )
    authorized = record_decision(awaiting, decision)
    uow.apply_decision_transition(
        awaiting,
        authorized,
        decision,
        organization_scope="*",
        approval_satisfaction=ApprovalSatisfaction(
            satisfaction_id=uuid4(),
            case_id=authorized.case_id,
            authority_epoch=authorized.authority_epoch,
            policy_ref=original.policy_ref,
            decision_ids=(decision.decision_id,),
            satisfied_roles=("procurement_approver",),
        ),
    )
    repository = TransactionRepository(store)
    qualified = repository.append_assessment(
        TransactionQualificationAssessment(
            case_id=authorized.case_id,
            authority_epoch=authorized.authority_epoch,
            assessment_kind="vendor_qualification",
            input_refs=("vendor:42",),
            rule_ref="m8-vendor-master-v1",
            result=TransactionQualificationResult.QUALIFIED,
        )
    )
    provider = _FinancialProvider()
    completed = FinancialExecutionEngine(store, provider).run(authorized.case_id)
    assert completed.status is CaseStatus.COMPLETED
    basis = GovernanceRepository(store).get_current_for_case(
        completed.case_id, completed.authority_epoch
    )
    assert basis is not None
    assert basis.transaction_qualifications

    repository.append_assessment(
        TransactionQualificationAssessment(
            case_id=authorized.case_id,
            authority_epoch=authorized.authority_epoch,
            assessment_kind="vendor_qualification",
            supersedes_assessment_id=qualified.assessment_id,
            input_refs=("vendor:42",),
            rule_ref="m8-vendor-master-v1",
            result=TransactionQualificationResult.MISMATCH,
            blocking_reasons=("vendor record changed",),
        )
    )
    current_case = store.get_case(authorized.case_id)
    validation = GovernanceRepository(store).revalidate(basis, current_case)
    assert not validation.valid
    assert "transaction qualification basis changed" in validation.reasons
