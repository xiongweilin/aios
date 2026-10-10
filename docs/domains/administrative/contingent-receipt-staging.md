# Contingent-policy evidence receipts (research staging only)

This is an additive interface to `ContingentPolicyCursor`. It is **not** a
production executor or a substitute for World Runtime authorization.

## Why

The original research-only cursor takes `independent_readback=True` from its
caller. That Boolean alone is not evidence: a caller can claim verification.
A real integration must anchor evidence outside the proposing agent.

## Receipt-enforced cursor

Supply both `verify_receipt` (a trusted, externally backed verifier callback)
and `effect_identities` (the durable identifiers bound to the current proposed
effects). Then use `observe_with_receipt` and `resolve_effect_with_receipt`.

- A receipt binds the current case ID, authority epoch, state version, step name,
  kind, disposition and nonempty evidence/source references.
- For a verified effect, the receipt must carry the independently bound durable
  effect identity. Names alone cannot identify a reality-changing attempt.
- Real authorization and probe-qualification callbacks must return exactly
  Boolean `True`. Truthy strings/objects, false values and callback failures
  block the cursor; they cannot be interpreted as approval.
- The verifier callback **must** independently resolve protected evidence and
  validate subject/operation, provenance, observation freshness, readback
  independence and the historical effect. The receipt fields do not prove this.
- In this mode, the legacy `independent_readback=True` path cannot advance a
  probe or a verified effect without a qualified receipt.
- Each independently accepted evidence locator can advance this in-memory cursor
  at most once, even if reused under a different source name. Repeated
  observations require genuinely fresh and independently verified evidence.
  This replay guard is **not durable across process restarts** and requires a
  protected evidence store and durable reconciliation before production use.
- Strict mode refuses to stage an effect without a bound durable effect ID.
- An effect-unknown report is **not** a verified outcome; it can only move to
  the precompiled qualified probe, not dispatch the same effect again.
- Even a verified policy `done` never closes the Administrative case.

The current tests use a fixture verifier rather than protected real evidence.
This feature therefore proves *staging API behavior under the callback's
assumptions*, not real-world evidence independence.

## Promotion conditions

Do not connect the new cursor to provider writes before independently
qualifying the callback against World Runtime's durable attempt/readback and
current contracts. Exercise unknown, stale, revoked, identity-rebound,
competing-writer and network-failure cases. A changed runtime binding requires
recompilation. Actual provider effects must continue through World Runtime;
domain outcome and completion remain domain-owned.

Evidence: `tests/domains/administrative/test_contingent_receipts.py`.
