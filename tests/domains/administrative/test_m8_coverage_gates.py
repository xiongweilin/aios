from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from administrative_orchestrator.domain import (
    AuthorityClass,
    EffectRecord,
    EffectReversibility,
    PolicyRef,
)
from administrative_orchestrator.effect_provider import (
    ObservationAvailability,
    ObservationFreshness,
    ObservationPresence,
    RealityObservation,
)
from administrative_orchestrator.financial import (
    ExpenseFacts,
    ExpensePolicy,
    InvoiceAPPolicy,
    InvoiceFacts,
    InvoiceLine,
    Money,
    ProcurementFacts,
    TransactionQualificationResult,
    has_material_financial_revision,
    match_three_way,
    qualify_vendor,
)
from administrative_orchestrator.intake.document_repository import (
    DocumentRepository,
    DocumentRepresentationConflict,
)
from administrative_orchestrator.intake.documents import (
    DocumentParseError,
    MessageAttachment,
    PdfTextDocumentParser,
)
from administrative_orchestrator.intake.models import DocumentRepresentation, SourceArtifact
from administrative_orchestrator.intake.repository import IntakeRepository
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.production_readiness import ProductionReadinessError
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_financial_observation,
)

NOW = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)


def _effect(*, target: str = "erp", operation: str = "purchase_order.create_draft") -> EffectRecord:
    return EffectRecord(
        effect_id=uuid4(),
        case_id=uuid4(),
        case_version=1,
        authority_epoch=1,
        authorization_id=uuid4(),
        obligation_id=uuid4(),
        governance_basis_id=uuid4(),
        target_system=target,
        operation=operation,
        subject_ref="transaction:test",
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=AuthorityClass.FINANCIAL,
        created_at=NOW,
        updated_at=NOW,
    )


def _financial_observation(effect: EffectRecord, **updates: object) -> RealityObservation:
    values = {
        "availability": ObservationAvailability.AVAILABLE,
        "presence": ObservationPresence.PRESENT,
        "freshness": ObservationFreshness.CURRENT,
        "target_system": effect.target_system,
        "operation": effect.operation,
        "subject_ref": effect.subject_ref,
        "state": {"payload": {"purchase_order_ref": "po:1"}},
        "observed_at": NOW,
    }
    values.update(updates)
    return RealityObservation(**values)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("availability", ObservationAvailability.UNAVAILABLE, VerificationDisposition.UNAVAILABLE),
        ("availability", ObservationAvailability.UNKNOWN, VerificationDisposition.UNKNOWN),
        ("freshness", ObservationFreshness.STALE, VerificationDisposition.STALE),
        ("freshness", ObservationFreshness.UNKNOWN, VerificationDisposition.UNKNOWN),
        ("presence", ObservationPresence.ABSENT, VerificationDisposition.ABSENT),
        ("presence", ObservationPresence.UNKNOWN, VerificationDisposition.UNKNOWN),
    ],
)
def test_financial_verification_fails_closed_for_non_authoritative_observations(
    field: str,
    value: object,
    expected: VerificationDisposition,
) -> None:
    effect = _effect()
    result = verify_financial_observation(
        effect,
        _financial_observation(effect, **{field: value}),
        expected_postcondition={
            "target_system": effect.target_system,
            "operation": effect.operation,
            "subject_ref": effect.subject_ref,
            "payload": {"purchase_order_ref": "po:1"},
            "settlement": "forbidden",
        },
    )
    assert result.disposition is expected


def test_financial_verification_reports_identity_and_payload_mismatches() -> None:
    effect = _effect()
    result = verify_financial_observation(
        effect,
        _financial_observation(
            effect,
            operation="purchase_order.confirm",
            state={"payload": "not-a-mapping"},
        ),
        expected_postcondition={
            "target_system": effect.target_system,
            "operation": effect.operation,
            "subject_ref": effect.subject_ref,
            "payload": {"purchase_order_ref": "po:1"},
        },
    )
    assert result.disposition is VerificationDisposition.MISMATCH
    assert "operation" in result.differences
    assert result.differences["payload"]["actual"] == "str"


def _source_artifact() -> SourceArtifact:
    return SourceArtifact(
        source_kind="attachment",
        source_system="test",
        tenant_ref="tenant:test",
        canonical_source_ref="attachment:test:1",
        source_event_ref="event:test:1",
        content_digest="a" * 64,
        storage_ref="sha256:" + "a" * 64,
        size=1,
        authenticity_class="test",
        retention_class="m8",
    )


def _representation(artifact_ref, *, representation_id=None, storage_ref="sha256:representation"):
    return DocumentRepresentation(
        representation_id=representation_id or uuid4(),
        source_artifact_ref=artifact_ref,
        representation_kind="plain-text",
        extractor_ref="test-parser",
        extractor_version="1",
        content_digest="b" * 64,
        storage_ref=storage_ref,
        size=4,
        created_at=NOW,
        metadata={"test": True},
    )


def test_document_representation_repository_enforces_identity_semantics_and_listing() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    artifact = IntakeRepository(store).append_source_artifact(_source_artifact())
    repository = DocumentRepository(store)
    original = _representation(artifact.artifact_id)

    assert repository.append_representation(original) == original
    assert repository.get(original.representation_id) == original
    assert repository.list_for_artifact(artifact.artifact_id) == [original]
    assert repository.get(uuid4()) is None

    with pytest.raises(DocumentRepresentationConflict, match="identity was reused"):
        repository.append_representation(
            original.model_copy(update={"storage_ref": "sha256:changed"})
        )

    with pytest.raises(DocumentRepresentationConflict, match="semantics already exist"):
        repository.append_representation(
            original.model_copy(update={"representation_id": uuid4()})
        )


def _pdf_attachment(content: bytes = b"not-a-pdf") -> MessageAttachment:
    return MessageAttachment(
        attachment_ref="pdf:test",
        message_ref="message:test",
        source_system="test",
        tenant_ref="tenant:test",
        source_event_ref="event:test",
        filename="document.pdf",
        mime_type="application/pdf",
        content=content,
    )


def test_pdf_parser_rejects_unsupported_and_bounded_inputs() -> None:
    with pytest.raises(ValueError, match="limits must be positive"):
        PdfTextDocumentParser(max_bytes=0)

    plain = _pdf_attachment().model_copy(update={"filename": "document.txt", "mime_type": "text/plain"})
    with pytest.raises(DocumentParseError, match="supported PDF"):
        PdfTextDocumentParser().parse(plain, b"text")

    with pytest.raises(DocumentParseError, match="byte limit"):
        PdfTextDocumentParser(max_bytes=1).parse(_pdf_attachment(), b"xx")

    with pytest.raises(DocumentParseError, match="malformed"):
        PdfTextDocumentParser().parse(_pdf_attachment(), b"not-a-pdf")


def test_pdf_parser_enforces_page_text_and_extraction_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    import pypdf

    class Page:
        def __init__(self, text: str = "text", *, fail: bool = False) -> None:
            self.text = text
            self.fail = fail

        def extract_text(self) -> str:
            if self.fail:
                raise RuntimeError("parser failure detail")
            return self.text

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(pages=[Page(), Page()]),
    )
    with pytest.raises(DocumentParseError, match="page limit"):
        PdfTextDocumentParser(max_pages=1).parse(_pdf_attachment(), b"ignored")

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(pages=[Page("")]),
    )
    with pytest.raises(DocumentParseError, match="no extractable text"):
        PdfTextDocumentParser().parse(_pdf_attachment(), b"ignored")

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(pages=[Page("long text")]),
    )
    with pytest.raises(DocumentParseError, match="text limit"):
        PdfTextDocumentParser(max_text_chars=1).parse(_pdf_attachment(), b"ignored")

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(pages=[Page(fail=True)]),
    )
    with pytest.raises(DocumentParseError, match="text extraction"):
        PdfTextDocumentParser().parse(_pdf_attachment(), b"ignored")


def test_legacy_completion_reports_missing_outcomes_and_realizations() -> None:
    from administrative_orchestrator.completion import assess_onboarding_completion
    from administrative_orchestrator.domain import ConfirmedOutcome, EvidenceRef

    effect = _effect(target="erp", operation="purchase_order.create_draft")
    expected_kind = "erp.purchase_order.create_draft.verified"
    empty = assess_onboarding_completion([effect], [])
    assert effect.effect_id in empty.missing_effect_ids
    assert expected_kind in empty.missing_outcome_kinds

    wrong = ConfirmedOutcome(
        case_id=effect.case_id,
        case_version=effect.case_version,
        authority_epoch=effect.authority_epoch,
        effect_id=effect.effect_id,
        realization_assessment_id=uuid4(),
        outcome_kind="erp.purchase_order.confirm.verified",
        evidence=[EvidenceRef(source="test", owner="test", observed_at=NOW)],
        confirmed_at=NOW,
    )
    wrong_result = assess_onboarding_completion([effect], [wrong])
    assert expected_kind in wrong_result.missing_outcome_kinds

    matching = wrong.model_copy(
        update={"outcome_kind": expected_kind, "realization_assessment_id": uuid4()}
    )
    missing_realization = assess_onboarding_completion([effect], [matching])
    assert effect.effect_id in missing_realization.missing_realization_obligation_ids


def test_financial_boundaries_cover_exact_values_and_policy_rejection_paths() -> None:
    with pytest.raises(ValueError, match="three-letter"):
        Money(amount="1.00", currency="US$")
    with pytest.raises(ValueError, match="negative"):
        Money(amount="-1.00", currency="USD")
    with pytest.raises(ValueError, match="binary floats"):
        ProcurementFacts(requested_quantity=1.2)
    with pytest.raises(ValueError, match="binary floats"):
        InvoiceLine(description="item", quantity=1.2, unit_price=Money(amount="1", currency="USD"))
    with pytest.raises(ValueError, match="unsupported"):
        has_material_financial_revision("unsupported", {}, {})

    policy_ref = PolicyRef(
        policy_id="invoice-ap-preparation",
        version="v1",
        owner="test",
        effective_from=NOW,
    )
    assert InvoiceAPPolicy(policy_ref).evaluate(InvoiceFacts()).missing_facts

    expense_policy = ExpensePolicy(policy_ref.model_copy(update={"policy_id": "expense-reimbursement"}))
    expense_values = {
        "employee_ref": "employee:test",
        "merchant": "Acme",
        "expense_date": "2026-09-12",
        "business_purpose": "M8 test",
        "receipt_ref": "receipt:test",
    }
    currency = ExpenseFacts(
        **expense_values,
        amount=Money(amount="1", currency="EUR"),
        category="office",
    )
    category = ExpenseFacts(
        **expense_values,
        amount=Money(amount="1", currency="USD"),
        category="other",
    )
    assert expense_policy.evaluate(currency).reopen_reason is not None
    assert expense_policy.evaluate(category).reopen_reason is not None

    vendor = SimpleNamespace(vendor_ref="vendor:1", legal_name="Acme", tax_id="TAX-1")
    assert qualify_vendor(candidate_name="Missing", candidate_tax_id=None, records=(vendor,)).result is TransactionQualificationResult.AMBIGUOUS
    assert qualify_vendor(candidate_name="Acme", candidate_tax_id=None, records=(vendor, vendor)).result is TransactionQualificationResult.AMBIGUOUS

    invoice = InvoiceFacts(
        total=Money(amount="10", currency="USD"),
        po_number="PO-1",
        line_items=(
            InvoiceLine(
                description="item",
                quantity="1",
                unit_price=Money(amount="10", currency="USD"),
            ),
        ),
    )
    assert match_three_way(invoice=invoice, purchase_order={"currency": "USD", "po_number": "PO-1", "total": "bad"}, receipt={}) is TransactionQualificationResult.INCOMPLETE
    assert match_three_way(invoice=invoice, purchase_order={"currency": "USD", "po_number": "PO-1", "total": "10", "line_items": "bad"}, receipt={}) is TransactionQualificationResult.MISMATCH


def test_readiness_endpoints_fail_closed_on_world_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from administrative_orchestrator import api, operations_api

    settings = SimpleNamespace(
        runtime_profile="staging",
        world_runtime_mode="cutover",
        auth_mode="oidc",
        hris_source_kind="odoo",
        iam_source_kind="keycloak",
        auto_create_schema=False,
        external_effects_enabled=False,
        authority_enforcement_enabled=True,
    )

    monkeypatch.setattr(api, "_settings", settings)
    monkeypatch.setattr(
        api,
        "validate_world_runtime_compatibility",
        lambda _: (_ for _ in ()).throw(ProductionReadinessError("mismatch")),
    )
    with pytest.raises(HTTPException) as api_error:
        api.readyz()
    assert api_error.value.status_code == 503

    monkeypatch.setattr(api, "validate_world_runtime_compatibility", lambda _: {})
    assert api.readyz()["world_runtime"] == "cutover"

    monkeypatch.setattr(operations_api, "_settings", settings)
    monkeypatch.setattr(
        operations_api,
        "validate_world_runtime_compatibility",
        lambda _: (_ for _ in ()).throw(ProductionReadinessError("mismatch")),
    )
    with pytest.raises(HTTPException) as operations_error:
        operations_api.readyz()
    assert operations_error.value.status_code == 503


def test_workflow_selects_financial_engine_without_preparing_runtime_effect_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from administrative_orchestrator import workflows
    from administrative_orchestrator.workflows import definitions

    settings = SimpleNamespace(
        worker_database_url=None,
        database_url="sqlite+pysqlite:///:memory:",
        world_runtime_mode="disabled",
        external_effects_enabled=True,
        sandbox_base_url="http://sandbox.test",
        provider_timeout_seconds=1.0,
    )
    case = SimpleNamespace(
        case_kind="expense-reimbursement",
        status=__import__("administrative_orchestrator.domain", fromlist=["CaseStatus"]).CaseStatus.AUTHORIZED,
        version=1,
        authority_epoch=1,
    )
    used = []

    class Store:
        def get_case(self, case_id):
            del case_id
            return case

    class Engine:
        def __init__(self, store, provider):
            del store, provider
            used.append("financial")

        def run(self, case_id):
            del case_id
            return case

    monkeypatch.setattr(definitions, "get_settings", lambda: settings)
    monkeypatch.setattr(definitions, "SqlStore", lambda _: Store())
    monkeypatch.setattr(definitions, "HttpEffectProvider", lambda *args, **kwargs: object())
    monkeypatch.setattr(definitions, "FinancialExecutionEngine", Engine)
    monkeypatch.setattr(definitions, "build_hris_source", lambda _: None)
    assert definitions.drive_onboarding_case_step(str(uuid4()))["status"] == "authorized"
    assert used == ["financial"]
    del workflows
