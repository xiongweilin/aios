# Governed contingent-policy staging — merge acceptance record

Date: 2026-10-10. Decision scope: **merge of an experimental, non-dispatching staging boundary**. This is not production authorization to use any new external effect.

## Exact verified source and durable test locations

- Repository `xiongweilin/aios` PR [#53](https://github.com/xiongweilin/aios/pull/53).
- Examined HEAD `15580399d295ba88020bc1b455dae162707343f3`; base `9484324d9451df3a2f86d555f165de6e7701ea7c`.
- [CI 38052319284](https://github.com/xiongweilin/aios/actions/runs/38052319284): Python job **938 passed, 1 skipped, 18 deselected**, all current/pinned BAA compatibility and aggregate checks passed.
- [Isolated real-product E2E 38052319307](https://github.com/xiongweilin/aios/actions/runs/38052319307): normal, lost_ack, readback_outage, runtime_bypass all passed.
- [Lifecycle acceptance 38052319283](https://github.com/xiongweilin/aios/actions/runs/38052319283), [hosted preflight 38052319346](https://github.com/xiongweilin/aios/actions/runs/38052319346), [analysis 38052319335](https://github.com/xiongweilin/aios/actions/runs/38052319335): all succeeded.
- [Paired BAA→AIOS research-branch contract 38052558817](https://github.com/xiongweilin/BAA-Protocol/actions/runs/38052558817) used the exact AIOS commit above; **22 staged-boundary adversary tests** plus end-to-end *no-provider-write* policy-lowering script passed.

## Adversarial acceptance coverage

| Potential exploit/defect | Verified negative response |
| --- | --- |
| An internally consistent but foreign subject/case/approval batch | Whole-batch preflight compares with **live** case subject, authority epoch and governance basis |
| Missing/fake future observation branch | Reject **whole policy** before any effect staging |
| Cyclic/unbounded/in-place-mutated policy tree | Reject cycles, effect replay, depth/node overflow; snapshot caller's tree |
| Unknown or unverified effect | Never consider successful by fiat, never redispatch blindly |
| Trusted reconciliation after uncertain effect | Permit only *previously compiled* qualified probe; any ensuing effect is reauthorized |
| Wrong/in-flight result or changed authority version | Reject and block cursor |
| Fabricated plan completion | `done` is only a policy hint; domain closure remains separately verified |

## Not qualified and exclusions

The staging cursor is **not** wired to direct provider dispatch, does not persist a transaction-safe effect ledger or independently prove callbacks truthful, and does not survive process restarts with exactly-once guarantee. `independent_readback` flags in unit tests are controlled fixture inputs. Cross-repo CI validates shape and staging behavior, **not live tenant authority or production evidence**. Existing World Runtime remains the authority and durable effect boundary.

**Merge policy:** safe to merge as isolated experiment plus hardened offboarding preflight after final green CI, but **not** to enable production autonomous execution or assert delivery/labor gains. A subsequent actual read-only production pilot needs fresh ON-DUTY authorization and independent operational evidence. This note documents the examined source HEAD; the documentation-only commit itself must receive green checks.
