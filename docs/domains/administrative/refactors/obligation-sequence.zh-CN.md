# Durable obligation sequence

本次 closure 后重构把 obligation tuple order 从 generic repository 根据 domain operation name 重建的隐式行为，改成显式 durable state。

## 所有权

Domain obligation derivation 拥有 immutable `AdministrativeObligationSet.obligations` tuple 的顺序。`ObligationRepository` 只负责忠实持久化和恢复已声明顺序。

Public `AdministrativeObligation` model 不新增 sequencing concept。`sequence` 是 `administrative_obligation` 上、以单个 `requirement_id` 为 scope 的 persistence metadata，因为 ordering 属于冻结 obligation graph representation，而不是单个 obligation 的 business meaning。

## 历史兼容

在 migration `0032_obligation_sequence` 之前，已持久化 obligation row 没有 ordinal。Runtime restoration 会根据 target system、operation name、authority class 和 obligation identity 重建顺序，并对 M8 ERP operation 设特殊 priority。

Migration `0032_obligation_sequence` 只执行一次 legacy reconstruction，并为所有历史 obligation set 保存 resulting ordinal。Migration 后 runtime persistence 不再知道 financial operation name。

新的 obligation set 持久化其 domain derivation 声明的 tuple order。如果读取时 ordinal 不是从 0 开始连续，则 fail closed。

## Invariant

- 不改变 obligation ID、requirement ID、authority epoch、governance basis ID、expected postcondition、fulfillment kind、effect link、completion semantics 或 Kernel contract；
- generic repository 不发明新的 ordering logic；
- persistence/restart 后仍保持 procurement draft-before-confirm；
- 历史 accepted M5/M7/M8 evidence 不被改写；
- downgrade 只移除 persistence ordinal 和其 uniqueness constraint；
- 本 PR 中 domain derivation 仍在 `obligations.py`；把 derivation 与 generic persistence 分离是后续独立重构。
