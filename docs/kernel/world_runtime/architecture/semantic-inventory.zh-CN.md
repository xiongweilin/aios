# 语义清单与所有权

World Runtime 将 universal role vocabulary 与具体 payload ownership 分开。

`semantic-language` 只拥有封闭的跨领域 role set 与 non-substitution rule。
Runtime subsystem 与 Domain Controller 拥有具体 schema、lifecycle、persistence 和 policy。

| Concept / role | Role vocabulary owner | Concrete payload owner | Durable |
| --- | --- | --- | --- |
| Claim / Evidence / Unknown | semantic-language | world-runtime/epistemics | yes |
| Decision | semantic-language | world-runtime/decisions | yes |
| Authorization | semantic-language | world-runtime/governance | yes |
| Responsibility | semantic-language | world-runtime/responsibility | yes |
| Revision | semantic-language | world-runtime/lineage | yes |
| Effect | semantic-language | world-runtime/execution / effect boundary | yes |
| Outcome | semantic-language | Domain Controller | yes |
| Goal | owner-local namespace | world-runtime/strategy | yes |
| Mandate | owner-local namespace | world-runtime/governance | yes |
| Conflict | owner-local namespace | world-runtime/epistemics | yes |
| ClaimRevision / EvidenceAssessment / BeliefState | owner-local namespace | world-runtime/epistemics | yes |
| CognitiveControllerState | owner-local namespace | world-runtime/cognition | yes |
| Experience | owner-local namespace | world-runtime/memory | yes |
| DomainAssignment / DomainReport | owner-local namespace | world-runtime/domains | yes |
| StrategyAssessment | owner-local namespace | world-runtime/strategy | yes |
| ResponsibilityRelation | owner-local namespace | world-runtime/responsibility | yes |
| StrategicIssue / StrategicOption / PortfolioProposal / StrategicPortfolio | owner-local namespace | world-runtime/strategy | yes |
| ResourceBudgetLine / ResourceAllocation | owner-local namespace | world-runtime/strategy | yes |
| QualificationBinding / ReviewCase | owner-local namespace | world-runtime/qualification | yes |
| Work / Run / ProviderAttempt / ProviderResult | owner-local namespace | world-runtime/execution | yes |
| Domain Acceptance / completion | owner-local namespace | Domain Controller | yes |

规则：

1. Universal role meaning 不等于 payload ownership。
2. 一个 concrete semantic identity 只有一个 payload owner；其他 subsystem 通过引用使用它，不复制出竞争 owner model。
3. Projection state 是 derived state，不会变成第二个 semantic authority。
4. Runtime 可以保存 Domain Outcome reference 的 lineage，但不会制造或重新解释 domain Outcome。
5. Runtime 拥有 generic Responsibility topology，而不是 domain process graph。
6. StrategicOption evaluation 是 evidence/context，不是 Decision authority；Runtime 不拥有 universal utility function。
7. QualificationBinding 记录当前使用依赖；dependency change 打开一个 ReviewCase，而不是改写 historical subject。
8. Review assessment 与 review resolution 是同一个 durable ReviewCase 上的两个不同 transition。
9. Personal fact、UI projection、model-routing policy 和可复用 cognitive procedure 不进入 Runtime semantic inventory。
