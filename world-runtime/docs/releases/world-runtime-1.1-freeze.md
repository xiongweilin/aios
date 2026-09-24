# World Runtime 1.1 contract

World Runtime 1.1 defines Runtime Protocol 4.0 and the authority/lifecycle/read-isolation
requirements of the current 1.1 line.

## Contract identifiers

- world-runtime package: `1.1.0`
- Runtime Protocol: `4.0`
- contract catalog: `world-runtime-contracts-v10`
- reference conformance: `world-runtime-conformance-v11`
- Domain Controller protocol: `domain-controller-protocol-v3`
- semantic-language: `0.2.0`

## Ownership boundary

World Runtime owns durable generic agency mechanics:

```text
identity / trust
ontology / epistemics
cognition state / experience memory
governance / decisions
standing responsibility / generic responsibility topology
strategy qualification / portfolio / resource exposure
continuous qualification / review obligations
execution / recovery / reality-effect fencing
backend-neutral durable ledger
```

It does not own Personal World facts, operator-interface state, model routing,
reusable cognitive procedures, domain-specific lifecycle semantics, universal
business-process semantics, a universal strategy scoring function, or external
system authority.

## Protocol 4.0 distinctions

```text
Authentication != Representation
Representation != Runtime transition authority
Runtime transition authority != Reality-effect authorization

Terminal Work/Run != fresh execution authority
Historical committed replay != fresh provider dispatch
Historical ambiguous attempt != new attempt

Authenticated read != arbitrary principal read
Effective principal match != sibling delegated-actor access
Unbound provider result != generally readable result
```

Together with the core non-substitution rules:

```text
Unknown != False
Claim != Evidence
Decision != Authorization
Authorization != Effect
Provider success != Effect
Effect != Outcome
Outcome != Acceptance
Child discharge != Parent satisfaction
Strategic evaluation != Decision
Dependency change != Subject invalidation
Review assessment != reauthorization/reopen action
Historical qualification != Current qualification
```

## 1.1.x evolution rule

The meaning of Runtime Protocol 4.0 and existing identifiers in
`world-runtime-contracts-v10` is stable.

A 1.1.x patch may correct defects, strengthen tests/failure paths, harden an
existing invariant, or improve performance without changing semantic identity or authority.

A change requires a later protocol/catalog identifier if it changes accepted wire input in a
breaking way, authentication/representation/authority requirements, fresh-execution legality,
provider-result read authorization, durable semantic identity, or the meaning of an existing
transition.

## Acceptance

Acceptance requires the AIOS root checks plus fresh Runtime and Domain Controller verification
against the current monorepo revision. A passing historical revision is not evidence for the
current tree.
