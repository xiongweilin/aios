# ADR 0007 — World Runtime cutover and semantic ownership

Status: accepted
Date: 2026-09-20

## Context

ADRs 0001 and 0002 established the correct separation between the Administrative domain and a
generic runtime, but the generic owner at that time was `agent-kernel`.

The runtime architecture has since converged into `world-runtime`, which also absorbs the
generic cognition/epistemic responsibilities formerly split across `meta-controller` and
`world-state`.

The Administrative code path has physically cut over to `WorldRuntimeBridge` and no longer
imports or deploys Agent Kernel.

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

- `agent-kernel` is a frozen predecessor and not a production dependency.
- `meta-controller` is not an independently authoritative deployed service.
- current documentation and deployment use World Runtime vocabulary;
- historical ADR/acceptance/migration identifiers remain unchanged where they are evidence;
- new Runtime features are justified by cross-domain runtime invariants, not by Administrative
  implementation convenience.
- `autonomous-development` must integrate as another external Domain Controller rather than
  moving Git/build/canary/release semantics into Runtime core.

## Supersession

This ADR supersedes the current-runtime-ownership portions of ADR 0001 and ADR 0002.
Those ADRs remain historical records of the architecture and migration plan accepted at the time.
