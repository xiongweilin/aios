# Predecessor deletion gate

This is the final physical-deletion gate for:

- `xiongweilin/meta-controller`
- `xiongweilin/agent-kernel`
- `xiongweilin/world-state`

## What repository CI can prove

The repository-level gate is satisfied only when all of the following are true:

1. `semantic-language` and `world-runtime` V1 tests pass.
2. The accepted frozen predecessor snapshots reconcile with `unresolved == 0` and `rejected == 0`.
3. The deletion dry-run checks out only the five current repositories:
   - semantic-language
   - world-runtime
   - control-plane
   - administrative-orchestrator
   - autonomous-development
4. Those repositories install and pass their non-external-service test suites without checking out any predecessor.
5. Active dependency manifests contain no `agent-kernel`, `meta-controller`, `world-state`, or `@worldstate/*` dependency.
6. Active source contains no predecessor imports or predecessor protocol ownership.
7. Historical documentation, migration provenance, frozen SHA references, and negative regression tests are explicitly allowed and do not count as active dependencies.

The machine check for items 5-7 is `scripts/deletion_gate.py`.

## Frozen predecessor lineage

- agent-kernel: `001717a117a2987e1b8aa21bda37dddae0f88364`
- meta-controller: `18e1078c1d6971a2232662b6cbded4ffdbc380b0`
- world-state: `4ed1c35ea14c7fd7d6c40d893c75131e12dbc008`

Contract-derived accepted snapshots for these SHAs live under
`tests/fixtures/predecessor_snapshots/` and are verified in CI.

## Live-state gate

GitHub repository state cannot prove that no predecessor database, journal, local data directory,
container volume, or externally deployed predecessor instance exists.

Therefore physical repository deletion additionally requires exactly one of these for each predecessor:

- a migration reconciliation report produced from the real deployed state with
  `unresolved == 0` and `rejected == 0`; or
- an explicit operator record stating that no live predecessor state exists.

The accepted fixture snapshots prove semantic replacement; they do not substitute for this operator evidence.

The live-state decision is a state-disposition decision, not a filename-count decision. The gate
fails only when at least one of the following is true:

- a predecessor writer is still running;
- active configuration still points to predecessor state;
- a predecessor database in an active state location contains undisposed unique semantic state;
- the real-state migration report contains `unresolved > 0` or `rejected > 0`.

An immutable archival snapshot, historical backup, accepted migration source, or superseded
snapshot with no unique identity does not fail the gate when its disposition, hash, and retention
location are recorded in the acceptance manifest.

## Physical deletion decision

Physical deletion is permitted only when:

```text
repository deletion dry-run = PASS
AND predecessor snapshot acceptance = PASS
AND active predecessor dependency gate = PASS
AND live-state evidence for all three predecessors = PASS
```

Until the live-state evidence is available, the three predecessor repositories remain frozen and must not receive new feature work.
