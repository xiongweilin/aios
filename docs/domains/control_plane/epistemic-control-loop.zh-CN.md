# Epistemic repair loop

Control Plane 拥有 domain-local epistemic 和 repair loop。它不 import 或投影到 `world_runtime.cognition`。

World Runtime 继续拥有 universal durable Responsibility、DomainAssignment、Decision、governance 和 audit semantics。Control-plane loop 只通过 public HTTP contract 与其通信。

## Domain loop

```text
World Runtime Responsibility / DomainAssignment
    -> PersonalController
    -> RepairEpistemicProfile
       - RepairIssue
       - RepairTension
       - RepairCandidate
       - RepairSelfModel
       - RepairIntent
    -> bounded diagnosis (reason.generate)
    -> RepairClosure
    -> local DomainWork / DomainRun
    -> bounded concrete provider
    -> reality observation / verification
    -> RepairRevision
    -> close / wait / explicit reopen
    -> typed DomainReport
    -> World Runtime assessment / Decision / discharge
```

第一次 diagnosis 是 evidence-acquisition problem。当 reality 与当前 repair closure 冲突且 controller 被 reopen 时，profile 标记 candidate-space incompleteness 和 repeated-reopen tension。下一轮必须改变 working distinction，而不是重复相同 root-cause partition。

Line-ending cleanup 是 representation-revision 的具体例子：repository `dirty` state 单独不足以形成 semantic distinction。Domain 先区分 semantic content change 与 line-ending representation noise。

## Authority ceiling

整个 epistemic profile 不携带 authority。

```text
RepairIssue          -/-> truth
RepairCandidate      -/-> qualification
RepairIntent         -/-> universal Decision
RepairIntent         -/-> universal Authorization
RepairClosure        -/-> universal Responsibility
CapabilityBelief     -/-> capability authority
ProviderSuccess      -/-> target recovery
RepresentationChange -/-> effect authorization
```

Profile 可以决定 control-plane domain 下一步调查什么，但不能创建 universal semantic authority。

Effectful work 必须通过 domain controller 的 bounded work lifecycle 和 concrete provider boundary。Universal completion 单独报告给 World Runtime。

## Domain-local hard gate

Local controller 在 policy/execution seam fail closed：

- controller decision 绑定当前 controller/version；
- closure 需要 explicit basis、acceptance criteria、verification plan；
- 没有 active closure 不能 propose Work；
- revision 需要 observed work 或 verification reality；
- close 需要 verification evidence；
- failed diagnosis 进入 wait，而不是编造 closure；
- closed controller 不隐式 restart；
- owner follow-up 通过 explicit revision path reopen。

这些是 control-plane domain invariant，不是 universal Runtime semantics。

## World Runtime boundary

启动时，`WorldRuntimeClient` 验证精确 external contract surface：

```text
runtime protocol 4.0
semantic-language 0.2.0
request-authentication-v2
transition-authority-v1
read-authorization-v1
persistent-responsibility-v3
responsibility-assessment-v3
responsibility-discharge-v3
work-admission-v4
decision-record-v4
mandate-registration-v4
authorization-issue-v4
domain-effect-execution-v3
domain-assignment-v3
domain-report-v3
```

Mismatch fail closed。

Bridge 使用这些 contract：

1. 创建 universal Responsibility；
2. offer/accept DomainAssignment；
3. 本地运行 control-plane-specific lifecycle；
4. 提交 typed basis/evidence/outcome reference；
5. propose assignment completion；
6. request responsibility assessment；
7. 记录 universal Decision；
8. discharge universal Responsibility。

不 import 或 pin Runtime Python package。

## Persistence 与 restart

`DomainJournal` 只持久化 domain-local controller、work、run 和 observation state。

它可以跨 process restart 并 repair stale local execution claim，但不会重建 universal Responsibility、Decision、Evidence、Outcome、Goal、Authorization 或 Strategy state。

核心架构 invariant：

```text
rich domain semantics
!=
second universal semantic owner
```
