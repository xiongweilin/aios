# Governed workflow authority contract

> 权威英文原文：[workflow-authority.md](workflow-authority.md)。本文件定义所有 Administrative case kind 共享的 authority path；noun 定义以 `domain-model.md` 为准。

## Entry

只有 authenticated ingress 或 authorized admission path 创建 `AdministrativeRequest` 和 durable `AdministrativeCase` 后，formal workflow 才开始。

```text
source event
→ IntakeReceipt / SourceArtifact / InterpretationRecord
→ candidate
→ IntakeAssessment
→ PromotionRecord
→ AdministrativeRequest
→ AdministrativeCase
```

Unstructured source material、candidate 和 interpretation 都不是 authority object。Direct authenticated request 可以直接进入 `AdministrativeRequest`，无需伪造 candidate chain。

## Main case states

```text
received
→ gathering_facts
→ ready_for_policy
→ awaiting_decision
→ authorized
→ executing
→ verifying
→ reconciling
→ completed
```

Cross-cutting：`waiting`、`reopen_required`、`failed`、`cancelled`。可以跳过状态，但只能因为对应 semantic requirement 不存在，不能因为 provider/transport 返回 success。

## External effect 前的 closure path

```text
current AdministrativeCase
→ current facts + provenance
→ current PolicyRef / PolicyEvaluation
→ current Principal / RoleAssignment / Delegation eligibility
→ Decision set
→ ApprovalSatisfaction (if required)
→ GovernanceBasis
→ AdministrativeObligationSet
→ ExecutionAuthorization
→ EffectRecord
→ World Runtime capability / Work / runtime authorization
→ physical RealityBoundary
```

每一步都是独立 qualification boundary。左侧对象存在不会自动授权创建右侧对象。

`GovernanceBasis` 冻结 fact/policy/organizational authority 依赖；`ExecutionAuthorization` 只在该 basis 仍 current 时授予精确 Administrative effect scope；World Runtime 再单独持有 physical execution 的 runtime authorization。

## Actor / semantic owner

- transport authentication：只证明 source identity，不证明 content truth；
- intake：artifact != interpretation；
- model/parser：interpretation != candidate authority；
- admission：admission != authoritative fact；
- approved fact owner：claim != authoritative observation；
- policy plane：policy definition != evaluation；
- identity plane：external subject != Principal；
- authority plane：eligibility != Decision；
- Decision：business judgment，不等于 approval satisfaction；
- Governance：approval != still-current basis；
- obligation：effect plan != obligation set；
- Administrative server：ExecutionAuthorization != Runtime Authorization；
- World Runtime：obligation/commitment != Work；ambiguous execution != retry permission；
- independent verifier：provider success != verification；
- Administrative verifier：Runtime evidence != ConfirmedOutcome；
- completion evaluator：outcome != completion；
- Runtime responsibility protocol：case complete != responsibility discharged。

## Revalidation / failure rules

Fact、policy、identity binding、role/delegation、approval、authority epoch 或 transaction qualification 变化时，旧 basis 必须重新 qualification；不能只因为 provider 仍可能成功就复用 stale authority。

Unknown result 进入 reconciliation，不获得 resend permission。External reality 必须通过独立 read-back 验证。Completion 只在 obligation set 被满足后成立；responsibility discharge 仍需要独立 assessment/Decision/transition。
