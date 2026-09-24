# Semantic ownership

The semantic kernel is intentionally small.

## Owned here

Claim, Evidence, Unknown, Conflict, Goal, Constraint, Mandate, Proposal, Decision,
Commitment, Permission, Obligation, Authorization, Capability, Action, Effect, Outcome,
Acceptance, Revision, and Responsibility.

## Not owned here

- lifecycle state machines;
- persistence and event sourcing;
- cognition/search policy;
- memory consolidation;
- portfolio strategy;
- work scheduling;
- provider protocols;
- deployment mechanics;
- domain concepts such as Employee, Invoice, ReleaseCandidate, CanaryStage, or KubernetesDeployment.

Those belong to the world runtime or to domain controllers.


## Promotion policy

Version 0.2 requires evidence from at least three materially different domains plus a demonstrated
semantic correctness failure when the distinction is collapsed. The executable gate is
`semantic_language.promotion`; candidate observations are recorded in
`docs/semantic-promotion-ledger.md`.
