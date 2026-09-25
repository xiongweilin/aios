# World Runtime contracts

This document defines Runtime-owned lifecycle, authority, persistence, and execution invariants.
Cross-domain meaning remains owned by `semantic-language`. Domain completion and real-world
outcome qualification remain owned by Domain Controllers.

The canonical version manifest is `src/world_runtime/contracts/catalog.toml`.

## Ownership rules

The Runtime may persist and govern a `Responsibility`, admit generic `Work`, record a
`Decision`, register a `Mandate`, issue and consume an `Authorization`, invoke a
capability, persist an execution attempt, and reconcile an ambiguous provider result.

The Runtime does not define employee onboarding, invoice matching, canary stages, release
promotion, customer conversion, or any other domain lifecycle.

The Runtime also does not promote provider success into a domain `Outcome`.
A Domain Controller must independently qualify reality and decide whether its semantic
postcondition has been satisfied.

## Responsibility lifecycle

A standing responsibility has stable identity, principal, subject, domain, scope, semantic
references, and lifecycle state.

`satisfied` and `failed` assessments require explicit basis references.
Discharge requires both a prior `satisfied` assessment and a durable Decision explicitly applicable to that Responsibility transition. Discharge is
therefore a semantic lifecycle transition, not a synonym for "workflow returned success".

## Domain Controller protocol

A `DomainAssignment` is a bounded delegation from one standing responsibility to one named
Domain Controller. It carries cross-domain references, resource budget, evidence requirements,
and review conditions. It is not Work and it is not an Authorization.

A `DomainReport` preserves the Controller-to-Runtime lineage for acceptance, progress, evidence,
outcome candidates, escalation, and completion proposals. The Runtime records these reports but
does not reinterpret domain-owned Outcome or Acceptance semantics.

An `outcome-candidate` report requires both evidence references and domain-owned outcome
references. A completion proposal does not discharge the standing responsibility; discharge still
requires an explicit Runtime responsibility assessment and Decision.

## Work and Run

Work may only be admitted under a current `active` standing responsibility. Work and Run are runtime
execution records, not business obligations or domain outcomes.

A Domain Controller may map one domain obligation to one or more Runtime work units, but the
mapping belongs to that Domain Controller.

## Authority

A Mandate establishes delegated scope. An empty `authority_ceiling` delegates no executable effect authority; unrestricted executable authority must be explicit, for example `{"action":"*","resource":"*"}`. An Authorization binds a principal, action, resource,
mandate, decision, and conditions. Authorization use is durable history.

Authorization is necessary where the capability contract requires it, but it never proves that
an effect occurred.

## Capability invocation

A capability contract may require an explicit resource boundary, subject version references,
and an Authorization.

Provider selection is an execution concern. Provider registration never becomes durable semantic
truth merely because a provider process is currently available.

## Durable attempts and reconciliation

For an idempotent effect, the Runtime records a durable provider attempt before crossing the
provider boundary.

If the process loses the acknowledgement after that point, the existence of the durable attempt
blocks redispatch. The only legal next step is exact-target reconciliation against the provider
that owned the historical attempt.

A reconciled provider result is still only an execution fact. Domain outcome verification remains
outside the Runtime.

## Epistemics and cognition

Epistemic state, cognitive search/closure/revision, experience memory, and strategy are Runtime
primitives. Their public semantic inputs should use `semantic-language` identities and
distinctions rather than introducing a second universal ontology.

## Strategy reassessment

A `StrategyAssessment` records whether an admitted Goal should continue, be revised, or stop
after new evidence and domain outcomes arrive. It requires explicit basis references and preserves
evidence/outcome lineage. It does not manufacture a new Goal or silently revise the Mandate.

## Contract evolution

A contract version changes only when externally observable Runtime semantics change. Internal
refactors do not mint new contract versions.

Historical predecessor contract identifiers may be cited by migration tooling, but they are not
aliases and do not remain active Runtime APIs.


## Durable effect identity

Fresh effectful invocation requires an explicit durable `idempotency_key`. Before provider dispatch, the Runtime binds that identity to a canonical semantic request fingerprint. The fingerprint covers capability, Work/Run binding, principal/resource coordinates, instruction and input artifacts, parameters and constraints, metadata, step identity, subject versions, and the effective effect class.

Authorization IDs, lease generations, provider preferences, timeout values, and transport request IDs are execution credentials rather than semantic effect identity, so they are intentionally excluded from the fingerprint. Reusing one durable identity for a different semantic request is an identity rebound and fails closed. Replay and ambiguous recovery are legal only for a request matching the historical fingerprint.

Protocol 1.4 changes the externally accepted input set: every fresh effectful invocation requires this durable non-rebindable identity. Read-only invocation may remain anonymous unless it opts into idempotent replay.


## Canonical provider boundary

`WorldRuntime.invoke()` is the sole Runtime path allowed to cross a capability
provider/reality boundary. `ExecutionService` owns Work/Run state, fencing, durable
effect-identity qualification, and invocation-legality preparation only. It does not
dispatch providers and exposes no `invoke()` method.

This is a Python-package surface cleanup only. Runtime Protocol 1.4 and
`capability-invocation-v3` remain unchanged because their HTTP semantics do not change.


## Closed capability request schema

Runtime Protocol 1.5 / `capability-invocation-v4` makes the top-level
`CapabilityRequest` schema closed. Undeclared fields are rejected before
invocation and never reach a provider.

Provider-specific executable semantics must be represented in declared request
fields. Use `parameters` for provider operation inputs, `constraints` for
execution constraints, and `metadata` only when the metadata is intentionally
part of semantic effect identity. These fields are already covered by the
durable effect fingerprint.

This change intentionally narrows the externally accepted HTTP input set. It is
therefore versioned as Runtime Protocol 1.5 rather than treated as an
implementation-only fix.


## Root of trust and Reality Boundary

Runtime Protocol 2.0 binds authority-bearing writes to authenticated principals,
supports bounded delegation, and attests Decision, Mandate, and Authorization
issuance. Historical unattested authority remains historical and cannot be
retroactively adopted as executable authenticated authority.

Runtime Protocol 2.1 adds the Domain reality boundary. Domain-owned provider
implementations remain outside Runtime, but a reality-changing dispatch requires
a durable semantic identity, current authority, and a single-use Runtime start
fence. A started or ambiguous effect may be reconciled; it may not be blindly
redispatched.

## Organization-grade durability

`organization-durability-v1` does not change Runtime Protocol 2.1 wire
semantics. It defines the storage/concurrency guarantees required for the same
semantic state machine to run across multiple Runtime processes.

A conforming durable ledger must provide:

- atomic semantic transactions spanning event and projection writes;
- database-level expected-version compare-and-swap for projections;
- exactly one fresh provider-attempt reservation winner for one durable effect
  identity;
- database-fenced Run lease acquisition so different workers cannot own the
  same active lease generation;
- database-fenced Domain-effect start so only one Runtime node receives fresh
  provider dispatch authority;
- portable StateBundle export/import independent of the concrete ledger backend.

SQLite is the local file-backed reference backend. PostgreSQL is the shared
organization-grade backend. PostgreSQL physical durability is additionally
verified by `postgres-backup-restore-v1`: a native `pg_dump` followed by
`pg_restore` must preserve Runtime semantic state and references.

These guarantees do not move HA orchestration, database replication policy, or
Domain-specific lifecycle semantics into World Runtime. They define correctness
of Runtime state under a shared durable store.


## Institutional continuity

`institutional-lineage-v1` persists the operational consequence of
`semantic-language.Revision` without redefining Revision itself. Runtime keeps
immutable historical objects and separately computes which object is currently
qualified.

A lineage is append-only and single-headed:

- a Revision must name both `supersedes_ref` and successor `target_ref`;
- kind and namespace are preserved across one lineage;
- explicit reason and basis references are required;
- only the current lineage head may be superseded;
- replay of the exact same Revision is idempotent;
- a competing branch from a historical object fails closed.

Current qualification is owner-specific:

- a historical Decision remains readable but cannot qualify a new current
  transition after it has been superseded or explicitly revoked; Decision
  content remains immutable while current qualification is recorded separately;
- Mandate revocation is durable history; Mandate supersession preserves
  historical Authorization and use records, but current authority cannot continue
  through the superseded Mandate;
- Authorization revocation preserves issuance and prior-use history while
  preventing every later use;
- a current StrategyAssessment may only be replaced by an explicit single-head
  supersession naming the prior assessment, reason, and basis; silent overwrite
  is invalid;
- an admitted Goal must first reach `revision-required`, then a successor Goal
  requires an explicit admission Decision identifying `supersedes_goal_id`;
- an Experience is applicable only when it is both `qualified` and the current
  lineage head; invalidated, reopened, and superseded Experience remains
  historical memory rather than silently disappearing;
- ontology definitions preserve every version. A new version cannot overwrite
  the current definition and must advance through an explicit Revision.

Ontology type definitions and Experience are Runtime-owned extension kinds and
therefore use non-universal SemanticRef namespaces. They do not become new
universal semantic-language primitives.

World Runtime 0.6 keeps Runtime Protocol 2.1 because these operations are
internal Runtime contracts. Exposing a future Controller-facing lineage command
would require an explicit protocol evolution rather than silently expanding
Protocol 2.1.


## World Runtime 1.0 governed-agency contracts

World Runtime 1.0 / Runtime Protocol 3.0 extends the durable Runtime without
turning it into a universal workflow engine.

### Cross-domain Responsibility topology

`responsibility-graph-v1` admits only the Runtime-owned generic relation
kinds `requires` and `contributes-to`.

A `requires` edge is a qualification dependency. The source Responsibility
cannot be assessed `satisfied` or discharged while the required target remains
unresolved. The target becoming discharged does not satisfy or discharge the
source.

Hard dependency cycles are rejected. Relation creation and retirement are
Decision-qualified, durable, and historical. Cross-principal relations fail
closed.

### Strategic agency

`strategic-agency-v1` persists strategic issues, externally evaluated options,
portfolio proposals, active portfolios, structured resource budgets, and
resource allocations.

Runtime does not rank options with a universal utility function. Option
evaluation is opaque structured evidence/context from the cognitive layer. A
portfolio becomes active only through an applicable Decision.

Resource budget lines bind amount and unit. Allocation is Decision-qualified,
principal-consistent, goal-scoped where applicable, and durably CAS-fenced so
multiple Runtime processes cannot collectively exceed one portfolio ceiling.

### Continuous qualification

`continuous-qualification-v1` records the dependencies that make a historical
subject currently usable.

A dependency version change creates a targeted `ReviewObligation`. It does
not silently invalidate the subject. A `RevalidationAssessment` records the
judgment reached by review.

`continue` resolves the review directly. Non-continue dispositions remain
`assessed` until the subsystem that owns the required action records an
explicit resolution reference. Dependency lineage may advance only after that
resolution.

This contract deliberately distinguishes:

```text
dependency changed != conclusion invalid
reviewed != reauthorized
reviewed != reopened
old != stale
newer != qualified
```

### Portable agency state

`StateBundle` remains backend-neutral. Before import, graph validation covers
the 1.0 projections in addition to the earlier Runtime graph:

- Responsibility relation endpoints;
- strategic issue -> Mandate;
- option/proposal/portfolio linkage;
- portfolio -> Decision;
- resource allocation -> portfolio/Responsibility/Decision;
- qualification review -> dependency;
- revalidation assessment -> review;
- superseded qualification dependency lineage.

A cryptographically self-consistent bundle with a dangling semantic reference
is still invalid.

### Protocol 3.0 trust/read boundary

Protocol 3.0 is breaking relative to 2.1.

Public Runtime mutation commands use closed Pydantic schemas. Unknown top-level
fields are rejected before semantic mutation.

Durable state reads require authentication. DomainAssignment and DomainReport
reads are visible to the owning principal or assigned Controller according to
their role in the Domain protocol.

Whole-agency StateBundle export/import is stronger than an ordinary domain
operation and therefore requires direct authentication as the
deployment-configured `root_principal`. Delegated Controller authority and
other directly authenticated principals cannot export or replace the whole
agency state. When no root principal is configured, the HTTP whole-agency state
surface is disabled.

The root principal is bootstrap trust configuration rather than imported
semantic state. A StateBundle cannot nominate or replace its own import
authority.

## 1.x compatibility policy

The 1.0.0 release freezes the meaning of Runtime Protocol 3.0 and every contract
identifier in `world-runtime-contracts-v9`.

Patch releases in the 1.0.x line may fix implementation defects, improve tests,
or harden an invariant without silently changing accepted wire input or the
meaning of an existing contract.

An externally observable additive Runtime surface requires an explicit protocol
or contract-catalog evolution. A change that narrows accepted input, changes
authentication/authority requirements, changes durable identity, or changes the
meaning of an existing transition is breaking and must not be shipped under the
same protocol identifier.

StateBundle format changes that are not backward import-compatible require a new
bundle version. Historical bundle/contract identifiers are never aliases for a
new meaning.


## Runtime Protocol 4.0 hardening

World Runtime 1.1 / Runtime Protocol 4.0 does not add a new agency ontology.
It hardens authority, execution lifecycle, and read isolation around the 1.0
kernel.

### Transition authority

Authentication proves caller identity. A delegation establishes bounded
representation of an effective principal. Neither fact alone qualifies every
Runtime state transition.

For a delegated caller, every generic Runtime mutation must be covered by the
active delegation's `authority_ceiling.operation`, optionally narrowed by
`resource`. Directly authenticated principals remain their own transition
authority root.

Identity delegation-topology mutation and assigned-controller Domain reporting
use their specialized authority rules; they are not generic Runtime transition
grants and therefore do not route through `assert_transition_authority()`.

This creates four distinct checks:

```text
authentication
!= representation
!= Runtime transition authority
!= reality-effect authorization
```

A delegated transition ceiling never replaces Mandate/Authorization
action-resource authority. Reality-changing effects must satisfy both.

### Fresh execution lifecycle

Work/Run lifecycle is authoritative for fresh execution:

- only `pending` or `running` Work may start a new Run;
- a fresh invocation referencing Work requires non-terminal Work;
- a fresh invocation referencing Run requires `Run.status == running`;
- exact committed idempotent replay is resolved before fresh-lifecycle checks;
- an existing ambiguous historical attempt may still enter reconciliation.

Therefore terminal execution state prevents new authority from being created
without destroying historical replay/recovery semantics.

### Read authorization

Provider result and reconciliation state are persisted with read-binding
metadata: effective principal, authenticated actor, Work, and Run.

A direct owning principal may read its result. A delegated actor may read only
results bound to the same effective principal and authenticated actor. Another
principal or sibling delegated actor is rejected. Historical results lacking
read-binding metadata fail closed to direct configured-root access.

These rules are versioned as `transition-authority-v1`,
`fresh-execution-lifecycle-v1`, and `read-authorization-v1`.


## Runtime Protocol 4.0 kernel hardening

World Runtime 1.1 / Runtime Protocol 4.0 is an explicit breaking evolution of
Protocol 3.0. It does not expand the Runtime into domain policy or a universal
workflow engine. It closes three generic agency boundaries that were still
implicit in the 1.0 surface.

### Transition authority is distinct from representation

Authentication establishes who presented a credential. A delegation may allow
that actor to represent an effective principal. Neither fact by itself grants
authority for every Runtime state transition.

Delegated Runtime mutations therefore require an explicit generic operation in
the active delegation authority ceiling:

```text
authenticated actor
    !=
effective principal representation
    !=
generic Runtime transition authority
    !=
effect action/resource Authorization
```

The generic transition dimension uses `authority_ceiling.operation`. Effect
authority continues to use `action` and `resource` and remains independently
qualified by Mandate/Authorization semantics. A delegation that permits
`operation = "invoke-capability"` but does not permit the requested
`action/resource` cannot execute that effect.

Directly authenticated principals remain their own Runtime transition authority
root. Domain-specific approval, role, governance-basis, and completion rules
remain owned by Domain Controllers.

### Fresh execution lifecycle

Historical execution state is not fresh execution authority.

A new Run may start only while its Work is non-terminal. A fresh provider or
Domain dispatch bound to a Run requires the referenced Work to remain
non-terminal and the Run to remain `running`.

These checks happen only on the fresh-execution path. Durable idempotent replay
and exact historical reconciliation are resolved before fresh-execution
qualification, so a terminal Run does not erase or invalidate historical effect
facts.

```text
terminal Work/Run
    -> no fresh dispatch

committed historical effect
    -> replay remains legal

ambiguous historical effect
    -> reconciliation remains legal
```

### Read authorization

Authentication alone is not sufficient for all durable execution reads.

Provider results and runtime-owned reconciliation attempts persist an access
binding containing their effective principal, authenticated actor, and Work/Run
coordinates. Reads require the same effective principal. When access is through
delegation, the authenticated actor must also match the actor that created the
attempt/result.

A directly authenticated owning principal may read state produced on its behalf
by a delegated actor. Historical provider results that predate this access
binding fail closed to direct configured-root access rather than becoming
globally readable.

Whole-agency StateBundle access remains governed by the stronger direct-root
rule introduced in Protocol 3.0.

### Protocol 4.0 versioned contracts

Protocol 4.0 introduces:

- `transition-authority-v1`;
- `fresh-execution-lifecycle-v1`;
- `read-authorization-v1`.

It also advances the externally affected contracts to:

- `run-lifecycle-v2`;
- `capability-invocation-v6`;
- `domain-effect-execution-v3`;
- `state-access-v2`.

The canonical catalog is `world-runtime-contracts-v10`; executable reference
conformance is `world-runtime-conformance-v11`.

Protocol 3.0 and the 1.0 release matrices remain immutable historical evidence.
