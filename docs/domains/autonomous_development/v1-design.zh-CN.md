# V1 Design — Autonomous Development Closed Loop

> 权威英文原文：[v1-design.md](v1-design.md)。状态：implementation acceptance candidate；Scope：V1；最后审查：2026-09-19。逐字段、逐状态和完整 acceptance table 以英文原文为准。

## 目标

V1 要证明：一个边界明确的软件/Agent 产品可以接收 human-owned requirement，由 Codex 实现和验证，形成 immutable build，部署为 candidate，经过 offline gate、canary、promotion/rollback 和 post-promotion soak，再利用可归因的 user feedback 与 runtime evidence 进入下一轮，而不需要人逐次决定具体代码改动。

```text
Requirement / Product Objective
→ Current ReleasedVersion
→ Traffic + Telemetry + Explicit Feedback
→ Evidence Window
→ Diagnosis
→ ChangeProposal
→ Isolated Worktree
→ Codex Implementation
→ Deterministic Verification + Codex Review
→ Immutable Build
→ Candidate Deployment
→ Offline Eval + Performance Gate
→ Canary 10% → 50% → 100%
   └─ hard regression → rollback/reject
→ Promotion
→ Post-promotion Soak
→ New ReleasedVersion
→ next evidence window
```

## 非目标

V1 不自建 coding/shell/repository-understanding agent；不让 Codex 持有 production credential 或 release authority；不自主改变 top-level product objective；不自主修改 autonomous-development 自身；不以单一 LLM judgment 决定 promotion；不要求 Kubernetes；不承诺 defect-free software。

## 所有权

Codex 负责候选 workspace 内的工程执行：inspect、reproduce、edit、test、local check、review remediation。

Autonomous Development 持有：

- development cycle 的原因和范围；
- evidence attribution；
- allowed/forbidden path 与 mutation budget；
- authoritative source/worktree revision；
- mandatory verification；
- build artifact identity；
- deployment/traffic identity；
- feedback-to-version binding；
- canary/promotion/rollback；
- `ReleasedVersion` 与 recovery。

Codex output 始终是 candidate，不是 release authority。

World Runtime 只在现实副作用边界提供 generic Responsibility/Work/Run/Decision/Mandate/Authorization/effect identity；Git、worktree、build、deployment、canary、promotion、rollback 和 ReleasedVersion 的 domain semantics 继续属于 Autonomous Development。

## Non-substitution invariants

```text
UserFeedback != ProductObjective
TelemetryObservation != Diagnosis
Diagnosis != ChangeAuthorization
CodexOutput != VerifiedChange
TestsPassed != ReleaseCandidate
BuildSucceeded != DeployableArtifact
DeploymentHealthy != ProductImproved
MetricImprovement != PromotionAuthority
CanaryCompleted != ReleaseFinalized
GitCommit != ReleasedVersion
ProviderSuccess != VerifiedExternalState
RetryableFailure != RetryPermission
```

## 小变更与机械 gate

每个 target 定义 allowed/forbidden paths、最大 scope、dependency policy、attempt/wall-clock/Codex budget 和 stop/escalation conditions。超预算 candidate 进入 BLOCKED，不能静默扩 scope。

可 deterministic 检查的内容必须由工具完成，例如 schema、import/layer boundary、lint/type、unit/integration、coverage、vulnerability/secret scan、image scan、health/readiness、performance、canary error/latency、artifact identity 和 feedback/version binding。

Codex review 只是补充 evidence，不能替代这些 gate。

## Durable lifecycle

Requirement、Diagnosis、ChangeProposal、candidate workspace、verification evidence、build artifact、deployment、canary、promotion/rollback、ReleasedVersion 和 feedback attribution 都有独立 durable identity。

Workflow interruption 依赖 durable state 恢复；external effect 依赖 stable operation identity 与 reconciliation，不能把 workflow retry 当作 effect retry permission。

Candidate failure、verification failure、deployment failure、canary regression、ambiguous external result 和 rollback 都保留历史，不能通过重试覆盖。

## Release gate

Build artifact 必须绑定 source revision 与 verification evidence。Candidate 先经过 offline eval/performance/security gate，再进入明确的 partial traffic exposure。

Hard regression 进入 rollback/reject。未满足 promotion criteria 时不能因为“看起来更好”扩大 traffic。

Canary 完成后还需要 post-promotion soak，因此 `CanaryCompleted != ReleaseFinalized`。

## Feedback 与证据归因

Telemetry 和 explicit user feedback 必须绑定到实际 serving release/deployment/cycle。不同版本的 evidence 不得混用。

Offline eval、production metric、explicit feedback、deterministic check 和 review 是不同 evidence type，不能互相替代。

## Acceptance

V1 acceptance 必须建立：完整 closed loop、restart/recovery、scope/budget enforcement、deterministic gate、artifact/deployment identity、progressive traffic、rollback、feedback attribution、promotion/soak，以及上述 non-substitution invariant。

完整 package layout、database schema、state enum、API、workflow step、failure matrix、threshold 和 acceptance scenario 以英文原文为权威。
