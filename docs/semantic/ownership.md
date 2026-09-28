# Semantic ownership

The semantic kernel is intentionally small. It owns role distinctions, not
the concrete payloads that happen to instantiate those roles.

## Universal roles owned here

- Claim
- Evidence
- Unknown
- Decision
- Authorization
- Effect
- Outcome
- Responsibility
- Revision

For these roles, `semantic-language` owns the stable cross-domain meaning and
reference vocabulary. The subsystem that creates an object owns its payload
schema, persistence, lifecycle, and policy.

## Owner-local concepts

Goal, Mandate, Conflict, Acceptance, Capability, Work, Run, Proposal,
Constraint, Commitment, Permission, Obligation, and domain concepts are not
universal kernel payloads. They remain owned by Runtime subsystems or Domain
Controllers and may use non-universal `SemanticRef` namespaces.

This avoids a central schema registry becoming the extension point for every
new domain concept.

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

## Promotion policy

Version 0.3 requires evidence from at least three materially different domains
plus a demonstrated cross-domain semantic correctness failure when the role
distinction is collapsed. Promotion must add only the role distinction; it
must not import owner-specific payload fields or lifecycle state.

The executable gate is `semantic_language.promotion`; candidate observations
are recorded in `docs/semantic-promotion-ledger.md`.
