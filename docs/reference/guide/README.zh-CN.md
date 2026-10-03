# 从 guide 迁入的工程设计参考

[English](README.md) | [简体中文](README.zh-CN.md)

`guide` 维护最小推导与概念框架。对照 AIOS 现有文档后，原 `guide/engineering/` 的三组中英文文档已迁入此处，**保留原有实质内容**，避免删除尚未集中收录的工程分析。这些文件是**非权威设计参考**，不是与 AIOS 现行契约并列的实施规范。

| 迁入文档 | AIOS 现行相关文档 |
| --- | --- |
| [工程行动链](action-chain.zh-CN.md) | [World Runtime 契约](../../kernel/world_runtime/contracts/runtime-contracts.zh-CN.md)、[行政领域架构](../../domains/administrative/architecture.zh-CN.md) |
| [精确语义](precise-semantics.zh-CN.md) | [语义归属](../../semantic/ownership.zh-CN.md)、[World Runtime 架构](../../kernel/world_runtime/architecture.zh-CN.md)、各领域契约 |
| [AIOS 架构概览](aios-architecture.zh-CN.md) | [AIOS README](../../../README.zh-CN.md)、`docs/kernel/` 与 `docs/domains/` 下的组件架构 |

迁入文档中的设计描述不表示所有机制都已经实现。实施语义由 AIOS 当前的契约、代码、测试和各领域所有者负责。形式证明由 [distinction-self-reference-lean](https://github.com/xiongweilin/distinction-self-reference-lean) 独立维护。

原始文档快照：[guide 511c073](https://github.com/xiongweilin/guide/tree/511c073322c6b38ed2d36b32492836abf4d69b58/engineering)。
