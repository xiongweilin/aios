# administrative-orchestrator

> AIOS domain 组件。权威英文原文：[README.md](README.md)。源码：`src/domains/administrative_orchestrator/`；Runtime：根目录 `compose.yaml`。

本组件作为 `world-runtime` 的 external Domain Controller，负责受治理的行政自动化。

它拥有 Administrative 语义：可信 intake、organizational authority、business obligation、effect intent、authoritative read-back、domain Outcome、completion、reconciliation qualification、commitment、communication 和 governed reopen；不拥有 generic persistent agency runtime。

## 当前执行拓扑

```text
organizational request / evidence
        ↓
Administrative domain
  facts / policy / authority
  GovernanceBasis
  AdministrativeObligationSet
  ExecutionAuthorization
  EffectRecord
        ↓
World Runtime
  Responsibility
  Work / Run
  Decision / Mandate / Authorization
  durable provider attempt
  provider invocation / reconciliation
        ↓
external system reality
        ↓
Administrative independent read-back
  EffectRealizationAssessment
  ConfirmedOutcome
  CompletionAssessment
  responsibility discharge / reopen
```

Provider success 只是 execution fact，不能证明 domain Outcome 或 case completion。

## 所有权

Administrative 拥有 request/case、immutable fact provenance、identity projection、role/delegation/policy、Decision/approval satisfaction、`GovernanceBasis`、business obligation、Administrative `ExecutionAuthorization`/`EffectRecord`、domain-specific verification/`ConfirmedOutcome`/completion/reopen，以及 employee lifecycle、financial transaction、commitment 和 communication semantics。

World Runtime 拥有 persistent responsibility、generic Work/Run、generic Decision/Mandate/Authorization、capability contract、provider selection/invocation、durable provider-attempt identity、idempotent replay、ambiguous-result reconciliation、generic execution evidence 和 persistent runtime state。

DBOS 负责 durable workflow scheduling/wait/replay；external system 继续是其现实状态的 authoritative owner。

## Non-substitution invariant

```text
Source authenticity != content truth
Interpretation != authoritative fact
Candidate != AdministrativeRequest
Decision != ApprovalSatisfaction
ApprovalSatisfaction != GovernanceBasis
GovernanceBasis != ExecutionAuthorization
ExecutionAuthorization != Runtime Authorization
AdministrativeObligation != Runtime Work
EffectRecord != external reality
Provider success != ConfirmedOutcome
OUTCOME_UNKNOWN != retry permission
Case completion != responsibility discharge
transport_accepted != delivery_confirmed
delivery_confirmed != human_read
Investigation != authority
ReframingProposal != reframe
Reopen != history deletion
```

这些是产品 invariant，不是命名约定。

## World Runtime 边界

Production boundary 位于 `src/domains/administrative_orchestrator/integrations/world_runtime.py`。Administrative 把受治理 effect 编译为：

```text
Responsibility
-> Work
-> Run
-> Decision
-> Mandate
-> Runtime Authorization
-> capability invocation
```

Runtime 在跨 provider boundary 前记录 provider attempt。Lost acknowledgement 因此进入同一 durable identity 下的 reconciliation，而不是获得重新发送权限。Administrative 仍执行独立 authoritative read-back，并拥有最终 business Outcome。

## 当前覆盖范围

当前包括 employee onboarding/offboarding、HRIS/IAM refresh 与 lifecycle effect、procurement、invoice/AP preparation、expense reimbursement、meeting self-commitment、explicit responsibility discharge、governed internal communication、bounded investigation/reframing/reopen、Operations API、PostgreSQL/DBOS durability 和 Runtime-state DR。

不声称拥有 payment/settlement authority、human-read proof、delegated commitment assignment 或 unrestricted autonomous administration。

Repository verification 由 AIOS 根 CI workflow 持有。
