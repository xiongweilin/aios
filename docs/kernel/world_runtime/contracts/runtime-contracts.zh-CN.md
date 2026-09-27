# World Runtime contracts

> 权威英文原文：[runtime-contracts.md](runtime-contracts.md)。Canonical manifest：`src/kernel/world_runtime/contracts/catalog.toml`。

本文件是中文结构化说明。逐字段、逐版本和完整协议细节以英文原文及 canonical catalog 为准。

## 所有权

World Runtime 持有通用 durable agency/execution 语义：Responsibility、Work、Run、Decision、Mandate、Authorization、capability invocation、durable provider attempt、reconciliation 和 recovery。

它不拥有 employee onboarding、invoice matching、canary/release 等 domain lifecycle，也不把 provider success 当作 domain Outcome。Domain Controller 必须独立读取现实并判断自己的 postcondition。

## Responsibility 与 Domain Controller

Standing Responsibility 有稳定 identity、principal、subject、domain、scope 和 lifecycle。Discharge 需要先有带 basis 的 satisfied assessment，再有明确适用于该 transition 的 durable Decision。

`DomainAssignment` 是 bounded delegation，不是 Work 或 Authorization。`DomainReport` 保存 Controller 到 Runtime 的 progress/evidence/outcome-candidate/completion lineage；completion proposal 不会自动 discharge Responsibility。

## Work、Mandate 与 Authorization

Work 只能在 current active Responsibility 下 admit。Work/Run 是执行记录，不是业务 obligation 或 domain outcome。

Mandate 建立 delegated scope；Authorization 绑定 principal、action、resource、mandate、decision 和条件。拥有 Authorization 仍不能证明 effect 已发生。

## Durable effect identity

Fresh effectful invocation 必须提供 durable `idempotency_key`，并在 provider dispatch 前绑定 semantic request fingerprint。Fingerprint 覆盖 capability、Work/Run、principal/resource、input、parameter/constraint、metadata、step identity、subject version 和 effect class。

同一 durable identity 不能绑定另一份不同 semantic request；identity rebound 必须 fail closed。

Runtime 在越过 provider boundary 前先记录 durable provider attempt。Lost acknowledgement 后不能重新 dispatch；只能针对历史 provider/target 做 exact reconciliation。Reconciled provider result 仍只是 execution fact。

## Canonical provider boundary

`WorldRuntime.invoke()` 是唯一允许跨 capability provider/reality boundary 的 Runtime 路径。`ExecutionService` 只负责 Work/Run、fencing 和 invocation qualification，不直接 dispatch provider。

Public capability/command schema 是 closed schema。未声明字段在 mutation/invocation 前拒绝；provider-specific executable input 必须进入 contract 已声明字段，并被 durable effect identity 覆盖。

## Trust 与 reality boundary

Authenticated identity、delegation、Decision、Mandate、Authorization 是不同层。Authority-bearing write 必须绑定当前有效 principal/authority。

Reality-changing dispatch 还需要 durable identity 和 single-use start fence。Started 或 ambiguous effect 可以 reconcile，不能 blind redispatch。

## Shared durability

Organization-grade ledger 必须保证：

- event/projection 原子 transaction；
- database-level expected-version CAS；
- 每个 durable effect identity 只有一个 fresh provider-attempt winner；
- Run lease 有 database fencing；
- Domain-effect start 有 database fencing；
- StateBundle 可以 backend-neutral export/import。

SQLite 是 local reference backend；PostgreSQL 是 shared backend，并通过 physical backup/restore 验证 durable state。

## 演进规则

Epistemic/cognition/memory/strategy 可以是 Runtime primitive，但不能形成第二个 universal semantic ontology。

Externally observable contract semantics 变化才创建新 contract version；内部 refactor 不创建新版本。
