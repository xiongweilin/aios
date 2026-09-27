# ADR 0003 — Trusted perception and admission

> 权威英文原文：[0003-trusted-perception-and-admission.md](0003-trusted-perception-and-admission.md)。

本 ADR 定义非结构化组织输入如何进入 Administrative system，而不把 transport authenticity、model interpretation 或 human review 静默提升为 authoritative fact 或 execution authority。

## 核心边界

```text
authenticated source
!= truthful content

SourceArtifact
!= InterpretationRecord

InterpretationRecord
!= Candidate authority

Candidate
!= AdministrativeRequest

Admission
!= authoritative business fact

Administrative admission
!= World Runtime Work admission
```

## Intake pipeline

非结构化 input 先成为 receipt/artifact，随后由 parser/model 产生可追踪 interpretation 和 candidate。Candidate 必须通过 deterministic rule 或 authorized human admission path，产生 durable IntakeAssessment/PromotionRecord 后，才能创建 formal request/case。

Model confidence 只是 interpretation metadata，不能成为 admission authority。

## Provenance

所有 representation/candidate 必须绑定 source、version/digest、extractor/model identity、时间和必要 evidence span。Raw source 和 derived representation 分开保存；后续 correction 不改写历史 artifact。

## Human review

Human confirmation 可以决定“这个 candidate 是否进入 formal Administrative model”，但不能让 candidate 中的每个 field 自动变成 authoritative fact。Formal case 进入后，仍必须从 approved system/fact owner 建立 current facts。

## Failure behavior

Ambiguous、unsupported 或 provenance 不完整的 candidate 保持 candidate/review state，不能 fail open。Reject 不删除 source/evidence history。Reprocessing 同一 immutable source 必须保持可追踪 identity，不能静默覆盖旧 interpretation。

本 ADR 只定义 perception/admission authority，不创建 execution、provider 或 completion authority。
