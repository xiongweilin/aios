# Golden semantic loop v1

规范架构场景：

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

Acceptance 属性：

- 每个 durable object 只有一个 canonical owner；
- provider success 不会被提升为 domain Outcome；
- Domain Controller 的 outcome lineage 通过 `DomainReport` 持久保存；
- process restart 后 Mandate、belief、assignment、responsibility 和 strategy state 仍保留；
- restart 后 replay 同一个 idempotent effect 不会再次跨越 reality boundary；
- Outcome 可以追溯到 assignment、responsibility、goal、decision、evidence basis 和 mandate。

可执行 acceptance test 为 `tests/test_golden_semantic_loop.py`。
