# V1 Research Basis

> 权威英文原文：[v1-research-basis.md](v1-research-basis.md)。状态：evidence/rationale document；最后审查：2026-09-18。本文记录影响 V1 的外部资料，不重新定义 V1 semantics；`v1-design.md` 才是权威设计。

## 采用的研究结论

### Autonomous coding harness

OpenAI Codex harness engineering 的主要启示：

- repository/environment legibility 是 Agent 效率的重要乘数；
- 每个 worktree 使用隔离 app instance，使候选可独立复现和验证；
- log、metric、trace 应直接对 Agent 可读；
- architecture invariant 应机械执行，而不是只写在 prose；
- 长期 Agent 工作需要自动清理，限制 architecture entropy；
- coding/reproduction/validation/review/CI remediation 可以高度自动化，但 product priority 和 feedback translation 仍是更高层责任。

V1 因此复用 Codex，而不是自建 coding agent；每个 candidate 使用 git worktree；verification/log/metric/trace 机器可读；architecture 进入 Import Linter/CI；code health 是 quality responsibility。

### 长时间 Agent 工作

Anthropic long-running harness 的经验：compaction 不能替代 durable handoff；长任务需要 decomposition、明确 artifact 和可恢复 state。

V1 把 cycle/candidate/evidence 持久化在 model context 之外；Codex thread ID 只是 reference；每个 phase 留下可恢复 artifact/receipt。

Planner/generator/evaluator 保持语义分离，但不创建三个新 Agent runtime：Codex 执行 model-backed work，deterministic gate 保持独立。

### Codex integration

V1 以 Codex App Server JSON-RPC 为主要 adapter；`codex exec` 仅用于 compatibility/smoke。Diagnosis read-only；implementation 使用 worktree 内 workspace-write；默认关闭网络；Codex 不获得 release/deployment credential；Diagnosis/review 使用 structured schema。

### Durable execution

DBOS 是 V1 durable workflow substrate，PostgreSQL 是 accepted local deployment 的必要条件。Workflow checkpoint/recovery 不意味着 external effect exactly-once；外部副作用仍需 stable operation ID、idempotency 和 reconciliation。

Temporal 没有被技术否定，只是 V1 不需要更大的 runtime surface，也不为了隐藏 DBOS 选择而增加 abstraction layer。

### Evaluation 与 production feedback

Offline eval、production monitoring、user feedback、A/B test、human review 覆盖不同 failure class，没有任何单一层足够。

V1 使用分层 gate：

```text
unit/contract
→ regression/eval
→ performance
→ live canary
→ post-promotion soak
```

Explicit user feedback 单独保存；没有单一 score 决定 release；critical criterion 需要 product-grounded/deterministic oracle。

### Progressive delivery

Canary 是 partial、time-limited exposure，并在扩大之前评估。Build/test/deploy 应 reproducible；变更应保持小；canary size/duration 必须足以有代表性。

研究资料提供 design evidence，不自动获得 V1 contract authority。完整引用、adopted/rejected rationale 和细节以英文原文为准。
