# Durable obligation sequence

This post-closure refactor makes obligation tuple order explicit durable state instead of reconstructing it from domain operation names inside the generic repository.

## Ownership

A domain obligation derivation owns the order of the immutable `AdministrativeObligationSet.obligations` tuple. `ObligationRepository` owns only faithful persistence and restoration of that declared order.

The public `AdministrativeObligation` model does not gain a sequencing concept. `sequence` is persistence metadata on `administrative_obligation`, scoped to one `requirement_id`, because ordering belongs to the frozen obligation graph representation rather than to one obligation's business meaning.

## Historical compatibility

Before migration `0032_obligation_sequence`, persisted obligation rows had no ordinal. Runtime restoration reconstructed an order from target system, operation names, authority class, and obligation identity, with special priorities for the M8 ERP operations.

Migration `0032_obligation_sequence` performs that legacy reconstruction exactly once and stores the resulting ordinal for every historical obligation set. After the migration, runtime persistence no longer knows financial operation names.

New obligation sets persist the tuple order declared by their domain derivation. A persisted set whose ordinals are not contiguous from zero fails closed on read.

## Invariants

- no change to obligation IDs, requirement IDs, authority epochs, governance basis IDs, expected postconditions, fulfillment kinds, effect links, completion semantics, or Kernel contracts;
- no new ordering logic is invented by the generic repository;
- procurement draft-before-confirm remains preserved after persistence and restart;
- historical accepted M5/M7/M8 evidence is not rewritten;
- downgrade removes only the persistence ordinal and its uniqueness constraint;
- domain derivation remains in `obligations.py` in this PR; separating derivation from generic persistence is a later, independent refactor.
