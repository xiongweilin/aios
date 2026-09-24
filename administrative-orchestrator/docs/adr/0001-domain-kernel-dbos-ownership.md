# ADR 0001 — Administrative, Agent Kernel, and DBOS ownership

Status: accepted (runtime ownership superseded by ADR 0007)
Date: 2026-09-08

## Context

`administrative-orchestrator` is the reference system for governed digital administrative automation.  It must remain a domain system rather than becoming a second generic agent runtime.  `agent-kernel` already owns canonical generic semantics for persistent responsibility, Work/Run execution, runtime authorization, RealityBoundary, provider execution, and recovery.  DBOS provides durable orchestration.

The first implementation slice historically kept a local physical effect executor so the administrative semantics could be proven independently.  As the system matures, that local runtime must converge on the canonical kernel without erasing the administrative distinctions that the domain owns.

## Decision

### Administrative owns

- AdministrativeRequest and AdministrativeCase business state;
- request claims, authoritative facts, provenance, and domain evidence;
- administrative policy versions and policy evaluation;
- organizational identity projection, role/delegation qualification, decisions and approval satisfaction;
- dependency-scoped GovernanceBasis and current governance revalidation;
- business obligations and their expected postconditions;
- AdministrativeExecutionGrant, once the existing historical ExecutionAuthorization terminology is migrated;
- AdministrativeEffectIntent, once the historical EffectRecord execution truth is migrated;
- domain semantic verification and administrative completion assessment;
- domain audit, review, exception, and reassessment surfaces.

### Agent Kernel owns

- StandingResponsibility and persistent responsibility semantics;
- ResponsibilityAssessment and WorkProposal semantics;
- priority/admission/reservation/commitment and Work materialization;
- Work / Run / Step / Attempt;
- generic runtime authorization and authorization use;
- capability routing and InvocationPermit;
- the unique physical RealityBoundary;
- provider invocation, execution attempt truth, ambiguous-result recovery, retry permission and reconciliation;
- generic Outcome/revision contracts.

Downstream administrative code may hold references/projections of kernel objects but must not mint, reconstruct, or redefine kernel authority.

### DBOS owns

- durable workflow orchestration;
- waits, wake-ups, resume and crash recovery of the administrative workflow;
- orchestration scheduling around durable domain state.

DBOS does not own administrative policy, business authority, business completion, or the physical effect boundary.

## Deterministic administrative work

A routine closed administrative workflow does **not** invent a CognitiveClosure merely to use Agent Kernel.  It may bypass cognitive control when facts, policy and business obligations are already closed.

It does **not** bypass persistent responsibility or Work admission.

Target handoff:

```text
AdministrativeCase
  -> Administrative policy / GovernanceBasis
  -> AdministrativeObligationSet
  -> AdministrativeExecutionGrant
  -> StandingResponsibility / ResponsibilityAssessment
  -> WorkProposal
  -> kernel priority/admission/reservation/commitment
  -> Work / Run
  -> kernel runtime authorization
  -> RealityBoundary
  -> provider
  -> runtime execution evidence
  -> fresh authoritative observation
  -> administrative semantic verification
  -> AdministrativeConfirmedOutcome projection
  -> CompletionAssessment
```

Negative invariants:

```text
AdministrativeObligation != AdministrativeEffectIntent
AdministrativeExecutionGrant != kernel runtime authorization
AdministrativeEffectIntent != provider invocation
provider success != administrative semantic verification
workflow termination != administrative completion
AdministrativeCase.COMPLETED != universal responsibility discharge
```

## Current migration rule

The current `ExecutionAuthorization` and `EffectRecord` tables are historical compatibility surfaces.  New semantics are introduced additively.  Historical rows are never reinterpreted in place.

The cutover sequence is:

1. close Administrative correctness gaps first: resource authorization, GovernanceBasis, ObligationSet, observation epistemics, fact provenance and policy lifecycle;
2. establish a single `integrations/kernel/` compatibility/adapter boundary;
3. run a shadow bridge that proves deterministic identity and lineage without executing physical effects;
4. cut over one capability at a time to kernel execution;
5. remove the final direct administrative provider execution only after crash/replay/reconciliation tests prove equivalent or stronger behavior.

## Consequences

- deterministic workflows remain simple and do not fabricate cognition;
- the kernel remains the only long-term owner of generic execution authority and physical effects;
- Administrative retains the business meaning of why an action is required and what counts as complete;
- DBOS remains replaceable orchestration infrastructure rather than a business state owner;
- migration can proceed without resetting the database or rewriting historical records.
