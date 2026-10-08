# P6 BAA/AIOS isolated offboarding quality baseline

This is **instrument qualification and a descriptive performance baseline**, not a throughput or production reliability acceptance test.

Every `Real Product Offboarding E2E` scenario emits an additional `p6-quality.json` artifact, even when the acceptance case fails after instrumentation has begun. It is extracted entirely from the existing disposable Keycloak/Odoo/World Runtime experiment; no new external endpoint or production credential is needed.

## Measurement contract

| Stage | Boundary | What it does *not* establish |
|---|---|---|
| `engine_drive` | One full `OffboardingExecutionEngine.run(case_id)` call, including local planning, state persistence and all covered effects | Pure admission latency, pure network latency |
| `gate_execute_including_admission_dispatch_readback` | One synchronous BAA-gated `EffectProvider.execute` call | Separate admission and provider dispatch/verification times |
| `gate_observe_including_independent_readback` | One synchronous BAA-gated `EffectProvider.observe` call | Continuous observation of real world; physical effect timestamp |

The wrapper delegates *exactly once* and returns the original provider response or raises the original exception. The timing recorder does not decide whether an effect is authorized, verified, replayable, or completed.

Each record includes the stage, allowlisted operation, monotonic duration (ns), allowlisted response category and exception **class** only. No bearer tokens, employee identifiers, credential values, payloads or exception text are included. An explicit observation overflow marks the evidence as `instrument_complete=false`.

The report includes `n`, minimum, P50/P95/P99, maximum and status counts for each stage. Percentiles use linearly interpolated empirical sample positions. They are **descriptive at every sample size**: a single isolated case and three effects cannot qualify production tail latency, throughput, error rate, CPU/memory, assurance labor, or principal attention. These dimensions remain unmeasured, not imputed zero.

## Current experiment scope

- One disposable isolated episode per matrix arm: `normal`, `lost_ack`, `readback_outage`, `runtime_bypass`.
- Each CI matrix arm has its own ephemeral container topology, generated test credentials, and `p6-quality.json` evidence.
- `runtime_bypass` may have zero BAA/AIOS stage observations because it tests direct runtime authorization denial; zeros in `n` are **not** zero latency or proof of no bypass attempts.
- The full driver duration recorded by earlier E2E acceptance remains comparable within its existing limitations. This extension adds component-level coarse timings without changing authorization and outcome requirements.
- Performance SLO thresholds remain **unset** until a future independently preregistered load model and acceptance budget exists.

## Reproduction

Open the CI artifact for `Real Product Offboarding E2E` and read `p6-quality.json` beside `evidence.json`. For a quick local conformance check (does not require a network or secrets):

```bash
python -m unittest discover -s tests/acceptance/baa_offboarding/real_e2e -p "test_p6_quality.py" -v
```

To advance to P6 acceptance, preregister a versioned workload, repetitions and warmup rules, concurrency distribution, fault schedule, measurement coverage, confidence-interval method, CPU/memory/network counters, SLO thresholds and production-like recovery budget **before** observing results. Do not silently treat these matrix artifacts as a soak or a P7 long-run trial.
