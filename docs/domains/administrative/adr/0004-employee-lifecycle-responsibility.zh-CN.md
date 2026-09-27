# ADR 0004 — Employee lifecycle responsibility

> 权威英文原文：[0004-employee-lifecycle-responsibility.md](0004-employee-lifecycle-responsibility.md)。状态：Accepted。日期：2026-09-10。

## 背景

M0–M6 已证明从非结构化组织输入到 trusted intake、candidate、human-confirmed admission、authoritative facts、policy、authority、obligation、Kernel-owned effect、independent verification 和 completion 的完整 Administrative vertical。M7 首次处理“既有关系终止”：关系失效、责任转移、历史保留、authority 在 qualified time 精确结束。

“Offboarding = 删除用户”是错误模型：它破坏 audit history、把 request/claim 与 authoritative truth 混同、无法表达 effective-time qualification，也无法承载未完成 continuity work。

## 决策

1. 新增唯一 case kind `employee-offboarding`，不拆新 repository。
2. Termination truth 只来自 authoritative HR source。Message 是 CLAIM，HRIS termination state/effective time 才是 authoritative。
3. Effective time 是 qualification，不是 delay。DBOS 可以 wait/wake，但 timer firing 不创造 authority；wake 后重新验证事实、policy、governance、identity、successor。
4. 三阶段：`SAFETY_REVOCATION` → `CONTINUITY_TRANSFER` → `EMPLOYMENT_FINALIZATION`。缺 successor 不得延迟安全 revocation；case 继续未完成。
5. Role/delegation 通过 validity 结束并追加 audit event，不删除历史。Departing principal 作为 delegation source/recipient 的两个方向都必须停止产生 current authority。
6. Transfer 是 typed requirement。Successor 必须 active、同 scope、policy-eligible、不同于 departing principal；消息中的名字不创造 authority。
7. External obligation 与 domain-state obligation 都是一等 fulfillment source；human attestation 不替代 material security proof。
8. Pre-effect governance basis 与 expected post-effect reality 分离；预期 self-induced change 不是 governance drift。
9. `case COMPLETED != responsibility DISCHARGED`。Discharge 需要 assessment、explicit Decision 和 lifecycle transition。
10. Kernel 只拥有 generic execution/authority seam；employee/termination/HRIS/IAM/successor 语义仍归 Administrative。
11. `execution_unknown` 不授权 retry，必须 exact historical reconciliation + independent verification。
12. Stale offboarding replay 不得作用于重新激活的新 employment episode；必要时增加显式 episode identity。

## 结果

M7 新增 durable model/migration，但保留 M0–M6 历史 migration/evidence。第二个 case kind 只推动最小必要的 obligation/completion/governance 泛化，不引入 universal workflow engine。
