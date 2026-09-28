# semantic-language

> [AIOS monorepo](../README.md) 中 `semantic-language/` 的组件；本目录不是独立 GitHub repository。

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white&style=flat-square)
![0.3](https://img.shields.io/badge/freeze-0.3-6f42c1?style=flat-square)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

一个刻意保持很小的跨领域 semantic boundary vocabulary。

本组件只拥有稳定 semantic role、reference、canonicalization 和
non-substitution rule。它刻意**不**拥有 payload schema、persistence、
orchestration、domain lifecycle、provider integration 或 owner-specific policy。

版本：0.3.0

## Universal role set

`SemanticKind` 是刻意封闭的：

`Claim`、`Evidence`、`Unknown`、`Decision`、`Authorization`、
`Effect`、`Outcome`、`Responsibility`、`Revision`。

这些 role 的具体 payload 由创建和治理它们的 subsystem 拥有。
Owner-local concept 使用明确的 non-universal namespace。

## Reference envelope

`SemanticRef.version` 是 SemanticRef wire-format version，当前为 `0.1`；
它刻意与 `semantic-language` package version 独立。Universal kind 必须来自
`SemanticKind`。Owner-specific kind 只有在使用明确 non-universal namespace
时才允许。

规范 contract 为
`contracts/semantic/semantic-kernel-v0.3.zh-CN.md`。
