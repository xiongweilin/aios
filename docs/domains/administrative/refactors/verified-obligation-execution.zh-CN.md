# Verified obligation execution boundary

本次 closure 后重构提取 `VerifiedObligationExecutor`，作为 onboarding、offboarding 和 bounded financial transaction 已共享 execution mechanic 的 composition seam。

## 所有权

`VerifiedObligationExecutor` 只拥有 generic post-authorization lifecycle：

- execution / reconciliation / verification state progression；
- 通过 configured provider dispatch 已经规划的 effect；
- 对 ambiguous 或 unavailable read-back fail closed；
- realization evidence creation；
- 精确的 effect-to-confirmed-outcome recording；
- domain completion assessment 前收集 current outcome 和 realization。

它**不**拥有 domain interpretation。Planning、qualification、effect ordering 和 payload dependency、semantic reality verification、completion meaning、reopen policy、effective-time rule、transfer semantics 和 financial transaction semantics 继续以 hook 形式由现有 execution engine 持有。

`OnboardingExecutionEngine` 现在是 compatibility facade：它持有这些 hook，并把 `run`、generic dispatch、generic verification mechanic 委托给一个 `VerifiedObligationExecutor` instance。已有 offboarding 和 financial subclass 继续通过 `super()` 进入同一 lifecycle。

## Compatibility

变更刻意保留历史 public class surface：

```text
FinancialExecutionEngine(OnboardingExecutionEngine)
OffboardingExecutionEngine(OnboardingExecutionEngine)
```

Child module 和 public method 不变。Offboarding 仍用 effective-time qualification 包裹 `super().run()`，保持显式 effect ordering，用 continuity transfer fulfillment 扩展 verification，并持有 transfer-specific completion blocking。Financial execution 仍先验证 financial case kind，再通过 `super().run()` delegate。

Financial qualification waiting 继续由 `OnboardingExecutionEngine._require_financial_qualifications` / `FinancialQualificationPending` 解释；generic executor 不 import 或解释 financial qualification semantics。Offboarding effective-time qualification、Administrative domain-state fulfillment、continuity transfer 和 transfer-specific reopen behavior 继续由 `OffboardingExecutionEngine` 解释。

## Invariant

- 无 schema/migration change；
- 无 capability/Agent Kernel contract change；
- 无 provider retry-policy change；
- `OUTCOME_UNKNOWN` 仍需要 reconciliation，绝不授予 blind retry permission；
- provider success 仍不替代 verified reality；
- 精确 effect / realization / confirmed-outcome lineage 不变；
- obligation completion semantics 继续由 domain owner 持有；
- authority-epoch 和 governance revalidation 不变；
- stable effect/outcome/evidence identity 继续由既有 domain facade 生成；
- M5/M7/M8 accepted behavior 和 evidence 不被改写。

简化历史 inheritance hierarchy 明确不在范围。本变更只是把已证明的 generic lifecycle 移到 composition seam 之后，不改变 domain ownership 或 external execution-engine API。
