# Semantic Kernel v0.2

## 所有权

本 contract 只拥有跨领域含义，不规定 storage、workflow、transport、orchestration、agent architecture 或 domain lifecycle。

## Epistemic 区分

- Claim != Evidence。
- Unknown != False。
- Conflict != Error。
- Historical assessment != current qualification。
- Derived evidence 不会仅因为模型输出它就变成 independent evidence。

## Intent 与 governance 区分

- Goal != Claim。
- Constraint != Goal。
- Proposal != Decision。
- Decision != Authorization。
- Policy satisfaction != Authorization。
- Authorization != Effect。

## Execution 区分

- Capability != Action。
- Action != Effect。
- Provider success != Effect。
- Effect != Outcome。
- Outcome != Acceptance。
- Work completion != Responsibility discharge。

## Promotion 规则

只有同时满足以下全部条件，新 concept 才属于 universal semantic kernel：

1. 至少三个实质不同 domain 都需要同一区分；
2. 合并区分会造成具体 semantic correctness failure；
3. 含义在这些 domain 中保持稳定；
4. 不依赖某一个 World Runtime implementation；
5. 不包含 domain-specific policy。

Promotion 必须显式并版本化。Promotion ledger 中的 observation 本身不是 promotion。
