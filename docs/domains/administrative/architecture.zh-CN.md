# Administrative Architecture

> 权威英文原文：[architecture.md](architecture.md)。本中文版保留当前架构边界、所有权和不可替代规则。

`administrative-orchestrator` 是 external Domain Controller。架构按 semantic ownership 组织，而不是按 process topology 或历史 milestone 组织。

## 1. 系统边界

Administrative 拥有 organizational meaning：source lineage、fact、policy、authority、obligation、intended business effect、authoritative verification、Outcome、completion 和 reopen。

World Runtime 拥有 generic persistent agency 和 execution。

```text
organizational reality
        ↓
Administrative
  perception / admission / case
  facts / policy / authority
  GovernanceBasis / obligations
  ExecutionAuthorization / EffectRecord
        ↓
World Runtime
  Responsibility / Work / Run
  Decision / Mandate / Authorization
  durable attempt / provider / reconciliation
        ↓
external systems
        ↓
Administrative
  authoritative read-back
  EffectRealizationAssessment
  ConfirmedOutcome
  completion / reopen
```

DBOS 负责 durable scheduling；transport/provider adapter 只负责外部交互。二者都不是 business authority 或 completion owner。

## 2. Administrative semantic plane

Perception/admission 链：

```text
provider/source event
→ IntakeReceipt
→ SourceArtifact
→ DocumentRepresentation
→ EvidenceSpan
→ InterpretationRecord
→ Candidate*
→ IntakeAssessment
→ PromotionRecord
→ AdministrativeRequest / AdministrativeCase
```

Source authenticity != content truth。Interpretation/candidate != authoritative fact。

Case/fact/policy/authority 链：

```text
FactSnapshot
→ PolicyEvaluation
→ Principal / RoleAssignment / Delegation
→ Decision
→ ApprovalSatisfaction
→ GovernanceBasis
```

`AdministrativeCase.version` 处理 state/history concurrency；`authority_epoch` 使 authority-sensitive closure 失效。执行和 completion 前必须 revalidate governance dependency。

Obligation/effect intent 链：

```text
AdministrativeObligationSet
  ├─ DOMAIN_STATE_VERIFIED
  └─ EXTERNAL_EFFECT_VERIFIED
          ↓
ExecutionAuthorization
          ↓
EffectRecord
```

Administrative `ExecutionAuthorization` 是 business authorization，不是 Runtime Authorization。`EffectRecord` 是 intent/lineage，不是 reality proof。

## 3. World Runtime plane

External effect 通过 `integrations/world_runtime.py` 建立：

```text
Responsibility
→ Work
→ Run
→ Decision
→ Mandate
→ Runtime Authorization
→ CapabilityRequest
→ durable provider attempt
→ provider invocation
```

Runtime 拥有 generic agency/execution primitive，不拥有 Administrative obligation、HR/finance semantics、`ConfirmedOutcome` 或 case completion。

## 4. Reality return path

```text
provider invocation
→ external reality
→ independent Administrative read-back
→ EffectRealizationAssessment
→ ConfirmedOutcome
→ CompletionAssessment
```

Provider success != `ConfirmedOutcome`。Reality 无法建立时，case 保持 waiting/unknown 或进入 governed reconciliation/reopen；timeout/retry count 不会把 unknown 变成 success。

## 5. Responsibility、commitment 与 communication

Business obligation 与 generic standing Responsibility 相关但不相同。Case completion 可以成为 responsibility discharge 的 evidence，但不是 discharge event。

Qualified self-commitment 进入 formal Administrative state，并可获得 Runtime standing Responsibility；创建 commitment 不自动创建 external effect。

Communication 必须保持：

```text
transport_accepted != delivery_confirmed != human_read
```

Runtime provider result 最多证明 execution acceptance；Administrative read-back 持有 delivery qualification。

## 6. Employee、financial、reconciliation 与 reopen

Onboarding、offboarding、procurement、invoice/AP preparation、expense reimbursement 共享同一 authority/obligation/effect/verification language。Domain Controller 决定成功 postcondition；Runtime 只执行 bounded capability。

```text
OUTCOME_UNKNOWN != retry permission
REOPEN_REQUIRED != execution authorization
compensation != hidden rollback
```

Ambiguous provider attempt 需要 matching durable Runtime identity 和 terminal reconciliation result；arbitrary string/model opinion 不是证据。

Reopen 推进 `authority_epoch`、保留历史并要求 fresh governance。

## 7. Cognition、repository 与历史边界

Administrative investigation 是 bounded domain workflow。Cognition output 不能生成 fact、authority、Decision、Work、effect 或 completion。

当前 topology 没有独立 authoritative `meta-controller`。

Historical migration name、acceptance record、tag、policy ID 或 ADR text 可以为了 replay/evidence 保留 predecessor vocabulary；新代码和当前运行语义统一使用 World Runtime vocabulary。

## 当前核心 invariant

```text
Authentication != Administrative authority
Source authenticity != content truth
Interpretation != authoritative fact
Candidate != formal Administrative state
External identity != Principal
Decision != ApprovalSatisfaction
ApprovalSatisfaction != GovernanceBasis
GovernanceBasis != ExecutionAuthorization
ExecutionAuthorization != Runtime Authorization
AdministrativeObligation != Runtime Work
EffectRecord != external reality
Provider success != ConfirmedOutcome
Runtime execution result != Administrative semantic outcome
OUTCOME_UNKNOWN != retry permission
Case completion != responsibility discharge
Investigation != authority
ReframingProposal != reframe
Reopen != history deletion
```
