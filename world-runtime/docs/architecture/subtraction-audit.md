# Semantic subtraction audit

This stage removes predecessor-era compatibility and records what intentionally remains.

## Deleted

- `BeliefVerdict.REJECTED` alias for `UNSUPPORTED`.
- `BeliefVerdict.CONFLICTED` alias for `DISPUTED`.
- any requirement for Domain Controllers to infer a bounded assignment from generic Work.

## Retained with explicit owners

- `ClaimRevision`, `EvidenceAssessment`, and `BeliefState`: epistemics.
- cognitive search/closure/revision state: cognition.
- `StandingResponsibility`: responsibility.
- `DomainAssignment` and `DomainReport`: domains.
- `Work`, `Run`, provider attempts/results: execution.
- `StrategyAssessment`: strategy.

## Explicit non-merges

Objects sharing a suffix such as `Assessment` are not merged unless their meaning and authority
are identical. Epistemic assessment, responsibility assessment, and strategy assessment answer
different questions and retain separate lifecycle owners.

The reduction target is zero duplicate semantic authority, not zero repeated implementation shape.
