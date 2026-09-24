# World Runtime 1.1 freeze

This document freezes Runtime Protocol 4.0 as the authority/lifecycle/read
isolation hardening release over the World Runtime 1.0 governed-agency kernel.

It does not reopen the 1.0 semantic ownership boundary. It versions the
breaking security requirements that could not correctly remain under Runtime
Protocol 3.0.

## Baseline

- semantic-language: `0.2.0`
- semantic-language commit: `eb8c6cb1757256ea9961201bd66ea79952de6134`
- world-runtime package: `1.1.0`
- world-runtime implementation/evidence baseline:
  `02c83f2a8e8cf68fc27897fec8bb8096b6dd8d39`
- Runtime Protocol: `4.0`
- contract catalog: `world-runtime-contracts-v10`
- reference conformance: `world-runtime-conformance-v11`
- Domain Controller protocol: `domain-controller-protocol-v3`

Frozen Controller commits:

- control-plane: `475cc5b3bbc714e65d71f133f4dfa838b249d817`
- administrative-orchestrator: `c44ca76daf6e2d9ecd4ab182d170176ff740babb`
- autonomous-development: `7a738277d3bb0bc71a7e620bbfedda6ebd4d9dd9`

The baseline above is the last non-freeze-evidence candidate before this
document and the 1.1 matrix were added. Commits after it may finalize pins,
release evidence, documentation, or CI metadata, but must not silently change
Protocol 4.0 semantics without moving the baseline.

## Frozen 1.0 ownership boundary

World Runtime continues to own durable generic agency mechanics:

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

It still does not own Personal World facts, UI projections, model routing,
reusable cognitive procedures, domain-specific process/lifecycle semantics,
universal business-process semantics, a universal strategy scoring function,
or external payment/device/government trust infrastructure.

## Protocol 4.0 frozen distinctions

Protocol 4.0 adds and freezes these non-substitution rules:

```text
Authentication != Representation
Representation != Runtime transition authority
Runtime transition authority != Reality-effect authorization

Terminal Work/Run != fresh execution authority
Historical committed replay != fresh provider dispatch
Historical ambiguous attempt != new attempt

Authenticated read != arbitrary principal read
Effective principal match != sibling delegated-actor access
Legacy unbound provider result != generally readable result
```

Together with the 1.0 rules:

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
`world-runtime-contracts-v10` is frozen.

A 1.1.x patch may correct defects, strengthen tests/failure paths, harden an
already-frozen invariant, or improve performance without changing semantic
identity or authority.

A change must move to a later protocol/catalog identifier if it changes accepted
wire input in a breaking way, changes authentication/representation/authority
requirements, changes fresh-execution legality, changes provider-result read
authorization, changes durable semantic identity, or changes the meaning of an
existing transition.

## Release acceptance

The canonical compatibility evidence is
`docs/releases/current-system-matrix-1.1.0.md`.

Protocol 4.0 is accepted only when ordinary Runtime CI, PostgreSQL integration,
the three-Controller HTTP matrix, and the Controllers' own CI/security/trust
gates are green at the frozen commits.
