# Kernel verification evidence boundary

Administrative Orchestrator delegates bounded physical execution for explicitly cut-over capabilities to Agent Kernel, but it does not delegate business obligation authority.

## Ownership

Agent Kernel owns the execution/reality side of the boundary:

- materialized Kernel Work and Run identity;
- bounded provider execution;
- independent objective verification;
- canonical `domain-effect-verification-evidence-view-v1` read evidence;
- the actual `observed_postcondition` and verifier provenance bound to that evidence.

Administrative Orchestrator owns the business side of the boundary:

- the AdministrativeCase and authority epoch;
- governance basis and approval satisfaction;
- AdministrativeObligation and its frozen expected postcondition;
- semantic comparison of observed reality against that obligation;
- ConfirmedOutcome creation;
- completion, reconciliation, or reopen decisions.

The Kernel evidence view is explicitly non-authoritative. Consuming it does not transfer Administrative obligation authority to Kernel.

## Completion is not transitive

These facts are deliberately distinct:

```text
Kernel execution status == COMPLETED
    != Kernel verification evidence as an Administrative observation
    != Administrative semantic verification == VERIFIED
    != Administrative ConfirmedOutcome
    != AdministrativeCase == COMPLETED
```

A completed Kernel execution receipt therefore cannot discharge an Administrative obligation by itself.

The cutover adapter reads the exact `evidence_ref` returned by Kernel, verifies that the evidence remains bound to the persisted Work/Run/Action lineage and the frozen expected postcondition, and only then exposes `observed_postcondition` as a `RealityObservation` to the Administrative verifier.

Administrative Orchestrator never reconstructs observed reality from its own expected postcondition.

## Fail-closed behavior

For Kernel-owned HRIS and IAM capabilities, the legacy Administrative provider is not a fallback execution or read-back path.

The observation remains unknown when any of the following is true:

- the Kernel execution has not reached an evidence-bearing terminal verification state;
- `evidence_ref` is absent or unknown;
- the evidence endpoint is unavailable or returns an incompatible view;
- the evidence Work, Run, or Action identity rebounds from the persisted projection;
- the evidence frozen expected postcondition rebounds from the persisted domain intent;
- the evidence objective result conflicts with the execution receipt.

These failures may cause reconciliation, but they do not authorize local execution or local read-back.

## Reality mismatch

A valid Kernel evidence view may be structurally and cryptographically well bound while still reporting reality that does not satisfy the Administrative obligation.

Example:

```text
Administrative expected:
  department_ref = department:engineering

Kernel independently observed:
  department_ref = department:finance
```

The evidence is still consumed as the actual observation. Administrative semantic verification returns a mismatch, no HRIS `ConfirmedOutcome` is minted, and the case enters `REOPEN_REQUIRED` under the current onboarding state machine. HRIS/IAM legacy execute and observe calls remain forbidden.

This is the intended boundary: Kernel owns reality observation; Administrative Orchestrator owns business interpretation and obligation discharge.

## Durability

The same boundary applies across DBOS/PostgreSQL restart. Kernel-owned effect-to-obligation/governance links and execution lineage are reloaded from durable Administrative storage; completed Kernel receipts must still resolve through canonical verification evidence before Administrative outcomes are confirmed. Restart does not re-enable the legacy provider path.
