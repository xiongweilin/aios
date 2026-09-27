# World Runtime 1.0 架构

`semantic-language` 拥有 universal cross-domain meaning 和 non-substitution rule。`world-runtime` 拥有 durable generic agency mechanic。Domain Controller 拥有 rich domain semantics、authoritative read-back、domain Outcome qualification、Acceptance 和 completion。

## Durable kernel

World Runtime 1.0 包含这些 Runtime-owned subsystem：

```text
ontology / identity
epistemics / cognition / memory
governance / decisions
strategy / responsibility
qualification / execution / recovery
```

Model、agent、worker、process、provider 和 Domain Controller 都是可替换 executor。Durable semantic state 在它们之外持续存在。

## 跨领域 responsibility

`StandingResponsibility` 不是 workflow task。Runtime 可以用小型 generic topology 关联 Responsibility：

- `requires`：hard qualification dependency；
- `contributes-to`：non-blocking support relation。

Required child 必须先 discharge，source 才能 assessment 为 `satisfied`；但 child completion 永远不意味着 parent satisfaction 或 discharge。Relation create/retire 需要 explicit Decision 并保留 history。Hard dependency cycle fail closed。

Runtime 拥有 global topology。Domain Controller 继续拥有一个 bounded assignment 如何 fulfilled。

## Strategic agency

Runtime 持久化 `StrategicIssue`、`StrategicOption`、`PortfolioProposal`、`StrategicPortfolio`、`ResourceBudgetLine` 和 `ResourceAllocation`。

Option generation/evaluation 可以来自 cognitive/model layer，但 Runtime 不定义 universal utility function，也不把 option 排名成 authoritative choice。

Portfolio activation、retirement、issue closure 和 resource allocation 都是 explicit Decision-qualified transition。Resource budget 包含 unit，并在 shared PostgreSQL execution 下通过 durable CAS 强制。

## Continuous qualification

Historical existence 与 current usability 分离。

`QualificationDependency` 记录当前使用依赖的具体 dependency/version 和 assumption。Material dependency change 创建 targeted `ReviewObligation`，不会静默修改或 invalidate subject。

`RevalidationAssessment` 记录 review judgment。`continue` 可以直接关闭 review。Revalidate、reopen、reauthorize 等其他 disposition 保持 pending，直到 owning subsystem 记录 explicit resolution；之后 dependency lineage 才能推进。

这是 dependency-driven requalification，不是 periodic freshness TTL。

## Reality boundary

Runtime 拥有 generic effect identity、authority qualification、provider-attempt reservation、Domain-effect dispatch fencing、ambiguous recovery 和 audit。

具体 lifecycle 由 domain 持有时，Domain Controller 保留 domain provider。Provider success 永远不会被提升成 domain Outcome 或 Acceptance。

## Persistence 与 continuity

SQLite 是 local/reference backend；PostgreSQL 是 shared organization-grade backend。两者实现相同 `SemanticLedger` contract。

PostgreSQL correctness 使用 database transaction 和 expected-version CAS，处理 shared projection、lease、dispatch winner、strategic allocation 及其他 durable transition。

`StateBundle` 是 backend-neutral full Runtime state。1.0 validation 检查 legacy/new agency projection 的 reference graph，包括 Responsibility relation、strategic portfolio/allocation 和 qualification review。

## Trust 与 protocol

Runtime Protocol 3.0 是 authenticated、closed-schema。

- authority-bearing write 由 principal/delegation qualification；
- public durable read 需要 authentication；
- DomainAssignment/Report read 对 owning principal 或 assigned Controller 可见；
- whole-agency StateBundle export/import 要求 deployment-configured `root_principal` 直接认证，不能使用 delegated Controller authority；
- 未配置 `root_principal` 时，HTTP whole-agency state surface 禁用。

Root principal 是 boot/deployment trust anchor，不是 imported semantic state。因此 StateBundle 不能重新定义谁被授权替换整个 Runtime state。

## Hard semantic boundary

- Unknown != False。
- Claim != Evidence。
- Decision != Authorization。
- Authorization != Effect。
- Provider success != Effect。
- Effect != Outcome。
- Outcome != Acceptance。
- Child discharge != Parent satisfaction。
- Strategic evaluation != Decision。
- Dependency change != Subject invalidation。
- Review assessment != Reauthorization/reopen action。
- Historical qualification != Current qualification。

## 明确位于 Runtime 之外

1.0 kernel 不拥有 Personal World fact/consumer ontology、Owner Console/UI projection、cognition model routing/provider selection policy、可复用 cognitive procedure/skill、domain-specific workflow/lifecycle semantics、payment/device/government trust infrastructure、universal strategy score 或 business-process language。
