# World Runtime 1.1 contract

World Runtime 1.1 定义 Runtime Protocol 4.0，以及当前 1.1 line 的 authority/lifecycle/read-isolation 要求。

## Contract identifier

- world-runtime package：`1.1.0`
- Runtime Protocol：`4.0`
- contract catalog：`world-runtime-contracts-v10`
- reference conformance：`world-runtime-conformance-v11`
- Domain Controller protocol：`domain-controller-protocol-v3`
- semantic-language：`0.2.0`

## 所有权边界

World Runtime 拥有 durable generic agency mechanic：

```text
identity / trust
ontology / epistemics
cognition state / experience memory
governance / decisions
standing responsibility / generic responsibility topology
strategy qualification / portfolio / resource exposure
continuous qualification / review obligations
execution / recovery / reality-effect fencing
backend-neutral durable ledger
```

它不拥有 Personal World fact、operator-interface state、model routing、可复用 cognitive procedure、domain-specific lifecycle semantics、universal business-process semantics、universal strategy scoring function 或 external system authority。

## Protocol 4.0 区分

```text
Authentication != Representation
Representation != Runtime transition authority
Runtime transition authority != Reality-effect authorization

Terminal Work/Run != fresh execution authority
Historical committed replay != fresh provider dispatch
Historical ambiguous attempt != new attempt

Authenticated read != arbitrary principal read
Effective principal match != sibling delegated-actor access
Unbound provider result != generally readable result
```

以及核心 non-substitution rule：

```text
Unknown != False
Claim != Evidence
Decision != Authorization
Authorization != Effect
Provider success != Effect
Effect != Outcome
Outcome != Acceptance
Child discharge != Parent satisfaction
Strategic evaluation != Decision
Dependency change != Subject invalidation
Review assessment != reauthorization/reopen action
Historical qualification != Current qualification
```

## 1.1.x 演进规则

Runtime Protocol 4.0 的含义和 `world-runtime-contracts-v10` 中已有 identifier 保持稳定。

1.1.x patch 可以修 defect、强化 test/failure path、加固 existing invariant 或改善 performance，但不能改变 semantic identity 或 authority。

如果变更会破坏性改变 accepted wire input、authentication/representation/authority requirement、fresh-execution legality、provider-result read authorization、durable semantic identity，或 existing transition 的含义，则必须使用后续 protocol/catalog identifier。

## Acceptance

Acceptance 需要 AIOS root checks，以及针对当前 monorepo revision 的新鲜 Runtime 和 Domain Controller verification。历史 revision 的 pass 不是当前 tree 的 evidence。
