from pathlib import Path

import httpx

from control_plane.app import _split_controller_reply, create_app
from control_plane.config import ControlPlaneConfig
from control_plane.runtime_bridge import WorldRuntimeClient
from tests.runtime_stub import RUNTIME_CONTRACTS, RuntimeStub


def _config(tmp_path: Path) -> ControlPlaneConfig:
    return ControlPlaneConfig(
        api_key="test-key",
        state_db=tmp_path / "control-plane-domain.db",
        artifact_root=tmp_path / "artifacts",
        agent_session_dir=tmp_path / "sessions",
        codex_worktree_root=tmp_path / "worktrees",
        prometheus_url="",
        alertmanager_url="",
        notification_enabled=False,
        environment_enabled=False,
        allowed_repo_roots=(str(tmp_path),),
    )


def test_app_is_external_domain_controller(tmp_path: Path) -> None:
    runtime = RuntimeStub()
    app = create_app(
        _config(tmp_path),
        runtime_transport=runtime.transport(),
    )

    assert not hasattr(app.state, "world_runtime")
    assert app.state.runtime_bridge.runtime is app.state.runtime_client
    capabilities = {
        capability
        for descriptor in app.state.provider_registry.list()
        for capability in descriptor.capabilities
    }
    assert "shell.exec" in capabilities
    assert "git.push_exact_ref" in capabilities
    assert "docker.compose.up" in capabilities
    assert any(path == "/v1/contracts" for _method, path, _payload in runtime.calls)


async def test_healthz_remains_profile_surface(tmp_path: Path) -> None:
    runtime = RuntimeStub()
    app = create_app(
        _config(tmp_path),
        runtime_transport=runtime.transport(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_controller_reply_syntax_is_explicit() -> None:
    assert _split_controller_reply("controller_123 continue") == (
        "controller_123",
        "continue",
    )
    assert _split_controller_reply("continue") is None


def test_world_runtime_client_sends_authentication_and_delegation_headers() -> None:
    observed: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers.get("authorization", "")
        observed["delegation"] = request.headers.get("x-world-runtime-delegation", "")
        return httpx.Response(
            200,
            json={
                "runtime_protocol": "4.0",
                "semantic_language": "0.2.0",
                "contracts": RUNTIME_CONTRACTS,
            },
        )

    client = WorldRuntimeClient(
        "http://runtime.test",
        transport=httpx.MockTransport(handler),
        bearer_token="controller-token",
        delegation_id="delegation:owner-controller",
    )
    try:
        client.ensure_contracts()
    finally:
        client.close()

    assert observed == {
        "authorization": "Bearer controller-token",
        "delegation": "delegation:owner-controller",
    }
