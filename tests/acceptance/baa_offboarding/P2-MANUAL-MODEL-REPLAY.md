# P2 archived read-only maintenance model replay — manual execution contract

The canonical GitHub Actions workflow is **BAA P2 Isolated Read-Only Maintenance Model Replay v1**. It runs on the self-hosted Windows runner and does not connect to live Keycloak, Odoo or World Runtime. The only permitted model endpoint is the existing local loopback gateway.

## Manual selection

The workflow has no push, pull request, or cron trigger. Two separate workflow-dispatch inputs are required:

- `run_mode=source_preflight_only` (**default**) and `approve_finite_model_sampling=no` (**default**): download the frozen P7 Actions ZIP, validate exact SHA-256 and all five episode projections, run offline unit tests, parse the standalone source qualification JSON, and check that the loopback model gateway/catalog is available. **No model generation call** is made. The source artifact may expire; missing bytes result in a failure, not reconstructed evidence.
- `run_mode=model_sample` **plus** `approve_finite_model_sampling=yes`: perform the same qualification and then sample the fixed P2 protocol with at most 96 distinct model calls. This can incur model/API costs and must be explicitly approved on each run.

Mismatched combinations are rejected. Automatic retries of experiments are not scheduled; the workflow never writes to product systems. A source-preflight success means only that the instrument and existing gateway are ready, not that any model was sampled.

## First-run provenance boundary

The first real-model study **already completed** on [AIOS run 37725010049](https://github.com/xiongweilin/aios/actions/runs/37725010049), with BAA instrument `82370d7991eea9c288126610594a208efff06baa`: 11 physical model calls, 45 regime rows, and **no BAA delegation-frontier expansion** (C0 and C1: 0/5 all arms; C2: 1/5 all arms). Its full bilingual frozen evidence and losslessly retained `result.json` are in the [BAA result archive](https://github.com/xiongweilin/BAA-Protocol/blob/main/experiments/p2-readonly-maintenance-model-v1-result.md).

This revised workflow pins the later BAA `3c9aec12cb261621cf79e4e693498af6f738647c`, which fixes a redundant source-only JSON sidecar formatting issue. **This does not rewrite, recompute, or replace the first run.** Any subsequent model result must be versioned independently, including new gateway and billing provenance. A successful result would still be a correlated, offline archived-evidence replay, not a randomized online maintenance trial or actual attention-risk calibration.
