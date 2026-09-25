# Semantic inventory and ownership

World Runtime uses one canonical owner per semantic concept. Universal meaning is owned by
`semantic-language`; Runtime owns durable lifecycle specializations; Domain Controllers own
domain-specific lifecycle, Outcome qualification, Acceptance, and completion.

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

Rules:

1. One semantic identity is referenced by multiple subsystems; it is not copied into subsystem-local
   substitutes.
2. Projection state is derived state and does not become a second semantic authority.
3. Runtime may preserve lineage for a Domain Outcome reference, but it does not manufacture or
   reinterpret the domain Outcome.
4. Historical predecessor aliases are not retained after cutover unless an active consumer requires
   them.


Additional 1.0 ownership rules:

5. Runtime owns the generic Responsibility topology, not domain process graphs.
6. StrategicOption evaluation is data/evidence, not Decision authority; Runtime
   does not own a universal utility function.
7. Qualification dependencies describe the basis for current use. A dependency
   change creates review work rather than rewriting the historical subject.
8. Personal facts, UI projections, model-routing policy, and reusable cognitive
   procedures remain outside the Runtime.
