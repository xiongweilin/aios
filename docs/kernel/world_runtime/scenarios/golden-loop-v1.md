# Golden semantic loop v1

The canonical architecture scenario is:

```text
Mandate
  -> Evidence / Claim / Belief
  -> Decision
  -> Goal
  -> StandingResponsibility
  -> DomainAssignment
  -> Work / Run
  -> Authorization
  -> external effect
  -> Domain OutcomeCandidate
  -> new Evidence
  -> Belief revision
  -> StrategyAssessment
  -> Responsibility discharge
```

Acceptance properties:

- every durable object has one canonical owner;
- provider success is not promoted to a domain Outcome;
- Domain Controller outcome lineage is durable through `DomainReport`;
- a process restart preserves Mandate, belief, assignment, responsibility, and strategy state;
- replaying the same idempotent effect after restart does not cross the reality boundary again;
- an Outcome can be traced back to its assignment, responsibility, goal, decision, evidence basis,
  and mandate.

The executable acceptance test is `tests/test_golden_semantic_loop.py`.
