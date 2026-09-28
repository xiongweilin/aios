# Isolated V1 acceptance profile

The `target/` directory is a disposable, Dockerizable target for acceptance. The independent CI
workflow creates a unique Compose project, PostgreSQL/DBOS state, runtime state root, target Git
repository, Docker network and serving release for each run. It uses a protocol-only Codex stub
for readiness and does not call a real model provider or register anything in production.

The current target definition and its immutable base-image/dependency choices are documented in
[target/README.md](target/README.md). Acceptance evidence is run-specific: health/readiness,
SBOM, vulnerability, failure-injection and end-to-end results must be collected from the exact
image and environment used for that run.

Run outputs are not source code and are not committed under `acceptance/runs/`. CI should retain
them as workflow artifacts; local acceptance should retain them in an operator-controlled evidence
location when needed. Git history preserves previously committed acceptance snapshots.

Run the complete isolated lifecycle locally with:

```bash
python tests/acceptance/autonomous_development/run_acceptance.py \
  --evidence-path /path/to/acceptance-evidence.json
```

The runner bootstraps the target into the temporary Autodev database, waits for runtime and target
readiness, writes one task to target reality, restarts the target container, reads the task back
through the HTTP contract and directly from the container filesystem, scans the image, and then
removes the temporary target container, Compose project, images and state.
