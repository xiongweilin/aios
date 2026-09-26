from __future__ import annotations

import json
import threading
from pathlib import Path, PureWindowsPath

import pytest
from websockets.sync.server import ServerConnection, serve

from integrations.codex_app_server import (
    CodexBridgeError,
    HostPathMapper,
    RemoteCodexAppServer,
)


class FakeAppServer:
    def __init__(
        self,
        *,
        lose_turn_result: bool = False,
        user_agent_initialize: bool = False,
        retain_lost_turn: bool = False,
        allowed_profiles: tuple[str, ...] = (":read-only", ":workspace"),
        terminal_status: str = "completed",
        server_request_method: str | None = None,
        fail_method: str | None = None,
    ) -> None:
        self.lose_turn_result = lose_turn_result
        self.user_agent_initialize = user_agent_initialize
        self.retain_lost_turn = retain_lost_turn
        self.allowed_profiles = allowed_profiles
        self.terminal_status = terminal_status
        self.server_request_method = server_request_method
        self.fail_method = fail_method
        self.messages: list[dict[str, object]] = []
        self.turns: list[dict[str, object]] = []
        self.server_responses: list[dict[str, object]] = []
        self._lock = threading.Lock()

        def process_request(
            connection: ServerConnection,
            request: object,
        ) -> object | None:
            headers = getattr(request, "headers")
            if headers.get("Authorization") != "Bearer test-transport-token":
                return connection.respond(401, "unauthorized")
            return None

        self.server = serve(
            self._handle,
            "127.0.0.1",
            0,
            process_request=process_request,
        )
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)

    def _handle(self, connection: ServerConnection) -> None:
        for raw in connection:
            message = json.loads(raw)
            method = message.get("method")
            with self._lock:
                self.messages.append(dict(message))

            if self.fail_method is not None and method == self.fail_method:
                connection.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "error": {"code": -32000, "message": "configured failure"},
                        }
                    )
                )
                continue
            if method is None and message.get("id") == "server-request-1":
                with self._lock:
                    self.server_responses.append(dict(message))
                continue

            if method == "initialize":
                result = (
                    {
                        "userAgent": "Codex CLI/0.154.0 (Windows; x86_64)"
                    }
                    if self.user_agent_initialize
                    else {"serverInfo": {"name": "codex", "version": "0.154.0"}}
                )
                connection.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "result": result,
                        }
                    )
                )
            elif method == "initialized":
                continue
            elif method == "permissionProfile/list":
                connection.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "result": {
                                "data": [
                                    {"id": profile, "allowed": True}
                                    for profile in self.allowed_profiles
                                ]
                            },
                        }
                    )
                )
            elif method in {"thread/start", "thread/resume"}:
                thread_id = (
                    "thread-test"
                    if method == "thread/start"
                    else message["params"]["threadId"]
                )
                connection.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "result": {"thread": {"id": thread_id}},
                        }
                    )
                )
            elif method == "turn/start":
                params = message["params"]
                prompt = params["input"][0]["text"]
                turn = {
                    "id": "turn-test",
                    "status": self.terminal_status,
                    "items": [
                        {
                            "type": "userMessage",
                            "content": [{"type": "text", "text": prompt}],
                        },
                        {"type": "agentMessage", "text": "verified-result"},
                    ],
                }
                if not self.lose_turn_result or self.retain_lost_turn:
                    with self._lock:
                        self.turns.append(turn)
                if self.server_request_method is not None:
                    server_request_params: dict[str, object] = {}
                    if self.server_request_method == "item/fileChange/requestApproval":
                        server_request_params["grantRoot"] = message["params"]["cwd"]
                    elif self.server_request_method == "item/commandExecution/requestApproval":
                        server_request_params["cwd"] = str(
                            PureWindowsPath(message["params"]["cwd"]).parent / "outside"
                        )
                    connection.send(
                        json.dumps(
                            {
                                "id": "server-request-1",
                                "method": self.server_request_method,
                                "params": server_request_params,
                            }
                        )
                    )
                connection.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "result": {"turn": {"id": "turn-test", "status": "inProgress"}},
                        }
                    )
                )
                if self.lose_turn_result:
                    connection.close()
                    return
                connection.send(
                    json.dumps(
                        {
                            "method": "item/completed",
                            "params": {
                                "item": {"type": "agentMessage", "text": "verified-result"}
                            },
                        }
                    )
                )
                connection.send(
                    json.dumps(
                        {
                            "method": "turn/completed",
                            "params": {
                                "turn": {"id": "turn-test", "status": self.terminal_status}
                            },
                        }
                    )
                )
            elif method == "thread/read":
                with self._lock:
                    turns = list(self.turns)
                connection.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "result": {"thread": {"id": "thread-test", "turns": turns}},
                        }
                    )
                )
            elif method == "turn/interrupt":
                connection.send(json.dumps({"id": message["id"], "result": {}}))
            else:
                connection.send(
                    json.dumps(
                        {
                            "id": message.get("id"),
                            "error": {"code": -32601, "message": "unsupported"},
                        }
                    )
                )


def _client(tmp_path: Path, server: FakeAppServer) -> RemoteCodexAppServer:
    token = tmp_path / "transport-token"
    token.write_text("test-transport-token", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    mapping = tmp_path / "path-map.json"
    mapping.write_text(
        json.dumps(
            {
                "version": 1,
                "roots": [
                    {
                        "containerRoot": "/workspace",
                        "hostRoot": str(workspace),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return RemoteCodexAppServer(
        url=f"ws://127.0.0.1:{server.port}",
        token_file=token.resolve(),
        path_map_file=mapping.resolve(),
        journal_root=(tmp_path / "aios-state").resolve(),
        client_name="aios-test",
    )


def test_health_accepts_codex_cli_user_agent_initialize_response(tmp_path: Path) -> None:
    server = FakeAppServer(user_agent_initialize=True)
    try:
        assert _client(tmp_path, server).health() == "Codex CLI/0.154.0 (Windows; x86_64)"
    finally:
        server.close()


def test_remote_turn_uses_authenticated_jsonrpc_and_reconciles_cached_identity(
    tmp_path: Path,
) -> None:
    server = FakeAppServer()
    try:
        client = _client(tmp_path, server)
        result = client.run_turn(
            request_id="autodev:cycle-1:implementation-1",
            prompt="make the change",
            cwd="/workspace",
            sandbox="workspace-write",
            thread_id=None,
            resume_key="cycle-1:implementation",
            model="gpt-test",
            timeout_seconds=2,
        )
        replay = client.run_turn(
            request_id="autodev:cycle-1:implementation-1",
            prompt="make the change",
            cwd="/workspace",
            sandbox="workspace-write",
            thread_id=None,
            resume_key="cycle-1:implementation",
            model="gpt-test",
            timeout_seconds=2,
        )

        assert result.completed
        assert result.server_version == "0.154.0"
        initialize = next(message for message in server.messages if message.get("method") == "initialize")
        assert initialize["params"]["capabilities"]["experimentalApi"] is True
        assert result.agent_messages == ("verified-result",)
        assert replay.result_sha256 == result.result_sha256
        assert sum(message.get("method") == "turn/start" for message in server.messages) == 1
        thread_read = next(message for message in server.messages if message.get("method") == "thread/read")
        assert thread_read["params"]["includeTurns"] is True
        turn_start = next(message for message in server.messages if message.get("method") == "turn/start")
        assert turn_start["params"]["cwd"].endswith("workspace")
        assert turn_start["params"]["permissions"] == ":workspace"
        assert turn_start["params"]["runtimeWorkspaceRoots"] == [str(tmp_path / "workspace")]
        assert "sandboxPolicy" not in turn_start["params"]
        assert "AIOS-REQUEST-ID:autodev:cycle-1:implementation-1" in turn_start["params"]["input"][0]["text"]
    finally:
        server.close()


def test_read_only_turn_uses_restricted_profile_and_only_mapped_workspace_root(
    tmp_path: Path,
) -> None:
    server = FakeAppServer()
    try:
        result = _client(tmp_path, server).run_turn(
            request_id="autodev:readonly-smoke",
            prompt="respond only with a short confirmation",
            cwd="/workspace",
            sandbox="read-only",
            thread_id=None,
            resume_key=None,
            model=None,
            timeout_seconds=2,
        )
        turn_start = next(message for message in server.messages if message.get("method") == "turn/start")
        assert result.completed
        assert turn_start["params"]["permissions"] == ":read-only"
        assert turn_start["params"]["runtimeWorkspaceRoots"] == [str(tmp_path / "workspace")]
        assert "sandboxPolicy" not in turn_start["params"]
    finally:
        server.close()


def test_remote_turn_marks_lost_completion_unknown_and_does_not_redispatch(
    tmp_path: Path,
) -> None:
    server = FakeAppServer(lose_turn_result=True)
    try:
        client = _client(tmp_path, server)
        kwargs = {
            "request_id": "control-plane:request-1",
            "prompt": "inspect only",
            "cwd": "/workspace",
            "sandbox": "read-only",
            "thread_id": None,
            "resume_key": "control-plane:run-1",
            "model": None,
            "timeout_seconds": 2,
        }
        with pytest.raises(CodexBridgeError) as error:
            client.run_turn(**kwargs)
        assert error.value.outcome == "unknown"

        with pytest.raises(CodexBridgeError) as replay_error:
            client.run_turn(**kwargs)
        assert replay_error.value.outcome == "unknown"
        assert sum(message.get("method") == "turn/start" for message in server.messages) == 1
    finally:
        server.close()


def test_path_mapper_rejects_unmounted_container_worktree(tmp_path: Path) -> None:
    server = FakeAppServer()
    try:
        client = _client(tmp_path, server)
        with pytest.raises(ValueError, match="outside configured host bind mounts"):
            client.run_turn(
                request_id="invalid-path",
                prompt="no-op",
                cwd=Path("/unmounted/repository"),
                sandbox="read-only",
                thread_id=None,
                resume_key=None,
                model=None,
                timeout_seconds=1,
            )
    finally:
        server.close()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "must use version 1"),
        ({"version": 1, "roots": {}}, "roots must be a list"),
        ({"version": 1, "roots": ["/workspace"]}, "root must be an object"),
        ({"version": 1, "roots": [{}]}, "require string paths"),
        (
            {"version": 1, "roots": [{"containerRoot": "workspace", "hostRoot": "/host"}]},
            "container roots must be absolute",
        ),
        (
            {"version": 1, "roots": [{"containerRoot": "/workspace", "hostRoot": "host"}]},
            "host roots must be absolute",
        ),
    ],
)
def test_path_mapper_rejects_malformed_map_entries(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    mapping = tmp_path / "path-map.json"
    mapping.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        HostPathMapper.from_file(mapping)


def test_request_id_is_validated_before_journal_path_is_created(tmp_path: Path) -> None:
    server = FakeAppServer()
    try:
        client = _client(tmp_path, server)
        with pytest.raises(ValueError, match="unsupported characters"):
            client._journal_path("../outside")
        with pytest.raises(ValueError, match="unsupported characters"):
            client.run_turn(
                request_id="../outside",
                prompt="must not dispatch",
                cwd="/workspace",
                sandbox="read-only",
                thread_id=None,
                resume_key=None,
                model=None,
                timeout_seconds=1,
            )

        assert not (tmp_path / "outside.json").exists()
        assert server.messages == []
    finally:
        server.close()


def test_remote_turn_reconciles_a_lost_reply_without_redispatch(tmp_path: Path) -> None:
    server = FakeAppServer(lose_turn_result=True, retain_lost_turn=True)
    try:
        client = _client(tmp_path, server)
        kwargs = {
            "request_id": "autodev:reconcile-lost-reply",
            "prompt": "reconcile this turn",
            "cwd": "/workspace",
            "sandbox": "workspace-write",
            "thread_id": None,
            "resume_key": None,
            "model": None,
            "timeout_seconds": 2,
        }
        with pytest.raises(CodexBridgeError) as lost:
            client.run_turn(**kwargs)
        recovered = client.run_turn(**kwargs)

        assert lost.value.outcome == "unknown"
        assert recovered.completed
        assert recovered.agent_messages == ("verified-result",)
        assert sum(message.get("method") == "turn/start" for message in server.messages) == 1
    finally:
        server.close()


def test_missing_permission_profile_prevents_turn_dispatch(tmp_path: Path) -> None:
    server = FakeAppServer(allowed_profiles=(":read-only",))
    try:
        with pytest.raises(CodexBridgeError) as error:
            _client(tmp_path, server).run_turn(
                request_id="autodev:workspace-write-denied",
                prompt="do not dispatch",
                cwd="/workspace",
                sandbox="workspace-write",
                thread_id=None,
                resume_key=None,
                model=None,
                timeout_seconds=2,
            )

        assert error.value.outcome == "not_started"
        assert not any(message.get("method") == "turn/start" for message in server.messages)
    finally:
        server.close()


@pytest.mark.parametrize(
    ("method", "sandbox", "expected"),
    [
        ("item/fileChange/requestApproval", "workspace-write", "accept"),
        ("item/fileChange/requestApproval", "read-only", "decline"),
        ("item/commandExecution/requestApproval", "workspace-write", "decline"),
    ],
)
def test_server_approval_requests_are_bounded_to_the_workspace(
    tmp_path: Path,
    method: str,
    sandbox: str,
    expected: str,
) -> None:
    server = FakeAppServer(server_request_method=method)
    try:
        result = _client(tmp_path, server).run_turn(
            request_id=f"autodev:approval:{sandbox}:{expected}",
            prompt="exercise server approval",
            cwd="/workspace",
            sandbox=sandbox,
            thread_id=None,
            resume_key=None,
            model=None,
            timeout_seconds=2,
        )

        assert result.completed
        assert server.server_responses[0]["result"]["decision"] == expected
    finally:
        server.close()


def test_remote_rpc_error_is_reported_before_dispatch(tmp_path: Path) -> None:
    server = FakeAppServer(fail_method="thread/start")
    try:
        with pytest.raises(CodexBridgeError, match="Codex RPC failed"):
            _client(tmp_path, server).run_turn(
                request_id="autodev:thread-start-error",
                prompt="do not dispatch",
                cwd="/workspace",
                sandbox="read-only",
                thread_id=None,
                resume_key=None,
                model=None,
                timeout_seconds=2,
            )

        assert not any(message.get("method") == "turn/start" for message in server.messages)
    finally:
        server.close()


def test_failed_remote_turn_is_journaled_and_not_replayed(tmp_path: Path) -> None:
    server = FakeAppServer(terminal_status="failed")
    try:
        client = _client(tmp_path, server)
        kwargs = {
            "request_id": "autodev:failed-turn",
            "prompt": "return a failure",
            "cwd": "/workspace",
            "sandbox": "read-only",
            "thread_id": None,
            "resume_key": "failed-turn",
            "model": None,
            "timeout_seconds": 2,
        }
        with pytest.raises(CodexBridgeError) as error:
            client.run_turn(**kwargs)
        assert error.value.outcome == "failed"
        with pytest.raises(CodexBridgeError, match="prior Codex request failed"):
            client.run_turn(**kwargs)
        assert sum(message.get("method") == "turn/start" for message in server.messages) == 1
    finally:
        server.close()
