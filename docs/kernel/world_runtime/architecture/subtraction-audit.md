# Semantic ownership audit

The Runtime reduction target is zero duplicate semantic authority, not zero
implementation types.

## Removed duplicate owners

- Universal payload dataclasses were removed from `semantic-language`; the package now keeps only role vocabulary, references, canonicalization, and non-substitution rules.
- `Responsibility` is one durable owner model. There is no separate `StandingResponsibility` payload.
- Decision currentness is part of the Decision owner lifecycle rather than a parallel qualification object.
- Qualification uses `QualificationBinding + ReviewCase`; assessment and resolution are transitions on the same review instead of separate durable top-level objects.
- Goal payload and lifecycle belong to strategy.
- Mandate payload and lifecycle belong to governance.
- Revision payload and lineage belong to lineage.
- Claim/Evidence/Unknown payloads and epistemic assessment models belong to epistemics.

## Deliberate non-merges

Objects with similar implementation shapes remain separate when they answer different
questions or carry different authority. Epistemic assessment, Responsibility assessment,
strategy assessment, authorization use, and review resolution are not interchangeable.

Hard semantic boundaries remain even when payload ownership is local:

- Claim != Evidence
- Decision != Authorization
- Authorization != Effect
- Effect != Outcome
- Responsibility != Effect

## Extension rule

New domain concepts should extend their owner module and, when cross-subsystem references
are needed, use a non-universal namespace. Adding a domain feature must not require adding a
new universal dataclass or editing a central payload registry.
