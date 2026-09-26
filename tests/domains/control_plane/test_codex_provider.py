from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import control_plane.codex_provider as codex_provider
from control_plane.codex_provider import CodexProvider, _resolve_cli
from control_plane.provider_protocol import CapabilityRequest, InvocationContext
from integrations.codex_app_server import CodexBridgeError, RemoteCodexTurn


def _request(**overrides: Any) -> CapabilityRequest:
    values: dict[str, Any] = {
        "id": "request-codex-1",
        "capability": "reason.generate",
        "instruction": "diagnose this alert",
        "timeout_seconds": 30,
    }
    values.update(overrides)
    return CapabilityRequest(**values)


def _context() -> InvocationContext:
    return InvocationContext(runtime_id="test-runtime")


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        timeout: bool = False,
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._timeout = timeout
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._timeout:
            raise TimeoutError
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


class _PreparedBoundary:
    def __init__(self, cwd: Path, cleanup_calls: list[bool]) -> None:
        self.cwd = cwd
        self.env = {"CODEX_STUB": "1"}
        self._cleanup_calls = cleanup_calls

    def cleanup(self) -> None:
        self._cleanup_calls.append(True)


class _ExecutionBoundary:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.cleanup_calls: list[bool] = []

    def prepare(self, repo: str, sandbox: str) -> _PreparedBoundary:
        del sandbox
        return _PreparedBoundary(Path(repo), self.cleanup_calls)

    def redact_transcript(self, text: str) -> str:
        return text.replace("secret", "[redacted]")


class _RemoteAppServer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.request: dict[str, Any] | None = None

    def run_turn(self, **request: Any) -> RemoteCodexTurn:
        self.request = request
        if self.error is not None:
            raise self.error
        return RemoteCodexTurn(
            request_id=str(request["request_id"]),
            thread_id="remote-thread",
            turn_id="remote-turn",
            status="completed",
            server_version="test-version",
            events=(),
            agent_messages=("remote-secret-result",),
            result_sha256="synthetic-result-digest",
        )


def test_resolve_cli_prefers_explicit_path(tmp_path: Path) -> None:
    explicit = tmp_path / "codex"
    assert _resolve_cli(explicit) == explicit


def test_resolve_cli_falls_back_to_default_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex_provider.shutil, "which", lambda _name: None)
    assert _resolve_cli(None) == Path("codex")


def test_resolve_cli_uses_discovered_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        codex_provider.shutil,
        "which",
        lambda name: "/usr/local/bin/codex" if name == "codex" else None,
    )
    assert _resolve_cli(None) == Path("/usr/local/bin/codex")


@pytest.mark.asyncio
async def test_health_reports_available_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def start(*args: Any, **kwargs: Any) -> _FakeProcess:
        del args, kwargs
        return _FakeProcess(returncode=0, stdout=b"codex 1.2.3\n")

    monkeypatch.setattr(codex_provider.asyncio, "create_subprocess_exec", start)
    health = await CodexProvider(cli=tmp_path / "codex").health()

    assert health.available is True
    assert "codex 1.2.3" in health.detail


@pytest.mark.asyncio
async def test_health_reports_start_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def start(*args: Any, **kwargs: Any) -> _FakeProcess:
        del args, kwargs
        raise FileNotFoundError("codex missing")

    monkeypatch.setattr(codex_provider.asyncio, "create_subprocess_exec", start)
    health = await CodexProvider(cli=tmp_path / "codex").health()

    assert health.available is False
    assert "codex missing" in health.detail


@pytest.mark.asyncio
async def test_invoke_requires_a_prompt(tmp_path: Path) -> None:
    provider = CodexProvider(cli=tmp_path / "codex")

    result = await provider.invoke(_request(instruction=None), _context())

    assert result.status == "failed"
    assert result.error == {"type": "invalid_request", "message": "prompt required"}


@pytest.mark.asyncio
async def test_invoke_requires_an_absolute_repo_for_remote_execution(tmp_path: Path) -> None:
    remote = _RemoteAppServer()
    provider = CodexProvider(cli=tmp_path / "codex", remote_app_server=remote)

    result = await provider.invoke(_request(parameters={"repo": "relative"}), _context())

    assert result.error == {"type": "invalid_request", "message": "repo path must be absolute"}
    assert remote.request is None


@pytest.mark.asyncio
async def test_remote_invoke_persists_redacted_transcript_and_cleans_boundary(
    tmp_path: Path,
) -> None:
    boundary = _ExecutionBoundary(tmp_path / "remote-sessions")
    remote = _RemoteAppServer()
    provider = CodexProvider(
        cli=tmp_path / "codex",
        model="gpt-6-luna",
        execution_boundary=boundary,
        remote_app_server=remote,
    )

    result = await provider.invoke(
        _request(parameters={"repo": str(tmp_path.resolve()), "model": "gpt-6-luna"}),
        _context(),
    )

    assert result.status == "succeeded"
    assert result.metadata["transport"] == "codex-app-server-v1"
    assert result.metadata["thread_id"] == "remote-thread"
    assert remote.request is not None
    assert remote.request["cwd"] == tmp_path.resolve()
    assert remote.request["sandbox"] == "read-only"
    assert remote.request["model"] == "gpt-6-luna"
    assert boundary.cleanup_calls == [True]
    transcript = (boundary.session_dir / "request-codex-1.jsonl").read_text(encoding="utf-8")
    assert "remote-[redacted]-result" in transcript
    assert "remote_request_id" in transcript


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_type", "retryable"),
    [
        (CodexBridgeError("ambiguous", outcome="unknown"), "outcome_unknown", False),
        (CodexBridgeError("not sent", outcome="not_started"), "remote_codex", True),
        (OSError("disconnected"), "remote_codex_io", None),
    ],
)
async def test_remote_invoke_maps_transport_failures_and_cleans_boundary(
    tmp_path: Path,
    failure: Exception,
    expected_type: str,
    retryable: bool | None,
) -> None:
    boundary = _ExecutionBoundary(tmp_path / "remote-sessions")
    remote = _RemoteAppServer(error=failure)
    provider = CodexProvider(
        cli=tmp_path / "codex",
        execution_boundary=boundary,
        remote_app_server=remote,
    )

    result = await provider.invoke(
        _request(parameters={"repo": str(tmp_path.resolve())}),
        _context(),
    )

    assert result.status == "failed"
    assert result.error["type"] == expected_type
    if retryable is not None:
        assert result.error["retryable"] is retryable
    assert boundary.cleanup_calls == [True]


@pytest.mark.asyncio
async def test_invoke_persists_redacted_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    boundary = _ExecutionBoundary(tmp_path / "sessions")
    provider = CodexProvider(cli=tmp_path / "codex", execution_boundary=boundary)
    process = _FakeProcess(returncode=0, stdout=b'{"text": "secret"}\n')

    async def start(*args: Any, **kwargs: Any) -> _FakeProcess:
        del args, kwargs
        return process

    monkeypatch.setattr(codex_provider.asyncio, "create_subprocess_exec", start)
    result = await provider.invoke(_request(parameters={"repo": str(tmp_path)}), _context())

    assert result.status == "succeeded"
    assert result.metadata["sandbox"] == "read-only"
    assert boundary.cleanup_calls == [True]
    transcript = (boundary.session_dir / "request-codex-1.jsonl").read_text(encoding="utf-8")
    assert "[redacted]" in transcript


@pytest.mark.asyncio
async def test_invoke_survives_transcript_persistence_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session_file = tmp_path / "sessions-file"
    session_file.write_text("not a directory", encoding="utf-8")
    boundary = _ExecutionBoundary(session_file)
    provider = CodexProvider(cli=tmp_path / "codex", execution_boundary=boundary)
    process = _FakeProcess(returncode=0, stdout=b"transcript")

    async def start(*args: Any, **kwargs: Any) -> _FakeProcess:
        del args, kwargs
        return process

    monkeypatch.setattr(codex_provider.asyncio, "create_subprocess_exec", start)
    result = await provider.invoke(
        _request(parameters={"repo": str(tmp_path.resolve())}),
        _context(),
    )

    assert result.status == "succeeded"


@pytest.mark.asyncio
async def test_invoke_timeout_kills_the_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _FakeProcess(timeout=True)

    async def start(*args: Any, **kwargs: Any) -> _FakeProcess:
        del args, kwargs
        return process

    monkeypatch.setattr(codex_provider.asyncio, "create_subprocess_exec", start)
    result = await CodexProvider(cli=tmp_path / "codex").invoke(
        _request(parameters={"repo": str(tmp_path.resolve())}),
        _context(),
    )

    assert result.status == "failed"
    assert result.error == {"type": "timeout", "message": "codex session timed out"}
    assert process.killed is True


@pytest.mark.asyncio
async def test_invoke_reports_process_start_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def start(*args: Any, **kwargs: Any) -> _FakeProcess:
        del args, kwargs
        raise OSError("spawn failed")

    monkeypatch.setattr(codex_provider.asyncio, "create_subprocess_exec", start)
    result = await CodexProvider(cli=tmp_path / "codex").invoke(
        _request(parameters={"repo": str(tmp_path.resolve())}),
        _context(),
    )

    assert result.status == "failed"
    assert result.error == {"type": "process_start", "message": "spawn failed"}


@pytest.mark.asyncio
async def test_invoke_reports_nonzero_exit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = _FakeProcess(returncode=3, stderr=b"boom")

    async def start(*args: Any, **kwargs: Any) -> _FakeProcess:
        del args, kwargs
        return process

    monkeypatch.setattr(codex_provider.asyncio, "create_subprocess_exec", start)
    result = await CodexProvider(cli=tmp_path / "codex").invoke(
        _request(parameters={"repo": str(tmp_path.resolve())}),
        _context(),
    )

    assert result.status == "failed"
    assert result.error == {"type": "codex_exit", "exit_code": 3}
    assert result.message == "boom"


@pytest.mark.asyncio
async def test_cancel_and_reconcile_are_noops(tmp_path: Path) -> None:
    provider = CodexProvider(cli=tmp_path / "codex")

    assert await provider.cancel("request-codex-1") is None
    assert await provider.reconcile("request-codex-1") is None
