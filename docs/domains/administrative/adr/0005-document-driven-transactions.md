# ADR 0005 — Document-Driven Organizational Transactions

Status: **accepted for the recorded isolated-staging scope; Admin PR #80 and
Kernel PR #99 merged. This ADR records the M8 decision boundary; M9 is governed
separately by ADR 0006 and its acceptance record.**

## Decision

M8 extends the existing Administrative governed-effect chain with bounded,
document-driven transaction preparation. Raw provider artifacts remain
immutable source evidence. Any parser or OCR output is a separate immutable
`DocumentRepresentation` with its own extractor identity, version, digest,
storage reference, and page metadata. An `EvidenceSpan` may point at the
representation that produced it; historical spans may remain null.

Human confirmation admits a candidate request, not the truth of extracted
facts. Transaction facts remain claims until they are qualified by an
authoritative source or an explicitly recorded, current qualification
assessment. Every qualification assessment records its input references,
rule identity, result, blockers, case, and authority epoch.

The first transaction case kinds are exactly:

```text
procurement-request
invoice-ap-preparation
expense-reimbursement
```

They can create only bounded ERP preparation effects:

```text
purchase_order.create_draft
purchase_order.confirm
vendor_bill.create_draft
expense_report.create
```

The Kernel owns physical execution and independent readback for these
capabilities. Bank transfers, payment execution, settlement, generic RAG,
automatic approval, and a second workflow/controller authority are out of
scope.

## Consequences

- A parser failure is classified into a bounded, safe error taxonomy and is
  never converted into an empty successful representation.
- Representation identity is content-addressed by source artifact, extractor,
  extractor version, and representation digest.
- One immutable obligation set is allowed for each `(case_id,
  authority_epoch)`.
- Completion binds each expected business outcome to the effect that produced
  it; an outcome from another effect cannot satisfy the obligation.
- ERP connectors use durable request/subject markers, reconcile ambiguous
  results, and fail closed when an exact external identity is unavailable.
- M5–M7 migrations, acceptance records, and volumes remain historical
  evidence and are not rewritten.

## Rejected alternatives

- Treating raw PDFs or model output as authoritative facts.
- Reusing a parser's text directly without a durable representation lineage.
- Calling Odoo or a bank directly from Administrative code outside the Kernel
  capability boundary.
- Adding a generic document-understanding or RAG subsystem to the milestone.
- Making `expense-reimbursement` an actual payment workflow.
