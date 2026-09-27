# Personal World Contracts

> 权威英文原文：[contracts.md](contracts.md)。当前 package baseline：**1.0.0**；contract manifest：**personal-world-contracts-v1**；semantic-language baseline：**0.2.0**。

## Provenance contracts

`SourceDescriptor` 标识信息来源，支持 human-explicit、domain-controller、external-record、import、model-inference、derived。来源描述本身不证明内容为真。

`Observation` 是某时刻从某 source 观察到某值的 immutable record。

`Claim` 是从 source 派生、可由 observation 支撑的 immutable assertion；Claim 不自动成为 current PersonalFact。

## Personal record

所有 personal record 都包含 stable `lineage_id`、monotonic revision、subject_id、semantic reference、value、source_refs、可选 claim_refs、temporal scope、sensitivity、qualification status、context 和 metadata。

Qualification status：

```text
candidate
current
contested
revalidation-required
superseded
retracted
```

历史 revision 不会被物理改写以伪造 supersession；lineage order 表示后续 revision，historical read 保留当时记录的 status。

## Admission 与 revision

请求写成 `current` 的 record，如果 evidence 不具资格，会降为 candidate。Model inference 不能直接创建 current PersonalFact；未接受的 inferred preference 保持 candidate；明确标记 accepted-inference 的 preference 可以 current；domain ingress 生成 candidate PersonalFact 并保留 domain ownership。

Current record 不能被只由不合格 evidence 支撑的新 revision 静默替换。

Revision 使用 CAS：

```text
expected_revision == current_revision
new_revision == current_revision + 1
```

Stale writer 收到 conflict，必须重新读取。

## Projection 与 trust

`ContextProjection` 包含 included current items、contested items、stale/revalidation-required items、excluded_count、source refs、purpose 和 scope。Candidate/retracted record 不能静默进入 normal included context。

Transport caller 总是提供 `X-Service-Identity` 和 `X-Purpose`。Local compatibility 可以使用 bearer credential；production v1.0 使用绑定 identity/purpose 的短生命周期 signed workload assertion。

Authentication 只证明 workload identity；DataAccessProfile 单独控制可访问 purpose、record kind 和 sensitivity；root subject 单独把整个 Personal World instance 限制到一个人。三者都不是 World Runtime Authorization。

## Domain ingress

`DomainPersonalProjection` 携带 subject_id、source_domain、source_object_ref、source_version、observed_at 和 domain claims。

每个 DomainClaim 只能映射到四种冻结 record kind：`fact`、`preference`、`relationship`、`resource-link`。HTTP boundary 要求 `source_domain` 匹配 authenticated service identity。Ingress 创建 provenance 和 candidate personal record，不声明 domain outcome。

## Erasure、Bundle 与时间重建

Full-subject erasure 删除该 subject 的 personal content，只保留 storage structure 必需 tombstone metadata。Kind-scoped erasure 只删除选中 kind 及直接关联 provenance；只有没有 surviving reference 时才 redaction source。

`personal-world-bundle-v1` 用于 recovery/export，保留 ID、lineage、temporal field、source link 和 data-access profile。Import 只允许空 store，避免隐藏 merge semantics。

`as_of` 是 bitemporal：revision 同时满足 `recorded_at <= t` 与 valid-time window 才具资格。Late-arriving correction 即使 valid-time 回溯，也不能在其 `recorded_at` 之前出现在 as-of view。

Consumer conformance 标识为 `personal-world-conformance-v1`。Consumer 必须验证 exact contract discovery 并保持 caller purpose；projection 仍只是 personal context，不是 Runtime Authorization 或 domain outcome truth。

## Backup 与 root-subject boundary

Erasure 立即作用于 active canonical storage 和之后生成的 derived surface。旧 backup 属于 operational backup，不是 live Personal World state；恢复 erasure 前 backup 时必须先 replay backup point 之后的 erasure obligation，再允许 exposure。

Production instance 严格绑定一个 `PERSONAL_WORLD_ROOT_SUBJECT_ID`。所有 subject-bearing read/write/projection/domain ingress/erasure/bundle import-export 跨越该 root 时 fail closed。
