# V1 operator 与 requirement contract

> 权威英文原文：[operator-contract.md](operator-contract.md)。状态：implemented contract，最后审查 2026-09-19。

本文件定义 Autonomous Development control plane 与 operator adapter 之间的 provider-neutral contract。Provider-specific message/user identifier 不存入 core domain；adapter 将其映射为 durable `request_id`，只发送 normalized request。

## Requirement lifecycle

`DevelopmentRequest` 是 immutable input。修改 requirement 会创建新 request，不会原地覆盖 `normalized_requirement_text` 或 `content_sha256`。

```text
received -> analyzing -> ready -> running -> completed
                                      |-> rolled-back
                                      |-> failed
                                      |-> cancelled
             -> needs-human --response--> ready
```

Request 保存 source label、external reference digest、title、normalized text、content digest、target ID、cycle ID、pending intervention ID、workflow attempt 和 active DBOS workflow ID。完整 requirement 保存在 request row；event payload 只携带 ID、digest 和 bounded summary。

`RequirementAnalysis` 由 read-only Codex turn 生成。其 bounded field 包括 summary、requirement acceptance criteria、requested path、expected behavior、risk、missing information、ambiguity 和 validation expectation。Mechanical policy validation 才是 authoritative：越界 path、forbidden path、缺失 baseline/contract recovery 或 material ambiguity 都必须进入 `HumanIntervention`，不能扩大 policy。

Actionable analysis 生成一个 deterministic `ChangeProposal`，绑定 current serving release、active objective revision、objective acceptance criteria、validated requested paths、forbidden paths、changed-file budget、attempt budget 和 contract gates。

Implementation、verification、build、deployment、k6、canary、promotion、rollback、soak 和 cleanup 继续由现有 `AutonomousIterationWorkflow` 与 `PostPromotionSoakWorkflow` 拥有。`RequirementAutonomyWorkflow` 只准备 cycle、委托既有 workflow，并写 terminal operator event。

## Local operator API

API 只绑定现有 loopback control plane `127.0.0.1:8765`，不是 public/LAN interface。

| Method | Path | 用途 |
|---|---|---|
| POST | `/v1/operator/requirements` | 提交 immutable normalized requirement；同 ID/内容幂等，内容冲突返回 409 |
| GET | `/v1/operator/requirements/{request_id}` | 读取 request/cycle/serving release/pending intervention |
| POST | `/v1/operator/requirements/{request_id}/start` | claim 一个 workflow identity 并立即返回；DBOS 后台运行 |
| POST | `/v1/operator/requirements/{request_id}/cancel` | 只在尚未进入 unsafe-to-cancel running cycle 前取消 |
| POST | `/v1/operator/interventions/{intervention_id}/responses` | 关闭 open intervention；同答案 replay 安全，改写答案被拒绝 |
| GET | `/v1/operator/events?after=N&limit=M` | 读取 durable monotonic outbox cursor；`limit <= 500` |
| POST | `/v1/operator/events/{event_id}/ack` | adapter 成功发送通知后 ACK |

Wire JSON 使用 camelCase。Human requirement 必须进入此 contract，不能被当作 `UserFeedback`。

## HMAC transport

Bridge/control plane 使用独立 operator HMAC secret，不能复用 gateway notification、administrative、user、control-plane 或 provider credential。

每个 request 包含 `X-Operator-Timestamp`、`X-Operator-Signature` 和 endpoint-specific identity。Canonical signed bytes：

```text
timestamp
request-or-event-id
UPPERCASE-METHOD
path[?canonical-query]
sha256(body-bytes)
```

默认 TTL 300 秒。Durable request ID、immutable content digest、workflow ID、event ID 和 ACK state 保证 retry/replayed provider delivery 幂等；同 identity 不同内容必须拒绝。

## Durable outbox

Application database 持有 `operator_events`。重要 event：`requirement_received`、`requirement_ready`、`development_started`、`needs_human`、`completed`、`rolled_back`、`failed`、`cancelled`。

Event sequence 单调递增。Bridge 只有 provider send 成功并显式 ACK 后才推进自身 cursor。Bridge outage 只能延迟通知，不能让 development workflow 失败或 rollback。
