# semantic-language

> Component of the [AIOS monorepo](../README.md) at `semantic-language/`; this directory is not an independent GitHub repository.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white&style=flat-square)
![0.3](https://img.shields.io/badge/freeze-0.3-6f42c1?style=flat-square)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A deliberately small cross-domain semantic boundary vocabulary.

This component owns stable semantic roles, references, canonicalization, and
non-substitution rules. It deliberately does **not** own payload schemas,
persistence, orchestration, domain lifecycles, provider integrations, or
owner-specific policy.

Version: 0.3.0

## Universal role set

`SemanticKind` is intentionally closed:

`Claim`, `Evidence`, `Unknown`, `Decision`, `Authorization`, `Effect`,
`Outcome`, `Responsibility`, and `Revision`.

Concrete payloads for those roles belong to the subsystem that creates and
governs them. Owner-local concepts use an explicit non-universal namespace.

## Reference envelope

`SemanticRef.version` is the SemanticRef wire-format version, currently
`0.1`; it is intentionally independent from the `semantic-language` package
version. Universal kinds must come from `SemanticKind`. Owner-specific kinds
are permitted only with an explicit non-universal namespace.

The normative contract is
`contracts/semantic/semantic-kernel-v0.3.md`.
