# ADR 0007 — World Runtime semantic ownership

Status: accepted
Date: 2026-09-20

## Context

Administrative requires a generic durable runtime owner without moving Administrative facts, policy,
obligations, outcome semantics, or completion into that runtime.

## Decision

Current ownership is:

```text
semantic-language
  cross-domain meaning and non-substitution rules

world-runtime
  persistent agency/runtime primitives
  responsibility / Work / Run
  governance / Decision / Mandate / Authorization
  provider execution / durable attempts / reconciliation
  generic epistemics / cognition / memory / strategy

administrative-orchestrator
  Administrative facts / policy / authority
  obligations / business effect intent
  authoritative read-back
  ConfirmedOutcome / completion / reopen
```

Administrative compiles a bounded domain effect into Runtime responsibility/authority/execution
objects, but it does not delegate domain Outcome semantics.

Provider success remains distinct from Administrative completion.

## Consequences

- new Runtime features are justified by cross-domain runtime invariants, not by Administrative implementation convenience;
- Autonomous Development integrates as another external Domain Controller rather than moving Git/build/canary/release semantics into Runtime core;
- Administrative retains authoritative read-back, domain Outcome, completion, and reopen semantics.
