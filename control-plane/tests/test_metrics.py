from pathlib import Path

from prometheus_client import CollectorRegistry, generate_latest

from control_plane.environment import CheckObservation, EnvironmentSnapshot
from control_plane.metrics import ControlPlaneMetricsCollector
from control_plane.runtime_bridge import DomainWork
from tests.domain_harness import DomainHarness, make_harness


def _scrape(harness: DomainHarness) -> str:
    registry = CollectorRegistry(auto_describe=False)
    registry.register(ControlPlaneMetricsCollector(harness.bridge))
    return generate_latest(registry).decode("utf-8")


def _work(harness: DomainHarness, *, kind: str, status: str) -> DomainWork:
    work = DomainWork(
        responsibility_ref="responsibility:test",
        proposal_ref=f"proposal:{kind}:{status}:{len(harness.bridge.list_work())}",
        kind=kind,
        status=status,
    )
    harness.journal.project_put(
        "work.current",
        work.id,
        work.model_dump(mode="json"),
    )
    return work


def test_profile_metrics_emit_zero_series_when_no_repairs_exist(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    try:
        text = _scrape(harness)

        assert 'control_plane_repairs_total{status="closed"} 0.0' in text
        assert 'control_plane_repairs_total{status="failed"} 0.0' in text
        assert "control_plane_repairs_active 0.0" in text
        assert "control_plane_candidates 0.0" in text
        assert "control_plane_recovery_retry_failed_total 0.0" in text
    finally:
        harness.close()


def test_profile_metrics_project_domain_work_state(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    try:
        _work(harness, kind="personal-incident-repair", status="failed")
        _work(harness, kind="personal-incident-repair", status="running")
        _work(harness, kind="personal-incident-repair", status="open")
        _work(harness, kind="personal-incident-repair", status="ready")
        _work(harness, kind="personal-incident-repair-blocked", status="waiting")
        _work(harness, kind="personal-command", status="pending")

        text = _scrape(harness)

        assert 'control_plane_repairs_total{status="failed"} 1.0' in text
        assert 'control_plane_repairs_total{status="active"} 1.0' in text
        assert 'control_plane_repairs_total{status="waiting"} 3.0' in text
        assert "control_plane_repairs_active 1.0" in text
        assert "control_plane_repairs_recoverable 3.0" in text
        assert "control_plane_candidates 0.0" in text
    finally:
        harness.close()


def test_profile_metrics_expose_environment_state(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    try:
        collector = ControlPlaneMetricsCollector(harness.bridge)
        collector.set_environment_snapshot(
            EnvironmentSnapshot(
                checked_at=123.0,
                observations=(
                    CheckObservation(
                        name="docker_build_cache",
                        status="problem",
                        severity="warning",
                        automation="codex-judgment",
                        detail="too large",
                        manual_action="manual",
                        metadata={"configured": True, "bytes": 2048},
                    ),
                ),
            )
        )
        collector.record_readiness(
            True,
            {"providers": [{"provider_id": "codex-primary", "available": True}]},
        )
        collector.record_current_provider_health(
            {"providers": [{"provider_id": "codex-primary", "available": False}]}
        )
        registry = CollectorRegistry(auto_describe=False)
        registry.register(collector)
        text = generate_latest(registry).decode("utf-8")

        assert (
            'control_plane_environment_check{automation="codex-judgment",'
            'check="docker_build_cache",configured="true",severity="warning",'
            'status="problem"} 1.0'
        ) in text
        assert "control_plane_docker_build_cache_bytes 2048.0" in text
        assert 'control_plane_ready_provider_mismatch{provider="codex-primary"} 1.0' in text
    finally:
        harness.close()
