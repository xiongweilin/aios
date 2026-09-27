# ADR 0006 — Meeting commitment 与受治理的内部通信

状态：accepted

## 决策

M9 把 meeting transcript 视为 untrusted source material。Provider-neutral intake profile `meeting.commitment.v1` 可以创建零个或多个 candidate commitment，但不能创建 authority、Kernel responsibility、Work admission、communication command 或 fulfillment fact。

Administrative domain 拥有 candidate classification、EvidenceSpan lineage、speaker-to-principal qualification、due-time qualification、human admission、case state、communication metadata，以及 completion/discharge coordination。Transcript speaker label 不是 principal。Candidate 只有在一个 current provider identity binding 唯一解析后才解除 blocker；零个或多个 binding 都保持 ambiguous。

只有 `explicit_self_commitment` candidate 可以 admit。对他人的 assignment、aspiration、suggestion、information 和 ambiguous commitment 继续作为 non-authoritative candidate。Qualified due time 必须 offset-aware；ambiguous relative time 需要 human basis。

Admission 使用 policy `meeting-commitment:m9-v1` 和 `administrative_operator` decision。Admission 创建 kind 为 `meeting-commitment` 的 AdministrativeCase 和 durable CommitmentRecord。Commitment 是 persistent responsibility proposal；不是 Administrative Work item，也不授权 fulfillment。

M9 confirmation/reminder message 是通过 provider-neutral transport 发送的 fixed-template direct message。Draft content 只存于 content-addressed ArtifactStore。Administrative database row 只保存 storage reference、digest、recipient identity、event identity 和 delivery state。Transport 接受一个 durable `communication_event_id`，绝不把 transport acceptance 当成 human read 或 commitment fulfillment。Lost transport ACK 为 `outcome_unknown`；系统 reconcile 同一 event，而不是用新 identity 重发。

Completion 与 responsibility discharge 分离。Fulfillment 需要 qualified committer 的 authorized attestation，或 independently verified objective evidence path。Discharge 依次需要 assessment、explicit decision 和 Kernel lifecycle transition。

## 后果

- M6 candidate/intake contract 继续可复用，旧 admission path 不变。
- Kernel 只接收 generic persistent-responsibility proposal object 和 generic capability `administrative.communication.message.send.v1`。
- Gateway 继续只是 transport boundary，不拥有 Administrative policy、identity、fulfillment 或 completion。
- M9 不能从 model response、transport HTTP success、provider message identifier 或 confirmation-message reply 单独声称 completion。

## 不在范围

Audio/ASR、meeting bot、calendar/email/SMS/Slack/group messaging、marketing/legal/payment authority、delegated assignment、generic task management 和 M10 scope 均不属于本 ADR。
