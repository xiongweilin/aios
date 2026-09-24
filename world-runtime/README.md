# world-runtime

> Component of the [AIOS monorepo](../README.md) at `world-runtime/`; this directory is not an independent GitHub repository.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/badge/version-1.1.0-6f42c1)

Persistent semantic runtime for long-lived agency.

The Runtime owns durable epistemics, cognition, memory, governance, decisions, strategy,
responsibility, and generic execution. Domain Controllers retain rich domain semantics and
receive bounded semantic assignments.

World Runtime 1.1.0 hardens the stable governed-agency kernel with Runtime Protocol 4.0. Protocol 4.0 keeps the 1.0 agency model intact while separating authenticated representation from delegated transition authority, making terminal Work/Run state authoritative for fresh execution, and binding provider-result reads to the owning principal/actor.

The 1.0 boundary is intentionally narrow: Runtime stores and governs generic durable agency state. It does not become a Personal World, model router, universal business-process engine, or Domain Controller.

## Ownership

`semantic-language` owns cross-domain meaning and non-substitution rules.

`world-runtime` owns persistent agency/runtime primitives:

```text
ontology / identity
epistemics
cognition
memory
governance
decisions
strategy
responsibility
execution
```

Domain Controllers own domain obligations, domain lifecycles, authoritative read-back,
Outcome/Acceptance semantics, and completion.

Provider success therefore never means domain Outcome or GoalAchievement.

## Canonical contracts

Runtime-owned lifecycle, authority, execution, and recovery semantics are versioned in
`src/world_runtime/contracts/catalog.toml` and exposed by `GET /v1/contracts`.

The semantic rules behind that catalog are in `docs/contracts/runtime-contracts.md`.

The catalog deliberately does not absorb `semantic-language` or Domain Controller semantics.

## Replacement status

`docs/replacement-gap-matrix.md` is the deletion gate for the three frozen predecessor
repositories. A matching module name is not considered evidence of replacement.

The matrix classifies every deletion-relevant predecessor invariant as:

- `migrated`;
- `intentionally deleted` with a new owner/rationale; or
- `still missing`.

The predecessors are not deletable while any deletion-blocking row remains `still missing`.

## Migration

Legacy state migration must produce typed canonical Runtime state plus a reconciliation report.
Opaque source-event envelopes are provenance only and do not count as semantic migration.

The migration pipeline reports unresolved source records explicitly; a migration is deletion-ready
only when required records reconcile without unresolved or rejected entries.


## Predecessor retirement

The current stable Runtime baseline is frozen in `docs/releases/world-runtime-1.1-freeze.md`.
The physical-deletion conditions for `meta-controller`, `agent-kernel`, and
`world-state` are defined in `docs/migration/deletion-gate.md` and enforced by the
`historical-predecessor-deletion-proof` workflow plus `scripts/deletion_gate.py`.

Repository CI can prove code/contract replacement. Physical deletion additionally requires
operator evidence that any real predecessor state has been migrated, or that no live predecessor
state exists.


## Supported execution surface

The supported capability/effect invocation API is `WorldRuntime.invoke()` (and the
HTTP Runtime Protocol endpoint backed by it). `ExecutionService` is an internal
Work/Run/fencing service and does not cross the provider/reality boundary. There is
intentionally no second in-process reality-boundary invocation API.


### Closed capability request schema

Runtime Protocol 4.0 keeps the closed top-level `CapabilityRequest` schema
introduced by Protocol 1.5 and extends the same closed-schema rule to public
Runtime command models. The authenticated trust boundary introduced in 2.0 and
Domain reality boundary introduced in 2.1 remain mandatory. Unknown top-level
command fields are rejected before semantic mutation.
Provider-specific executable inputs must use declared fields such as
`parameters`, `constraints`, or `metadata`, so all provider-visible effect
semantics are covered by the durable effect identity.


## Durable backends

SQLite remains the supported local/single-file mode. PostgreSQL is the
organization-grade shared durable mode.

Both implement the same `SemanticLedger` contract:

```text
transaction
append/events
project_get/project_put
StateBundle export/import
```

Expected-version projection writes are database-level compare-and-swap
operations. Runtime-owned provider attempt reservation, Domain effect start, and
Run lease acquisition use those durable transitions so competing Runtime
processes cannot both obtain fresh dispatch/lease authority.

PostgreSQL durability is continuously verified with two independent Runtime
instances plus a physical `pg_dump` / `pg_restore` smoke test.


## Institutional continuity

World Runtime distinguishes historical existence from current qualification.

`semantic-language.Revision` remains the meaning primitive for revision. Runtime
owns its durable lineage: one lineage has one current head, historical objects
remain auditable, and a successor must explicitly supersede the current head
with basis references.

This applies without turning Runtime into a universal ontology:

- Decision history is immutable; superseded Decisions no longer qualify current
  transitions.
- Mandate/Authorization history remains auditable; a superseded Mandate no
  longer qualifies current authority.
- Goal reassessment keeps its existing lifecycle; successor admission is
  explicit after `revision-required`.
- qualified Experience can be invalidated, reopened, or superseded; only a
  qualified current head is applicable.
- ontology type versions are append-only and require explicit Revision to
  advance the current version.

These continuity semantics remain part of the stable kernel. Runtime Protocol 4.0
adds new public agency/query commands without changing the historical meaning
of the 0.6 lineage rules.


## World Runtime 1.0 agency model

The 1.0 kernel adds three durable layers above institutional continuity:

```text
Standing Responsibility
        |
        +-- ResponsibilityRelation(requires | contributes-to)
        |
        v
StrategicIssue -> externally evaluated StrategicOption*
        |
        v
PortfolioProposal --explicit Decision--> StrategicPortfolio
        |
        v
ResourceAllocation -> bounded Responsibility work

Qualified historical basis
        |
        +-- QualificationDependency
        |
material dependency change
        v
ReviewObligation -> RevalidationAssessment -> explicit resolution/requalification
```

Important non-substitution rules:

- a required child Responsibility being discharged does not discharge its parent;
- all children being complete does not make the parent satisfied;
- a StrategicOption evaluation does not authorize selection;
- Runtime does not compute a universal strategy score or choose the "best" option;
- a dependency change does not invalidate a historical subject automatically;
- a review assessment is not the owning subsystem's reauthorization/reopen action;
- non-`continue` reviews remain pending until explicit resolution is recorded.

## Runtime Protocol 4.0

Protocol 4.0 is intentionally breaking relative to 3.0 because it narrows
delegated mutation authority and fresh-execution legality.

- authentication establishes who is calling;
- delegation establishes representation of an effective principal;
- delegated Runtime mutations additionally require an explicit `operation`
  ceiling, optionally resource-bounded;
- effect action/resource authority remains separately governed by
  Mandate/Authorization semantics;
- terminal Work cannot start a fresh Run;
- terminal Work/Run cannot authorize fresh invocation, while exact committed
  replay and historical reconciliation remain legal;
- provider-result and reconciliation reads are principal/actor isolated;
- legacy provider results without read-binding metadata require direct root
  access;
- public mutation schemas remain closed and whole-agency StateBundle access
  remains direct-root-only.

The canonical manifest is `world-runtime-contracts-v10`; the reference
conformance suite is `world-runtime-conformance-v11`.

StateBundle remains backend-neutral and validates the 1.0 agency reference graph
before import. SQLite remains the local/reference backend; PostgreSQL remains
the shared organization-grade backend.
