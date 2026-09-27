# semantic-language

> [AIOS monorepo](../README.md) 中 `semantic-language/` 的组件；本目录不是独立 GitHub repository。

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white&style=flat-square)
![0.2](https://img.shields.io/badge/freeze-0.2-6f42c1?style=flat-square)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

面向人类、制度和机器 agency 的小型通用 semantic kernel。

本组件拥有跨领域含义和 non-substitution rule。它刻意**不**拥有 workflow、persistence、orchestration、domain lifecycle 或 provider integration。

版本：0.2.0

## Reference envelope

`SemanticRef.version` 是 SemanticRef wire-format version，当前为 `0.1`；它刻意与 `semantic-language` package version 独立。Universal kind 必须来自 `SemanticKind`。Domain-specific reference kind 只有在使用明确的 non-universal namespace 时才允许。
