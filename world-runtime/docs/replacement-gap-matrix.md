# Replacement gap matrix

This matrix is the deletion gate for the frozen predecessor repositories:

- `agent-kernel`
- `meta-controller`
- `world-state`

A subsystem name existing in `world-runtime` is not evidence of replacement. Each stable
predecessor capability is classified as exactly one of:

- **migrated** — the replacement behavior and invariant are owned and tested in `world-runtime`;
- **intentionally deleted** — the predecessor behavior is deliberately not Runtime-owned, with
  the new owner or deletion rationale stated;
- **still missing** — deletion of the predecessor would remove a required invariant or recovery
  behavior.

## agent-kernel

| Stable capability / invariant | Status | World Runtime disposition |
| --- | --- | --- |
| Persistent responsibility identity and lifecycle | migrated | `ResponsibilityService`; satisfied/failed require basis, discharge requires Decision |
| Generic Work admission under responsibility | migrated | `ExecutionService.admit_work` |
| Generic Run lifecycle | migrated | `ExecutionService.start_run` / status projection |
| Provider registry and deterministic provider selection | migrated | `ProviderRegistry` |
| Capability-level authorization requirements | migrated | `CapabilityEffectRule` + `GovernanceService` |
| Authorization issuance and durable use history | migrated | `GovernanceService` |
| Projection compare-and-swap | migrated | `SQLiteLedger.project_put(expected_version=...)` |
| Durable pre-dispatch provider attempt | migrated | `execution.provider-attempt` is persisted before provider invoke |
| Idempotent completed-result replay | migrated | `execution.provider-idempotency` |
| Ambiguous result blocks blind redispatch | migrated | a started attempt without a committed result returns unknown unless reconciled |
| Exact historical provider reconciliation | migrated | reconciliation uses the provider id recorded on the durable attempt |
| Canonical Runtime contract catalog | migrated | `world-runtime/contracts` catalog and `/v1/contracts` surface |
| Provider success separated from domain Outcome | migrated | Runtime result is execution evidence only |
| Domain-specific verified outcome authority | intentionally deleted | Domain Controller owns authoritative read-back, Outcome, Acceptance, and completion |
| Domain-specific responsibility proposal/admission profiles | intentionally deleted | Domain Controller delegates a bounded responsibility directly; Runtime does not own business admission policy |
| Generic lease ownership and generation fencing | migrated | Run lease acquire/heartbeat/release is CAS-protected; dispatch validates owner, generation and expiry before crossing reality |
| Atomic multi-record semantic graph commit | migrated | SQLite semantic transactions atomically commit each V1 canonical transition graph; provider attempt and result graphs include all associated projections/events without reintroducing legacy Step/Attempt/Action models |
| Recovery disposition/application state machine | migrated | durable disposition, application and resolution records govern exact historical reconciliation without granting fresh invoke authority |
| Reconciliation repeatability authority/contract drift check | migrated | dispatch persists a versioned provider/protocol repeatability contract digest; recovery proceeds only when the current contract exactly matches and is repeat-safe |
| Portable full-state/bundle export with graph validation | migrated | state bundle v1 exports all events/projections with manifest digest; import validates integrity, canonical reference graph and empty-destination semantics before one atomic restore |
| Public conformance vectors for Runtime contracts | migrated | language-neutral vectors are published at /v1/contracts/vectors and a reference harness proves lifecycle, authority, ambiguity/reconciliation and restart/state-portability semantics |

## meta-controller

| Stable capability / invariant | Status | World Runtime disposition |
| --- | --- | --- |
| Epistemic assessment | migrated | `world_runtime.cognition.epistemic` |
| Candidate frontier and qualification | migrated | `world_runtime.cognition.candidates` |
| Search budget/policy and closure readiness | migrated | `world_runtime.cognition.planning` |
| Representation revision | migrated | `world_runtime.cognition.representation` |
| Working self-model and calibration | migrated | `world_runtime.cognition.self_model` |
| Experience consolidation/use policy | migrated | cognition experience/consolidation plus `MemoryService` |
| Policy journal and replay evaluation | migrated | `cognition.journal` / `cognition.replay` |
| Policy learning/promotion | migrated | `cognition.policy_learning` |
| Meta-controller → Agent Kernel compiler seam | intentionally deleted | cognition and legal Runtime state now share one owner; no compiler seam is retained |
| Separate meta-controller service/process identity | intentionally deleted | cognition is a Runtime subsystem, not an independently authoritative service |

## world-state

| Stable capability / invariant | Status | World Runtime disposition |
| --- | --- | --- |
| Stable Claim identity | migrated | `semantic-language.Claim` + Runtime claim projection |
| Immutable Evidence identity and provenance | migrated | duplicate evidence is rejected; evidence carries source, validity and derivation refs |
| Unknown as first-class unresolved gap | migrated | open/resolved unknown lifecycle is append-only in ledger events |
| Conflict as first-class epistemic object | migrated | conflict identity/members are persisted |
| Contextual evidence assessment | migrated | evidence assessment is append-only and belief is a projection |
| Recorded-time and valid-time on ledger events | migrated | `LedgerEvent.recorded_at` / `valid_at` |
| Full ClaimRevision model | migrated | stable Claim identity points to append-only ClaimRevision records with scope, requirements, falsifiers, valid time, previous revision and cause/actor lineage |
| Typed Conflict resolution history | migrated | conflicts have open/resolved projection plus append-only resolution history with actor and basis refs |
| Bitemporal query surface | migrated | claim_revision_as_of(valid_at, recorded_at) separates valid-time from ledger recorded-time and returns only revisions knowable at that record time |
| Falsification predicate DSL | migrated | Runtime supports deterministic eq/ne/gt/gte/lt/lte/exists/contains predicates for declared support requirements and falsification conditions |
| Confidence calibration semantics | migrated | belief verdict is requirement/coverage/falsification based; numeric confidence is optional and rejected unless it carries an explicit calibration_ref |

## Deletion gate

The predecessor repositories may be deleted only when all of the following are true:

1. Every row above is `migrated` or `intentionally deleted`; no deletion-blocking
   `still missing` row remains.
2. `control-plane` and at least two materially different external Domain Controllers run against
   the same Runtime contract surface without importing Runtime internals.
3. Runtime contract conformance tests cover lifecycle, authority, execution ambiguity,
   reconciliation, and restart behavior.
4. Legacy state migration produces typed canonical objects and a reconciliation report with zero
   unresolved required records for an accepted predecessor snapshot.
5. Frozen predecessor snapshots remain available until the migration report and replacement matrix
   are accepted; no new features are developed in them.

This matrix is intentionally narrower than a feature inventory. It tracks semantic ownership and
failure-path invariants that can block deletion.
