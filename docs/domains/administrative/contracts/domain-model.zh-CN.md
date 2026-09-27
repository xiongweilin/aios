# Administrative domain model

> 权威英文原文：[domain-model.md](domain-model.md)。本中文版保留核心 noun、ownership 与 non-substitution rule；字段级完整定义以英文原文为准。

## Perception / admission

- `IntakeReceipt`：接收事件的 durable transport record。
- `SourceArtifact`：immutable source material。
- `DocumentRepresentation`：parser/OCR/extractor 生成、带独立 provenance 的 representation。
- `EvidenceSpan`：source/representation 中的 bounded evidence reference。
- `InterpretationRecord`：对 source 的解释，不是 truth。
- Candidate：可被评估是否进入 formal model 的候选。
- `IntakeAssessment`：admit/reject/review 判断。
- `PromotionRecord`：candidate + assessment → formal request/case 的 durable lineage。

```text
Candidate != AdministrativeRequest
model confidence != admission authority
admission != fact authority
Administrative admission != Runtime Work admission
```

## Request / case / facts

`AdministrativeRequest` 是 formal trigger；`AdministrativeCase` 是跨 process、conversation、model、retry、provider session 存续的 durable matter。

`case_id` 是 stable identity；`version` 是 state/concurrency version；`authority_epoch` 是 authority-sensitive invalidation clock。

`EvidenceRef` 是带 source/fact owner/observation time/version/digest 的 bounded reference。

`FactAssertion` authority class：

- `CLAIM`：已声明但未独立建立；
- `ATTESTED`：按明确程序由 eligible source 接受的 testimony；
- `AUTHORITATIVE`：来自 approved system/owner 的 observation。

`FactSnapshot` 是某一历史时点 case 所依赖事实的 immutable projection。

## Identity / policy / authority

- `Principal`：Administrative 认可的 actor identity；transport subject/email/speaker label 不自动是 Principal。
- `IdentityBinding`：外部 identity 到 Principal 的 time-bounded mapping，只解决“是谁”，不解决“能决定什么”。
- `RoleAssignment`：组织 scope 内的 time-bounded role。
- `Delegation`：有边界的 role-use eligibility 转移，不是 Decision 或 effect authorization。
- `PolicyRef`：immutable policy version/context。
- `PolicyEvaluation`：把 current facts 应用于 policy。
- `Decision`：Principal 对精确 case version、authority epoch、policy、role 和 scope 的 bounded judgment；不是 execution authorization。
- `ApprovalSatisfaction`：满足 required role/quorum/distinct-principal 的 durable proof。
- `GovernanceBasis`：冻结 current facts、policy、scope、Principal/role/delegation、approval、epoch 和适用 transaction qualification。
- `ExecutionAuthorization`：Administrative server 生成的 exact-scope effect authorization，与 World Runtime runtime authorization 分开。

## Obligation / effect / outcome

`AdministrativeObligationSet` 冻结当前业务完成要求。`AdministrativeObligation` 可以要求 domain-state verification 或 external-effect verification。

`EffectRecord` 表示有 authority 的 business effect intent/lineage，不代表外部现实已改变。

`EffectRealizationAssessment` 使用 independent read-back 判断现实；`ConfirmedOutcome` 只在 domain verifier 建立 semantic postcondition 后生成。

`CompletionAssessment` 根据 immutable obligation set 和 verified outcome/domain state 判断 case 是否完成。

```text
EffectRecord != effect realized
provider success != ConfirmedOutcome
ConfirmedOutcome != case completion
case completion != responsibility discharge
```

## Commitment / communication / investigation

Commitment 是 durable responsibility proposal，不是 Work 或 execution authority。Communication draft/effect/delivery/read state 分离；`transport_accepted != delivery_confirmed != human_read`。

Investigation/reframing object 只提供 domain reasoning/evidence；不能创建 fact、authority、Decision、effect、Outcome 或 completion。

## 历史与 reopening

Correction、reassessment、reopen、reconciliation 和 responsibility discharge 都通过新增 durable record/state transition 保留历史，不删除旧 Decision、effect、evidence 或 outcome lineage。

任何字段级 schema、enum、identity、migration compatibility 和完整 object contract 以英文原文为准。
