# Semantic inventory and ownership

World Runtime separates universal role vocabulary from concrete payload ownership.

`semantic-language` owns the closed cross-domain role set and non-substitution
rules. Runtime subsystems and Domain Controllers own concrete schemas, lifecycle,
persistence, and policy.

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
| CognitiveEpisode | owner-local namespace | world-runtime/cognition | yes |
| Experience | owner-local namespace | world-runtime/memory | yes |
| DomainAssignment / DomainReport | owner-local namespace | world-runtime/domains | yes |
| StrategyAssessment | owner-local namespace | world-runtime/strategy | yes |
| ResponsibilityRelation | owner-local namespace | world-runtime/responsibility | yes |
| StrategicIssue / StrategicOption / PortfolioProposal / StrategicPortfolio | owner-local namespace | world-runtime/strategy | yes |
| ResourceBudgetLine / ResourceAllocation | owner-local namespace | world-runtime/strategy | yes |
| QualificationBinding / ReviewCase | owner-local namespace | world-runtime/qualification | yes |
| Work / Run / ProviderAttempt / ProviderResult | owner-local namespace | world-runtime/execution | yes |
| Domain Acceptance / completion | owner-local namespace | Domain Controller | yes |

Rules:

1. Universal role meaning is not the same thing as payload ownership.
2. A concrete semantic identity has one payload owner; other subsystems reference it rather than copying it into competing owner models.
3. Projection state is derived state and does not become a second semantic authority.
4. Runtime may preserve lineage for a Domain Outcome reference, but it does not manufacture or reinterpret the domain Outcome.
5. Runtime owns generic Responsibility topology, not domain process graphs.
6. StrategicOption evaluation is evidence/context, not Decision authority; Runtime does not own a universal utility function.
7. A QualificationBinding records a current-use dependency. A dependency change opens one ReviewCase rather than rewriting the historical subject.
8. Review assessment and review resolution are distinct transitions on the same durable ReviewCase.
9. Personal facts, UI projections, model-routing policy, and reusable cognitive procedures remain outside the Runtime semantic inventory.

10. Reference conformance runners are not Runtime payload owners. Public conformance vectors remain contract data; executable behavior is validated through the owning Runtime subsystem tests.
