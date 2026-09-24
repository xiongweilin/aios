from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import AuthorityClass, ReopenReason, UtcModel, utcnow
from .policy import (
    ApprovalRule,
    AuthorizedEffectTemplate,
    PolicyDisposition,
    PolicyEvaluation,
)


class Money(BaseModel):
    """Exact monetary value; binary floats are deliberately rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("amount", mode="before")
    @classmethod
    def reject_binary_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("monetary values must not use binary floats")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter uppercase code")
        return normalized

    @model_validator(mode="after")
    def validate_amount(self) -> Money:
        if self.amount < 0:
            raise ValueError("money amount cannot be negative")
        return self


class ProcurementFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    requested_quantity: Decimal | None = None
    estimated_amount: Money | None = None
    candidate_vendor: str | None = None
    vendor_ref: str | None = None
    vendor_tax_id: str | None = None
    cost_center: str | None = None
    needed_by: str | None = None
    quote_ref: str | None = None

    @field_validator("requested_quantity", mode="before")
    @classmethod
    def reject_float_quantity(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("quantities must not use binary floats")
        return value


class InvoiceLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str
    quantity: Decimal
    unit_price: Money
    line_total: Money | None = None

    @field_validator("quantity", mode="before")
    @classmethod
    def reject_float_line_quantity(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("quantities must not use binary floats")
        return value


class InvoiceFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_name: str | None = None
    vendor_ref: str | None = None
    vendor_tax_id: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    total: Money | None = None
    po_number: str | None = None
    line_items: tuple[InvoiceLine, ...] = ()
    document_revision: str | None = None
    document_digest: str | None = None


class ExpenseFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_ref: str | None = None
    merchant: str | None = None
    expense_date: str | None = None
    amount: Money | None = None
    category: str | None = None
    business_purpose: str | None = None
    receipt_ref: str | None = None


def has_material_financial_revision(
    case_kind: str,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> bool:
    """Return whether a document revision changes a governed dependency."""

    fields_by_case = {
        "procurement-request": (
            "description",
            "requested_quantity",
            "estimated_amount",
            "candidate_vendor",
            "vendor_ref",
            "vendor_tax_id",
            "cost_center",
            "needed_by",
            "quote_ref",
        ),
        "invoice-ap-preparation": (
            "vendor_name",
            "vendor_ref",
            "vendor_tax_id",
            "invoice_number",
            "invoice_date",
            "total",
            "po_number",
            "line_items",
            "document_revision",
            "document_digest",
        ),
        "expense-reimbursement": (
            "employee_ref",
            "merchant",
            "expense_date",
            "amount",
            "category",
            "business_purpose",
            "receipt_ref",
        ),
    }
    fields = fields_by_case.get(case_kind)
    if fields is None:
        raise ValueError(f"unsupported financial case kind: {case_kind!r}")
    return any(previous.get(field) != current.get(field) for field in fields)


class TransactionQualificationResult(StrEnum):
    QUALIFIED = "qualified"
    INCOMPLETE = "incomplete"
    MISMATCH = "mismatch"
    AMBIGUOUS = "ambiguous"
    DUPLICATE = "duplicate"


class VendorMasterRecord(BaseModel):
    vendor_ref: str
    legal_name: str
    tax_id: str | None = None
    company_ref: str | None = None


class VendorQualification(BaseModel):
    result: TransactionQualificationResult
    vendor: VendorMasterRecord | None = None
    blocking_reasons: tuple[str, ...] = ()


class InvoiceQualificationSummary(BaseModel):
    """Deterministic, non-authoritative inputs used before an AP draft."""

    vendor: VendorQualification
    duplicate: bool
    three_way_match: TransactionQualificationResult
    blocking_reasons: tuple[str, ...] = ()

    @property
    def result(self) -> TransactionQualificationResult:
        if self.vendor.result is not TransactionQualificationResult.QUALIFIED:
            return self.vendor.result
        if self.duplicate:
            return TransactionQualificationResult.DUPLICATE
        return self.three_way_match


class AdministrativeCaseEvidenceLink(UtcModel):
    """Durable case-to-source lineage for a transaction decision."""

    link_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    artifact_ref: UUID
    representation_ref: UUID | None = None
    declared_role: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=512)
    linked_at: datetime = Field(default_factory=utcnow)
    linked_by: str = Field(min_length=1, max_length=255)


class TransactionQualificationAssessment(UtcModel):
    assessment_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    authority_epoch: int = Field(ge=1)
    assessment_kind: str = Field(min_length=1, max_length=128)
    supersedes_assessment_id: UUID | None = None
    input_refs: tuple[str, ...] = Field(min_length=1)
    rule_ref: str = Field(min_length=1, max_length=512)
    result: TransactionQualificationResult
    blocking_reasons: tuple[str, ...] = Field(default=())
    created_at: datetime = Field(default_factory=utcnow)


class ProcurementPolicyDefinition(BaseModel):
    required_facts: tuple[str, ...] = (
        "description",
        "requested_quantity",
        "estimated_amount",
        "candidate_vendor",
        "cost_center",
    )
    normal_threshold: Money = Money(amount=Decimal("1000.00"), currency="USD")
    high_value_threshold: Money = Money(amount=Decimal("10000.00"), currency="USD")
    standard_approval: ApprovalRule = ApprovalRule(roles=("procurement_approver",))
    high_value_approval: ApprovalRule = ApprovalRule(
        roles=("procurement_approver", "finance_approver"),
        require_distinct_principals=True,
    )


class InvoiceAPPolicyDefinition(BaseModel):
    required_facts: tuple[str, ...] = (
        "vendor_name",
        "invoice_number",
        "invoice_date",
        "total",
        "po_number",
    )
    approval: ApprovalRule = ApprovalRule(roles=("finance_approver",))


class ExpensePolicyDefinition(BaseModel):
    required_facts: tuple[str, ...] = (
        "employee_ref",
        "merchant",
        "expense_date",
        "amount",
        "category",
        "receipt_ref",
    )
    receipt_required_above: Money = Money(amount=Decimal("25.00"), currency="USD")
    maximum_amount: Money = Money(amount=Decimal("1000.00"), currency="USD")
    allowed_categories: tuple[str, ...] = (
        "office",
        "office-supplies",
        "travel",
        "meals",
    )
    approval: ApprovalRule = ApprovalRule(roles=("finance_approver",))


class ProcurementPolicy:
    def __init__(self, policy_ref, *, definition: dict[str, Any] | None = None) -> None:
        self.policy_ref = policy_ref
        self.definition = ProcurementPolicyDefinition.model_validate(
            definition or ProcurementPolicyDefinition().model_dump(mode="json")
        )

    @staticmethod
    def default_definition() -> dict[str, Any]:
        return ProcurementPolicyDefinition().model_dump(mode="json")

    def evaluate(self, facts: ProcurementFacts) -> PolicyEvaluation:
        missing = tuple(
            name for name in self.definition.required_facts if getattr(facts, name) is None
        )
        if missing:
            return PolicyEvaluation(
                policy_ref=self.policy_ref,
                disposition=PolicyDisposition.NEED_MORE_FACTS,
                reason="required procurement facts are missing",
                missing_facts=missing,
            )
        assert facts.estimated_amount is not None
        if facts.estimated_amount.currency != self.definition.normal_threshold.currency:
            return PolicyEvaluation(
                policy_ref=self.policy_ref,
                disposition=PolicyDisposition.REOPEN_REQUIRED,
                reason="procurement currency is outside the configured policy currency",
                reopen_reason="unknown_risk_dimension",
            )
        approval = (
            self.definition.high_value_approval
            if facts.estimated_amount.amount > self.definition.high_value_threshold.amount
            else self.definition.standard_approval
        )
        return PolicyEvaluation(
            policy_ref=self.policy_ref,
            disposition=PolicyDisposition.HUMAN_DECISION_REQUIRED,
            reason="procurement requires configured financial approval",
            required_decision_roles=approval.roles,
            require_distinct_decision_principals=approval.require_distinct_principals,
            allowed_effects=(
                AuthorizedEffectTemplate(
                    target_system="erp",
                    operation="purchase_order.create_draft",
                    authority_class=AuthorityClass.FINANCIAL,
                ),
                AuthorizedEffectTemplate(
                    target_system="erp",
                    operation="purchase_order.confirm",
                    authority_class=AuthorityClass.FINANCIAL,
                ),
            ),
        )


class InvoiceAPPolicy:
    def __init__(self, policy_ref, *, definition: dict[str, Any] | None = None) -> None:
        self.policy_ref = policy_ref
        self.definition = InvoiceAPPolicyDefinition.model_validate(
            definition or InvoiceAPPolicyDefinition().model_dump(mode="json")
        )

    @staticmethod
    def default_definition() -> dict[str, Any]:
        return InvoiceAPPolicyDefinition().model_dump(mode="json")

    def evaluate(self, facts: InvoiceFacts) -> PolicyEvaluation:
        missing = tuple(
            name for name in self.definition.required_facts if getattr(facts, name) is None
        )
        if missing:
            return PolicyEvaluation(
                policy_ref=self.policy_ref,
                disposition=PolicyDisposition.NEED_MORE_FACTS,
                reason="required invoice facts are missing",
                missing_facts=missing,
            )
        return PolicyEvaluation(
            policy_ref=self.policy_ref,
            disposition=PolicyDisposition.HUMAN_DECISION_REQUIRED,
            reason="vendor bill preparation requires configured finance approval",
            required_decision_roles=self.definition.approval.roles,
            require_distinct_decision_principals=self.definition.approval.require_distinct_principals,
            allowed_effects=(
                AuthorizedEffectTemplate(
                    target_system="erp",
                    operation="vendor_bill.create_draft",
                    authority_class=AuthorityClass.FINANCIAL,
                ),
            ),
        )


class ExpensePolicy:
    def __init__(self, policy_ref, *, definition: dict[str, Any] | None = None) -> None:
        self.policy_ref = policy_ref
        self.definition = ExpensePolicyDefinition.model_validate(
            definition or ExpensePolicyDefinition().model_dump(mode="json")
        )

    @staticmethod
    def default_definition() -> dict[str, Any]:
        return ExpensePolicyDefinition().model_dump(mode="json")

    def evaluate(self, facts: ExpenseFacts) -> PolicyEvaluation:
        missing = tuple(
            name for name in self.definition.required_facts if getattr(facts, name) is None
        )
        if missing:
            return PolicyEvaluation(
                policy_ref=self.policy_ref,
                disposition=PolicyDisposition.NEED_MORE_FACTS,
                reason="required expense facts are missing",
                missing_facts=missing,
            )
        assert facts.amount is not None
        if facts.amount.currency != self.definition.maximum_amount.currency:
            return PolicyEvaluation(
                policy_ref=self.policy_ref,
                disposition=PolicyDisposition.REOPEN_REQUIRED,
                reason="expense currency is outside the configured policy currency",
                reopen_reason=ReopenReason.UNKNOWN_RISK_DIMENSION,
            )
        if facts.amount.amount > self.definition.maximum_amount.amount:
            return PolicyEvaluation(
                policy_ref=self.policy_ref,
                disposition=PolicyDisposition.REOPEN_REQUIRED,
                reason="expense exceeds the versioned maximum amount",
                reopen_reason=ReopenReason.SCOPE_EXPANSION,
            )
        if facts.category not in self.definition.allowed_categories:
            return PolicyEvaluation(
                policy_ref=self.policy_ref,
                disposition=PolicyDisposition.REOPEN_REQUIRED,
                reason="expense category is outside the configured allowlist",
                reopen_reason=ReopenReason.UNKNOWN_RISK_DIMENSION,
            )
        return PolicyEvaluation(
            policy_ref=self.policy_ref,
            disposition=PolicyDisposition.HUMAN_DECISION_REQUIRED,
            reason="expense record preparation requires configured finance approval",
            required_decision_roles=self.definition.approval.roles,
            allowed_effects=(
                AuthorizedEffectTemplate(
                    target_system="erp",
                    operation="expense_report.create",
                    authority_class=AuthorityClass.FINANCIAL,
                ),
            ),
        )


def qualify_vendor(
    *,
    candidate_name: str | None,
    candidate_tax_id: str | None,
    records: tuple[VendorMasterRecord, ...],
) -> VendorQualification:
    tax_id = (candidate_tax_id or "").strip()
    name = (candidate_name or "").strip().casefold()
    if tax_id:
        matches = tuple(record for record in records if record.tax_id == tax_id)
    else:
        matches = tuple(record for record in records if record.legal_name.casefold() == name)
    if len(matches) == 1:
        return VendorQualification(
            result=TransactionQualificationResult.QUALIFIED,
            vendor=matches[0],
        )
    if len(matches) == 0:
        return VendorQualification(
            result=TransactionQualificationResult.AMBIGUOUS,
            blocking_reasons=("authoritative vendor master returned no match",),
        )
    return VendorQualification(
        result=TransactionQualificationResult.AMBIGUOUS,
        blocking_reasons=("authoritative vendor master returned multiple matches",),
    )


def detect_duplicate_invoice(
    *,
    vendor_ref: str,
    invoice_number: str,
    existing: tuple[dict[str, str], ...],
) -> bool:
    return any(
        item.get("vendor_ref") == vendor_ref
        and item.get("invoice_number") == invoice_number
        for item in existing
    )


def detect_duplicate_document(
    *,
    content_digest: str | None,
    existing_artifacts: tuple[dict[str, str], ...],
) -> bool:
    """Return a duplicate signal without treating bytes as the full identity."""
    if not content_digest:
        return False
    return any(item.get("content_digest") == content_digest for item in existing_artifacts)


def match_three_way(
    *,
    invoice: InvoiceFacts,
    purchase_order: dict[str, Any],
    receipt: dict[str, Any],
) -> TransactionQualificationResult:
    if invoice.total is None:
        return TransactionQualificationResult.INCOMPLETE
    if invoice.total.currency != purchase_order.get("currency"):
        return TransactionQualificationResult.MISMATCH
    if invoice.po_number != purchase_order.get("po_number"):
        return TransactionQualificationResult.MISMATCH
    if invoice.vendor_ref and purchase_order.get("vendor_ref") and invoice.vendor_ref != purchase_order.get("vendor_ref"):
        return TransactionQualificationResult.MISMATCH
    if (
        invoice.vendor_tax_id
        and purchase_order.get("vendor_tax_id")
        and invoice.vendor_tax_id != purchase_order.get("vendor_tax_id")
    ):
        return TransactionQualificationResult.MISMATCH
    po_total = _decimal_value(purchase_order.get("total"))
    if po_total is None:
        return TransactionQualificationResult.INCOMPLETE
    if invoice.total.amount != po_total:
        return TransactionQualificationResult.MISMATCH
    if purchase_order.get("receipt_ref") != receipt.get("receipt_ref"):
        return TransactionQualificationResult.MISMATCH

    po_lines = purchase_order.get("line_items")
    receipt_lines = receipt.get("line_items")
    if po_lines is not None:
        if not isinstance(po_lines, (list, tuple)):
            return TransactionQualificationResult.MISMATCH
        if len(po_lines) != len(invoice.line_items):
            return TransactionQualificationResult.MISMATCH
        for invoice_line, po_line in zip(invoice.line_items, po_lines, strict=True):
            if not isinstance(po_line, dict):
                return TransactionQualificationResult.MISMATCH
            po_quantity = _decimal_value(po_line.get("quantity"))
            po_unit_price = _decimal_value(po_line.get("unit_price"))
            if po_quantity is None or po_unit_price is None:
                return TransactionQualificationResult.INCOMPLETE
            if invoice_line.quantity != po_quantity:
                return TransactionQualificationResult.MISMATCH
            if invoice_line.unit_price.currency != po_line.get("currency"):
                return TransactionQualificationResult.MISMATCH
            if invoice_line.unit_price.amount != po_unit_price:
                return TransactionQualificationResult.MISMATCH
    if receipt_lines is not None:
        if not isinstance(receipt_lines, (list, tuple)):
            return TransactionQualificationResult.MISMATCH
        if len(receipt_lines) != len(invoice.line_items):
            return TransactionQualificationResult.MISMATCH
        for invoice_line, receipt_line in zip(invoice.line_items, receipt_lines, strict=True):
            if not isinstance(receipt_line, dict):
                return TransactionQualificationResult.MISMATCH
            receipt_quantity = _decimal_value(receipt_line.get("quantity"))
            if receipt_quantity is None:
                return TransactionQualificationResult.INCOMPLETE
            if receipt_quantity < invoice_line.quantity:
                return TransactionQualificationResult.MISMATCH
    return TransactionQualificationResult.QUALIFIED


def _decimal_value(value: Any) -> Decimal | None:
    if value is None or isinstance(value, float):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def qualify_invoice_transaction(
    *,
    case_id: UUID,
    authority_epoch: int,
    invoice: InvoiceFacts,
    vendor_records: tuple[VendorMasterRecord, ...],
    purchase_order: dict[str, Any],
    receipt: dict[str, Any],
    existing_invoices: tuple[dict[str, str], ...],
    input_refs: tuple[str, ...],
    rule_ref: str,
    existing_artifacts: tuple[dict[str, str], ...] = (),
) -> tuple[InvoiceQualificationSummary, tuple[TransactionQualificationAssessment, ...]]:
    """Run vendor, duplicate, and three-way checks without side effects."""
    vendor = qualify_vendor(
        candidate_name=invoice.vendor_name,
        candidate_tax_id=invoice.vendor_tax_id,
        records=vendor_records,
    )
    vendor_assessment = TransactionQualificationAssessment(
        case_id=case_id,
        authority_epoch=authority_epoch,
        assessment_kind="vendor_qualification",
        input_refs=input_refs,
        rule_ref=rule_ref,
        result=vendor.result,
        blocking_reasons=vendor.blocking_reasons,
    )
    if vendor.vendor is None:
        summary = InvoiceQualificationSummary(
            vendor=vendor,
            duplicate=False,
            three_way_match=TransactionQualificationResult.INCOMPLETE,
            blocking_reasons=vendor.blocking_reasons,
        )
        return summary, (vendor_assessment,)

    duplicate = detect_duplicate_invoice(
        vendor_ref=vendor.vendor.vendor_ref,
        invoice_number=invoice.invoice_number or "",
        existing=existing_invoices,
    ) or detect_duplicate_document(
        content_digest=invoice.document_digest,
        existing_artifacts=existing_artifacts,
    )
    duplicate_result = (
        TransactionQualificationResult.DUPLICATE
        if duplicate
        else TransactionQualificationResult.QUALIFIED
    )
    duplicate_assessment = TransactionQualificationAssessment(
        case_id=case_id,
        authority_epoch=authority_epoch,
        assessment_kind="duplicate_invoice_check",
        input_refs=input_refs,
        rule_ref=rule_ref,
        result=duplicate_result,
        blocking_reasons=("authoritative ERP invoice identity already exists",)
        if duplicate
        else (),
    )
    three_way = match_three_way(
        invoice=invoice,
        purchase_order=purchase_order,
        receipt=receipt,
    )
    three_way_assessment = TransactionQualificationAssessment(
        case_id=case_id,
        authority_epoch=authority_epoch,
        assessment_kind="three_way_match",
        input_refs=input_refs,
        rule_ref=rule_ref,
        result=three_way,
        blocking_reasons=("invoice, PO, and receipt do not match",)
        if three_way is not TransactionQualificationResult.QUALIFIED
        else (),
    )
    summary = InvoiceQualificationSummary(
        vendor=vendor,
        duplicate=duplicate,
        three_way_match=three_way,
        blocking_reasons=tuple(
            reason
            for assessment in (duplicate_assessment, three_way_assessment)
            for reason in assessment.blocking_reasons
        ),
    )
    return summary, (vendor_assessment, duplicate_assessment, three_way_assessment)


__all__ = [
    "AdministrativeCaseEvidenceLink",
    "ExpenseFacts",
    "ExpensePolicy",
    "ExpensePolicyDefinition",
    "InvoiceAPPolicy",
    "InvoiceAPPolicyDefinition",
    "InvoiceFacts",
    "InvoiceLine",
    "InvoiceQualificationSummary",
    "Money",
    "ProcurementFacts",
    "ProcurementPolicy",
    "ProcurementPolicyDefinition",
    "TransactionQualificationAssessment",
    "TransactionQualificationResult",
    "VendorMasterRecord",
    "VendorQualification",
    "detect_duplicate_invoice",
    "detect_duplicate_document",
    "has_material_financial_revision",
    "match_three_way",
    "qualify_invoice_transaction",
    "qualify_vendor",
]
