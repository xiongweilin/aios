# Semantic Kernel v0.3

## 范围

Universal semantic kernel 只拥有跨领域 role distinction、versioned reference、canonicalization
和 non-substitution rule。它不拥有具体 payload schema、persistence、workflow、lifecycle state、
policy、orchestration 或 domain process model。

## Universal role

封闭的 universal role 集合为：

- Claim
- Evidence
- Unknown
- Decision
- Authorization
- Effect
- Outcome
- Responsibility
- Revision

某个 role 的具体 payload 由创建并治理它的 subsystem 拥有。
Role distinction 可以是 universal；payload schema 不是。

## Owner-local concept

Goal、Mandate、Conflict、Acceptance、Capability、Work、Run、Proposal、Constraint、
Commitment、Permission、Obligation 以及 domain-specific object 都是 owner-local。
当需要跨 subsystem 引用时，它们可以使用 non-universal `SemanticRef.namespace`。

Owner-local 不代表语义不重要，而是表示扩展或修改该 concept 不应要求修改 universal kernel。

## 必须保留的 non-substitution boundary

至少必须保留：

- Claim != Evidence
- Decision != Authorization
- Authorization != Effect
- Effect != Outcome
- Responsibility != Effect

Owner-specific contract 可以定义额外 hard boundary，而无需把对应 payload 提升进 universal kernel。

## Promotion 规则

只有同时满足以下条件，一个 role 才能进入 universal set：

1. 至少三个实质不同 domain 都需要同一区分；
2. 合并该区分会造成具体的 cross-domain correctness failure；
3. role meaning 在这些 domain 中稳定；
4. 该区分不依赖某一个 Runtime implementation；
5. promotion 不会带入 owner-specific payload field 或 lifecycle state。

Promotion 必须显式并版本化。用于 promotion 的 evidence 与 universal role set 分开记录。
