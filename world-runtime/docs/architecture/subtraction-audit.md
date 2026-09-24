# Semantic ownership audit

The Runtime keeps semantic owners separate even when implementation shapes look similar.

## Current owners

- `ClaimRevision`, `EvidenceAssessment`, and `BeliefState`: epistemics.
- cognitive search/closure/revision state: cognition.
- `StandingResponsibility`: responsibility.
- `DomainAssignment` and `DomainReport`: domains.
- `Work`, `Run`, provider attempts/results: execution.
- `StrategyAssessment`: strategy.

## Non-merges

Objects sharing a suffix such as `Assessment` are not merged unless their meaning and authority
are identical. Epistemic assessment, responsibility assessment, and strategy assessment answer
different questions and retain separate lifecycle owners.

The reduction target is zero duplicate semantic authority, not zero repeated implementation shape.
