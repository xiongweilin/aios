# Commitment service structural refactor

This post-closure refactor preserves the `MeetingCommitmentService` public facade while moving bounded implementation ownership out of `commitment_service.py`.

Responsibilities are separated as follows:

- `commitment_service.py`: candidate admission, speaker qualification, policy/approval helpers, stable public facade, explicit responsibility discharge.
- `commitment_communication.py`: communication draft/effect/obligation construction, direct transport classification, Kernel communication cutover.
- `commitment_responsibility.py`: Kernel responsibility-prefix provisioning.
- `commitment_lifecycle.py`: fulfillment transition.
- `commitment_due.py`: due-state advancement and reminder dispatch.
- `commitment_revision.py`: due-time revision and authority requalification.
- `commitment_cancellation.py`: cancellation and stale prepared-communication closure.
- `commitment_common.py`: shared M9 service contracts and stable namespace constants.

Compatibility constraints:

- `MeetingCommitmentService`, `CommitmentIntakeError`, `ResponsibilityProvisioner`, `ResponsibilityRefs`, and `KernelCommitmentResponsibilityProvisioner` remain importable from `administrative_orchestrator.commitment_service`.
- Existing module-level `httpx` and `KernelExecutionBridge` monkeypatch seams remain effective because the facade injects their current values into collaborators at call time.
- No schema, persisted identity, authority epoch, approval, obligation, effect, recovery, completion, or responsibility-discharge semantics are intentionally changed.
