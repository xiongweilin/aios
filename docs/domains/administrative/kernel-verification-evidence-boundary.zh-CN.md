# Kernel verification evidence boundary

Administrative Orchestrator 把明确 cut-over capability 的边界 physical execution 委托给 Agent Kernel，但不委托 business obligation authority。

## 所有权

Agent Kernel 拥有 execution/reality 一侧：

- materialized Kernel Work/Run identity；
- bounded provider execution；
- independent objective verification；
- canonical `domain-effect-verification-evidence-view-v1` read evidence；
- 绑定到该 evidence 的实际 `observed_postcondition` 和 verifier provenance。

Administrative Orchestrator 拥有 business 一侧：

- AdministrativeCase 和 authority epoch；
- governance basis 和 approval satisfaction；
- AdministrativeObligation 及其 frozen expected postcondition；
- observed reality 与 obligation 的 semantic comparison；
- ConfirmedOutcome creation；
- completion、reconciliation 或 reopen decision。

Kernel evidence view 明确是 non-authoritative。消费它不会把 Administrative obligation authority 转给 Kernel。

## Completion 不具传递性

以下事实刻意区分：

```text
Kernel execution status == COMPLETED
    != Kernel verification evidence as an Administrative observation
    != Administrative semantic verification == VERIFIED
    != Administrative ConfirmedOutcome
    != AdministrativeCase == COMPLETED
```

因此 completed Kernel execution receipt 本身不能 discharge Administrative obligation。

Cutover adapter 读取 Kernel 返回的精确 `evidence_ref`，验证 evidence 仍绑定 persisted Work/Run/Action lineage 和 frozen expected postcondition，然后才把 `observed_postcondition` 暴露为 Administrative verifier 的 `RealityObservation`。

Administrative Orchestrator 绝不从自己的 expected postcondition 重建 observed reality。

## Fail-closed behavior

对 Kernel-owned HRIS/IAM capability，legacy Administrative provider 不是 fallback execution/read-back path。

以下任一情况使 observation 保持 unknown：

- Kernel execution 尚未到达携带 evidence 的 terminal verification state；
- `evidence_ref` 缺失或 unknown；
- evidence endpoint unavailable 或返回 incompatible view；
- evidence Work/Run/Action identity 与 persisted projection rebound；
- evidence frozen expected postcondition 与 persisted domain intent rebound；
- evidence objective result 与 execution receipt 冲突。

这些 failure 可以触发 reconciliation，但不授权 local execution 或 local read-back。

## Reality mismatch

有效 Kernel evidence view 可以在结构和绑定上正确，但报告的现实仍不满足 Administrative obligation。

例如：

```text
Administrative expected:
  department_ref = department:engineering

Kernel independently observed:
  department_ref = department:finance
```

该 evidence 仍作为实际 observation 被消费。Administrative semantic verification 返回 mismatch，不创建 HRIS `ConfirmedOutcome`，case 按当前 onboarding state machine 进入 `REOPEN_REQUIRED`。HRIS/IAM legacy execute/observe call 继续禁止。

这就是预期边界：Kernel 拥有 reality observation；Administrative Orchestrator 拥有 business interpretation 和 obligation discharge。

## Durability

DBOS/PostgreSQL restart 后边界不变。Kernel-owned effect-to-obligation/governance link 和 execution lineage 从 durable Administrative storage 重载；completed Kernel receipt 仍必须通过 canonical verification evidence 解析后，才能确认 Administrative outcome。Restart 不会重新启用 legacy provider path。
