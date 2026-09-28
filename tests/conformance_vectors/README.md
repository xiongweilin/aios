# World Runtime conformance vector tests

The canonical public suite remains `src/kernel/world_runtime/contracts/vectors.json`, which is
also served by the World Runtime contract API. `traceability.json` pins the raw file SHA-256 and
maps every vector ID to one or more concrete pytest behavior tests; `test_traceability.py` creates
one pytest case per vector and rejects missing or renamed test targets.

The regular CI test step executes the mapped SQLite/API behavior tests. PostgreSQL-only vector
targets run in the separate CI PostgreSQL conformance step. When a vector changes, update its suite
version, SHA-256, traceability target and behavior test in the same change.
