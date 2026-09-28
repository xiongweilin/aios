# 语义所有权

Semantic kernel 刻意保持很小。它拥有 role distinction，而不是恰好实例化这些
role 的具体 payload。

## 本层拥有的 universal role

- Claim
- Evidence
- Unknown
- Decision
- Authorization
- Effect
- Outcome
- Responsibility
- Revision

对这些 role，`semantic-language` 拥有稳定的跨领域含义与 reference vocabulary；
创建对象的 subsystem 拥有 payload schema、persistence、lifecycle 和 policy。

## Owner-local concept

Goal、Mandate、Conflict、Acceptance、Capability、Work、Run、Proposal、
Constraint、Commitment、Permission、Obligation 以及 domain concept 都不是
universal kernel payload。它们由 Runtime subsystem 或 Domain Controller 拥有，
需要跨 subsystem 引用时使用 non-universal `SemanticRef` namespace。

这样可以避免中央 schema registry 变成所有新 domain concept 的扩展点。

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

## Promotion policy

Version 0.3 要求：至少三个实质不同 domain 都需要该 role distinction，并且能够证明
合并后会发生 cross-domain semantic correctness failure。Promotion 只能加入 role
distinction，不能带入 owner-specific payload field 或 lifecycle state。

可执行 gate 是 `semantic_language.promotion`；candidate observation 记录在
`docs/semantic-promotion-ledger.md`。
