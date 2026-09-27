# 威胁模型

Personal World 预计会包含 Personal AI OS 中最敏感的一部分长期数据，因此 trust boundary 刻意比普通 agent memory store 更窄。

## 受保护资产

包括 canonical personal record、provenance/historical lineage、sensitive relationship/resource link、context projection、disclosure policy 和 export bundle。Password、OAuth refresh token、API key、private key 等 secret 不属于 Personal World，必须放在专门 secret store；这里只保留 opaque credential ref。

## 威胁与缓解

### Service identity spoofing
威胁：caller 伪造 `X-Service-Identity`。  
缓解：production v1.0 要求短生命周期 signed workload assertion，绑定 `X-Service-Identity`、`X-Purpose` 和有界 timestamp。本地 compatibility mode 可用 bearer credential；TLS termination 和 secret rotation 由 deployment 负责。

### Cross-purpose disclosure
威胁：合法 service 请求与自身 purpose 无关的 personal context。  
缓解：DataAccessProfile 把 service identity 绑定到明确 purpose、allowed record kind 和 sensitivity ceiling；purpose 不允许时 projection/search fail closed。

### Prompt injection 导致 context exfiltration
模型能生成文本不等于获得 authentication。Calling service identity 和 purpose 在 prompt 外评估，minimum-necessary projection 是默认 API 形态。

### Model inference 被提升为 fact
Model-inference source 只创建 candidate fact。除非 record type 有显式 accepted-inference rule，否则拒绝 revalidate 为 current；目前只允许 Preference。

### 恶意 domain projection
`source_domain` 必须匹配 authenticated service identity。Domain ingress 创建 candidate personal fact 并保留 source object/version metadata；domain lifecycle 仍由 domain owner 持有。

### Lost update / concurrent writer
使用 monotonic revision CAS + unique lineage/revision database constraint；PostgreSQL append 时锁定 current lineage head。

### Historical rewriting
Observation、claim 和 record revision 都以 append 为主；supersede 时不改写 prior revision。

### Erasure overreach
只有确认 store 中没有 surviving observation、claim、record reference 后才做 source redaction；kind-scoped erasure 只沿选中 record 的 provenance 执行。

### Derived-index leakage
Retrieval index 是 derived、可重建的。Production external index 必须支持从 canonical record delete/rebuild，绝不能成为 personal fact 唯一 source。

### Backup leakage 与 erasure resurrection
Bundle endpoint 仅 admin 可用。Erasure 后的新 bundle 必须不再包含被删值。Physical backup 必须加密、访问受控、有限期保留。恢复 erasure 前 backup 时必须隔离，直到 replay 所有 post-backup erasure obligation。CI 执行 logical bundle restore 和 physical `pg_dump`/`pg_restore` drill，但不声称应用本身能强制 backup retention。

## v1.0 后剩余风险

- workload HMAC secret 仍需 external rotation/secret management；此处未实现 mTLS；
- baseline 未实现 field-level cryptographic encryption；
- purpose string 是明确 contract，不是通用 policy language；
- domain-specific sensitivity classification 仍依赖 submitting integration；
- external semantic/vector index 需要自己的 deletion conformance test。

### Cross-subject access
Production startup 要求一个 `PERSONAL_WORLD_ROOT_SUBJECT_ID`。Subject-bearing API surface 和 portable bundle import/export 在跨越该 root 时 fail closed。
