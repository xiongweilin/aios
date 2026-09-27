# 架构

## 使命

Personal World 是一个人不断演化世界的 durable、user-owned representation。它跨 model、agent、console、process 和时间保持 personal continuity。

它回答：

- 关于这个人已知什么？
- 为什么知道？
- 现在是否仍有效？
- authoritative source 在哪里？
- 为当前 purpose 是否允许投影这些信息？

它不决定现实世界中应该发生什么，也不授予 execution authority。

## 所有权边界

Personal World 拥有：provenance、observation 和 claim、qualified personal fact、preference、relationship、external resource link、temporal lineage、freshness/revalidation state、sensitivity classification、purpose-limited context projection，以及基于 canonical personal record 的 derived retrieval。

它不拥有 Decision、Authorization、Mandate、Responsibility、Work、Run、Effect、Outcome、provider execution、domain lifecycle、agent/model routing、secret/credential 或 model-private memory。

## 核心 non-substitution rule

1. Source != Observation != Claim != current personal state。
2. Historical validity != current validity。
3. Projection != canonical truth。
4. Personal context != authority。
5. Domain projection != domain ownership。
6. Model inference != accepted personal truth。
7. Derived retrieval index != canonical storage。

## Canonical data path

```text
Human / Domain / External source
        ↓
SourceDescriptor
        ↓
Observation
        ↓
Claim
        ↓
Qualification / admission
        ↓
Personal Record Revision
        ↓
Current lineage head
        ↓
Purpose-limited ContextProjection
        ↓
Cognitive plane
```

Observation 和 claim immutable。Personal record 通过 append revision 演进，correction 不改写 prior revision。

## Public record kind

v1.0 baseline 只暴露 PersonalFact、Preference、Relationship、ResourceLink 四种顶层 personal record kind。新的 domain concept 通常继续留在 Domain Controller，通过 ResourceLink 或 domain-namespaced projection 引用；Personal World 不应成为 universal business ontology。

## 时间模型

每条 record 可以携带 `observed_at`、`recorded_at`、`valid_from`、`valid_until`。As-of read 选择请求时刻已知且有效的最新 recorded revision；current read 选择最新 non-erased lineage head。

## Domain 与 Runtime 边界

Domain Controller 可以提交 `DomainPersonalProjection`。Personal World 记录 source、observation、claim 和 candidate personal fact，但不复制 domain lifecycle authority。

World Runtime 与 Personal World 是独立 durable system：Personal World 回答“这个人的世界是什么”；World Runtime 回答“存在哪些 durable agency，以及为什么可以继续”。Runtime 可以引用 Personal World record 作为 basis material，但不能复制 ownership；Personal World 不能签发 Runtime authorization。

## Projection、Storage 与 Retrieval

Caller 请求 purpose-limited projection，而不是 unrestricted personal state。Filtering 考虑 authenticated service identity、declared purpose、allowed record kinds、sensitivity ceiling、requested scope、qualification state 和 optional retrieval query。Projection 是 disposable，可从 canonical state 重建。

SQLite 支持 local single-node；PostgreSQL 支持 shared durable operation。Revision write 使用 expected-revision CAS；PostgreSQL append 前还锁定 current lineage head。Bundle export 保持 stable ID/lineage；import 只用于 restore，并要求空 target store。

内置 retrieval 从 canonical record 派生，结合 lexical overlap 和 deterministic hashed-vector similarity。它可以删除并重建而不丢失 truth；未来 external vector index 必须遵守同一规则。

## Deployment identity 与 root subject

v1.0 production profile 把一个 service instance 绑定到一个 root personal subject。这是 instance boundary，不是新 semantic object。Production workload authentication 是短生命周期 signed identity；它、DataAccessProfile disclosure policy 和 root-subject boundary 与 Runtime authority 相互独立。
