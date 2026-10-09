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

## BAA research integration (not an AIOS-wide guarantee)

[BAA-Protocol](https://github.com/xiongweilin/BAA-Protocol) studies bounded admission, narrow capabilities, independent read-back, and recovery over **specified, version-pinned AIOS execution interfaces**. See the [pinned AIOS integration boundary](https://github.com/xiongweilin/BAA-Protocol/blob/main/integration/README.md) and [claim/evidence index](https://github.com/xiongweilin/BAA-Protocol/blob/main/experiments/claim-evidence-index.md).

Its finite checks, isolated product acceptance, and mixed prospective delegation studies do **not** establish that all AIOS runtime operations pass through BAA, that production deployments are certified, that all external harm is measurable, or that total human review labor declines. For any concrete AIOS deployment, authorization and effect semantics remain governed by the current AIOS contracts, code, and independently applicable tests; a BAA guarantee requires a separately qualified interface, evidence bridge, assumptions, and version.
