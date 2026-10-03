# Migrated guide engineering references

[English](README.md) | [简体中文](README.zh-CN.md)

The `guide` repository maintains its minimal derivation and conceptual framework. The engineering analysis formerly in `guide/engineering/` has been moved here after comparing existing AIOS documentation. The substantive content of all six files is preserved to avoid losing material not assembled into a single AIOS document. These are **non-normative design references**—not parallel implementation contracts.

| Migrated reference | Maintained AIOS documentation |
| --- | --- |
| [Engineering action chain](action-chain.md) | [World Runtime contracts](../../kernel/world_runtime/contracts/runtime-contracts.md), [Administrative architecture](../../domains/administrative/architecture.md) |
| [Precise semantics](precise-semantics.md) | [Semantic ownership](../../semantic/ownership.md), [World Runtime architecture](../../kernel/world_runtime/architecture.md), domain contracts |
| [AIOS architecture overview](aios-architecture.md) | [AIOS README](../../../README.md), component architectures in `docs/kernel/` and `docs/domains/` |

Migrated architecture notes are not evidence that every described feature is implemented. Actual contracts, source, and tests remain authoritative. Formalization lives in [distinction-self-reference-lean](https://github.com/xiongweilin/distinction-self-reference-lean).

Original source snapshot: [guide 511c073](https://github.com/xiongweilin/guide/tree/511c073322c6b38ed2d36b32492836abf4d69b58/engineering).
