# 语义所有权审计

即使实现形态相似，Runtime 仍保持不同 semantic owner 分离。

## 当前 owner

- `ClaimRevision`、`EvidenceAssessment`、`BeliefState`：epistemics。
- cognitive search/closure/revision state：cognition。
- `StandingResponsibility`：responsibility。
- `DomainAssignment`、`DomainReport`：domains。
- `Work`、`Run`、provider attempt/result：execution。
- `StrategyAssessment`：strategy。

## 不合并规则

即使对象都带 `Assessment` 后缀，也只有在含义和 authority 完全相同时才合并。Epistemic assessment、responsibility assessment 和 strategy assessment 回答不同问题，并保持独立 lifecycle owner。

精简目标是“零重复 semantic authority”，而不是“零重复实现形态”。
