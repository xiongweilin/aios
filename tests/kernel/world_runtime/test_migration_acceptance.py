from pathlib import Path

from world_runtime.migration_acceptance import verify_accepted_snapshot_directory


def test_frozen_predecessor_accepted_snapshots_reconcile_without_required_gaps() -> None:
    root = Path(__file__).parent / "fixtures" / "predecessor_snapshots"
    results = verify_accepted_snapshot_directory(root)

    assert {item.source for item in results} == {
        "agent-kernel",
        "meta-controller",
        "world-state",
    }
    assert all(item.report.deletion_ready for item in results)
    assert all(item.report.unresolved == 0 for item in results)
    assert all(item.report.rejected == 0 for item in results)
    assert sum(item.report.intentionally_skipped for item in results) == 1
