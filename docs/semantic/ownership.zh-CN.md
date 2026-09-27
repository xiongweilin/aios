# 语义所有权

Semantic kernel 刻意保持很小。

## 本层拥有

Claim、Evidence、Unknown、Conflict、Goal、Constraint、Mandate、Proposal、Decision、Commitment、Permission、Obligation、Authorization、Capability、Action、Effect、Outcome、Acceptance、Revision 和 Responsibility。

## 本层不拥有

- lifecycle state machine；
- persistence 和 event sourcing；
- cognition/search policy；
- memory consolidation；
- portfolio strategy；
- work scheduling；
- provider protocol；
- deployment mechanics；
- Employee、Invoice、ReleaseCandidate、CanaryStage、KubernetesDeployment 等 domain concept。

这些属于 world runtime 或 domain controller。

## Promotion policy

Version 0.2 要求：至少三个实质不同 domain 都出现该区分，并且能够证明在合并该区分时会发生 semantic correctness failure。可执行 gate 是 `semantic_language.promotion`；candidate observation 记录在 `docs/semantic-promotion-ledger.md`。
