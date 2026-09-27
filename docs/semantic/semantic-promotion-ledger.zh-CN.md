# Semantic promotion ledger

本 ledger 记录未来 universal semantics 的候选。某个候选仅仅在一个 Runtime 或一个 domain 有用，并不会让它自动成为 semantic kernel 的一部分。

Promotion 要求：

1. 至少三个实质不同 domain 中出现同一区分；
2. 合并该区分会导致具体 semantic correctness failure；
3. 含义独立于 workflow 或 transport 且保持稳定；
4. 不依赖某一个 World Runtime implementation；
5. 不嵌入 domain policy。

## 当前候选

| Candidate | Development | Administrative | Personal operations | Status |
| --- | --- | --- | --- | --- |
| Assignment != Responsibility | observed | observed | observed | candidate；需要验证 collapse failure |
| Qualification != Permission | observed | observed | partial | 不具备资格 |
| Delegation != Authorization | partial | observed | partial | 不具备资格 |
| GoalAchievement != Outcome | observed | partial | partial | 不具备资格 |
| CurrentQualification != HistoricalExperience | observed | observed | partial | 不具备资格 |

本表中的任何 candidate 都不会因为被记录在此而获得 promotion。Promotion 需要单独的 semantic change、counterexample 和 conformance test。
