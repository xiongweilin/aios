# World Runtime 1.0 architecture

`semantic-language` owns universal cross-domain meaning and non-substitution
rules. `world-runtime` owns durable generic agency mechanics. Domain
Controllers own rich domain semantics, authoritative read-back, domain Outcome
qualification, Acceptance, and completion.

## Durable kernel

World Runtime 1.0 contains these Runtime-owned subsystems:

```text
ontology / identity
epistemics / cognition / memory
governance / decisions
strategy / responsibility
qualification / execution / recovery
```

Models, agents, workers, processes, providers, and Domain Controllers are
replaceable executors. Durable semantic state survives them.

## Cross-domain responsibility

A `StandingResponsibility` is not a workflow task. Runtime may relate
Responsibilities with a small generic topology:

- `requires`: a hard qualification dependency;
- `contributes-to`: a non-blocking support relation.

A required child must be discharged before its source can be assessed
`satisfied`, but child completion never implies parent satisfaction or
discharge. Relation creation and retirement require explicit Decisions and
preserve history. Hard dependency cycles fail closed.

Runtime owns the global topology. Domain Controllers continue to own how one
bounded assignment is fulfilled.

## Strategic agency

Runtime persists:

```text
StrategicIssue
StrategicOption
PortfolioProposal
StrategicPortfolio
ResourceBudgetLine
ResourceAllocation
```

Option generation and evaluation may come from a cognitive/model layer, but
Runtime does not define a universal utility function and does not rank options
into an authoritative choice.

Portfolio activation, retirement, issue closure, and resource allocation are
explicitly Decision-qualified transitions. Resource budgets include units and
are enforced with durable CAS under shared PostgreSQL execution.

## Continuous qualification

Historical existence is distinct from current usability.

A `QualificationDependency` records the specific dependency/version and
assumption on which a current use relies. A material dependency change creates
a targeted `ReviewObligation`; it does not silently mutate or invalidate the
subject.

A `RevalidationAssessment` records the review judgment. `continue` may close
the review directly. Other dispositions such as revalidate, reopen, or
reauthorize remain pending until the owning subsystem records an explicit
resolution. Only then may the dependency lineage advance.

This is dependency-driven requalification, not periodic freshness TTL.

## Reality boundary

Runtime owns generic effect identity, authority qualification, provider-attempt
reservation, Domain-effect dispatch fencing, ambiguous recovery, and audit.

Domain Controllers retain domain providers where the domain owns the concrete
lifecycle. Provider success is never promoted into domain Outcome or
Acceptance.

## Persistence and continuity

SQLite is the local/reference backend. PostgreSQL is the shared
organization-grade backend. Both implement the same `SemanticLedger`
contract.

PostgreSQL correctness uses database transactions and expected-version CAS for
shared projections, leases, dispatch winners, strategic allocations, and other
durable transitions.

`StateBundle` is backend-neutral full Runtime state. 1.0 validation checks the
reference graph for legacy and new agency projections, including Responsibility
relations, strategic portfolios/allocations, and qualification reviews.

## Trust and protocol

Runtime Protocol 3.0 is authenticated and closed-schema.

- authority-bearing writes are principal/delegation qualified;
- public durable reads require authentication;
- DomainAssignment/Report reads are visible to the owning principal or assigned
  Controller;
- whole-agency StateBundle export/import requires direct authentication as the
  deployment-configured `root_principal`, not delegated Controller authority;
- if `root_principal` is not configured, the HTTP whole-agency state surface is
  disabled.

The root principal is a boot/deployment trust anchor, not imported semantic
state. StateBundle therefore cannot redefine the principal that is authorized to
replace the whole Runtime state.

## Hard semantic boundaries

- Unknown != False.
- Claim != Evidence.
- Decision != Authorization.
- Authorization != Effect.
- Provider success != Effect.
- Effect != Outcome.
- Outcome != Acceptance.
- Child discharge != Parent satisfaction.
- Strategic evaluation != Decision.
- Dependency change != Subject invalidation.
- Review assessment != Reauthorization/reopen action.
- Historical qualification != Current qualification.

## Explicitly outside the Runtime

The 1.0 kernel does not own:

- Personal World facts or consumer ontology;
- Owner Console/UI projections;
- model routing or provider selection policy for cognition;
- reusable cognitive procedures/skills;
- domain-specific workflow/lifecycle semantics;
- payment/device/government trust infrastructure;
- a universal strategy score or business-process language.
