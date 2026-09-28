# Semantic Kernel v0.3

## Scope

The universal semantic kernel owns only cross-domain role distinctions, versioned references,
canonicalization, and non-substitution rules. It does not own concrete payload schemas,
persistence, workflow, lifecycle state, policy, orchestration, or domain process models.

## Universal roles

The closed universal role set is:

- Claim
- Evidence
- Unknown
- Decision
- Authorization
- Effect
- Outcome
- Responsibility
- Revision

A concrete payload for one of these roles belongs to the subsystem that creates and governs it.
A role distinction is universal; a payload schema is not.

## Owner-local concepts

Concepts such as Goal, Mandate, Conflict, Acceptance, Capability, Work, Run, Proposal,
Constraint, Commitment, Permission, Obligation, and domain-specific objects are owner-local.
They may use a non-universal `SemanticRef.namespace` when a cross-subsystem reference is needed.

Owner-local does not mean semantically unimportant. It means extending or changing that concept
must not require editing the universal kernel.

## Required non-substitution boundaries

At minimum, implementations must preserve these distinctions:

- Claim != Evidence
- Decision != Authorization
- Authorization != Effect
- Effect != Outcome
- Responsibility != Effect

Owner-specific contracts may define additional hard boundaries without promoting their payloads
into the universal kernel.

## Promotion rule

A role may enter the universal set only when all of the following hold:

1. at least three materially different domains require the same distinction;
2. collapsing the distinction creates a concrete cross-domain correctness failure;
3. the role meaning is stable across those domains;
4. the distinction is independent of one Runtime implementation;
5. promotion does not import owner-specific payload fields or lifecycle state.

Promotion is explicit and versioned. Evidence for promotion is recorded separately from the
universal role set.
