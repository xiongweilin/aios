# world-runtime

> AIOS kernel 组件。权威英文原文：[README.md](README.md)。源码：`src/kernel/world_runtime/`；Runtime：根目录 `compose.yaml`。

World Runtime 是长期 agency 的 persistent semantic runtime。它拥有 durable epistemics、cognition、memory、governance、decision、strategy、responsibility 和 generic execution；Domain Controller 保留 rich domain semantics 和 bounded assignment。

World Runtime 1.1.0 使用 Runtime Protocol 4.0，在保持 1.0 agency model 的同时，把 authenticated representation 与 delegated transition authority 分开，使 terminal Work/Run 对 fresh execution 具有约束力，并把 provider-result read 绑定到 owning principal/actor。

## 所有权

`semantic-language` 拥有 cross-domain meaning 和 non-substitution rule。

`world-runtime` 拥有：

```text
ontology / identity
epistemics
cognition
memory
governance
decisions
strategy
responsibility
execution
```

Domain Controller 拥有 domain obligation、domain lifecycle、authoritative read-back、Outcome/Acceptance 和 completion。Provider success 永远不等于 domain Outcome 或 GoalAchievement。

## Runtime 与 contract

World Runtime 只通过根 Compose topology 运行，没有 native host service path。

Runtime-owned lifecycle/authority/execution/recovery contract 位于 `src/kernel/world_runtime/contracts/catalog.toml`，由 `GET /v1/contracts` 暴露。Semantic rule 位于 `docs/contracts/runtime-contracts.md`。Runtime Protocol 4.0/1.1 evolution rule 位于 `docs/releases/world-runtime-1.1-freeze.md`。

支持的 reality-boundary invocation 是 `WorldRuntime.invoke()` 及对应 HTTP endpoint。`ExecutionService` 只是内部 Work/Run/fencing service，不跨 provider boundary，也不存在第二套 in-process reality-boundary API。

## Closed schema 与 durable backend

Protocol 4.0 保持 closed top-level `CapabilityRequest` 和 public command model。Unknown top-level field 在 semantic mutation 前拒绝；provider-specific executable input 必须进入声明字段，使 durable effect identity 覆盖其语义。

SQLite 是 local/single-file mode，PostgreSQL 是 organization-grade shared durable mode。两者实现统一 `SemanticLedger`：transaction、append/events、project_get/project_put、StateBundle export/import。

Expected-version projection write 使用 database CAS。Provider-attempt reservation、Domain effect start、Run lease acquisition 都通过 durable transition，避免竞争 Runtime 同时取得 fresh dispatch/lease authority。

## Institutional continuity

Runtime 区分 historical existence 与 current qualification。`semantic-language.Revision` 是 revision meaning primitive；Runtime 持有 durable lineage，一个 lineage 只有一个 current head，historical object 可审计，successor 通过 basis reference 显式 supersede current head。

Decision、Mandate/Authorization、Goal、Experience 和 ontology version 都保持历史与当前资格分离。

## 1.0 agency model 与 Protocol 4.0

核心结构包含 Standing Responsibility、ResponsibilityRelation、StrategicIssue/Option、PortfolioProposal/Portfolio、ResourceAllocation，以及 QualificationDependency → ReviewObligation → RevalidationAssessment。

重要规则：

- child discharge != parent discharge；
- all children complete != parent satisfied；
- StrategicOption evaluation != selection authority；
- dependency change != historical subject invalidation；
- review assessment != owning subsystem reauthorization/reopen。

Protocol 4.0 进一步要求：authentication 只建立 caller identity；delegation 只建立 representation；delegated mutation 还受 operation/resource ceiling 限制；effect authority 仍由 Mandate/Authorization 单独治理；terminal Work/Run 不授权 fresh execution，但 exact committed replay 和 historical reconciliation 仍可合法进行；provider-result/reconciliation read 按 principal/actor 隔离；legacy unbound result 需要 direct root access；whole-agency StateBundle 仍 direct-root-only。

Canonical manifest：`world-runtime-contracts-v10`。Reference conformance：`world-runtime-conformance-v11`。
