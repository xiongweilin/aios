# semantic-language

> Component of the [AIOS monorepo](../README.md) at `semantic-language/`; this directory is not an independent GitHub repository.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white&style=flat-square)
![0.2](https://img.shields.io/badge/freeze-0.2-6f42c1?style=flat-square)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A small universal semantic kernel for human, institutional, and machine agency.

This component owns cross-domain meanings and non-substitution rules. It deliberately does **not** own workflows, persistence, orchestration, domain lifecycles, or provider integrations.

Version: 0.2.0


## Reference envelope

`SemanticRef.version` is the SemanticRef wire-format version, currently `0.1`; it is intentionally independent from the `semantic-language` package version. Universal kinds must come from `SemanticKind`. Domain-specific reference kinds are permitted only with an explicit non-universal namespace.
