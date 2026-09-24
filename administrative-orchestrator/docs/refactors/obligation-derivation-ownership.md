# Obligation derivation ownership

This post-closure refactor separates the generic obligation contract from Administrative domain interpretation without changing any accepted execution semantics.

## Boundary

`obligations.py` owns only the reusable obligation vocabulary, durable rows, repository behavior, fulfillment records, and a compatibility facade for historical imports.

Domain interpretation is owned by:

- `onboarding_obligations.py` for employee-onboarding obligation derivation;
- `offboarding_obligations.py` for employee-offboarding, authority-revocation, and continuity-transfer obligation derivation;
- `financial_obligations.py` for procurement, invoice/AP preparation, and expense obligation derivation;
- `obligation_derivation.py` for fail-closed case-kind dispatch only;
- `obligation_derivation_common.py` for stable construction shared by domain derivations.

Execution code imports derivation functions from the owning domain modules. Existing callers may continue importing the historical names from `obligations.py`; those functions are thin lazy forwarding wrappers and contain no case or operation interpretation.

## Invariants

- no database migration;
- no obligation, requirement, governance-basis, authorization, effect, outcome, or fulfillment identity changes;
- no change to declared obligation tuple order or migration `0032` sequence semantics;
- no change to expected postconditions or fulfillment kinds;
- no change to authority epochs, approvals, completion, responsibility discharge, Kernel contracts, capability contracts, or provider behavior;
- historical M5/M6/M7/M8/M9 acceptance evidence and tags remain immutable.

The purpose is responsibility ownership, not file-size reduction: generic persistence preserves a frozen obligation graph; each domain remains responsible for deciding what that graph means.
