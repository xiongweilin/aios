# Engineering action chain

> **Migrated design reference (not the current implementation contract):** Transferred from [guide/engineering/action-chain.md](https://github.com/xiongweilin/guide/blob/511c073322c6b38ed2d36b32492836abf4d69b58/engineering/action-chain.md) to preserve engineering rationale. Current AIOS behavior, authority, state, and contracts are defined by AIOS's maintained `docs/`, `contracts/`, source, and tests. The conceptual framework belongs to [guide](https://github.com/xiongweilin/guide); this note does not define its foundational ontology.

[English](./action-chain.md) | [简体中文](./action-chain.zh-CN.md)

> Position: engineering semantics that must remain explicit when a purposeful finite actor is implemented as a long-running system that creates auditable real effects and silent collapse would cause correctness failure.

Framework level requires only:

`choice / action ≠ real effect ≠ feedback`

Engineering systems often need a finer decomposition.

## 1. Reference chain

```text
current boundary / sufficiency basis
→ Decision
→ Governance basis / Commitment
→ Authorization
→ Execution attempt
→ Effect
→ Observation / authoritative read-back
→ Verification
→ Outcome
→ Completion / remaining obligation
→ Retain / Recovery / Revision / Reopen
```

These roles need not map one-to-one to services, classes, or tables, but when materially relevant they must not be silently collapsed into one state.

## 2. Core non-substitution

`Candidate ≠ Decision`

`Decision ≠ Authorization`

`Authorization ≠ Execution`

`Execution success ≠ Effect`

`Effect ≠ Observation`

`Observation ≠ Verification`

`Effect ≠ Outcome`

`Outcome ≠ Completion`

`Completion ≠ long-term Responsibility discharge`

These are not ultimate ontological conclusions. They are engineering boundaries when collapse creates concrete failure.

## 3. Decision is not Authorization

A system may have formed a choice while the current principal still lacks authority to act on the resource. A valid state can therefore be:

`Decision = 1, Authorization = 0`

Collapsing them either loses the real decision or manufactures authority.

## 4. Effect is not Outcome

An external provider may successfully create a real change while the intended domain property is not achieved. For example, a deployment occurs but the product metric does not improve:

`Effect = 1, Outcome = 0`

A provider receipt establishes only execution / effect facts at proportional scope, not a domain outcome.

## 5. External reality cannot atomically commit with a local transaction

A database transaction cannot atomically commit together with external APIs, devices, humans, robots, organizational systems, and a local ledger.

The system must therefore represent states such as:

- request sent but effect unknown;
- external effect occurred but local confirmation was lost;
- partial success;
- effect may have occurred but is unsafe to replay;
- reconciliation, compensation, or recovery required.

`transport idempotency ≠ effect idempotency`

## 6. Durable effect identity and idempotency

High-consequence effects should have stable identity to prevent duplicate execution after timeout, loss of effect attempts across process restart, concurrent dispatch by multiple workers, and rebinding one idempotency key to a different effect.

Mechanisms can include CAS, unique constraints, leases, dispatch fencing, outbox/inbox, and others; guide prescribes no single implementation.

## 7. Observation and verification

Observation should come from the reality side when possible rather than merely repeat executor output.

Verification checks frozen postconditions such as object identity, target state, invariant state, material side effects, effect scope, and temporal validity.

`provider success ≠ verified reality`

## 8. Outcome and Completion

Outcome is domain interpretation / qualification of real effects. Completion may additionally require discharged obligations, acceptable residual risk, ended monitoring, completed compensation, or satisfied responsibility-release conditions.

`Outcome ≠ Completion`

## 9. Recovery and reopening

Exception paths should preserve reconcile, retry only when effect semantics permit it, compensate, rollback, stop, reauthorize, and reopen boundary.

Recovery success itself requires reality-side verification rather than only a recovery program exit code.

## 10. Engineering minimization rule

Promote a distinction into universal engineering semantics only when:

1. multiple materially different domains need it;
2. collapse produces a concrete correctness failure;
3. meaning is stable across those domains;
4. it is independent of a particular provider or workflow;
5. promotion does not pull domain payload into the universal kernel.

AIOS semantic promotion is one concrete implementation of this principle.