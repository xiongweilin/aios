# 语义清单与所有权

World Runtime 对每个 semantic concept 使用一个 canonical owner。Universal meaning 由 `semantic-language` 拥有；Runtime 拥有 durable lifecycle specialization；Domain Controller 拥有 domain-specific lifecycle、Outcome qualification、Acceptance 和 completion。

| Concept | Canonical owner | Durable |
| --- | --- | --- |
| Claim / Evidence / Unknown / Conflict | semantic-language | yes |
| Goal / Constraint / Mandate | semantic-language | yes |
| Decision / Authorization / Responsibility | semantic-language | yes |
| Effect / Outcome / Acceptance | semantic-language | yes |
| ClaimRevision / EvidenceAssessment / BeliefState | world-runtime/epistemics | yes |
| CognitiveControllerState | world-runtime/cognition | yes |
| Experience | world-runtime/memory | yes |
| StandingResponsibility | world-runtime/responsibility | yes |
| DomainAssignment / DomainReport | world-runtime/domains | yes |
| StrategyAssessment | world-runtime/strategy | yes |
| ResponsibilityRelation | world-runtime/responsibility | yes |
| StrategicIssue / StrategicOption / PortfolioProposal / StrategicPortfolio | world-runtime/strategy | yes |
| ResourceBudgetLine / ResourceAllocation | world-runtime/strategy | yes |
| QualificationDependency / ReviewObligation / RevalidationAssessment | world-runtime/qualification | yes |
| Work / Run / ProviderAttempt / ProviderResult | world-runtime/execution | yes |
| Domain Outcome qualification / Domain Acceptance | Domain Controller | yes |

规则：

1. 一个 semantic identity 可以被多个 subsystem 引用，但不能被复制成 subsystem-local substitute。
2. Projection state 是 derived state，不会变成第二个 semantic authority。
3. Runtime 可以保存 Domain Outcome reference 的 lineage，但不会制造或重新解释 domain Outcome。
4. Runtime 拥有 generic Responsibility topology，而不是 domain process graph。
5. StrategicOption evaluation 是 data/evidence，不是 Decision authority；Runtime 不拥有 universal utility function。
6. Qualification dependency 描述当前使用的 basis。Dependency change 创建 review work，而不是改写 historical subject。
8. Personal fact、UI projection、model-routing policy 和可复用 cognitive procedure 继续位于 Runtime 之外。
