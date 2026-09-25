# Isolated V1 acceptance profile

The `target/` directory is a disposable, Dockerizable target for local acceptance. Keep its
database, DBOS system state, runtime state root and Docker resources separate from any existing
registered target. The target is intentionally not included in a production bootstrap manifest.

The current target definition and its immutable base-image/dependency choices are documented in
[target/README.md](target/README.md). Acceptance evidence is run-specific: health/readiness,
SBOM, vulnerability, failure-injection and end-to-end results must be collected from the exact
image and environment used for that run.

Run outputs are not source code and are not committed under `acceptance/runs/`. CI should retain
them as workflow artifacts; local acceptance should retain them in an operator-controlled evidence
location when needed. Git history preserves previously committed acceptance snapshots.
