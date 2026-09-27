# Commitment service 结构重构

本次 closure 后重构保留 `MeetingCommitmentService` public facade，同时把边界明确的 implementation ownership 从 `commitment_service.py` 移出。

职责拆分：

- `commitment_service.py`：candidate admission、speaker qualification、policy/approval helper、稳定 public facade、显式 responsibility discharge。
- `commitment_communication.py`：communication draft/effect/obligation construction、direct transport classification、Kernel communication cutover。
- `commitment_responsibility.py`：Kernel responsibility-prefix provisioning。
- `commitment_lifecycle.py`：fulfillment transition。
- `commitment_due.py`：due-state advancement 和 reminder dispatch。
- `commitment_revision.py`：due-time revision 和 authority requalification。
- `commitment_cancellation.py`：cancellation 和 stale prepared-communication closure。
- `commitment_common.py`：共享 M9 service contract 和稳定 namespace constant。

Compatibility constraint：

- `MeetingCommitmentService`、`CommitmentIntakeError`、`ResponsibilityProvisioner`、`ResponsibilityRefs`、`KernelCommitmentResponsibilityProvisioner` 继续可以从 `administrative_orchestrator.commitment_service` import。
- 既有 module-level `httpx` 和 `KernelExecutionBridge` monkeypatch seam 继续有效，因为 facade 在 call time 把当前值注入 collaborator。
- 不刻意改变 schema、persisted identity、authority epoch、approval、obligation、effect、recovery、completion 或 responsibility-discharge semantics。
