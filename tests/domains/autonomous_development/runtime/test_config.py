from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from autonomous_development.runtime.config import RuntimeSettings


def settings(tmp_path: Path, **overrides: object) -> RuntimeSettings:
    values: dict[str, object] = {
        "database_url": SecretStr("sqlite+pysqlite:///:memory:"),
        "dbos_system_database_url": SecretStr("sqlite:///:memory:"),
        "state_root": tmp_path.resolve(),
        "telemetry_queries": {"requests": "sum(rate(http_requests_total[5m]))"},
    }
    values.update(overrides)
    return RuntimeSettings(**values)


def test_runtime_settings_derive_state_paths(tmp_path: Path) -> None:
    configured = settings(tmp_path)

    assert configured.evidence_root == tmp_path.resolve() / "evidence"
    assert configured.traffic_state_root == tmp_path.resolve() / "traffic"
    assert configured.worktree_root == tmp_path.resolve() / "worktrees"
    assert configured.codex_thread_journal_root == tmp_path.resolve() / "codex-threads"


def test_runtime_settings_allow_container_network_services(tmp_path: Path) -> None:
    configured = settings(
        tmp_path,
        canary_proxy_base_url="http://candidate-proxy:8766",
        prometheus_base_url="http://prometheus:9090",
        world_runtime_base_url="http://world-runtime:8086",
        personal_world_base_url="http://personal-world:8080",
    )

    assert configured.prometheus_base_url == "http://prometheus:9090"
    assert configured.world_runtime_base_url == "http://world-runtime:8086"


def test_runtime_settings_reject_incomplete_service_urls(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        settings(tmp_path, prometheus_base_url="prometheus:9090")

    with pytest.raises(ValidationError):
        settings(tmp_path, world_runtime_base_url="http://world-runtime")


def test_runtime_settings_reject_relative_state_root() -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings(
            database_url=SecretStr("sqlite+pysqlite:///:memory:"),
            dbos_system_database_url=SecretStr("sqlite:///:memory:"),
            state_root=Path("relative"),
        )