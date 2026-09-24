from datetime import timedelta
from pathlib import Path

from control_plane.domain_store import utcnow
from control_plane.runtime_bridge import DomainWork
from control_plane.state_reconciliation import (
    reconcile_repair_state,
    settle_waiting_execution_claims,
)
from tests.domain_harness import DomainHarness, make_harness


def _work(
    harness: DomainHarness,
    *,
    kind: str,
    status: str = "running",
    age: timedelta | None = None,
) -> DomainWork:
    updated_at = utcnow() - age if age is not None else utcnow()
    work = DomainWork(
        responsibility_ref="responsibility:test",
        proposal_ref=f"proposal:{kind}:{len(harness.bridge.list_work())}",
        kind=kind,
        status=status,
        updated_at=updated_at,
    )
    harness.journal.project_put(
        "work.current",
        work.id,
        work.model_dump(mode="json"),
    )
    return work


def test_reconcile_repair_state_removes_impossible_running_claims(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    try:
        blocked = _work(
            harness,
            kind="personal-incident-repair-blocked",
        )
        blocked_run = harness.bridge.start_run(
            blocked.id,
            workflow_id="personal-blocked-escalation",
        )

        stale = _work(
            harness,
            kind="personal-incident-repair",
            age=timedelta(hours=1),
        )
        stale_run = harness.bridge.start_run(
            stale.id,
            workflow_id="generic-task",
        )

        counts = reconcile_repair_state(
            harness.bridge,
            stale_after_seconds=900,
        )

        assert counts == {
            "blocked_work_waiting": 1,
            "running_runs_interrupted": 2,
            "stale_work_waiting": 1,
        }
        assert harness.bridge.get_work(blocked.id).status == "waiting"
        assert harness.bridge.get_work(stale.id).status == "waiting"
        assert harness.bridge.list_runs(blocked.id)[-1].id == blocked_run.id
        assert harness.bridge.list_runs(blocked.id)[-1].status == "interrupted"
        assert harness.bridge.list_runs(stale.id)[-1].id == stale_run.id
        assert harness.bridge.list_runs(stale.id)[-1].status == "interrupted"
    finally:
        harness.close()


def test_settle_waiting_execution_claims_does_not_claim_completion(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    try:
        work = _work(harness, kind="personal-incident-repair")
        run = harness.bridge.start_run(
            work.id,
            workflow_id="personal-incident-repair",
        )

        counts = settle_waiting_execution_claims(harness.bridge, work)

        assert counts == {
            "running_runs_interrupted": 1,
            "waiting_work_settled": 1,
        }
        assert harness.bridge.get_work(work.id).status == "waiting"
        assert harness.bridge.list_runs(work.id)[-1].id == run.id
        assert harness.bridge.list_runs(work.id)[-1].status == "interrupted"
    finally:
        harness.close()
