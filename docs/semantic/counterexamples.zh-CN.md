# 反例

只有在合并某个语义区分会造成 correctness failure 时，才把该区分提升为通用语义。

## Decision 不是 Authorization

机构可以决定购买设备，但实际行动的 principal 仍可能没有执行购买的 authority。记录 Decision 不能自动生成 Authorization。

## Effect 不是 Outcome

Deployment API 可能报告成功，但预期产品属性仍未变化。Provider success 和由此产生的 external Effect 都不能建立 domain Outcome。

## Responsibility 不是 Work

一个 standing responsibility 可能跨越多个 Work unit、retry、process restart 和 provider change。完成一个 Work item 不能解除 Responsibility。

## Evidence 不是 Claim

Telemetry record 是关于某个 proposition 的 evidence，它不会变成 proposition 本身。互相冲突的 evidence 必须能同时表示，而不是覆盖 Claim。
